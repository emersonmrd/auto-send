import pytest
import httpx
from src.domain.channels.chat_discovery import DiscoveredChat, ChatIdentifier
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, WebhookActiveError
from src.infrastructure.resilience import CircuitBreaker, CircuitBreakerOpenException, CircuitState
from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp
from tests.unit.test_resilience import FakeClock

TOKEN = "123456789:SecretTokenThatMustNeverLeak_42"


def use_transport(monkeypatch, handler):
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request):
        requests.append(request)
        return handler(request)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(recording)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return requests


def chat(id_, title, type_="channel", username=None):
    data = {"id": id_, "title": title, "type": type_}
    if username:
        data["username"] = username
    return data


def updates(*items):
    return httpx.Response(200, json={"ok": True, "result": [{"update_id": i + 1, **u} for i, u in enumerate(items)]})


async def test_discover_calls_get_updates_without_offset_or_allowed_updates(monkeypatch):
    requests = use_transport(monkeypatch, lambda r: updates())

    await TelegramGatewayHttp(base_url="https://api.telegram.org").discover_chats(TOKEN)

    [request] = requests
    assert request.method == "GET"
    assert request.url.path == f"/bot{TOKEN}/getUpdates"
    # Sem offset os updates não são confirmados (outro consumidor do bot continua recebendo);
    # sem allowed_updates a configuração do bot não é alterada.
    assert "offset" not in request.url.params
    assert "allowed_updates" not in request.url.params
    assert request.url.params["timeout"] == "0"


async def test_discover_extracts_unique_chats_from_every_update_kind(monkeypatch):
    use_transport(
        monkeypatch,
        lambda r: updates(
            {"my_chat_member": {"chat": chat(-1001111111111, "Canal A", username="canala"), "new_chat_member": {"status": "administrator"}}},
            {"channel_post": {"chat": chat(-1001111111111, "Canal A renomeado", username="canala")}},
            {"edited_channel_post": {"chat": chat(-1002222222222, "Canal B")}},
            {"message": {"chat": chat(-1003333333333, "Supergrupo", "supergroup")}},
            {"edited_message": {"chat": chat(-444444444, "Grupo comum", "group")}},
            {"message": {"chat": {"id": 987654, "type": "private", "first_name": "Ana"}}},
            {"callback_query": {"id": "1"}},
        ),
    )

    chats = await TelegramGatewayHttp(base_url="https://api.telegram.org").discover_chats(TOKEN)

    assert chats == [
        DiscoveredChat(chat_id="-1001111111111", title="Canal A renomeado", chat_type="channel", username="canala"),
        DiscoveredChat(chat_id="-1002222222222", title="Canal B", chat_type="channel"),
        DiscoveredChat(chat_id="-1003333333333", title="Supergrupo", chat_type="supergroup"),
        DiscoveredChat(chat_id="-444444444", title="Grupo comum", chat_type="group"),
    ]


async def test_discover_drops_chats_the_bot_has_left(monkeypatch):
    use_transport(
        monkeypatch,
        lambda r: updates(
            {"channel_post": {"chat": chat(-1001111111111, "Canal A")}},
            {"my_chat_member": {"chat": chat(-1001111111111, "Canal A"), "new_chat_member": {"status": "left"}}},
            {"my_chat_member": {"chat": chat(-1002222222222, "Canal B"), "new_chat_member": {"status": "kicked"}}},
            {"my_chat_member": {"chat": chat(-1002222222222, "Canal B"), "new_chat_member": {"status": "administrator"}}},
        ),
    )

    chats = await TelegramGatewayHttp(base_url="https://api.telegram.org").discover_chats(TOKEN)

    assert [c.chat_id for c in chats] == ["-1002222222222"]


async def test_resolve_calls_get_chat_with_the_username(monkeypatch):
    requests = use_transport(
        monkeypatch,
        lambda r: httpx.Response(200, json={"ok": True, "result": chat(-1001111111111, "Canal A", username="canala")}),
    )

    result = await TelegramGatewayHttp(base_url="https://api.telegram.org").resolve_chat(
        TOKEN, ChatIdentifier("@canala")
    )

    [request] = requests
    assert request.method == "GET"
    assert request.url.path == f"/bot{TOKEN}/getChat"
    assert request.url.params["chat_id"] == "@canala"
    assert result == DiscoveredChat(chat_id="-1001111111111", title="Canal A", chat_type="channel", username="canala")


