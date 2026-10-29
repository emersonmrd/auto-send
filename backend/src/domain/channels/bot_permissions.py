from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Optional

from src.domain.channels.channel import Channel, ChatType


class BotMemberStatus(str, Enum):
    """Situação do bot no chat, como o getChatMember a informa (#107)."""

    CREATOR = "creator"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"


class SendContent(str, Enum):
    """Cada tipo de envio que o Telegram libera em separado (#107)."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    POLL = "poll"


@dataclass(frozen=True)
class SendPermissions:
    """O que um membro pode enviar: o padrão do grupo ou as permissões de um membro restrito."""

    can_send_messages: bool = False
    can_send_photos: bool = False
    can_send_videos: bool = False
    can_send_polls: bool = False


_ALL = SendPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_polls=True)
_NONE = SendPermissions()


def _effective_send_permissions(
    chat_type: ChatType,
    bot_status: BotMemberStatus,
    can_post_messages: bool,
    own: Optional[SendPermissions],
    chat_default: SendPermissions,
) -> SendPermissions:
    if bot_status is BotMemberStatus.CREATOR:
        return _ALL
    if chat_type is ChatType.CHANNEL:
        # Em canal só publica o administrador com permissão de publicar.
        return _ALL if bot_status is BotMemberStatus.ADMINISTRATOR and can_post_messages else _NONE
    if bot_status is BotMemberStatus.ADMINISTRATOR:
        return _ALL
    if bot_status is BotMemberStatus.MEMBER:
        return chat_default
    if bot_status is BotMemberStatus.RESTRICTED and own is not None:
        # O restrito precisa da própria permissão e da do grupo.
        return SendPermissions(
            can_send_messages=own.can_send_messages and chat_default.can_send_messages,
            can_send_photos=own.can_send_photos and chat_default.can_send_photos,
            can_send_videos=own.can_send_videos and chat_default.can_send_videos,
            can_send_polls=own.can_send_polls and chat_default.can_send_polls,
        )
    return _NONE


@dataclass(frozen=True)
class BotPermissions:
    """O que o bot pode enviar a um destino, lido do Telegram em checked_at (#107)."""

    # None: canal vinculado antes da #99, ainda sem tipo, quando o Telegram não responde pelo chat.
    chat_type: Optional[ChatType]
    is_forum: bool
    bot_status: BotMemberStatus
    checked_at: datetime
    can_send_messages: bool = False
    can_send_photos: bool = False
    can_send_videos: bool = False
    can_send_polls: bool = False

    def __post_init__(self):
        Channel._check_kind(self.chat_type, self.is_forum)
        if self.checked_at.utcoffset() != timedelta(0):
            raise ValueError("checked_at must be in UTC")

    @property
    def is_outside_chat(self) -> bool:
        return self.bot_status in (BotMemberStatus.LEFT, BotMemberStatus.KICKED)

    def denied(self, contents: Iterable[SendContent]) -> Optional[SendContent]:
        """O primeiro conteúdo, na ordem dada, que o bot não pode enviar; None se pode todos."""
        allowed = {
            SendContent.TEXT: self.can_send_messages,
            SendContent.PHOTO: self.can_send_photos,
            SendContent.VIDEO: self.can_send_videos,
            SendContent.POLL: self.can_send_polls,
        }
        return next((c for c in contents if not allowed[c]), None)

    @classmethod
    def evaluate(
        cls,
        *,
        chat_type: ChatType,
        is_forum: bool,
        bot_status: BotMemberStatus,
        can_post_messages: bool,
        own: Optional[SendPermissions],
        chat_default: SendPermissions,
        checked_at: datetime,
    ) -> "BotPermissions":
        sends = _effective_send_permissions(chat_type, bot_status, can_post_messages, own, chat_default)
        return cls(
            chat_type=chat_type,
            is_forum=is_forum,
            bot_status=bot_status,
            checked_at=checked_at,
            can_send_messages=sends.can_send_messages,
            can_send_photos=sends.can_send_photos,
            can_send_videos=sends.can_send_videos,
            can_send_polls=sends.can_send_polls,
        )

    @classmethod
    def outside_chat(cls, *, chat_type: Optional[ChatType], is_forum: bool, checked_at: datetime) -> "BotPermissions":
        # O Telegram recusou a consulta (bot removido ou chat apagado): o tipo é o que estava salvo.
        return cls(chat_type=chat_type, is_forum=is_forum, bot_status=BotMemberStatus.LEFT, checked_at=checked_at)
