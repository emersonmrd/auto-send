from datetime import datetime, timezone

import pytest
from src.application.errors import ChannelNotFoundError, ProfileNotFoundError
from src.application.read_bot_permissions_use_case import ReadBotPermissionsUseCase
from src.domain.channels.bot_permissions import BotMemberStatus, BotPermissions
from src.domain.channels.channel import Channel, ChatType
from src.domain.ports.bot_permissions_gateway import IBotPermissionsGateway
from src.domain.ports.chat_discovery_gateway import BotNotChannelAdminError, TelegramUnavailableError
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_repositories import InMemoryChannelRepository, InMemoryProfileRepository

TOKEN = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
CHAT_ID = "-1001234567890"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
READ = BotPermissions(
    chat_type=ChatType.SUPERGROUP, is_forum=False, bot_status=BotMemberStatus.MEMBER, checked_at=NOW, can_send_messages=True
)


class FakeGateway(IBotPermissionsGateway):
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def read_bot_permissions(self, bot_token, chat_id):
        self.calls.append((bot_token, chat_id))
        if self.error:
            raise self.error
        return READ


async def setup(chat_type=ChatType.SUPERGROUP, is_forum=False, with_profile=True):
    profiles, channels = InMemoryProfileRepository(), InMemoryChannelRepository()
    if with_profile:
        await profiles.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    await channels.save(Channel(id="c-1", profile_id="p-1", title="Grupo", chat_id=CHAT_ID, chat_type=chat_type, is_forum=is_forum))
    return profiles, channels


async def test_reads_the_permissions_with_the_profile_token_and_the_channel_chat_id():
    profiles, channels = await setup()
    gateway = FakeGateway()

    result = await ReadBotPermissionsUseCase(profiles, channels, gateway, clock=lambda: NOW).execute("c-1")

    assert result is READ
    assert gateway.calls == [(TOKEN, CHAT_ID)]


async def test_unknown_channel_is_not_found():
    profiles, channels = await setup()
    gateway = FakeGateway()
    with pytest.raises(ChannelNotFoundError):
        await ReadBotPermissionsUseCase(profiles, channels, gateway).execute("missing")
    assert gateway.calls == []


async def test_channel_without_profile_is_profile_not_found():
    profiles, channels = await setup(with_profile=False)
    with pytest.raises(ProfileNotFoundError):
        await ReadBotPermissionsUseCase(profiles, channels, FakeGateway()).execute("c-1")


@pytest.mark.parametrize("chat_type, is_forum", [(ChatType.SUPERGROUP, True), (ChatType.CHANNEL, False), (None, False)])
async def test_bot_outside_the_chat_keeps_the_saved_kind(chat_type, is_forum):
    profiles, channels = await setup(chat_type=chat_type, is_forum=is_forum)
    gateway = FakeGateway(BotNotChannelAdminError("Bot is not administrator in the channel"))

    result = await ReadBotPermissionsUseCase(profiles, channels, gateway, clock=lambda: NOW).execute("c-1")

    assert result == BotPermissions.outside_chat(chat_type=chat_type, is_forum=is_forum, checked_at=NOW)


def test_default_clock_is_utc_now():
    clock = ReadBotPermissionsUseCase(None, None, None).clock
    assert clock().tzinfo is timezone.utc


async def test_telegram_unavailable_propagates():
    profiles, channels = await setup()
    with pytest.raises(TelegramUnavailableError):
        await ReadBotPermissionsUseCase(profiles, channels, FakeGateway(TelegramUnavailableError("x"))).execute("c-1")
