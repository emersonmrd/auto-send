from dataclasses import dataclass
import uuid

from src.application.channel_classification import classify_from_telegram
from src.application.errors import ChannelAlreadyRegisteredError, ProfileNotFoundError
from src.domain.channels.channel import Channel
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.chat_discovery_gateway import IChatDiscoveryGateway
from src.domain.ports.profile_repository import IProfileRepository


@dataclass(frozen=True)
class RegisterChannelCommand:
    profile_id: str
    title: str
    chat_id: str
    invite_link: str = ""


class RegisterChannelUseCase:
    def __init__(
        self,
        profile_repo: IProfileRepository,
        channel_repo: IChannelRepository,
        discovery_gateway: IChatDiscoveryGateway,
    ):
        self.profile_repo = profile_repo
        self.channel_repo = channel_repo
        self.discovery_gateway = discovery_gateway

    async def execute(self, command: RegisterChannelCommand) -> Channel:
        profile = await self.profile_repo.get_by_id(command.profile_id)
        if profile is None:
            raise ProfileNotFoundError(command.profile_id)

        existing = await self.channel_repo.list_by_profile(command.profile_id)
        if any(c.chat_id == command.chat_id for c in existing):
            raise ChannelAlreadyRegisteredError()

        # Chat_id inválido levanta ValueError antes de qualquer chamada ao Telegram.
        channel = Channel(
            id=str(uuid.uuid4()),
            profile_id=command.profile_id,
            title=command.title,
            chat_id=command.chat_id,
            invite_link=command.invite_link,
        )
        token = profile.credentials.token
        await self.discovery_gateway.ensure_bot_can_post(token, channel.chat_id)
        await classify_from_telegram(channel, token, self.discovery_gateway)
        await self.channel_repo.save(channel)
        return channel
