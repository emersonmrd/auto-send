import pytest
from src.application.create_profile_use_case import CreateProfileUseCase, CreateProfileDTO
from src.infrastructure.in_memory_repositories import InMemoryProfileRepository

class FakeTelegramGateway:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def validate_bot_token(self, token: str):
        if self.should_fail:
            raise ValueError("Token rejected")
        return {"id": 12345, "username": "valid_profile_bot", "is_bot": True}

    async def send_broadcast(self, bot_token: str, chat_id: str, message):
        return True

@pytest.mark.asyncio
async def test_should_create_profile_successfully_via_use_case():
    repo = InMemoryProfileRepository()
    gateway = FakeTelegramGateway()
    use_case = CreateProfileUseCase(profile_repo=repo, telegram_gateway=gateway)

    dto = CreateProfileDTO(
        name="Camila",
        bot_token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
        avatar_url="https://example.com/camila.png",
    )

    result = await use_case.execute(dto)
    assert result.name == "Camila"
    assert result.credentials.bot_username == "valid_profile_bot"
    assert result.avatar_url == "https://example.com/camila.png"

    saved = await repo.get_by_id(result.id)
    assert saved is not None
    assert saved.id == result.id

@pytest.mark.asyncio
async def test_should_fail_when_telegram_token_validation_fails():
    repo = InMemoryProfileRepository()
    gateway = FakeTelegramGateway(should_fail=True)
    use_case = CreateProfileUseCase(profile_repo=repo, telegram_gateway=gateway)

    dto = CreateProfileDTO(
        name="Invalid",
        bot_token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
    )

    with pytest.raises(ValueError, match="Token rejected"):
        await use_case.execute(dto)
