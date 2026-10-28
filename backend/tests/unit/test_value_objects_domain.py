"""Contrato dos valores do domínio: strings dos enums (gravadas no banco e expostas na API), imutabilidade dos
value objects, valores padrão e mensagens de erro exatas (viram o `detail` das respostas 422)."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastPoll,
    BroadcastStatus,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    DispatchStrategy,
    InlineButton,
    MediaAttachment,
    MediaType,
    PollType,
)
from src.domain.channels.channel import Channel
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile

VALID_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ12345"


def _raises_exactly(message, fn, *args, **kwargs):
    with pytest.raises(ValueError) as exc:
        fn(*args, **kwargs)
    assert str(exc.value) == message


def _assert_recent_utc(moment):
    assert moment.tzinfo == timezone.utc
    assert abs(datetime.now(timezone.utc) - moment) < timedelta(seconds=5)


def test_enum_values_are_the_persisted_strings():
    assert {m.name: m.value for m in MediaType} == {"VIDEO": "VIDEO", "PHOTO": "PHOTO"}
    assert {m.name: m.value for m in PollType} == {"REGULAR": "regular", "QUIZ": "quiz"}
    assert {m.name: m.value for m in DispatchStrategy} == {
        "TEXT_ONLY": "TEXT_ONLY",
        "SINGLE_MEDIA_WITH_CAPTION": "SINGLE_MEDIA_WITH_CAPTION",
        "SPLIT_TEXT_THEN_MEDIA": "SPLIT_TEXT_THEN_MEDIA",
        "POLL": "POLL",
    }
    assert {m.name: m.value for m in BroadcastStatus} == {
        "PENDING": "PENDING",
        "SCHEDULED": "SCHEDULED",
        "MISFIRED": "MISFIRED",
        "DISPATCHING": "DISPATCHING",
        "COMPLETED": "COMPLETED",
        "PARTIALLY_COMPLETED": "PARTIALLY_COMPLETED",
        "FAILED": "FAILED",
        "CANCELLED": "CANCELLED",
    }
    assert {m.name: m.value for m in DeliveryFailureCategory} == {
        "BOT_NOT_IN_CHAT": "BOT_NOT_IN_CHAT",
        "NO_POST_PERMISSION": "NO_POST_PERMISSION",
        "INVALID_TOKEN": "INVALID_TOKEN",
        "RATE_LIMITED": "RATE_LIMITED",
        "TELEGRAM_UNAVAILABLE": "TELEGRAM_UNAVAILABLE",
        "OTHER": "OTHER",
    }


def test_value_objects_are_immutable():
    button = InlineButton(text="Saiba mais", url="https://t.me/+news")
    media = MediaAttachment(file_path="/tmp/v.mp4", media_type=MediaType.VIDEO, file_size=1)
    credentials = BotCredentials(token=VALID_TOKEN, bot_username="acme_bot")
    delivery_result = ChannelDeliveryResult.success("-1001234567890")
    poll = BroadcastPoll(question="Pergunta?", options=["Opção 1", "Opção 2"])

    with pytest.raises(FrozenInstanceError):
        button.url = "https://evil.example"
    with pytest.raises(FrozenInstanceError):
        media.file_path = "/etc/passwd"
    with pytest.raises(FrozenInstanceError):
        credentials.token = "leaked"
    with pytest.raises(FrozenInstanceError):
        delivery_result.delivered = False
    with pytest.raises(FrozenInstanceError):
        poll.question = "Modificado"


def test_media_attachment_metadata_defaults_to_none():
    media = MediaAttachment(file_path="/tmp/p.jpg", media_type=MediaType.PHOTO, file_size=1)
    assert (media.duration, media.width, media.height, media.thumbnail_path) == (None, None, None, None)


def test_broadcast_message_defaults():
    msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001234567890"])
    assert msg.text == ""
    assert msg.media is None
    assert msg.button is None
    assert msg.poll is None
    assert msg.status is BroadcastStatus.PENDING
    assert msg.scheduled_at is None
    assert msg.delivery_results == []
    _assert_recent_utc(msg.created_at)


def test_channel_defaults():
    channel = Channel(id="c", profile_id="p", title="Novidades", chat_id="-1001234567890")
    assert channel.invite_link == ""
    assert channel.is_active is True
    _assert_recent_utc(channel.created_at)


def test_profile_defaults():
    profile = Profile(id="p", name="Acme", credentials=BotCredentials(token=VALID_TOKEN, bot_username="acme_bot"))
    assert profile.avatar_url is None
    assert profile.is_active is True
    _assert_recent_utc(profile.created_at)


def test_validation_error_messages_are_exact():
    _raises_exactly("Insecure or invalid URL scheme. Only https:// allowed.", InlineButton, text="t", url="http://a.com")
    _raises_exactly(
        "Insecure or invalid URL scheme: Private network prohibited.", InlineButton, text="t", url="https://localhost/"
    )
    _raises_exactly("Insecure or invalid URL scheme: Private IP prohibited.", InlineButton, text="t", url="https://10.0.0.1/")
    _raises_exactly(
        "Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)",
        Channel,
        id="c",
        profile_id="p",
        title="t",
        chat_id="123",
    )
    _raises_exactly("Invalid Telegram Bot Token format", BotCredentials, token="bad", bot_username="b")


def test_lifecycle_error_messages_are_exact():
    msg = BroadcastMessage(id="b", profile_id="p", target_channel_ids=["-1001234567890"], status=BroadcastStatus.COMPLETED)
    _raises_exactly("Cannot cancel an in-flight or completed broadcast", msg.cancel)
    _raises_exactly(
        "Cannot reschedule an in-flight, completed, or cancelled broadcast",
        msg.reschedule,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    _raises_exactly("Cannot update content of an in-flight, completed, or cancelled broadcast", msg.update_content, "x")
