from typing import Dict, List, Optional
from src.domain.profiles.profile import Profile
from src.domain.ports.profile_repository import IProfileRepository
from src.domain.channels.channel import Channel
from src.domain.ports.channel_repository import IChannelRepository

class InMemoryProfileRepository(IProfileRepository):
    def __init__(self):
        self._profiles: Dict[str, Profile] = {}

    async def save(self, profile: Profile) -> None:
        self._profiles[profile.id] = profile

    async def get_by_id(self, profile_id: str) -> Optional[Profile]:
        return self._profiles.get(profile_id)

    async def list_all(self) -> List[Profile]:
        return list(self._profiles.values())

    async def delete(self, profile_id: str) -> bool:
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            return True
        return False

class InMemoryChannelRepository(IChannelRepository):
    def __init__(self):
        self._channels: Dict[str, Channel] = {}

    async def save(self, channel: Channel) -> None:
        self._channels[channel.id] = channel

    async def get_by_id(self, channel_id: str) -> Optional[Channel]:
        return self._channels.get(channel_id)

    async def list_by_profile(self, profile_id: str) -> List[Channel]:
        return [c for c in self._channels.values() if c.profile_id == profile_id]

    async def delete(self, channel_id: str) -> bool:
        if channel_id in self._channels:
            del self._channels[channel_id]
            return True
        return False
