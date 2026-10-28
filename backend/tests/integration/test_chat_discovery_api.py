import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from src.domain.channels.channel import Channel, ChatType
from src.domain.channels.chat_discovery import DiscoveredChat
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.domain.ports.chat_discovery_gateway import (
    BotNotChannelAdminError,
    ChatDiscoveryError,
    IChatDiscoveryGateway,
    TelegramUnavailableError,
    WebhookActiveError,
)
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

    async def ensure_bot_can_post(self, bot_token, chat_id):
        if self.error:
            raise self.error
        self.resolved.append(chat_id)


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
            {"chat_id": "-1001234567890", "title": "Canal de Novidades", "type": "channel", "username": "canalnovidades", "registrable": True, "is_forum": False, "already_registered": True},
            {"chat_id": "-444444444", "title": "Grupo comum", "type": "group", "username": None, "registrable": False, "is_forum": False, "already_registered": False},
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
    assert resp.json() == {"chat_id": "-1001234567890", "title": "Canal de Novidades", "type": "channel", "username": "canalnovidades", "registrable": True, "is_forum": False}
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


# Issue #2: Verificação de permissão de administrador no cadastro e na edição de canal
async def test_create_channel_succeeds_when_bot_is_admin_with_post_permission(client):
    gateway = use_gateway(StubGateway())
    resp = await client.post(
        "/api/v1/profiles/p-1/channels",
        json={"title": "Canal de Novidades", "chat_id": "-1001234567890"},
    )
    assert resp.status_code == 201
    # ensure_bot_can_post e depois o getChat que informa o tipo (#99).
    assert gateway.resolved == ["-1001234567890", "-1001234567890"]


