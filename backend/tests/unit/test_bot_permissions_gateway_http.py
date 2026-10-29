from datetime import timezone

import httpx
import pytest
from src.domain.channels.bot_permissions import BotMemberStatus
from src.domain.channels.channel import ChatType
from src.domain.ports.bot_permissions_gateway import IBotPermissionsGateway
from src.domain.ports.chat_discovery_gateway import BotNotChannelAdminError, TelegramUnavailableError
from src.infrastructure.resilience import CircuitBreaker, CircuitState
from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp
from tests.unit.test_chat_discovery_gateway_http import TOKEN, use_transport
from tests.unit.test_resilience import FakeClock

CHAT_ID = "-1001234567890"
BOT_ID = 123456789
GROUP_DEFAULTS = {
    "can_send_messages": True,
    "can_send_photos": False,
    "can_send_videos": True,
    "can_send_polls": True,
    "can_send_audios": True,
}


def telegram(member: dict, chat: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": BOT_ID, "is_bot": True}})
        if method == "getChatMember":
            return httpx.Response(200, json={"ok": True, "result": {"user": {"id": BOT_ID}, **member}})
        if method == "getChat":
            return httpx.Response(200, json={"ok": True, "result": {"id": int(CHAT_ID), "title": "Acme", **chat}})
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})

    return handler


def sends(p):
    return (p.can_send_messages, p.can_send_photos, p.can_send_videos, p.can_send_polls)


async def read(monkeypatch, member, chat, **gateway_kwargs):
    requests = use_transport(monkeypatch, telegram(member, chat))
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", **gateway_kwargs)
    return await gateway.read_bot_permissions(TOKEN, CHAT_ID), requests


def test_the_http_gateway_implements_the_bot_permissions_port():
    assert isinstance(TelegramGatewayHttp(base_url="https://api.telegram.org"), IBotPermissionsGateway)


async def test_reads_the_bot_member_and_the_chat_with_get(monkeypatch):
    _, requests = await read(monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": GROUP_DEFAULTS})

    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", f"/bot{TOKEN}/getMe"),
        ("GET", f"/bot{TOKEN}/getChatMember"),
        ("GET", f"/bot{TOKEN}/getChat"),
    ]
    assert dict(requests[1].url.params) == {"chat_id": CHAT_ID, "user_id": str(BOT_ID)}
    assert dict(requests[2].url.params) == {"chat_id": CHAT_ID}


async def test_group_member_gets_the_group_default_permissions(monkeypatch):
    p, _ = await read(monkeypatch, {"status": "member"}, {"type": "supergroup", "permissions": GROUP_DEFAULTS})

    assert (p.chat_type, p.is_forum, p.bot_status) == (ChatType.SUPERGROUP, False, BotMemberStatus.MEMBER)
    assert sends(p) == (True, False, True, True)
    assert p.checked_at.tzinfo is timezone.utc


async def test_group_without_permissions_field_allows_nothing_to_a_member(monkeypatch):
    p, _ = await read(monkeypatch, {"status": "member"}, {"type": "supergroup"})
    assert sends(p) == (False,) * 4


async def test_forum_is_read_from_the_chat(monkeypatch):
    p, _ = await read(monkeypatch, {"status": "member"}, {"type": "supergroup", "is_forum": True, "permissions": GROUP_DEFAULTS})
    assert p.is_forum is True


async def test_restricted_bot_uses_its_own_permissions_and_the_group_ones(monkeypatch):
    member = {
        "status": "restricted",
        "is_member": True,
        "can_send_messages": True,
        "can_send_photos": True,
        "can_send_videos": False,
        "can_send_polls": True,
    }
    p, _ = await read(monkeypatch, member, {"type": "supergroup", "permissions": GROUP_DEFAULTS})

    assert p.bot_status is BotMemberStatus.RESTRICTED
    assert sends(p) == (True, False, False, True)


async def test_restricted_bot_that_left_the_group_is_outside_the_chat(monkeypatch):
    member = {"status": "restricted", "is_member": False, "can_send_messages": True}
    p, _ = await read(monkeypatch, member, {"type": "supergroup", "permissions": GROUP_DEFAULTS})

    assert p.bot_status is BotMemberStatus.LEFT
    assert sends(p) == (False,) * 4


@pytest.mark.parametrize(
    "member, expected",
    [
        ({"status": "administrator", "can_post_messages": True}, (True,) * 4),
        ({"status": "administrator", "can_post_messages": False}, (False,) * 4),
        ({"status": "administrator"}, (True,) * 4),
        ({"status": "creator"}, (True,) * 4),
        ({"status": "left"}, (False,) * 4),
        ({"status": "kicked"}, (False,) * 4),
    ],
    ids=["admin-can-post", "admin-cannot-post", "admin-without-field", "creator", "left", "kicked"],
)
async def test_channel_permissions_follow_the_bot_status(monkeypatch, member, expected):
    p, _ = await read(monkeypatch, member, {"type": "channel"})

    assert p.chat_type is ChatType.CHANNEL
    assert p.bot_status is BotMemberStatus(member["status"])
    assert sends(p) == expected


async def test_unknown_member_status_counts_as_outside_the_chat(monkeypatch):
    p, _ = await read(monkeypatch, {"status": "something_new"}, {"type": "channel"})
    assert p.bot_status is BotMemberStatus.LEFT


@pytest.mark.parametrize(
    "status, description",
    [(400, "Bad Request: chat not found"), (403, "Forbidden: bot is not a member of the channel chat")],
)
async def test_telegram_refusing_the_chat_means_the_bot_is_not_in_it(monkeypatch, status, description):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": BOT_ID}})
        return httpx.Response(status, json={"ok": False, "error_code": status, "description": description})

    use_transport(monkeypatch, handler)
    with pytest.raises(BotNotChannelAdminError) as exc:
        await TelegramGatewayHttp(base_url="https://api.telegram.org").read_bot_permissions(TOKEN, CHAT_ID)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("status", [429, 500, 502])
async def test_rate_limit_and_server_errors_are_telegram_unavailable_and_open_the_circuit(monkeypatch, status):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0, time_func=FakeClock().time)
    use_transport(monkeypatch, lambda r: httpx.Response(status, json={"ok": False, "error_code": status, "description": "Down"}))

    with pytest.raises(TelegramUnavailableError, match=r"^Could not reach Telegram, try again$"):
        await TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb).read_bot_permissions(TOKEN, CHAT_ID)
    assert cb.state == CircuitState.OPEN


async def test_timeout_is_telegram_unavailable_without_the_token(monkeypatch):
    def raise_timeout(request: httpx.Request):
        raise httpx.ConnectTimeout(f"Timed out calling {request.url}")

    use_transport(monkeypatch, raise_timeout)
    with pytest.raises(TelegramUnavailableError, match=r"^Could not reach Telegram, try again$") as exc:
        await TelegramGatewayHttp(base_url="https://api.telegram.org").read_bot_permissions(TOKEN, CHAT_ID)
    assert "SecretToken" not in str(exc.value)


async def test_chat_that_is_no_longer_a_channel_or_supergroup_means_the_bot_cannot_be_checked(monkeypatch):
    use_transport(monkeypatch, telegram({"status": "member"}, {"type": "private"}))
    with pytest.raises(BotNotChannelAdminError):
        await TelegramGatewayHttp(base_url="https://api.telegram.org").read_bot_permissions(TOKEN, CHAT_ID)
