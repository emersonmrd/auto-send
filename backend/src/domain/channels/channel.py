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
    message_thread_id: Optional[int] = None
    topic_name: Optional[str] = None

    def __post_init__(self):
        self.check_chat_id(self.chat_id)
        self._check_kind(self.chat_type, self.is_forum)
        self._check_topic(self.message_thread_id)
        if self.topic_name is not None:
            self.topic_name = self.topic_name.strip() or None

    @staticmethod
    def _check_topic(message_thread_id: Optional[int]) -> None:
        if message_thread_id is not None:
            if not isinstance(message_thread_id, int) or isinstance(message_thread_id, bool) or message_thread_id <= 0:
                raise ValueError("message_thread_id must be a positive integer")

    @property
    def destination_id(self) -> str:
        if self.message_thread_id:
            return f"{self.chat_id}:{self.message_thread_id}"
        return self.chat_id

    def set_topic(self, message_thread_id: Optional[int], topic_name: Optional[str] = None) -> None:
        self._check_topic(message_thread_id)
        self.message_thread_id = message_thread_id
        self.topic_name = topic_name.strip() or None if topic_name is not None else None

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
        self.message_thread_id = None
        self.topic_name = None

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
