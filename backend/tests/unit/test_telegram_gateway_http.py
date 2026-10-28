from unittest.mock import patch
import tempfile
import os
import json
import pytest
import httpx
from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastPoll,
    MediaAttachment,
    MediaType,
    InlineButton,
    PollType,
)

@pytest.fixture
def sample_image_file(tmp_path):
    img_path = tmp_path / "test_photo.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0" + b"dummy photo content")
    return str(img_path)

@pytest.fixture
def sample_video_file(tmp_path):
    vid_path = tmp_path / "test_video.mp4"
    vid_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"dummy video content")
    return str(vid_path)

@pytest.fixture
def sample_thumb_file(tmp_path):
    thumb_path = tmp_path / "test_thumb.jpg"
    thumb_path.write_bytes(b"\xff\xd8\xff\xe0" + b"dummy thumbnail jpeg content")
    return str(thumb_path)

@pytest.mark.asyncio
async def test_should_send_photo_with_caption_using_send_photo_endpoint_and_photo_field(
    sample_image_file, monkeypatch
):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    
    # Intercept httpx.AsyncClient requests
    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-photo-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Photo caption under 1024 chars",
        media=MediaAttachment(
            file_path=sample_image_file,
            media_type=MediaType.PHOTO,
            file_size=os.path.getsize(sample_image_file),
        ),
        button=InlineButton(text="Docs Link", url="https://example.com/news"),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    
    # Endpoint must be sendPhoto
    assert req.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendPhoto"
    assert req.method == "POST"
    
    # Must use multipart form with "photo" key (not "video")
    content = req.read()
    assert b'name="photo"' in content
    assert b'name="video"' not in content
    assert b'name="caption"' in content
    assert b"Photo caption under 1024 chars" in content

@pytest.mark.asyncio
async def test_should_send_video_with_caption_using_send_video_endpoint_and_video_field(
    sample_video_file, monkeypatch
):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 102}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    
    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-video-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video caption under 1024 chars",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
        ),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    
    # Endpoint must be sendVideo
    assert req.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendVideo"
    assert req.method == "POST"
    
    content = req.read()
    assert b'name="video"' in content
    assert b'name="photo"' not in content
    assert b'name="caption"' in content
    assert b"Video caption under 1024 chars" in content

@pytest.mark.asyncio
async def test_should_split_text_and_media_with_photo(
    sample_image_file, monkeypatch
):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 103}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    
    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    long_text = "L" * 1050
    message = BroadcastMessage(
        id="broadcast-photo-split",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text=long_text,
        media=MediaAttachment(
            file_path=sample_image_file,
            media_type=MediaType.PHOTO,
            file_size=os.path.getsize(sample_image_file),
        ),
        button=InlineButton(text="Join", url="https://example.com/join"),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 2
    
    # Request 1: sendMessage with long text and reply_markup
    req1 = recorded_requests[0]
    assert req1.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage"
    payload1 = json.loads(req1.content)
    assert payload1["text"] == long_text
    assert "reply_markup" in payload1

    # Request 2: sendPhoto with photo multipart key
    req2 = recorded_requests[1]
    assert req2.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendPhoto"
    content2 = req2.read()
    assert b'name="photo"' in content2
    assert b'name="video"' not in content2


@pytest.mark.asyncio
async def test_telegram_gateway_circuit_breaker_rate_limit_429(monkeypatch):
    """Quando o Telegram retorna HTTP 429 com retry_after, o circuit breaker deve abrir imediatamente."""
    from src.infrastructure.resilience import CircuitBreaker, CircuitBreakerOpenException, CircuitState
    from tests.unit.test_resilience import FakeClock

    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0, time_func=clock.time)
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb)

    def mock_handler(request: httpx.Request):
        return httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 25}},
            headers={"retry-after": "25"}
        )

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-429",
        profile_id="profile-1",
        target_channel_ids=["-100123"],
        text="Test 429",
    )

    result = await gateway.send_broadcast(
        bot_token="bot_token_123",
        chat_id="-100123",
        message=message,
    )
    assert result is False
    assert cb.state == CircuitState.OPEN

    # Próxima chamada deve falhar rápido sem disparar request
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)
    assert exc_info.value.retry_after == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_telegram_gateway_circuit_breaker_5xx_consecutive_failures(monkeypatch):
    """Falhas consecutivas 5xx abrem o circuit breaker e subsequentes falham rápido."""
    from src.infrastructure.resilience import CircuitBreaker, CircuitBreakerOpenException, CircuitState
    from tests.unit.test_resilience import FakeClock

    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30.0, time_func=clock.time)
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb)

    def mock_handler(request: httpx.Request):
        return httpx.Response(502, text="Bad Gateway")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-502",
        profile_id="profile-1",
        target_channel_ids=["-100123"],
        text="Test 502",
    )

    # 1ª falha
    res1 = await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)
    assert res1 is False
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 1

    # 2ª falha -> atinge limiar 2
    res2 = await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)
    assert res2 is False
    assert cb.state == CircuitState.OPEN

    # 3ª chamada -> Fast-fail com CircuitBreakerOpenException
    with pytest.raises(CircuitBreakerOpenException):
        await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)


