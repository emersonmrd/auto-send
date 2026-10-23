from typing import Dict, List, Optional
from src.domain.broadcast.broadcast_message import BroadcastMessage, BroadcastStatus
from src.domain.ports.broadcast_repository import IBroadcastRepository

class InMemoryBroadcastRepository(IBroadcastRepository):
    def __init__(self):
        self._broadcasts: Dict[str, BroadcastMessage] = {}

    async def save(self, broadcast: BroadcastMessage) -> None:
        self._broadcasts[broadcast.id] = broadcast

    async def get_by_id(self, broadcast_id: str) -> Optional[BroadcastMessage]:
        return self._broadcasts.get(broadcast_id)

    async def list_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        return [b for b in self._broadcasts.values() if b.profile_id == profile_id]

    async def get_scheduled_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        scheduled = [
            b for b in self._broadcasts.values()
            if b.profile_id == profile_id
            and b.status in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED]
            and b.scheduled_at is not None
        ]
        return sorted(scheduled, key=lambda b: b.scheduled_at)

    async def list_pending_scheduled(self) -> List[BroadcastMessage]:
        return [
            b for b in self._broadcasts.values()
            if b.status in [BroadcastStatus.PENDING, BroadcastStatus.SCHEDULED] and b.scheduled_at is not None
        ]
