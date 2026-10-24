import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from src.domain.channels.channel import Channel
from src.domain.channels.chat_discovery import DiscoveredChat
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, IChatDiscoveryGateway, WebhookActiveError
from src.infrastructure.resilience import CircuitBreakerOpenException
from src.infrastructure.sqlite_repositories import Base
from src.presentation.main import app, channel_repo, engine, get_chat_discovery_gateway, profile_repo

TOKEN = "1234567890:SecretTokenThatMustNeverLeak_42"
CHANNEL = DiscoveredChat(chat_id="-1001234567890", title="Canal de Novidades", chat_type="channel", username="canalnovidades")
GROUP = DiscoveredChat(chat_id="-444444444", title="Grupo comum", chat_type="group")


class StubGateway(IChatDiscoveryGateway):
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.resolved: list[str] = []

    async def discover_chats(self, bot_token):
        if self.error:
            raise self.error
        return [CHANNEL, GROUP]

    async def resolve_chat(self, bot_token, identifier):
        if self.error:
            raise self.error
        self.resolved.append(identifier.as_chat_id())
        return CHANNEL


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await profile_repo.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def use_gateway(gateway: IChatDiscoveryGateway) -> IChatDiscoveryGateway:
    app.dependency_overrides[get_chat_discovery_gateway] = lambda: gateway
    return gateway


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_discover_lists_chats_marking_registered_and_registrable(client):
    use_gateway(StubGateway())
    await channel_repo.save(Channel(id="c-1", profile_id="p-1", title="Canal de Novidades", chat_id=CHANNEL.chat_id))

    resp = await client.post("/api/v1/profiles/p-1/discover-chats")

    assert resp.status_code == 200
    assert resp.json() == {
        "chats": [
            {"chat_id": "-1001234567890", "title": "Canal de Novidades", "type": "channel", "username": "canalnovidades", "registrable": True, "already_registered": True},
            {"chat_id": "-444444444", "title": "Grupo comum", "type": "group", "username": None, "registrable": False, "already_registered": False},
        ]
    }
    assert TOKEN not in resp.text


async def test_discover_for_missing_profile_is_404(client):
    use_gateway(StubGateway())
    resp = await client.post("/api/v1/profiles/nao-existe/discover-chats")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Profile not found"}


@pytest.mark.parametrize(
    "error",
    [
        ChatDiscoveryError("Telegram API error (401): Unauthorized"),
        WebhookActiveError("Bot webhook is active: automatic discovery is unavailable"),
        CircuitBreakerOpenException(retry_after=25),
    ],
)
async def test_discover_telegram_refusal_is_400_with_reason(client, error):
    use_gateway(StubGateway(error=error))
    resp = await client.post("/api/v1/profiles/p-1/discover-chats")
    assert resp.status_code == 400
    assert resp.json()["detail"] == str(error)


async def test_resolve_returns_the_chat(client):
    gateway = use_gateway(StubGateway())

    resp = await client.post("/api/v1/profiles/p-1/resolve-chat", json={"identifier": "t.me/canalnovidades"})

    assert resp.status_code == 200
    assert resp.json() == {"chat_id": "-1001234567890", "title": "Canal de Novidades", "type": "channel", "username": "canalnovidades", "registrable": True}
    assert gateway.resolved == ["@canalnovidades"]


@pytest.mark.parametrize(
    "identifier, chat_id",
    [
        ("https://t.me/c/1234567890/15", "-1001234567890"),
        ("-1001234567890", "-1001234567890"),
        ("@canalnovidades", "@canalnovidades"),
        ("https://t.me/canalnovidades/42", "@canalnovidades"),
    ],
)
async def test_resolve_accepts_post_link_chat_id_and_username(client, identifier, chat_id):
    gateway = use_gateway(StubGateway())

    resp = await client.post("/api/v1/profiles/p-1/resolve-chat", json={"identifier": identifier})

    assert resp.status_code == 200
    assert gateway.resolved == [chat_id]


async def test_resolve_invite_link_is_422_explaining_what_to_use(client):
    gateway = use_gateway(StubGateway())
    resp = await client.post("/api/v1/profiles/p-1/resolve-chat", json={"identifier": "https://t.me/+convite"})
    assert resp.status_code == 422
    assert resp.json() == {
        "detail": "Invite links (t.me/+...) cannot be resolved by a bot: use the link of a post in the channel or the -100... chat ID"
    }
    assert gateway.resolved == []


@pytest.mark.parametrize("body", [{"identifier": "https://t.me/+convite"}, {"identifier": ""}, {}, {"identifier": 123}])
async def test_resolve_invalid_identifier_is_422(client, body):
    gateway = use_gateway(StubGateway())
    resp = await client.post("/api/v1/profiles/p-1/resolve-chat", json=body)
    assert resp.status_code == 422
    assert gateway.resolved == []


async def test_resolve_for_missing_profile_is_404(client):
    use_gateway(StubGateway())
    resp = await client.post("/api/v1/profiles/nao-existe/resolve-chat", json={"identifier": "@canalnovidades"})
    assert resp.status_code == 404


async def test_resolve_telegram_refusal_is_400(client):
    use_gateway(StubGateway(error=ChatDiscoveryError("Telegram API error (400): Bad Request: chat not found")))
    resp = await client.post("/api/v1/profiles/p-1/resolve-chat", json={"identifier": "@canalnovidades"})
    assert resp.status_code == 400
    assert "chat not found" in resp.json()["detail"]
