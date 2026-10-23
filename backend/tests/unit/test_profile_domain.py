import pytest
from src.domain.profiles.profile import Profile
from src.domain.profiles.bot_credentials import BotCredentials

def test_should_create_profile_with_valid_data():
    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="acme_bot")
    profile = Profile(
        id="profile-1",
        name="Acme",
        avatar_url="https://example.com/avatar.jpg",
        credentials=creds,
    )
    
    assert profile.id == "profile-1"
    assert profile.name == "Acme"
    assert profile.credentials.bot_username == "acme_bot"
    assert profile.is_active is True

def test_should_activate_and_deactivate_profile():
    creds = BotCredentials(token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz", bot_username="acme_bot")
    profile = Profile(id="profile-1", name="Acme", credentials=creds)
    
    profile.deactivate()
    assert profile.is_active is False
    profile.activate()
    assert profile.is_active is True

def test_should_fail_when_token_is_empty_or_malformed():
    with pytest.raises(ValueError, match="Invalid Telegram Bot Token format"):
        BotCredentials(token="invalid_token", bot_username="test_bot")

    with pytest.raises(ValueError, match="Invalid Telegram Bot Token format"):
        BotCredentials(token="12345", bot_username="test_bot")
