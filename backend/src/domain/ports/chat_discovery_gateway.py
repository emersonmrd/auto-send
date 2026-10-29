from abc import ABC, abstractmethod
from typing import List
from src.domain.channels.chat_discovery import DiscoveredChat, ChatIdentifier


class ChatDiscoveryError(Exception):
    """O Telegram não atendeu a descoberta ou a resolução (bot sem acesso, webhook ativo, rede). Sem token na mensagem."""


class WebhookActiveError(ChatDiscoveryError):
    """O bot tem webhook ativo (outro sistema recebe os updates): a descoberta automática não funciona, o getChat sim."""


class BotInUseError(ChatDiscoveryError):
    """Outro programa está lendo os updates deste bot em paralelo (409 'terminated by other getUpdates request', #32)."""


class BotNotChannelAdminError(ChatDiscoveryError):
    """O bot não está no canal ou não é administrador com permissão de publicar (getChatMember, #2)."""


class BotCannotSendInGroupError(BotNotChannelAdminError):
    """O bot está no grupo, mas o grupo não deixa ele enviar mensagens (permissões de membro, #100)."""


class TelegramUnavailableError(ChatDiscoveryError):
    """O Telegram não respondeu ou falhou (rede, timeout, 429, 5xx ou circuito aberto, #2)."""


class IChatDiscoveryGateway(ABC):
    @abstractmethod
    async def discover_chats(self, bot_token: str) -> List[DiscoveredChat]:
        """Chats (canais e grupos) em que o bot está, pelos updates pendentes, sem confirmá-los."""
        pass

    @abstractmethod
    async def resolve_chat(self, bot_token: str, identifier: ChatIdentifier) -> DiscoveredChat:
        """Chat pelo @username ou pelo chat_id -100... (getChat)."""
        pass

    @abstractmethod
    async def ensure_bot_can_post(self, bot_token: str, chat_id: str) -> None:
        """Confere que o bot pode postar: em canal, administrador com permissão de publicar (#2); em grupo, basta
        ser membro que o grupo deixa enviar mensagens (#100)."""
        pass
