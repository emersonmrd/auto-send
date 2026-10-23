from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

# Canal ou supergrupo do Telegram: -100 seguido de dígitos.
CHANNEL_CHAT_ID_PATTERN = r"^-100\d{9,}$"

@dataclass
class Channel:
    id: str
    profile_id: str
    title: str
    chat_id: str
    invite_link: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        # Validação do formato de chat_id do Telegram (normalmente começa com -100 para canais ou supergrupos)
        if not re.match(CHANNEL_CHAT_ID_PATTERN, self.chat_id):
            raise ValueError("Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)")

