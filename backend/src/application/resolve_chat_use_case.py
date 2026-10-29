from src.application.errors import ProfileNotFoundError
from src.domain.channels.chat_discovery import DiscoveredChat, ChatIdentifier
from src.domain.ports.chat_discovery_gateway import IChatDiscoveryGateway
from src.domain.ports.profile_repository import IProfileRepository


class ResolveChatUseCase:
    def __init__(self, profile_repo: IProfileRepository, discovery_gateway: IChatDiscoveryGateway):
        self.profile_repo = profile_repo
        self.discovery_gateway = discovery_gateway

    async def execute(self, profile_id: str, raw_identifier: str) -> DiscoveredChat:
        # Identificador inválido levanta ValueError antes de qualquer chamada ao Telegram.
        identifier = ChatIdentifier.parse(raw_identifier)
        profile = await self.profile_repo.get_by_id(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        chat = await self.discovery_gateway.resolve_chat(profile.credentials.token, identifier)
        if identifier.message_thread_id is not None and chat.is_forum:
            return DiscoveredChat(
                chat_id=chat.chat_id,
                title=chat.title,
                chat_type=chat.chat_type,
                username=chat.username,
                is_forum=chat.is_forum,
                message_thread_id=identifier.message_thread_id,
                topic_name=chat.topic_name,
            )
        return chat
