from abc import ABC, abstractmethod
from typing import List, Optional
from src.domain.broadcast.broadcast_message import BroadcastMessage

class IBroadcastRepository(ABC):
    @abstractmethod
    async def save(self, broadcast: BroadcastMessage) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, broadcast_id: str) -> Optional[BroadcastMessage]:
        pass

    @abstractmethod
    async def list_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        pass

    @abstractmethod
    async def get_scheduled_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        pass

    @abstractmethod
    async def list_pending_scheduled(self) -> List[BroadcastMessage]:
        pass
