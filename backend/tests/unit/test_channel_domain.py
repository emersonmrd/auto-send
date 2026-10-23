import pytest
from src.domain.channels.channel import Channel

def test_should_create_valid_channel():
    c = Channel(
        id="c-1",
        profile_id="p-1",
        title="Canal de Novidades",
        chat_id="-1001234567890",
        invite_link="https://t.me/+xyz",
    )
    assert c.id == "c-1"
    assert c.title == "Canal de Novidades"
    assert c.chat_id == "-1001234567890"
    assert c.is_active is True

def test_should_fail_when_chat_id_is_invalid():
    with pytest.raises(ValueError, match="Invalid Telegram Channel Chat ID format"):
        Channel(
            id="c-2",
            profile_id="p-1",
            title="Invalid",
            chat_id="123456",
        )

    with pytest.raises(ValueError, match="Invalid Telegram Channel Chat ID format"):
        Channel(
            id="c-3",
            profile_id="p-1",
            title="Invalid",
            chat_id="-200123456789",
        )
