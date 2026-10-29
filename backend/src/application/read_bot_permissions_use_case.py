from datetime import datetime, timezone
from typing import Callable

from src.application.errors import ChannelNotFoundError, ProfileNotFoundError
from src.domain.channels.bot_permissions import BotPermissions
from src.domain.ports.bot_permissions_gateway import IBotPermissionsGateway
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.chat_discovery_gateway import BotNotChannelAdminError
from src.domain.ports.profile_repository import IProfileRepository


class ReadBotPermissionsUseCase:
    """O que o bot do perfil pode enviar a um destino, lido do Telegram na hora (#107)."""

    def __init__(
        self,
        profile_repo: IProfileRepository,
        channel_repo: IChannelRepository,
        gateway: IBotPermissionsGateway,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.profile_repo = profile_repo
        self.channel_repo = channel_repo
        self.gateway = gateway
        self.clock = clock

    async def execute(self, channel_id: str) -> BotPermissions:
        channel = await self.channel_repo.get_by_id(channel_id)
        if channel is None:
            raise ChannelNotFoundError(channel_id)
        profile = await self.profile_repo.get_by_id(channel.profile_id)
        if profile is None:
            raise ProfileNotFoundError(channel.profile_id)
        try:
            return await self.gateway.read_bot_permissions(profile.credentials.token, channel.chat_id)
        except BotNotChannelAdminError:
            # O Telegram recusou a consulta: o bot saiu ou foi removido do chat.
            return BotPermissions.outside_chat(chat_type=channel.chat_type, is_forum=channel.is_forum, checked_at=self.clock())