async def test_create_channel_returns_400_when_bot_is_not_admin_and_does_not_save(client):
    use_gateway(StubGateway(error=BotNotChannelAdminError("Bot is not administrator in the channel")))
    resp = await client.post(
        "/api/v1/profiles/p-1/channels",
        json={"title": "Canal Sem Admin", "chat_id": "-1001234567890"},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Bot is not administrator in the channel"}
    assert TOKEN not in resp.text
    assert await channel_repo.list_by_profile("p-1") == []


@pytest.mark.parametrize(
    "error",
    [
        TelegramUnavailableError("Could not reach Telegram, try again"),
        CircuitBreakerOpenException(retry_after=30),
    ],
)
async def test_create_channel_returns_503_when_telegram_is_unreachable_and_does_not_save(client, error):
    use_gateway(StubGateway(error=error))
    resp = await client.post(
        "/api/v1/profiles/p-1/channels",
        json={"title": "Canal Offline", "chat_id": "-1001234567890"},
    )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Could not reach Telegram, try again"}
    assert TOKEN not in resp.text
    assert await channel_repo.list_by_profile("p-1") == []


async def test_update_channel_checks_telegram_only_when_chat_id_changes(client):
    await channel_repo.save(
        Channel(id="c-edit", profile_id="p-1", title="Original", chat_id="-1001111111111", chat_type=ChatType.CHANNEL)
    )

    # 1. Só o nome muda num canal que já tem tipo: não consulta o Telegram
    gateway = use_gateway(StubGateway(error=TelegramUnavailableError("Could not reach Telegram, try again")))
    resp_rename = await client.put(
        "/api/v1/channels/c-edit",
        json={"name": "Renomeado", "telegram_channel_id": "-1001111111111"},
    )
    assert resp_rename.status_code == 200
    assert gateway.resolved == []

    # 2. O chat_id muda e o bot não é admin: 400 e não salva
    use_gateway(StubGateway(error=BotNotChannelAdminError("Bot is not administrator in the channel")))
    resp_forbidden = await client.put(
        "/api/v1/channels/c-edit",
        json={"name": "Renomeado", "telegram_channel_id": "-1002222222222"},
    )
    assert resp_forbidden.status_code == 400
    assert resp_forbidden.json() == {"detail": "Bot is not administrator in the channel"}
    assert (await channel_repo.get_by_id("c-edit")).chat_id == "-1001111111111"

    # 3. O chat_id muda e o Telegram está fora do ar: 503 e não salva
    use_gateway(StubGateway(error=TelegramUnavailableError("Could not reach Telegram, try again")))
    resp_unavailable = await client.put(
        "/api/v1/channels/c-edit",
        json={"name": "Renomeado", "telegram_channel_id": "-1002222222222"},
    )
    assert resp_unavailable.status_code == 503
    assert resp_unavailable.json() == {"detail": "Could not reach Telegram, try again"}
    assert (await channel_repo.get_by_id("c-edit")).chat_id == "-1001111111111"


async def test_create_channel_returns_409_when_chat_id_already_registered_for_profile(client):
    use_gateway(StubGateway())
    resp1 = await client.post(
        "/api/v1/profiles/p-1/channels",
        json={"title": "Canal Original", "chat_id": "-1001234567890"},
    )
    assert resp1.status_code == 201

    # Segunda tentativa com o mesmo chat_id para o mesmo perfil deve retornar 409 Conflict
    resp2 = await client.post(
        "/api/v1/profiles/p-1/channels",
        json={"title": "Canal Duplicado", "chat_id": "-1001234567890"},
    )
    assert resp2.status_code == 409
    assert resp2.json() == {"detail": "Channel already registered for this profile"}


async def test_update_channel_returns_409_when_target_chat_id_already_used_in_same_profile(client):
    use_gateway(StubGateway())
    await channel_repo.save(Channel(id="c-dup-1", profile_id="p-1", title="Canal 1", chat_id="-1001111111111"))
    await channel_repo.save(Channel(id="c-dup-2", profile_id="p-1", title="Canal 2", chat_id="-1002222222222"))

    # Tenta mudar c-dup-2 para o chat_id de c-dup-1
    resp = await client.put(
        "/api/v1/channels/c-dup-2",
        json={"name": "Canal 2 Alterado", "telegram_channel_id": "-1001111111111"},
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Channel already registered for this profile"}
    assert (await channel_repo.get_by_id("c-dup-2")).chat_id == "-1002222222222"


# Issue #99: tipo do chat e fórum
FORUM = DiscoveredChat(chat_id="-1009876543210", title="Grupo VIP", chat_type="supergroup", is_forum=True)


class ForumGateway(StubGateway):
    async def discover_chats(self, bot_token):
        return [FORUM]

    async def resolve_chat(self, bot_token, identifier):
        return FORUM


async def test_discover_and_resolve_report_forums(client):
    use_gateway(ForumGateway())

    discovered = await client.post("/api/v1/profiles/p-1/discover-chats")
    resolved = await client.post("/api/v1/profiles/p-1/resolve-chat", json={"identifier": FORUM.chat_id})

    assert discovered.json()["chats"][0]["is_forum"] is True
    assert resolved.json()["is_forum"] is True


async def test_create_channel_saves_and_lists_the_kind_reported_by_telegram(client):
    use_gateway(ForumGateway())

    created = await client.post("/api/v1/profiles/p-1/channels", json={"title": "Grupo VIP", "chat_id": FORUM.chat_id})
    listed = await client.get("/api/v1/profiles/p-1/channels")

    assert created.status_code == 201
    assert (created.json()["chat_type"], created.json()["is_forum"]) == ("supergroup", True)
    [item] = listed.json()
    assert (item["chat_type"], item["is_forum"]) == ("supergroup", True)


async def test_channel_linked_before_chat_types_is_listed_without_kind_and_gets_it_on_edit(client):
    await channel_repo.save(Channel(id="c-old", profile_id="p-1", title="Grupo VIP", chat_id=FORUM.chat_id))
    use_gateway(ForumGateway())

    before = (await client.get("/api/v1/profiles/p-1/channels")).json()[0]
    edited = await client.put("/api/v1/channels/c-old", json={"name": "Grupo VIP", "telegram_channel_id": FORUM.chat_id})
    after = (await client.get("/api/v1/profiles/p-1/channels")).json()[0]

    assert (before["chat_type"], before["is_forum"]) == (None, False)
    assert edited.status_code == 200
    assert (edited.json()["chat_type"], edited.json()["is_forum"]) == ("supergroup", True)
    assert (after["chat_type"], after["is_forum"]) == ("supergroup", True)


async def test_update_unknown_channel_is_404(client):
    use_gateway(StubGateway())
    resp = await client.put("/api/v1/channels/c-x", json={"name": "X", "telegram_channel_id": FORUM.chat_id})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Channel not found"}
