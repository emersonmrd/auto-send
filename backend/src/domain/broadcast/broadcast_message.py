import ipaddress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional
from urllib.parse import urlparse

# Margem para o datetime-local do navegador (sem segundos) e relógios levemente atrasados; vale para POST e PATCH.
SCHEDULE_CLOCK_TOLERANCE = timedelta(seconds=60)
DEFAULT_MISFIRE_GRACE_MINUTES = 30


class DueScheduleAction(str, Enum):
    WAIT = "WAIT"
    DISPATCH = "DISPATCH"
    MISFIRE = "MISFIRE"


def ensure_schedulable(run_at: datetime, now: datetime) -> None:
    if run_at.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")
    if run_at < now - SCHEDULE_CLOCK_TOLERANCE:
        raise ValueError("scheduled_at cannot be in the past")


def evaluate_due_schedule(
    scheduled_at: datetime, now: datetime, grace_window: timedelta
) -> DueScheduleAction:
    if scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")
    if grace_window < timedelta(0):
        raise ValueError("grace_window cannot be negative")
    if now < scheduled_at:
        return DueScheduleAction.WAIT
    if now - scheduled_at <= grace_window:
        return DueScheduleAction.DISPATCH
    return DueScheduleAction.MISFIRE


class MediaType(str, Enum):
    VIDEO = "VIDEO"
    PHOTO = "PHOTO"

