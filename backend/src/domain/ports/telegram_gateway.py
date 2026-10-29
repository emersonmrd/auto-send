from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional
from src.domain.broadcast.broadcast_message import BroadcastMessage

class ITelegramGateway(ABC):
    @abstractmethod
    async def validate_bot_token(self, token: str) -> Dict[str, Any]:
        """Chama getMe do Telegram e retorna os dados do bot ou levanta exceção se inválido"""
        pass

    @abstractmethod
    async def send_broadcast(
        self,
        bot_token: str,
        chat_id: str,
        message: BroadcastMessage,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        file_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
    ) -> bool:
        """Despacha a mensagem para o chat_id respeitando a estratégia (legenda ou divisão)"""
        pass
