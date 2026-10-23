from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from src.domain.profiles.bot_credentials import BotCredentials

@dataclass
class Profile:
    id: str
    name: str
    credentials: BotCredentials
    avatar_url: Optional[str] = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False
