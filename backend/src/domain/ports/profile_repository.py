from abc import ABC, abstractmethod
from typing import List, Optional
from src.domain.profiles.profile import Profile

class IProfileRepository(ABC):
    @abstractmethod
    async def save(self, profile: Profile) -> None:
        pass

    @abstractmethod
    async def get_by_id(self, profile_id: str) -> Optional[Profile]:
        pass

    @abstractmethod
    async def list_all(self) -> List[Profile]:
        pass

    @abstractmethod
    async def delete(self, profile_id: str) -> bool:
        pass
