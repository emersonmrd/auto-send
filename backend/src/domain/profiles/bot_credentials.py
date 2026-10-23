import re
from dataclasses import dataclass

@dataclass(frozen=True)
class BotCredentials:
    token: str
    bot_username: str

    def __post_init__(self):
        # Tokens do bot do Telegram têm formato: 8 a 10 dígitos : string alfanumérica de 30-40 caracteres
        token_pattern = r"^\d{8,12}:[A-Za-z0-9_-]{20,}$"
        if not re.match(token_pattern, self.token):
            raise ValueError("Invalid Telegram Bot Token format")

