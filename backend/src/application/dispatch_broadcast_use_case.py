from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional, Protocol, Tuple
import asyncio

from src.application.errors import BroadcastAbortedError
from src.domain.broadcast.broadcast_message import BroadcastMessage, BroadcastStatus, ChannelDeliveryResult
from src.domain.ports.broadcast_repository import IBroadcastRepository

ProgressCallback = Callable[[int, int], None]
# Envia para um chat e devolve (resultado, erro no formato antigo da resposta, file_id que o Telegram devolveu).
ChannelSender = Callable[
    [str, Optional[ProgressCallback], Optional[str]],
    Awaitable[Tuple[ChannelDeliveryResult, Optional[str], Optional[str]]],
]


class DispatchObserver(Protocol):
    """Observer: quem acompanha o disparo (a tela de progresso) sem o caso de uso conhecê-lo."""

    async def should_stop(self) -> bool: ...

    def upload_progress_callback(self) -> Optional[ProgressCallback]: ...

    def channel_done(self, done: int, total: int) -> None: ...


@dataclass(frozen=True)
class DispatchOutcome:
    dispatched_count: int
    errors: List[str]


class DispatchBroadcastUseCase:
    def __init__(self, broadcast_repo: IBroadcastRepository):
        self.broadcast_repo = broadcast_repo

    async def execute(self, broadcast: BroadcastMessage, send: ChannelSender, observer: DispatchObserver) -> DispatchOutcome:
        results: List[ChannelDeliveryResult] = []
        errors: List[str] = []
        try:
            broadcast.status = BroadcastStatus.DISPATCHING
            await self.broadcast_repo.save(broadcast)

            targets = broadcast.target_channel_ids
            # A mídia sobe uma vez; os outros canais recebem o file_id do primeiro envio aceito (#83).
            file_id: Optional[str] = None
            for idx, chat_id in enumerate(targets):
                if await observer.should_stop():
                    raise asyncio.CancelledError()
                progress = observer.upload_progress_callback() if broadcast.media and not file_id else None
                result, legacy_error, uploaded_file_id = await send(chat_id, progress, file_id)
                results.append(result)
                if result.delivered:
                    file_id = file_id or uploaded_file_id
                elif legacy_error:
                    errors.append(legacy_error)
                if not broadcast.media:
                    observer.channel_done(idx + 1, len(targets))

            broadcast.finish_dispatch_with_results(results)
            await self.broadcast_repo.save(broadcast)
        except asyncio.CancelledError:
            broadcast.abort_dispatch(results)
            await self.broadcast_repo.save(broadcast)
            raise BroadcastAbortedError() from None
        except Exception:
            broadcast.abort_dispatch(results)
            await self.broadcast_repo.save(broadcast)
            raise
        return DispatchOutcome(dispatched_count=sum(r.delivered for r in results), errors=errors)