async def test_resolve_calls_get_chat_with_the_numeric_chat_id(monkeypatch):
    # Canal privado informado pelo link do post ou pelo ID: getChat aceita o -100... e funciona com webhook ativo.
    requests = use_transport(monkeypatch, lambda r: httpx.Response(200, json={"ok": True, "result": chat(-1001234567890, "Canal Privado")}))

    result = await TelegramGatewayHttp(base_url="https://api.telegram.org").resolve_chat(TOKEN, ChatIdentifier("-1001234567890"))

    [request] = requests
    assert request.url.path == f"/bot{TOKEN}/getChat"
    assert request.url.params["chat_id"] == "-1001234567890"
    assert result == DiscoveredChat(chat_id="-1001234567890", title="Canal Privado", chat_type="channel")


async def test_discover_with_active_webhook_raises_a_typed_error_without_token(monkeypatch):
    use_transport(
        monkeypatch,
        lambda r: httpx.Response(
            409,
            json={"ok": False, "error_code": 409, "description": "Conflict: can't use getUpdates method while webhook is active; use deleteWebhook to delete the webhook first"},
        ),
    )
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    with pytest.raises(WebhookActiveError) as exc:
        await gateway.discover_chats(TOKEN)
    assert isinstance(exc.value, ChatDiscoveryError)
    assert str(exc.value) == "Bot webhook is active: automatic discovery is unavailable"
    assert TOKEN not in str(exc.value)
    # Webhook ativo é configuração do bot, não falha do Telegram: não conta para o circuit breaker.
    assert gateway.circuit_breaker.state == CircuitState.CLOSED
    assert gateway.circuit_breaker.failure_count == 0


async def test_resolve_rejects_a_private_chat(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(200, json={"ok": True, "result": {"id": 42, "type": "private"}}))

    with pytest.raises(ChatDiscoveryError, match="not a channel or group"):
        await TelegramGatewayHttp(base_url="https://api.telegram.org").resolve_chat(
            TOKEN, ChatIdentifier("@umapessoa")
        )


@pytest.mark.parametrize(
    "status, description",
    [
        (400, "Bad Request: chat not found"),
        (401, "Unauthorized"),
        (500, "Internal Server Error"),
    ],
)
async def test_telegram_error_becomes_chat_discovery_error_without_token(monkeypatch, status, description):
    use_transport(monkeypatch, lambda r: httpx.Response(status, json={"ok": False, "error_code": status, "description": description}))
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    for call in (gateway.discover_chats(TOKEN), gateway.resolve_chat(TOKEN, ChatIdentifier("@canala"))):
        with pytest.raises(ChatDiscoveryError) as exc:
            await call
        assert description in str(exc.value)
        assert TOKEN not in str(exc.value)
        assert "SecretToken" not in str(exc.value)


async def test_429_opens_the_circuit_with_retry_after(monkeypatch):
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0, time_func=clock.time)
    requests = use_transport(
        monkeypatch,
        lambda r: httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 25}},
        ),
    )
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb)

    with pytest.raises(ChatDiscoveryError, match="Too Many Requests"):
        await gateway.discover_chats(TOKEN)
    assert cb.state == CircuitState.OPEN

    with pytest.raises(CircuitBreakerOpenException) as exc:
        await gateway.discover_chats(TOKEN)
    assert exc.value.retry_after == pytest.approx(25.0)
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("timed out"), httpx.ConnectError("connection refused")])
async def test_network_failure_becomes_chat_discovery_error_and_counts_for_the_circuit(monkeypatch, error):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0, time_func=FakeClock().time)

    def raise_error(request):
        raise error

    use_transport(monkeypatch, raise_error)
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb)

    with pytest.raises(ChatDiscoveryError) as exc:
        await gateway.resolve_chat(TOKEN, ChatIdentifier("@canala"))
    assert TOKEN not in str(exc.value)
    assert cb.state == CircuitState.OPEN


async def test_invalid_json_becomes_chat_discovery_error(monkeypatch):
    use_transport(monkeypatch, lambda r: httpx.Response(200, content=b"<html>proxy</html>"))

    with pytest.raises(ChatDiscoveryError, match="Invalid JSON response"):
        await TelegramGatewayHttp(base_url="https://api.telegram.org").discover_chats(TOKEN)

