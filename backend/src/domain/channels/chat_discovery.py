from dataclasses import dataclass
from typing import Optional
import re

from src.domain.channels.channel import CHANNEL_CHAT_ID_PATTERN

# Username público do Telegram: 5 a 32 caracteres, começa com letra, só letras, dígitos e "_".
_USERNAME_PATTERN = r"[A-Za-z][A-Za-z0-9_]{4,31}"
# Link público t.me/<username> (ou telegram.me), com ou sem esquema e barra final.
_PUBLIC_LINK_PATTERN = r"(?:https?://)?(?:t|telegram)\.me/([^/?#]+)/?"
_DISCOVERABLE_CHAT_TYPES = ("channel", "supergroup", "group")


@dataclass(frozen=True)
class PublicChatIdentifier:
    """@username de um canal ou grupo público, para o Telegram resolver o chat_id numérico."""

    username: str

    def __post_init__(self):
        if not re.fullmatch(_USERNAME_PATTERN, self.username):
            raise ValueError("Invalid public chat identifier (use @username or t.me/username)")

    @classmethod
    def parse(cls, raw: str) -> "PublicChatIdentifier":
        value = raw.strip()
        link = re.fullmatch(_PUBLIC_LINK_PATTERN, value, re.IGNORECASE)
        if link:
            value = link.group(1)
        elif value.startswith("@"):
            value = value[1:]
        return cls(username=value)

    def as_chat_id(self) -> str:
        return f"@{self.username}"


@dataclass(frozen=True)
class DiscoveredChat:
    """Chat em que o bot está, como o Telegram o informou."""

    chat_id: str
    title: str
    chat_type: str
    username: Optional[str] = None

    def __post_init__(self):
        if not re.fullmatch(r"-\d+", self.chat_id) or self.chat_type not in _DISCOVERABLE_CHAT_TYPES:
            raise ValueError("Invalid discovered chat (expected a channel or group with a negative numeric id)")

    @property
    def is_registrable(self) -> bool:
        # Só canais e supergrupos (-100...) viram Channel; grupo comum aparece na lista, mas não pode ser vinculado.
        return bool(re.fullmatch(CHANNEL_CHAT_ID_PATTERN, self.chat_id))
