from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from src.application.broadcast_rules import ensure_poll_fits_targets, parse_schedule
from src.application.errors import BroadcastNotFoundError
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    InlineButton,
    ensure_schedulable,
)
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.broadcast_scheduler import IBroadcastScheduler
from src.domain.ports.channel_repository import IChannelRepository


@dataclass(frozen=True)
class UpdateBroadcastCommand:
    """PATCH: todo campo é opcional; None mantém o valor atual."""

    broadcast_id: str
    text: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    target_channel_ids: Optional[List[str]] = None


class UpdateBroadcastUseCase:
    def __init__(
        self,
        channel_repo: IChannelRepository,
        broadcast_repo: IBroadcastRepository,
        scheduler: IBroadcastScheduler,
    ):
        self.channel_repo = channel_repo
        self.broadcast_repo = broadcast_repo
        self.scheduler = scheduler

    async def execute(self, command: UpdateBroadcastCommand) -> BroadcastMessage:
        broadcast = await self.broadcast_repo.get_by_id(command.broadcast_id)
        if broadcast is None:
            raise BroadcastNotFoundError(command.broadcast_id)
        if broadcast.status not in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED, BroadcastStatus.MISFIRED):
            raise ValueError("Cannot edit an in-flight, completed, or cancelled broadcast")

        button = self._button(broadcast, command)
        new_run_date = parse_schedule(command.scheduled_at) if command.scheduled_at is not None else None

        now = datetime.now(timezone.utc)
        was_edit_locked = broadcast.edit_locked_until is not None
        # Salvar no modo edição sem novo horário, depois que o horário passou, exige um horário futuro (#15).
        if (
            new_run_date is None
            and was_edit_locked
            and broadcast.scheduled_at is not None
            and broadcast.status != BroadcastStatus.MISFIRED
        ):
            ensure_schedulable(broadcast.scheduled_at, now=now)

        if command.target_channel_ids is not None:
            await ensure_poll_fits_targets(broadcast.poll, broadcast.profile_id, command.target_channel_ids, self.channel_repo)
        text = command.text if command.text is not None else broadcast.text
        broadcast.update_content(text=text, button=button)
        if command.target_channel_ids is not None:
            broadcast.update_target_channels(command.target_channel_ids)

        if new_run_date is not None:
            broadcast.reschedule(new_run_date)
            self.scheduler.reschedule_broadcast(broadcast.id, new_run_date)
        elif was_edit_locked:
            broadcast.release_edit_lock(now)
            if broadcast.scheduled_at is not None and broadcast.status in (BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED):
                self.scheduler.reschedule_broadcast(broadcast.id, broadcast.scheduled_at)

        await self.broadcast_repo.save(broadcast)
        return broadcast

    @staticmethod
    def _button(broadcast: BroadcastMessage, command: UpdateBroadcastCommand) -> Optional[InlineButton]:
        text, url = command.button_text, command.button_url
        if text is None and url is None:
            return broadcast.button
        # Os dois vazios removem o botão; só um deles é erro (AGENTS.md §12).
        if text == "" and url == "":
            return None
        if text is None or url is None or not text.strip() or not url.strip():
            raise ValueError("Both button_text and button_url are required when defining an inline button")
        return InlineButton(text=text, url=url)
