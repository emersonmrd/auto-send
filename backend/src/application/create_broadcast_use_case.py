from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional
import uuid

from src.application.broadcast_rules import ensure_poll_fits_targets, parse_schedule
from src.application.errors import ProfileNotFoundError
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastPoll,
    BroadcastStatus,
    InlineButton,
    MediaAttachment,
    PollType,
    validate_and_escape_telegram_html,
)
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.broadcast_scheduler import IBroadcastScheduler
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.profile_repository import IProfileRepository

# Grava a mídia enviada e devolve o anexo; roda só depois que o resto do pedido foi validado.
MediaLoader = Callable[[], Awaitable[Optional[MediaAttachment]]]


@dataclass(frozen=True)
class PollSpec:
    question: str
    options: List[str]
    is_anonymous: bool = True
    allows_multiple_answers: bool = False
    poll_type: str = "regular"
    correct_option_id: Optional[int] = None
    explanation: Optional[str] = None
    is_closed: bool = False

    def to_poll(self) -> BroadcastPoll:
        explanation = self.explanation.strip() if self.explanation and self.explanation.strip() else None
        return BroadcastPoll(
            question=self.question.strip(),
            options=[str(o).strip() for o in self.options],
            is_anonymous=self.is_anonymous,
            allows_multiple_answers=self.allows_multiple_answers,
            poll_type=PollType.QUIZ if self.poll_type.lower() == "quiz" else PollType.REGULAR,
            correct_option_id=self.correct_option_id,
            explanation=explanation,
            is_closed=self.is_closed,
        )


@dataclass(frozen=True)
class CreateBroadcastCommand:
    profile_id: str
    target_channel_ids: List[str]
    text: str = ""
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    has_media: bool = False
    poll: Optional[PollSpec] = field(default=None)


class CreateBroadcastUseCase:
    def __init__(
        self,
        profile_repo: IProfileRepository,
        channel_repo: IChannelRepository,
        broadcast_repo: IBroadcastRepository,
        scheduler: IBroadcastScheduler,
    ):
        self.profile_repo = profile_repo
        self.channel_repo = channel_repo
        self.broadcast_repo = broadcast_repo
        self.scheduler = scheduler

    async def execute(self, command: CreateBroadcastCommand, load_media: MediaLoader) -> BroadcastMessage:
        if await self.profile_repo.get_by_id(command.profile_id) is None:
            raise ProfileNotFoundError(command.profile_id)

        button = None
        if command.button_text and command.button_url:
            button = InlineButton(text=command.button_text, url=command.button_url)
        text = validate_and_escape_telegram_html(command.text or "")
        scheduled_at = parse_schedule(command.scheduled_at) if command.scheduled_at and command.scheduled_at.strip() else None

        poll = None
        if command.poll is not None:
            if command.has_media:
                raise ValueError("A broadcast cannot have both media and a poll")
            poll = command.poll.to_poll()
            await ensure_poll_fits_targets(poll, command.profile_id, command.target_channel_ids, self.channel_repo)

        # Mídia por último: nada vai para temp_media/ se o pedido já é inválido.
        media = await load_media()
        broadcast = BroadcastMessage(
            id=str(uuid.uuid4()),
            profile_id=command.profile_id,
            target_channel_ids=command.target_channel_ids,
            text=text,
            media=media,
            button=button,
            poll=poll,
            scheduled_at=scheduled_at,
            status=BroadcastStatus.SCHEDULED if scheduled_at else BroadcastStatus.PENDING,
        )
        await self.broadcast_repo.save(broadcast)
        if scheduled_at:
            self.scheduler.schedule_broadcast(broadcast.id, scheduled_at)
        return broadcast
