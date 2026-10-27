from abc import ABC, abstractmethod
from typing import List, Optional
from src.domain.broadcast.message_template import MessageTemplate


class IMessageTemplateRepository(ABC):
    @abstractmethod
    async def save(self, template: MessageTemplate) -> None:
        """Salva ou atualiza um modelo de mensagem."""
        pass

    @abstractmethod
    async def get_by_id(self, template_id: str) -> Optional[MessageTemplate]:
        """Recupera um modelo pelo ID."""
        pass

    @abstractmethod
    async def list_by_profile(self, profile_id: str) -> List[MessageTemplate]:
        """Lista todos os modelos de mensagem associados a um perfil ordenados por criação desc."""
        pass

    @abstractmethod
    async def delete(self, template_id: str) -> bool:
        """Remove um modelo pelo ID. Retorna True se existia e foi removido."""
        pass
