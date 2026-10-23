from abc import ABC, abstractmethod
from typing import List
from src.domain.channels.chat_discovery import DiscoveredChat, PublicChatIdentifier


class ChatDiscoveryError(Exception):
    """O Telegram não atendeu a descoberta ou a resolução (bot sem acesso, webhook ativo, rede). Sem token na mensagem."""


class IChatDiscoveryGateway(ABC):
    @abstractmethod
    async def discover_chats(self, bot_token: str) -> List[DiscoveredChat]:
        """Chats (canais e grupos) em que o bot está, pelos updates pendentes, sem confirmá-los."""
        pass

    @abstractmethod
    async def resolve_chat(self, bot_token: str, identifier: PublicChatIdentifier) -> DiscoveredChat:
        """Chat público pelo @username."""
        pass