class DispatchStrategy(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    SINGLE_MEDIA_WITH_CAPTION = "SINGLE_MEDIA_WITH_CAPTION"
    SPLIT_TEXT_THEN_MEDIA = "SPLIT_TEXT_THEN_MEDIA"

class BroadcastStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    MISFIRED = "MISFIRED"
    DISPATCHING = "DISPATCHING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeliveryFailureCategory(str, Enum):
    BOT_NOT_IN_CHAT = "BOT_NOT_IN_CHAT"
    NO_POST_PERMISSION = "NO_POST_PERMISSION"
    INVALID_TOKEN = "INVALID_TOKEN"
    RATE_LIMITED = "RATE_LIMITED"
    TELEGRAM_UNAVAILABLE = "TELEGRAM_UNAVAILABLE"
    OTHER = "OTHER"


@dataclass(frozen=True)
class ChannelDeliveryResult:
    chat_id: str
    delivered: bool
    failure_category: Optional[DeliveryFailureCategory] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.chat_id or not self.chat_id.strip():
            raise ValueError("chat_id cannot be empty")
        if self.delivered and self.failure_category is not None:
            raise ValueError("Delivered result cannot have a failure_category")
        if not self.delivered and self.failure_category is None:
            raise ValueError("Failed delivery result requires a failure_category")

    @classmethod
    def success(cls, chat_id: str) -> "ChannelDeliveryResult":
        return cls(chat_id=chat_id, delivered=True)

    @classmethod
    def failure(
        cls,
        chat_id: str,
        category: DeliveryFailureCategory,
        detail: Optional[str] = None,
    ) -> "ChannelDeliveryResult":
        return cls(
            chat_id=chat_id,
            delivered=False,
            failure_category=category,
            detail=detail,
        )

@dataclass(frozen=True)
class InlineButton:
    text: str
    url: str

    def __post_init__(self):
        parsed = urlparse(self.url)
        # Exigir HTTPS para evitar vazamento ou SSRF com http/file/gopher
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("Insecure or invalid URL scheme. Only https:// allowed.")
        
        # Bloquear localhost e IPs privados
        hostname = parsed.hostname or ""  # pragma: no mutate - qualquer string que não seja IP nem host bloqueado dá o mesmo resultado
        if hostname.lower() in ["localhost", "127.0.0.1", "0.0.0.0"]:  # nosec B104 - lista de hosts bloqueados (anti-SSRF), não é bind
            raise ValueError("Insecure or invalid URL scheme: Private network prohibited.")
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None  # Nome de domínio padrão público (não é um IP literal)

        if ip is not None and (ip.is_private or ip.is_loopback):
            raise ValueError("Insecure or invalid URL scheme: Private IP prohibited.")

@dataclass(frozen=True)
class MediaAttachment:
    file_path: str
    media_type: MediaType
    file_size: int
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail_path: Optional[str] = None

@dataclass
class BroadcastMessage:
    id: str
    profile_id: str
    target_channel_ids: List[str]
    text: str = ""
    media: Optional[MediaAttachment] = None
    button: Optional[InlineButton] = None
    status: BroadcastStatus = BroadcastStatus.PENDING
    scheduled_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    delivery_results: List[ChannelDeliveryResult] = field(default_factory=list)

    def get_dispatch_strategy(self) -> DispatchStrategy:
        if not self.media:
            return DispatchStrategy.TEXT_ONLY
        
        # Limite oficial de legenda no Telegram é de 1024 caracteres
        if len(self.text) <= 1024:
            return DispatchStrategy.SINGLE_MEDIA_WITH_CAPTION
        
        return DispatchStrategy.SPLIT_TEXT_THEN_MEDIA

    def finish_dispatch(self, delivered: int, total: int) -> None:
        if not 0 <= delivered <= total:
            raise ValueError("delivered must be between 0 and total")
        if delivered == 0:
            self.status = BroadcastStatus.FAILED
        elif delivered == total:
            self.status = BroadcastStatus.COMPLETED
        else:
            self.status = BroadcastStatus.PARTIALLY_COMPLETED

    def finish_dispatch_with_results(self, results: List[ChannelDeliveryResult]) -> None:
        self.delivery_results = list(results)
        delivered = sum(1 for r in self.delivery_results if r.delivered)
        self.finish_dispatch(delivered=delivered, total=len(self.target_channel_ids))

    def fail_all_channels(
        self, category: DeliveryFailureCategory, detail: Optional[str] = None
    ) -> None:
        results = [
            ChannelDeliveryResult.failure(cid, category=category, detail=detail)
            for cid in self.target_channel_ids
        ]
        self.finish_dispatch_with_results(results)

    def mark_misfired(self) -> None:
        if self.status not in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]:
            raise ValueError("Only pending or scheduled broadcasts can become misfired")
        self.status = BroadcastStatus.MISFIRED

    def start_dispatch(self) -> None:
        if self.status not in [
            BroadcastStatus.PENDING,
            BroadcastStatus.SCHEDULED,
            BroadcastStatus.MISFIRED,
        ]:
            raise ValueError(
                "Cannot dispatch an in-flight, completed, failed, or cancelled broadcast"
            )
        self.status = BroadcastStatus.DISPATCHING

    def cancel(self) -> None:
        if self.status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED]:
            raise ValueError("Cannot cancel an in-flight or completed broadcast")
        self.status = BroadcastStatus.CANCELLED

    def reschedule(self, new_run_date: datetime) -> None:
        if self.status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
            raise ValueError("Cannot reschedule an in-flight, completed, or cancelled broadcast")
        self.scheduled_at = new_run_date
        self.status = BroadcastStatus.SCHEDULED

    def update_content(self, text: str, button: Optional[InlineButton] = None) -> None:
        if self.status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
            raise ValueError("Cannot update content of an in-flight, completed, or cancelled broadcast")
        self.text = text
        self.button = button

    def is_pending_or_scheduled(self) -> bool:
        return self.status in [
            BroadcastStatus.PENDING,
            BroadcastStatus.SCHEDULED,
            BroadcastStatus.MISFIRED,
        ]

    def remove_target_channel(self, chat_id: str) -> bool:
        if self.status == BroadcastStatus.DISPATCHING:
            raise ValueError(
                "There is a broadcast currently dispatching. Wait for it to finish and try again."
            )
        if not self.is_pending_or_scheduled():
            raise ValueError(
                "Cannot modify target channels of a completed, failed, or cancelled broadcast"
            )
        if chat_id not in self.target_channel_ids:
            return False
        self.target_channel_ids = [cid for cid in self.target_channel_ids if cid != chat_id]
        if not self.target_channel_ids:
            self.status = BroadcastStatus.CANCELLED
        return True

    def replace_target_channel(self, old_chat_id: str, new_chat_id: str) -> bool:
        if self.status == BroadcastStatus.DISPATCHING:
            raise ValueError(
                "There is a broadcast currently dispatching. Wait for it to finish and try again."
            )
        if not self.is_pending_or_scheduled():
            raise ValueError(
                "Cannot modify target channels of a completed, failed, or cancelled broadcast"
            )
        if old_chat_id == new_chat_id or old_chat_id not in self.target_channel_ids:
            return False
        updated: List[str] = []
        for cid in self.target_channel_ids:
            replacement = new_chat_id if cid == old_chat_id else cid
            if replacement not in updated:
                updated.append(replacement)
        self.target_channel_ids = updated
        return True
