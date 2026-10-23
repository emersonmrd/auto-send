from dataclasses import dataclass
from typing import List
from src.application.errors import ProfileNotFoundError
from src.domain.channels.chat_discovery import DiscoveredChat
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.chat_discovery_gateway import IChatDiscoveryGateway
from src.domain.ports.profile_repository import IProfileRepository


@dataclass(frozen=True)
class DiscoveredChatView:
    chat: DiscoveredChat
    already_registered: bool


class DiscoverChatsUseCase:
    def __init__(
        self,
        profile_repo: IProfileRepository,
        channel_repo: IChannelRepository,
        discovery_gateway: IChatDiscoveryGateway,
    ):
        self.profile_repo = profile_repo
        self.channel_repo = channel_repo
        self.discovery_gateway = discovery_gateway

    async def execute(self, profile_id: str) -> List[DiscoveredChatView]:
        profile = await self.profile_repo.get_by_id(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)

        chats = await self.discovery_gateway.discover_chats(profile.credentials.token)
        registered = {c.chat_id for c in await self.channel_repo.list_by_profile(profile_id)}
        return [DiscoveredChatView(chat=c, already_registered=c.chat_id in registered) for c in chats]
