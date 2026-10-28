from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import re

# Canal ou supergrupo do Telegram: -100 seguido de dígitos.
CHANNEL_CHAT_ID_PATTERN = r"^-100\d{9,}$"


class ChatType(str, Enum):
    """Tipo do chat como o Telegram o informa (#99)."""

    CHANNEL = "channel"
    SUPERGROUP = "supergroup"
    GROUP = "group"


@dataclass
class Channel:
    id: str
    profile_id: str
    title: str
    chat_id: str
    invite_link: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # None: canal vinculado antes da #99, ainda sem tipo; é preenchido na próxima edição.
    chat_type: Optional[ChatType] = None
    is_forum: bool = False

    def __post_init__(self):
        self.check_chat_id(self.chat_id)
        self._check_kind(self.chat_type, self.is_forum)

    @staticmethod
    def check_chat_id(chat_id: str) -> None:
        # Validação do formato de chat_id do Telegram (normalmente começa com -100 para canais ou supergrupos)
        if not re.match(CHANNEL_CHAT_ID_PATTERN, chat_id):
            raise ValueError("Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)")

    def relink(self, chat_id: str) -> None:
        # Outro chat: o tipo do anterior não vale mais até o Telegram informar o novo.
        self.check_chat_id(chat_id)
        self.chat_id = chat_id
        self.chat_type = None
        self.is_forum = False

    def classify(self, chat_type: ChatType, is_forum: bool) -> None:
        self._check_kind(chat_type, is_forum)
        self.chat_type = chat_type
        self.is_forum = is_forum

    @staticmethod
    def _check_kind(chat_type: Optional[ChatType], is_forum: bool) -> None:
        # Grupo comum muda de id ao virar supergrupo: vinculá-lo quebraria o canal salvo.
        if chat_type is ChatType.GROUP:
            raise ValueError("A basic group cannot be registered: convert it to a supergroup first")
        if is_forum and chat_type is not ChatType.SUPERGROUP:
            raise ValueError("Only supergroups can be forums")