@pytest.mark.asyncio
async def test_telegram_gateway_circuit_breaker_recovery_half_open_to_closed(monkeypatch):
    """Após o período de cooldown, o circuito vai para HALF_OPEN e fecha após chamada bem sucedida."""
    from src.infrastructure.resilience import CircuitBreaker, CircuitState
    from tests.unit.test_resilience import FakeClock

    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=20.0, time_func=clock.time)
    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org", circuit_breaker=cb)

    status_code_to_return = [500]

    def mock_handler(request: httpx.Request):
        sc = status_code_to_return[0]
        if sc == 200:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})
        return httpx.Response(sc, text="Error")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-recovery",
        profile_id="profile-1",
        target_channel_ids=["-100123"],
        text="Recovery test",
    )

    # Falha inicial abre o circuito
    await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)
    assert cb.state == CircuitState.OPEN

    # Avança tempo para além do recovery_timeout
    clock.advance(20.5)
    assert cb.state == CircuitState.HALF_OPEN

    # Próxima chamada tem sucesso
    status_code_to_return[0] = 200
    success = await gateway.send_broadcast(bot_token="bot_token_123", chat_id="-100123", message=message)
    assert success is True
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_telegram_gateway_reads_base_url_from_env_and_handles_413_large_video(sample_video_file, monkeypatch):
    """Configura base_url via env e propaga erro detalhado em 413 com vídeo > 50MB na API pública."""
    monkeypatch.setenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org/")
    gateway = TelegramGatewayHttp()
    assert gateway.base_url == "https://api.telegram.org"

    def mock_handler(request: httpx.Request):
        return httpx.Response(
            413,
            json={"ok": False, "error_code": 413, "description": "Request Entity Too Large"},
        )

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    large_size = 55 * 1024 * 1024  # 55MB (> 50MB)
    message = BroadcastMessage(
        id="broadcast-413-large",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Vídeo grande",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=large_size,
        ),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is False
    assert gateway.last_error is not None
    assert "413" in gateway.last_error
    assert "Request Entity Too Large" in gateway.last_error
    assert "Arquivo excede o limite de 50MB da API pública do Telegram" in gateway.last_error


@pytest.mark.asyncio
async def test_telegram_gateway_transparent_fallback_when_local_bot_api_not_configured(monkeypatch):
    """Se base_url aponta para http://telegram-bot-api:8081 mas TELEGRAM_API_ID/HASH estão vazios, faz fallback para api.telegram.org."""
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)

    gateway = TelegramGatewayHttp(base_url="http://telegram-bot-api:8081")
    effective = await gateway.resolve_effective_base_url()
    assert effective == "https://api.telegram.org"


@pytest.mark.asyncio
async def test_telegram_gateway_uses_local_bot_api_when_configured_and_reachable(monkeypatch):
    """Se TELEGRAM_API_ID/HASH estão definidos e o servidor local responde, mantém http://telegram-bot-api:8081."""
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_API_HASH", "fake-api-hash")

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, json={"ok": True})

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    gateway = TelegramGatewayHttp(base_url="http://telegram-bot-api:8081")
    effective = await gateway.resolve_effective_base_url()
    assert effective == "http://telegram-bot-api:8081"



@pytest.mark.asyncio
async def test_gateway_without_api_credentials_never_uses_the_portable_local_server(monkeypatch):
    """No pacote portátil a base local é 127.0.0.1:<porta>, não o host telegram-bot-api do Compose."""
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)

    gateway = TelegramGatewayHttp(base_url="http://127.0.0.1:8081")
    effective = await gateway.resolve_effective_base_url()
    assert effective == "https://api.telegram.org"


