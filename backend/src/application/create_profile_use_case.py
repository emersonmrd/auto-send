import uuid
from dataclasses import dataclass
from typing import Optional
from src.domain.profiles.profile import Profile
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.ports.profile_repository import IProfileRepository
from src.domain.ports.telegram_gateway import ITelegramGateway

@dataclass
class CreateProfileDTO:
    name: str
    bot_token: str
    avatar_url: Optional[str] = None

class CreateProfileUseCase:
    def __init__(self, profile_repo: IProfileRepository, telegram_gateway: ITelegramGateway):
        self.profile_repo = profile_repo
        self.telegram_gateway = telegram_gateway

    async def execute(self, dto: CreateProfileDTO) -> Profile:
        # 1. Valida o token e busca o username oficial via Telegram
        bot_info = await self.telegram_gateway.validate_bot_token(dto.bot_token)
        bot_username = bot_info.get("username", "")

        # 2. Cria a entidade de domínio
        credentials = BotCredentials(token=dto.bot_token, bot_username=bot_username)
        profile = Profile(
            id=str(uuid.uuid4()),
            name=dto.name,
            credentials=credentials,
            avatar_url=dto.avatar_url
        )

        # 3. Salva no repositório
        await self.profile_repo.save(profile)
        return profile
