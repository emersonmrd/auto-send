from dataclasses import dataclass
from typing import Optional
import re

from src.domain.channels.channel import CHANNEL_CHAT_ID_PATTERN, ChatType

# Username público do Telegram: 5 a 32 caracteres, começa com letra, só letras, dígitos e "_".
_USERNAME_PATTERN = r"[A-Za-z][A-Za-z0-9_]{4,31}"
_TME = r"(?:https?://)?(?:t|telegram)\.me/"
# Convite (t.me/+hash, t.me/joinchat/hash): a Bot API não resolve.
_INVITE_LINK_PATTERN = _TME + r"(?:\+|joinchat/).*"
# "Copiar link" de um post ou tópico de canal/grupo privado: t.me/c/<id>/<post> ou t.me/c/<id>/<topic>/<msg>
_PRIVATE_POST_LINK_PATTERN = _TME + r"c/(\d+)(?:/(\d+))?(?:/(\d+))?/?"
# Canal público ou post dele: t.me/<username> ou t.me/<username>/<post>.
_PUBLIC_LINK_PATTERN = _TME + r"([^/?#]+)(?:/\d+)?/?"
_DISCOVERABLE_CHAT_TYPES = ("channel", "supergroup", "group")


@dataclass(frozen=True)
class ChatIdentifier:
    """Canal informado pelo operador, no formato que o getChat aceita: @username ou o chat_id -100..."""

    value: str
    message_thread_id: Optional[int] = None

    def __post_init__(self):
        if not (re.fullmatch("@" + _USERNAME_PATTERN, self.value) or re.fullmatch(CHANNEL_CHAT_ID_PATTERN, self.value)):
            raise ValueError("Invalid chat identifier (use @username, t.me/username, a post link t.me/c/... or the -100... chat ID)")

    @classmethod
    def parse(cls, raw: str) -> "ChatIdentifier":
        value = raw.strip()
        if re.fullmatch(_INVITE_LINK_PATTERN, value, re.IGNORECASE):
            raise ValueError("Invite links (t.me/+...) cannot be resolved by a bot: use the link of a post in the channel or the -100... chat ID")
        private_post = re.fullmatch(_PRIVATE_POST_LINK_PATTERN, value, re.IGNORECASE)
        public_link = re.fullmatch(_PUBLIC_LINK_PATTERN, value, re.IGNORECASE)
        thread_id: Optional[int] = None
        if private_post:
            value = f"-100{private_post.group(1)}"
            # Se houver 3 segmentos c/<chat>/<topic>/<msg>, o segundo é o tópico. Se houver 2 c/<chat>/<topic>, é o tópico/post.
            if private_post.group(3):
                thread_id = int(private_post.group(2))
            elif private_post.group(2):
                thread_id = int(private_post.group(2))
        elif public_link:
            value = f"@{public_link.group(1)}"
        elif not value.startswith(("@", "-")):
            value = f"@{value}"
        return cls(value, message_thread_id=thread_id)

    def as_chat_id(self) -> str:
        return self.value


@dataclass(frozen=True)
class DiscoveredChat:
    """Chat em que o bot está, como o Telegram o informou."""

    chat_id: str
    title: str
    chat_type: str
    username: Optional[str] = None
    # Supergrupo com tópicos ativados (#99).
    is_forum: bool = False
    message_thread_id: Optional[int] = None
    topic_name: Optional[str] = None

    def __post_init__(self):
        if not re.fullmatch(r"-\d+", self.chat_id) or self.chat_type not in _DISCOVERABLE_CHAT_TYPES:
            raise ValueError("Invalid discovered chat (expected a channel or group with a negative numeric id)")

    @property
    def kind(self) -> ChatType:
        return ChatType(self.chat_type)

    @property
    def is_registrable(self) -> bool:
        # Só canais e supergrupos (-100...) viram Channel; grupo comum aparece na lista, mas não pode ser vinculado.
        return bool(re.fullmatch(CHANNEL_CHAT_ID_PATTERN, self.chat_id))