@pytest.mark.asyncio
async def test_gateway_falls_back_when_the_portable_local_server_is_down(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_API_HASH", "fake-api-hash")

    def refuse(request: httpx.Request):
        raise httpx.ConnectError("All connection attempts failed", request=request)

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(refuse)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    gateway = TelegramGatewayHttp(base_url="http://127.0.0.1:8081")
    effective = await gateway.resolve_effective_base_url()
    assert effective == "https://api.telegram.org"


@pytest.mark.asyncio
async def test_send_video_includes_supports_streaming(monkeypatch, sample_video_file):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    message = BroadcastMessage(
        id="broadcast-streaming-test",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video with supports streaming test",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
        )
    )

    success = await gateway.send_broadcast(
        bot_token="bot_token_123",
        chat_id="-1001234567890",
        message=message,
    )
    assert success is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert "sendVideo" in str(req.url)
    content = req.read()
    assert b'name="supports_streaming"' in content
    assert b"\r\n\r\ntrue\r\n" in content
    assert b'name="chat_id"' in content
    assert b"-1001234567890" in content
    assert b'name="video"' in content
    assert b"video/mp4" in content


@pytest.mark.asyncio
async def test_send_video_includes_duration_width_height(monkeypatch, sample_video_file):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1000}})

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    message = BroadcastMessage(
        id="broadcast-duration-test",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video with duration",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            duration=145,
            width=1920,
            height=1080,
        )
    )

    success = await gateway.send_broadcast(
        bot_token="bot_token_123",
        chat_id="-1001234567890",
        message=message,
    )
    assert success is True
    assert len(recorded_requests) == 1
    content = recorded_requests[0].read()
    assert b'name="duration"' in content
    assert b"\r\n\r\n145\r\n" in content
    assert b'name="width"' in content
    assert b"\r\n\r\n1920\r\n" in content
    assert b'name="height"' in content
    assert b"\r\n\r\n1080\r\n" in content


@pytest.mark.asyncio
async def test_should_send_video_split_text_and_media_with_supports_streaming(
    monkeypatch, sample_video_file
):
    """Garante que no modo split (texto > 1024 chars + vídeo), a chamada de mídia envia supports_streaming=true e chat_id."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 104}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    long_text = "V" * 1050
    message = BroadcastMessage(
        id="broadcast-video-split",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text=long_text,
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
        ),
        button=InlineButton(text="Assistir Agora", url="https://example.com/watch"),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 2

    # Request 1: sendMessage com texto longo e inline button
    req1 = recorded_requests[0]
    assert req1.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage"
    payload1 = json.loads(req1.content)
    assert payload1["chat_id"] == "-1001234567890"
    assert payload1["text"] == long_text
    assert "reply_markup" in payload1

    # Request 2: sendVideo multipart com chat_id, supports_streaming=true e arquivo video/mp4
    req2 = recorded_requests[1]
    assert req2.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendVideo"
    content2 = req2.read()
    assert b'name="chat_id"' in content2
    assert b"-1001234567890" in content2
    assert b'name="supports_streaming"' in content2
    assert b"\r\n\r\ntrue\r\n" in content2
    assert b'name="video"' in content2
    assert b"video/mp4" in content2
    assert b'name="caption"' not in content2


@pytest.mark.asyncio
async def test_should_never_include_supports_streaming_for_photos(
    monkeypatch, sample_image_file
):
    """Garante que fotos NUNCA recebem o parâmetro supports_streaming, tanto direto quanto split."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 105}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    # 1. Modo direto (SINGLE_MEDIA_WITH_CAPTION)
    msg_single = BroadcastMessage(
        id="broadcast-photo-single-no-stream",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Photo caption",
        media=MediaAttachment(
            file_path=sample_image_file,
            media_type=MediaType.PHOTO,
            file_size=os.path.getsize(sample_image_file),
        ),
    )
    ok_single = await gateway.send_broadcast(
        bot_token="token_photo", chat_id="-1001234567890", message=msg_single
    )
    assert ok_single is True
    req_single = recorded_requests[-1]
    assert "sendPhoto" in str(req_single.url)
    content_single = req_single.read()
    assert b"supports_streaming" not in content_single
    assert b'name="photo"' in content_single
    assert b"image/jpeg" in content_single

    # 2. Modo split (SPLIT_TEXT_THEN_MEDIA)
    msg_split = BroadcastMessage(
        id="broadcast-photo-split-no-stream",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="P" * 1050,
        media=MediaAttachment(
            file_path=sample_image_file,
            media_type=MediaType.PHOTO,
            file_size=os.path.getsize(sample_image_file),
        ),
    )
    ok_split = await gateway.send_broadcast(
        bot_token="token_photo", chat_id="-1001234567890", message=msg_split
    )
    assert ok_split is True
    req_photo_split = recorded_requests[-1]
    assert "sendPhoto" in str(req_photo_split.url)
    content_split = req_photo_split.read()
    assert b"supports_streaming" not in content_split
    assert b'name="photo"' in content_split
    assert b"image/jpeg" in content_split


