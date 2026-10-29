from abc import ABC, abstractmethod

from src.domain.channels.bot_permissions import BotPermissions


class IBotPermissionsGateway(ABC):
    @abstractmethod
    async def read_bot_permissions(self, bot_token: str, chat_id: str) -> BotPermissions:
        """O que o bot pode enviar ao chat agora (getChatMember e getChat, #107). Bot fora do chat ou chat
        inexistente levanta BotNotChannelAdminError; Telegram fora do ar, TelegramUnavailableError."""
        pass
