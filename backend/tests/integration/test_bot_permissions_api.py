from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from src.domain.channels.bot_permissions import BotMemberStatus, BotPermissions
from src.domain.channels.channel import Channel, ChatType
from src.domain.ports.bot_permissions_gateway import IBotPermissionsGateway
from src.domain.ports.chat_discovery_gateway import BotNotChannelAdminError, TelegramUnavailableError
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.resilience import CircuitBreakerOpenException
from src.infrastructure.sqlite_repositories import Base
from src.presentation.main import app, channel_repo, engine, get_bot_permissions_gateway, profile_repo

TOKEN = "1234567890:SecretTokenThatMustNeverLeak_42"
CHAT_ID = "-1001234567890"
CHECKED_AT = datetime(2026, 10, 28, 12, 30, 5, tzinfo=timezone.utc)


class StubGateway(IBotPermissionsGateway):
    def __init__(self, result: BotPermissions | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    async def read_bot_permissions(self, bot_token, chat_id):
        self.calls.append(chat_id)
        if self.error:
            raise self.error
        return self.result


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await profile_repo.save(Profile(id="p-1", name="Acme", credentials=BotCredentials(token=TOKEN, bot_username="acme_bot")))
    await channel_repo.save(
        Channel(id="c-1", profile_id="p-1", title="Grupo de Novidades", chat_id=CHAT_ID, chat_type=ChatType.SUPERGROUP)
    )
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def use_gateway(gateway: StubGateway) -> StubGateway:
    app.dependency_overrides[get_bot_permissions_gateway] = lambda: gateway
    return gateway


async def test_returns_what_the_bot_can_send_in_the_channel(client):
    permissions = BotPermissions(
        chat_type=ChatType.SUPERGROUP,
        is_forum=True,
        bot_status=BotMemberStatus.MEMBER,
        checked_at=CHECKED_AT,
        can_send_messages=True,
        can_send_videos=True,
    )
    gateway = use_gateway(StubGateway(result=permissions))

    resp = await client.get("/api/v1/channels/c-1/bot-permissions")

    assert resp.status_code == 200
    assert resp.json() == {
        "chat_type": "supergroup",
        "is_forum": True,
        "bot_status": "member",
        "can_send_messages": True,
        "can_send_photos": False,
        "can_send_videos": True,
        "can_send_polls": False,
        "checked_at": "2026-10-28T12:30:05Z",
    }
    assert gateway.calls == [CHAT_ID]
    assert TOKEN not in resp.text


async def test_bot_outside_the_chat_is_200_with_status_left(client):
    use_gateway(StubGateway(error=BotNotChannelAdminError("Bot is not administrator in the channel")))

    resp = await client.get("/api/v1/channels/c-1/bot-permissions")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["chat_type"], body["bot_status"], body["can_send_messages"]) == ("supergroup", "left", False)


async def test_unknown_channel_is_404(client):
    gateway = use_gateway(StubGateway())
    resp = await client.get("/api/v1/channels/nao-existe/bot-permissions")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Channel not found"}
    assert gateway.calls == []


@pytest.mark.parametrize("error", [TelegramUnavailableError("Could not reach Telegram, try again"), CircuitBreakerOpenException(retry_after=25)])
async def test_telegram_unavailable_is_503(client, error):
    use_gateway(StubGateway(error=error))
    resp = await client.get("/api/v1/channels/c-1/bot-permissions")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Could not reach Telegram, try again"}