@pytest.mark.asyncio
async def test_send_video_with_thumbnail_multipart_single(
    sample_video_file, sample_thumb_file, monkeypatch
):
    """Quando media tem thumbnail_path, gateway deve enviar thumbnail (e thumb) via multipart no sendVideo sem enviar cover."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 120}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-video-thumb-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video with thumbnail",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            thumbnail_path=sample_thumb_file,
        ),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert "sendVideo" in str(req.url)

    content = req.read()
    assert b'name="video"' in content
    assert b'name="supports_streaming"' in content
    assert b'name="thumbnail"; filename=' in content
    assert b"dummy thumbnail jpeg content" in content
    assert b'name="thumbnail"\r\n\r\nattach://thumbnail' in content
    assert b'name="thumb"\r\n\r\nattach://thumbnail' in content
    assert b'name="cover"' not in content


@pytest.mark.asyncio
async def test_send_video_with_thumbnail_sets_attach_syntax_for_thumbnail_and_thumb(
    sample_video_file, sample_thumb_file, monkeypatch
):
    """
    Especificação Telegram Bot API para sendVideo com thumbnail multipart:
    Os campos 'thumbnail' e 'thumb' no form-data (data) DEVEM apontar para o arquivo
    anexado via 'attach://thumbnail' (com 'thumbnail' em files).
    O parâmetro 'cover' NÃO deve ser enviado para não forçar o Telegram a inflar a capa estática (> 50MB).
    """
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 125}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-video-thumb-attach-check",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video with explicit attach syntax verification",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            thumbnail_path=sample_thumb_file,
        ),
    )

    await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    content = req.read()

    # O arquivo thumbnail deve estar presente no multipart (files)
    assert b'name="thumbnail"; filename=' in content
    assert b"dummy thumbnail jpeg content" in content

    # Os campos data["thumbnail"] e data["thumb"] devem ter attach://thumbnail
    assert b'name="thumbnail"\r\n\r\nattach://thumbnail' in content
    assert b'name="thumb"\r\n\r\nattach://thumbnail' in content

    # O parâmetro 'cover' NÃO deve ser enviado
    assert b'name="cover"' not in content


@pytest.mark.asyncio
async def test_send_video_split_with_thumbnail_multipart(
    sample_video_file, sample_thumb_file, monkeypatch
):
    """No modo split (>1024 caracteres), o segundo request (sendVideo) deve conter 'thumbnail', 'thumb' e 'supports_streaming' (sem 'cover')."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 121}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    long_caption = "T" * 1050
    message = BroadcastMessage(
        id="broadcast-video-thumb-split",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text=long_caption,
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            thumbnail_path=sample_thumb_file,
        ),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 2
    # Request 1: sendMessage com texto longo
    assert "sendMessage" in str(recorded_requests[0].url)

    # Request 2: sendVideo com video, supports_streaming e thumbnail (sem cover)
    req_video = recorded_requests[1]
    assert "sendVideo" in str(req_video.url)
    content = req_video.read()
    assert b'name="video"' in content
    assert b'name="supports_streaming"' in content
    assert b'name="thumbnail"; filename=' in content
    assert b"dummy thumbnail jpeg content" in content
    assert b'name="thumbnail"\r\n\r\nattach://thumbnail' in content
    assert b'name="thumb"\r\n\r\nattach://thumbnail' in content
    assert b'name="cover"' not in content


@pytest.mark.asyncio
async def test_send_video_without_thumbnail_does_not_send_thumbnail_field(
    sample_video_file, monkeypatch
):
    """Quando thumbnail_path é None, gateway NÃO deve incluir o campo thumbnail no sendVideo."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 122}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-video-no-thumb",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video without thumbnail",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            thumbnail_path=None,
        ),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    content = recorded_requests[0].read()
    assert b'name="video"' in content
    assert b'name="supports_streaming"' in content
    assert b'name="thumbnail"' not in content



@pytest.mark.asyncio
async def test_send_video_with_missing_thumbnail_file_skips_thumbnail(
    sample_video_file, monkeypatch
):
    """Se thumbnail_path aponta para arquivo que não existe no disco, gateway deve enviar video sem o campo thumbnail."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 123}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-video-missing-thumb",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video missing thumb file",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            thumbnail_path="/tmp/non_existent_thumbnail_12345.jpg",
        ),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    content = recorded_requests[0].read()
    assert b'name="video"' in content
    assert b'name="supports_streaming"' in content
    assert b'name="thumbnail"' not in content


