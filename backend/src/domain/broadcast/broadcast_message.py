import ipaddress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional
from urllib.parse import urlparse

# Margem para o datetime-local do navegador (sem segundos) e relógios levemente atrasados; vale para POST e PATCH.
SCHEDULE_CLOCK_TOLERANCE = timedelta(seconds=60)


def ensure_schedulable(run_at: datetime, now: datetime) -> None:
    if run_at.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")
    if run_at < now - SCHEDULE_CLOCK_TOLERANCE:
        raise ValueError("scheduled_at cannot be in the past")


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
    DISPATCHING = "DISPATCHING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

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
