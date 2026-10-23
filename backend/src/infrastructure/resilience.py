import time
import asyncio
import logging
from enum import Enum
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    """Lançada quando o Circuit Breaker está em estado OPEN e rejeita a execução."""

    def __init__(self, message: str = "Circuit is OPEN. Requests are blocked.", retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class CircuitBreaker:
    """
    Circuit Breaker com suporte a Rate Limiting (HTTP 429) e falhas consecutivas (5xx / erros de rede).
    
    Estados:
    - CLOSED: Operação normal. Conta falhas consecutivas.
    - OPEN: Falha rápida para todas as chamadas por tempo de cooldown ou retry_after especificado.
    - HALF_OPEN: Permite uma chamada de teste após o cooldown. Se tiver sucesso, volta para CLOSED. Se falhar, reabre OPEN.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        time_func: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._time_func = time_func

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._open_until = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        now = self._time_func()
        if self._state == CircuitState.OPEN and now >= self._open_until:
            return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def _sync_state(self) -> None:
        """Atualiza o estado interno se o tempo de cooldown tiver expirado."""
        now = self._time_func()
        if self._state == CircuitState.OPEN and now >= self._open_until:
            self._state = CircuitState.HALF_OPEN

    async def can_execute(self) -> bool:
        """Verifica se uma requisição pode ser executada. Levanta CircuitBreakerOpenException se bloqueada."""
        async with self._lock:
            self._sync_state()
            if self._state == CircuitState.OPEN:
                wait_time = max(0.0, self._open_until - self._time_func())
                raise CircuitBreakerOpenException(
                    f"Circuit is OPEN. Blocked for {wait_time:.1f}s more.",
                    retry_after=wait_time,
                )
            return True

    async def record_success(self) -> None:
        """Registra um sucesso de requisição, resetando o circuito para CLOSED."""
        async with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    async def record_failure(self, retry_after: Optional[float] = None) -> None:
        """
        Registra uma falha de requisição.
        Se retry_after for fornecido (ex: HTTP 429), abre o circuito imediatamente por esse período.
        Caso contrário, incrementa falhas consecutivas e abre se atingir failure_threshold.
        """
        async with self._lock:
            now = self._time_func()
            self._last_failure_time = now

            if retry_after is not None and retry_after > 0:
                # HTTP 429 ou indicação explícita de cooldown: abre imediatamente
                self._state = CircuitState.OPEN
                self._open_until = now + retry_after
                logger.warning(
                    f"Circuit Breaker forced OPEN due to explicit rate limit / retry-after: {retry_after}s"
                )
                return

            if self._state == CircuitState.HALF_OPEN:
                # Falhou na tentativa de recuperação, reabre pelo recovery_timeout
                self._state = CircuitState.OPEN
                self._open_until = now + self.recovery_timeout
                logger.warning(f"Circuit Breaker test failed in HALF_OPEN. Re-opening for {self.recovery_timeout}s")
                return

            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._open_until = now + self.recovery_timeout
                logger.warning(
                    f"Circuit Breaker threshold ({self.failure_threshold}) reached. Opening for {self.recovery_timeout}s"
                )

    async def execute(self, coro_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Invoca coro_func(*args, **kwargs) protegido pelo Circuit Breaker.
        Nota: A detecção de erros HTTP específicos pode ser manipulada pelo chamador ou por exceções levantadas.
        """
        await self.can_execute()
        try:
            result = await coro_func(*args, **kwargs)
            await self.record_success()
            return result
        except Exception as e:
            # Re-raises após registrar falha genérica caso não tenha sido tratada antes
            await self.record_failure()
            raise e
