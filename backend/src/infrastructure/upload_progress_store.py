import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping


class UploadProgressStore(MutableMapping[str, dict]):
    """
    Progresso de upload em memória, com TTL e limite de itens (AGENTS.md §8.7).

    O prazo conta do último acesso: o callback de progresso lê a entrada a cada bloco enviado,
    então um upload longo não expira no meio. Cada escrita descarta o que passou do prazo e,
    acima do limite, as entradas usadas há mais tempo (LRU).
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_items: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_items <= 0:
            raise ValueError("ttl_seconds and max_items must be positive")
        self._ttl = ttl_seconds
        self._max_items = max_items
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    def __getitem__(self, key: str) -> dict:
        _, value = self._entries[key]
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        return value

    def __setitem__(self, key: str, value: dict) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        self._evict()

    def __delitem__(self, key: str) -> None:
        del self._entries[key]

    def __contains__(self, key: object) -> bool:
        # Sem renovar o prazo: só ler a entrada conta como uso.
        return key in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    def _evict(self) -> None:
        deadline = self._clock() - self._ttl
        # A ordem é do uso mais antigo para o mais novo: as expiradas estão no começo.
        while self._entries:
            oldest_key, (last_used, _) = next(iter(self._entries.items()))
            if last_used >= deadline and len(self._entries) <= self._max_items:
                break
            del self._entries[oldest_key]
