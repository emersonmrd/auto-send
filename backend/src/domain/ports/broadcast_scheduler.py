from abc import ABC, abstractmethod
from datetime import datetime


class IBroadcastScheduler(ABC):
    """Agenda o disparo de um broadcast; o job tem id broadcast_{id} e reagendar o substitui (AGENTS.md §12)."""

    @abstractmethod
    def schedule_broadcast(self, broadcast_id: str, run_date: datetime) -> str:
        pass

    @abstractmethod
    def reschedule_broadcast(self, broadcast_id: str, new_run_date: datetime) -> None:
        pass
