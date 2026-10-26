import pytest
from src.application.discover_chats_use_case import DiscoverChatsUseCase
from src.application.errors import ProfileNotFoundError
from src.application.resolve_chat_use_case import ResolveChatUseCase
from src.domain.channels.channel import Channel
from src.domain.channels.chat_discovery import DiscoveredChat, ChatIdentifier
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, IChatDiscoveryGateway
from src.infrastructure.in_memory_repositories import InMemoryChannelRepository, InMemoryProfileRepository

TOKEN = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
CHANNEL = DiscoveredChat(chat_id="-1001234567890", title="Canal de Novidades", chat_type="channel", username="canalnovidades")
NEWS = DiscoveredChat(chat_id="-1009876543210", title="Novidades", chat_type="channel")


class FakeDiscoveryGateway(IChatDiscoveryGateway):
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple] = []

    async def discover_chats(self, bot_token):
        self.calls.append(("discover", bot_token))
        if self.error:
            raise self.error
        return [CHANNEL, NEWS]

    async def resolve_chat(self, bot_token, identifier):
        self.calls.append(("resolve", bot_token, identifier))
        if self.error:
            raise self.error
        return CHANNEL

    async def ensure_bot_can_post(self, bot_token, chat_id):
        self.calls.append(("ensure_bot_can_post", bot_token, chat_id))
        if self.error:
            raise self.error


@pytest.fixture
async def repos():
    profiles = InMemoryProfileRepository()
    channels = InMemoryChannelRepository()
    await profiles.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    return profiles, channels


async def test_discover_returns_chats_of_the_profile_bot_marking_registered_ones(repos):
    profiles, channels = repos
    await channels.save(Channel(id="c-1", profile_id="p-1", title="Canal de Novidades", chat_id=CHANNEL.chat_id))
    gateway = FakeDiscoveryGateway()

    result = await DiscoverChatsUseCase(profiles, channels, gateway).execute("p-1")

    assert gateway.calls == [("discover", TOKEN)]
    assert [(v.chat, v.already_registered) for v in result] == [(CHANNEL, True), (NEWS, False)]


async def test_discover_does_not_mark_channels_of_another_profile(repos):
    profiles, channels = repos
    await channels.save(Channel(id="c-9", profile_id="p-2", title="Canal de Novidades", chat_id=CHANNEL.chat_id))

    result = await DiscoverChatsUseCase(profiles, channels, FakeDiscoveryGateway()).execute("p-1")

    assert [v.already_registered for v in result] == [False, False]


async def test_discover_for_missing_profile_does_not_call_telegram(repos):
    profiles, channels = repos
    gateway = FakeDiscoveryGateway()

    with pytest.raises(ProfileNotFoundError):
        await DiscoverChatsUseCase(profiles, channels, gateway).execute("nao-existe")
    assert gateway.calls == []


async def test_discover_propagates_telegram_refusal(repos):
    profiles, channels = repos
    gateway = FakeDiscoveryGateway(error=ChatDiscoveryError("Unauthorized"))

    with pytest.raises(ChatDiscoveryError, match="Unauthorized"):
        await DiscoverChatsUseCase(profiles, channels, gateway).execute("p-1")


async def test_resolve_parses_the_identifier_and_uses_the_profile_bot(repos):
    profiles, _ = repos
    gateway = FakeDiscoveryGateway()

    chat = await ResolveChatUseCase(profiles, gateway).execute("p-1", "https://t.me/canalnovidades")

    assert chat == CHANNEL
    assert gateway.calls == [("resolve", TOKEN, ChatIdentifier("@canalnovidades"))]


async def test_resolve_rejects_invalid_identifier_before_calling_telegram(repos):
    profiles, _ = repos
    gateway = FakeDiscoveryGateway()

    for raw in ("https://t.me/+convite", "@x"):
        with pytest.raises(ValueError, match="cannot be resolved by a bot|Invalid chat identifier"):
            await ResolveChatUseCase(profiles, gateway).execute("p-1", raw)
    assert gateway.calls == []


async def test_resolve_converts_a_private_post_link_to_the_channel_id(repos):
    profiles, _ = repos
    gateway = FakeDiscoveryGateway()

    await ResolveChatUseCase(profiles, gateway).execute("p-1", "https://t.me/c/1234567890/15")

    assert gateway.calls == [("resolve", TOKEN, ChatIdentifier("-1001234567890"))]


async def test_resolve_for_missing_profile_does_not_call_telegram(repos):
    profiles, _ = repos
    gateway = FakeDiscoveryGateway()

    with pytest.raises(ProfileNotFoundError):
        await ResolveChatUseCase(profiles, gateway).execute("nao-existe", "@canalnovidades")
    assert gateway.calls == []
