from dataclasses import dataclass
from src.application.channel_classification import classify_from_telegram
from src.application.errors import (
    ChannelAlreadyRegisteredError,
    ChannelDispatchingError,
    ChannelNotFoundError,
    ProfileNotFoundError,
)
from src.domain.broadcast.broadcast_message import BroadcastStatus
from src.domain.channels.channel import Channel
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.chat_discovery_gateway import IChatDiscoveryGateway
from src.domain.ports.profile_repository import IProfileRepository


@dataclass(frozen=True)
class UpdateChannelCommand:
    channel_id: str
    title: str
    chat_id: str


class UpdateChannelUseCase:
    def __init__(
        self,
        profile_repo: IProfileRepository,
        channel_repo: IChannelRepository,
        broadcast_repo: IBroadcastRepository,
        discovery_gateway: IChatDiscoveryGateway,
    ):
        self.profile_repo = profile_repo
        self.channel_repo = channel_repo
        self.broadcast_repo = broadcast_repo
        self.discovery_gateway = discovery_gateway

    async def execute(self, command: UpdateChannelCommand) -> Channel:
        channel = await self.channel_repo.get_by_id(command.channel_id)
        if channel is None:
            raise ChannelNotFoundError(command.channel_id)
        # Chat_id inválido levanta ValueError antes de qualquer chamada ao Telegram.
        Channel.check_chat_id(command.chat_id)

        old_chat_id = channel.chat_id
        if command.chat_id != old_chat_id:
            await self._move_to_new_chat(channel, old_chat_id, command.chat_id)
        elif channel.chat_type is None:
            profile = await self.profile_repo.get_by_id(channel.profile_id)
            if profile is not None:
                await classify_from_telegram(channel, profile.credentials.token, self.discovery_gateway)

        channel.title = command.title
        await self.channel_repo.save(channel)
        return channel

    async def _move_to_new_chat(self, channel: Channel, old_chat_id: str, new_chat_id: str) -> None:
        siblings = await self.channel_repo.list_by_profile(channel.profile_id)
        if any(c.id != channel.id and c.chat_id == new_chat_id for c in siblings):
            raise ChannelAlreadyRegisteredError()
        broadcasts = await self.broadcast_repo.list_by_profile(channel.profile_id)
        if any(b.status == BroadcastStatus.DISPATCHING and old_chat_id in b.target_channel_ids for b in broadcasts):
            raise ChannelDispatchingError()

        profile = await self.profile_repo.get_by_id(channel.profile_id)
        if profile is None:
            raise ProfileNotFoundError(channel.profile_id)
        token = profile.credentials.token
        await self.discovery_gateway.ensure_bot_can_post(token, new_chat_id)

        for b in broadcasts:
            if b.is_pending_or_scheduled() and b.replace_target_channel(old_chat_id, new_chat_id):
                await self.broadcast_repo.save(b)
        channel.relink(new_chat_id)
        await classify_from_telegram(channel, token, self.discovery_gateway)