# ============================================================================
# TDD Red Tests: Envio Seguro de reply_markup em TelegramGatewayHttp
# ============================================================================

@pytest.mark.asyncio
async def test_single_media_serializes_reply_markup_json_safely(sample_video_file, monkeypatch):
    """Garante que SINGLE_MEDIA_WITH_CAPTION serializa reply_markup com inline_keyboard valido no multipart."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 201}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-markup-single",
        profile_id="profile-markup",
        target_channel_ids=["-1001122334455"],
        text="Legenda curta do video",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            width=1080,
            height=1920,
        ),
        button=InlineButton(text="Entrar na Comunidade", url="https://t.me/community_chat"),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:TEST_TOKEN_MARKUP_1",
        chat_id="-1001122334455",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    raw_content = req.read().decode("utf-8", errors="replace")

    # Verifica que o campo reply_markup esta presente no multipart
    assert 'name="reply_markup"' in raw_content

    # Extrai o valor JSON de reply_markup do multipart
    import re
    match = re.search(r'name="reply_markup"\r?\n\r?\n([^\r\n]+)', raw_content)
    assert match is not None, "Campo reply_markup nao encontrado ou vazio no corpo multipart"
    markup_json = match.group(1).strip()
    parsed_markup = json.loads(markup_json)

    assert "inline_keyboard" in parsed_markup
    assert parsed_markup["inline_keyboard"] == [[{"text": "Entrar na Comunidade", "url": "https://t.me/community_chat"}]]


@pytest.mark.asyncio
async def test_split_text_then_media_serializes_reply_markup_safely_and_not_dropped(
    sample_video_file, monkeypatch
):
    """Garante que SPLIT_TEXT_THEN_MEDIA nao descarta reply_markup e serializa inline_keyboard valido em ambas chamadas."""
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 202}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    long_text = "T" * 1200
    message = BroadcastMessage(
        id="broadcast-markup-split",
        profile_id="profile-markup-split",
        target_channel_ids=["-1009988776655"],
        text=long_text,
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
            width=1080,
            height=1920,
        ),
        button=InlineButton(text="Ver Detalhes", url="https://example.com/checkout"),
    )

    result = await gateway.send_broadcast(
        bot_token="123456:TEST_TOKEN_MARKUP_2",
        chat_id="-1009988776655",
        message=message,
    )

    assert result is True
    assert len(recorded_requests) == 2

    # Request 1: sendMessage (texto longo)
    req1 = recorded_requests[0]
    payload1 = json.loads(req1.content)
    assert "reply_markup" in payload1
    assert "inline_keyboard" in payload1["reply_markup"]
    assert payload1["reply_markup"]["inline_keyboard"] == [
        [{"text": "Ver Detalhes", "url": "https://example.com/checkout"}]
    ]

    # Request 2: sendVideo (midia) - nao deve descartar reply_markup
    req2 = recorded_requests[1]
    raw_content2 = req2.read().decode("utf-8", errors="replace")
    assert 'name="reply_markup"' in raw_content2, "reply_markup foi descartado no envio da midia no modo split"

    import re
    match2 = re.search(r'name="reply_markup"\r?\n\r?\n([^\r\n]+)', raw_content2)
    assert match2 is not None
    parsed_markup2 = json.loads(match2.group(1).strip())
    assert parsed_markup2["inline_keyboard"] == [
        [{"text": "Ver Detalhes", "url": "https://example.com/checkout"}]
    ]


@pytest.mark.asyncio
async def test_telegram_gateway_send_broadcast_with_progress_callback_streams_file_and_notifies_progress(
    sample_video_file, monkeypatch
):
    """
    Testa que ao fornecer progress_callback no send_broadcast (SINGLE_MEDIA),
    o gateway utiliza o ProgressFileReader no streaming do arquivo e o callback
    é disparado com o avanço de bytes até total_bytes.
    """
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        # O consumo de request.read() dispara a leitura do ProgressFileReader
        _ = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1001}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    file_size = os.path.getsize(sample_video_file)
    message = BroadcastMessage(
        id="broadcast-prog-single",
        profile_id="profile-prog-1",
        target_channel_ids=["-1001234567890"],
        text="Single media with progress",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=file_size,
        ),
    )

    progress_reports = []

    def on_progress(sent_bytes: int, total_bytes: int):
        progress_reports.append((sent_bytes, total_bytes))

    result = await gateway.send_broadcast(
        bot_token="123456:PROGRESS_TOKEN_SINGLE",
        chat_id="-1001234567890",
        message=message,
        progress_callback=on_progress,
    )

    assert result is True
    assert len(recorded_requests) == 1
    assert len(progress_reports) > 0
    assert progress_reports[-1][0] == file_size
    assert progress_reports[-1][1] == file_size


@pytest.mark.asyncio
async def test_telegram_gateway_send_broadcast_split_mode_triggers_progress_callback_on_media_request(
    sample_video_file, monkeypatch
):
    """
    Testa que ao fornecer progress_callback no send_broadcast em modo SPLIT (texto longo + mídia),
    o callback de progresso é disparado durante o envio da mídia (2ª requisição).
    """
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        _ = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1002}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")

    original_client_init = httpx.AsyncClient.__init__
    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    file_size = os.path.getsize(sample_video_file)
    long_caption = "B" * 1500
    message = BroadcastMessage(
        id="broadcast-prog-split",
        profile_id="profile-prog-2",
        target_channel_ids=["-1001234567890"],
        text=long_caption,
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=file_size,
        ),
    )

    progress_reports = []

    def on_progress(sent_bytes: int, total_bytes: int):
        progress_reports.append((sent_bytes, total_bytes))

    result = await gateway.send_broadcast(
        bot_token="123456:PROGRESS_TOKEN_SPLIT",
        chat_id="-1001234567890",
        message=message,
        progress_callback=on_progress,
    )

    assert result is True
    assert len(recorded_requests) == 2
    assert len(progress_reports) > 0
    assert progress_reports[-1][0] == file_size
    assert progress_reports[-1][1] == file_size


@pytest.mark.asyncio
async def test_dispatch_broadcast_to_channel_maps_all_telegram_failure_categories_and_redacts_token(monkeypatch):
    """
    Issue #31: Mapeamento das respostas do Telegram para DeliveryFailureCategory
    e garantia de que o token do bot nunca aparece no motivo ou em logs (§9).
    """
    from src.domain.broadcast.broadcast_message import DeliveryFailureCategory
    from src.infrastructure.telegram_gateway_http import dispatch_broadcast_to_channel

    secret_token = "999888777:SECRET_TOKEN_NEVER_LEAK_THIS_12345"
    scenario = {"status": 200, "body": {"ok": True}, "exc": None}

    def mock_handler(request: httpx.Request):
        if scenario["exc"] is not None:
            raise scenario["exc"](request=request)
        return httpx.Response(scenario["status"], json=scenario["body"])

    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    msg = BroadcastMessage(
        id="b-cat",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Teste de categorias",
    )

    cases = [
        (400, {"ok": False, "description": "Bad Request: chat not found"}, DeliveryFailureCategory.BOT_NOT_IN_CHAT),
        (403, {"ok": False, "description": "Forbidden: bot was kicked from the channel chat"}, DeliveryFailureCategory.BOT_NOT_IN_CHAT),
        (400, {"ok": False, "description": "Bad Request: not enough rights to send text messages to the chat"}, DeliveryFailureCategory.NO_POST_PERMISSION),
        (403, {"ok": False, "description": "Forbidden: need administrator rights in the channel chat"}, DeliveryFailureCategory.NO_POST_PERMISSION),
        (401, {"ok": False, "description": f"Unauthorized for {secret_token}"}, DeliveryFailureCategory.INVALID_TOKEN),
        (429, {"ok": False, "description": "Too Many Requests: retry after 15", "parameters": {"retry_after": 15}}, DeliveryFailureCategory.RATE_LIMITED),
        (502, {"ok": False, "description": "Bad Gateway"}, DeliveryFailureCategory.TELEGRAM_UNAVAILABLE),
        (400, {"ok": False, "description": f"Bad Request: message is too long (/bot{secret_token}/sendMessage)"}, DeliveryFailureCategory.OTHER),
    ]

    for status_code, body, expected_cat in cases:
        gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
        scenario["status"] = status_code
        scenario["body"] = body
        scenario["exc"] = None

        res = await dispatch_broadcast_to_channel(
            gateway=gateway,
            bot_token=secret_token,
            chat_id="-1001234567890",
            message=msg,
        )
        assert res.delivered is False
        assert res.failure_category is expected_cat
        assert secret_token not in (res.detail or "")
        assert secret_token not in (gateway.last_error or "")

    # Timeout / erro de rede -> TELEGRAM_UNAVAILABLE sem vazar o token
    gateway_net = TelegramGatewayHttp(base_url="https://api.telegram.org")
    scenario["exc"] = lambda request: httpx.ReadTimeout(
        f"ReadTimeout calling https://api.telegram.org/bot{secret_token}/sendMessage",
        request=request,
    )
    res_net = await dispatch_broadcast_to_channel(
        gateway=gateway_net,
        bot_token=secret_token,
        chat_id="-1001234567890",
        message=msg,
    )
    assert res_net.delivered is False
    assert res_net.failure_category is DeliveryFailureCategory.TELEGRAM_UNAVAILABLE
    assert secret_token not in (res_net.detail or "")
    assert secret_token not in (gateway_net.last_error or "")


def test_classify_telegram_error_upgraded_group():
    from src.infrastructure.telegram_gateway_http import classify_telegram_error
    from src.domain.broadcast.broadcast_message import DeliveryFailureCategory
    cat, desc = classify_telegram_error(400, "Bad Request: group chat was upgraded to a supergroup, migrate to chat_id -1001234567890")
    assert cat == DeliveryFailureCategory.BOT_NOT_IN_CHAT
    assert "group chat was upgraded" in desc


def test_translate_telegram_error_pt_catalog():
    from src.infrastructure.telegram_gateway_http import translate_telegram_error_pt, TELEGRAM_ERROR_TRANSLATIONS_PT

    assert len(TELEGRAM_ERROR_TRANSLATIONS_PT) >= 14
    for pattern, text in TELEGRAM_ERROR_TRANSLATIONS_PT:
        assert text and len(text) > 10

    cases = [
        ("Bad Request: chat not found", "Canal ou grupo não encontrado"),
        ("Bad Request: group chat was upgraded to a supergroup", "O grupo foi promovido para supergrupo"),
        ("Bad Request: have no rights to send a message", "não tem permissão"),
        ("Bad Request: not enough rights to send text messages to the chat", "não tem permissão"),
        ("Forbidden: bot was blocked by the user", "bloqueado pelo usuário"),
        ("Forbidden: bot was kicked from the channel chat", "não é membro ou foi removido"),
        ("Bad Request: message is too long", "limite de caracteres"),
        ("Bad Request: message caption is too long", "legenda da mídia"),
        ("Bad Request: message text is empty", "não pode estar vazio"),
        ("Bad Request: BUTTON_URL_INVALID", "URL informada para o botão é inválida"),
        ("Bad Request: can't parse entities: Character '(' is reserved", "formatação HTML ou Markdown"),
        ("Bad Request: wrong file identifier/HTTP URL specified", "carregar ou processar o arquivo de mídia"),
        ("Forbidden: user is deactivated", "desativado"),
        ("Unauthorized", "Token do bot inválido"),
        ("Too Many Requests: retry after 25", "Limite de requisições"),
    ]

    for raw, expected_substr in cases:
        translated = translate_telegram_error_pt(raw)
        assert translated is not None, f"Failed to translate: {raw}"
        assert expected_substr.lower() in translated.lower()

    assert translate_telegram_error_pt(None) is None
    assert translate_telegram_error_pt("") is None
    assert translate_telegram_error_pt("An unknown upstream custom error") is None


@pytest.mark.asyncio
async def test_send_broadcast_captures_file_id_from_telegram_video_response(sample_video_file, monkeypatch):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={
            "ok": True,
            "result": {
                "message_id": 201,
                "video": {
                    "file_id": "telegram_video_file_id_123",
                    "file_unique_id": "uniq_123",
                    "width": 1920,
                    "height": 1080,
                }
            }
        })

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-vid-1",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="Video caption",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
        ),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is True
    assert getattr(gateway, "last_uploaded_file_id", None) == "telegram_video_file_id_123"


@pytest.mark.asyncio
async def test_send_broadcast_with_file_id_sends_file_id_string_without_reading_disk(monkeypatch):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 202}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    # Note that file_path does not exist on disk!
    message = BroadcastMessage(
        id="broadcast-vid-reuse",
        profile_id="profile-1",
        target_channel_ids=["-1009999999999"],
        text="Caption for second channel",
        media=MediaAttachment(
            file_path="/non_existent_path/video.mp4",
            media_type=MediaType.VIDEO,
            file_size=50000000,
        ),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1009999999999",
        message=message,
        file_id="telegram_video_file_id_123",
    )
    assert ok is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendVideo"
    content = req.read()
    # Deve conter o file_id como string no corpo
    assert b"telegram_video_file_id_123" in content


@pytest.mark.asyncio
async def test_send_broadcast_with_file_id_cleans_thumbnail_references(monkeypatch, tmp_path):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 203}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    dummy_thumb = tmp_path / "thumb.jpg"
    dummy_thumb.write_bytes(b"dummy jpeg")

    message = BroadcastMessage(
        id="broadcast-vid-reuse-thumb",
        profile_id="profile-1",
        target_channel_ids=["-1009999999999"],
        text="Caption for second channel",
        media=MediaAttachment(
            file_path="/non_existent_path/video.mp4",
            media_type=MediaType.VIDEO,
            file_size=50000000,
            thumbnail_path=str(dummy_thumb),
        ),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1009999999999",
        message=message,
        file_id="telegram_video_file_id_123",
    )
    assert ok is True
    assert len(recorded_requests) == 1
    content = recorded_requests[0].read().decode("latin1")
    assert "attach://thumbnail" not in content
    assert "telegram_video_file_id_123" in content


@pytest.mark.asyncio
async def test_send_broadcast_video_without_caption_omits_caption_field(sample_video_file, monkeypatch):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 204}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    message = BroadcastMessage(
        id="broadcast-vid-no-cap",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        text="",
        media=MediaAttachment(
            file_path=sample_video_file,
            media_type=MediaType.VIDEO,
            file_size=os.path.getsize(sample_video_file),
        ),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is True
    assert len(recorded_requests) == 1
    content = recorded_requests[0].read().decode("latin1")
    assert 'name="caption"' not in content
    assert 'name="parse_mode"' not in content


@pytest.mark.asyncio
async def test_send_broadcast_regular_poll_using_send_poll_endpoint(monkeypatch):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 301, "poll": {"id": "p-1"}}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    poll = BroadcastPoll(
        question="Qual sua linguagem preferida?",
        options=["Python", "TypeScript", "Rust"],
        is_anonymous=False,
        allows_multiple_answers=True,
        poll_type=PollType.REGULAR,
        is_closed=False,
    )
    message = BroadcastMessage(
        id="broadcast-poll-reg",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        poll=poll,
        button=InlineButton(text="Votar no site", url="https://example.com/poll"),
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.method == "POST"
    assert req.url.path.endswith("/sendPoll")
    body = json.loads(req.read())
    assert body["chat_id"] == "-1001234567890"
    assert body["question"] == "Qual sua linguagem preferida?"
    assert body["options"] == ["Python", "TypeScript", "Rust"]
    assert body["is_anonymous"] is False
    assert body["allows_multiple_answers"] is True
    assert body["type"] == "regular"
    assert "correct_option_id" not in body
    assert "explanation" not in body
    assert body["reply_markup"]["inline_keyboard"][0][0]["text"] == "Votar no site"


@pytest.mark.asyncio
async def test_send_broadcast_quiz_poll_with_correct_option_and_explanation(monkeypatch):
    recorded_requests = []

    def mock_handler(request: httpx.Request):
        recorded_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 302, "poll": {"id": "p-quiz"}}})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    poll = BroadcastPoll(
        question="Qual a capital da França?",
        options=["Londres", "Paris", "Berlim"],
        poll_type=PollType.QUIZ,
        correct_option_id=1,
        explanation="Paris é a capital e maior cidade da França.",
        is_closed=True,
    )
    message = BroadcastMessage(
        id="broadcast-poll-quiz",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        poll=poll,
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    body = json.loads(req.read())
    assert body["type"] == "quiz"
    assert body["correct_option_id"] == 1
    assert body["explanation"] == "Paris é a capital e maior cidade da França."
    assert body["is_closed"] is True


@pytest.mark.asyncio
async def test_send_broadcast_poll_handles_telegram_error(monkeypatch):
    def mock_handler(request: httpx.Request):
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: poll options must not be empty"})

    gateway = TelegramGatewayHttp(base_url="https://api.telegram.org")
    original_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    poll = BroadcastPoll(
        question="Q?",
        options=["A", "B"],
    )
    message = BroadcastMessage(
        id="broadcast-poll-err",
        profile_id="profile-1",
        target_channel_ids=["-1001234567890"],
        poll=poll,
    )

    ok = await gateway.send_broadcast(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="-1001234567890",
        message=message,
    )
    assert ok is False
    assert gateway.last_failure_category is not None









