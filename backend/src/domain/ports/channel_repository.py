from abc import ABC, abstractmethod
from typing import List, Optional
from src.domain.channels.channel import Channel

class IChannelRepository(ABC):
    @abstractmethod
    async def save(self, channel: Channel) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, channel_id: str) -> Optional[Channel]:
        pass

    @abstractmethod
    async def list_by_profile(self, profile_id: str) -> List[Channel]:
        pass

    @abstractmethod
    async def delete(self, channel_id: str) -> bool:
        pass
