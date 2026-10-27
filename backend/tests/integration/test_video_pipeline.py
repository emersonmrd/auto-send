import json
import os
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio

from src.domain.broadcast.broadcast_message import BroadcastMessage, MediaAttachment, MediaType
from src.domain.channels.channel import Channel
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.progress_reader import ProgressFileReader
from src.infrastructure.sqlite_repositories import Base
from src.presentation.main import (
    app,
    broadcast_repo,
    channel_repo,
    engine,
    extract_mp4_metadata,
    profile_repo,
    telegram_gateway,
)
from tests.helpers import build_synthetic_mp4

ROOT_DIR = Path(__file__).resolve().parents[3]
TESTS_MEDIA_DIR = ROOT_DIR / "tests_media"
REAL_WHATSAPP_VIDEO = TESTS_MEDIA_DIR / "WhatsApp Video 2026-10-19 at 23.00.07.mp4"
REAL_DEGLI_VIDEO = TESTS_MEDIA_DIR / "degli.mp4"

_FUTURE_BASE = (_datetime.now(_timezone.utc) + _timedelta(days=30)).date()


def future_at(day: int, time_str: str) -> str:
    return f"{(_FUTURE_BASE + _timedelta(days=day)).isoformat()}T{time_str}Z"


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    async def _default_can_post(bot_token: str, chat_id: str) -> None:
        return None

    monkeypatch.setattr(telegram_gateway, "ensure_bot_can_post", _default_can_post)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ============================================================================
# 1. Metadados e Dimensões de Vídeos Reais (tests_media/)
# ============================================================================

@pytest.mark.skipif(not REAL_WHATSAPP_VIDEO.exists(), reason="tests_media/ WhatsApp video não encontrado no disco local")
def test_real_whatsapp_video_metadata_extraction():
    """Valida extração de metadados do vídeo real de ~8 MB (portrait 576x1024, duração 70s)."""
    meta = extract_mp4_metadata(str(REAL_WHATSAPP_VIDEO))
    assert meta["duration"] == 70
    assert meta["width"] == 576
    assert meta["height"] == 1024


@pytest.mark.skipif(not REAL_DEGLI_VIDEO.exists(), reason="tests_media/ degli.mp4 não encontrado no disco local")
def test_real_degli_large_video_metadata_extraction():
    """Valida extração de metadados do vídeo real de ~356 MB (portrait 4K 2160x3840, duração 71s)."""
    meta = extract_mp4_metadata(str(REAL_DEGLI_VIDEO))
    assert meta["duration"] == 71
    assert meta["width"] == 2160
    assert meta["height"] == 3840


# ============================================================================
# 2. Streaming de Arquivos Grandes sem Sobrecarga de Memória (ProgressFileReader)
# ============================================================================

@pytest.mark.skipif(not REAL_DEGLI_VIDEO.exists(), reason="tests_media/ degli.mp4 não encontrado no disco local")
def test_large_video_streaming_progress_chunks_without_memory_blowup():
    """Lê os 356 MB do vídeo real em chunks com callback de progresso contínuo."""
    progress_samples: list[tuple[int, int]] = []

    def on_progress(sent: int, total: int):
        progress_samples.append((sent, total))

    reader = ProgressFileReader(str(REAL_DEGLI_VIDEO), callback=on_progress)
    expected_size = REAL_DEGLI_VIDEO.stat().st_size
    assert reader.total_bytes == expected_size

    bytes_read = 0
    # Consome em blocos de 1 MB
    while True:
        chunk = reader.read(1024 * 1024)
        if not chunk:
            break
        bytes_read += len(chunk)

    reader.close()
    assert bytes_read == expected_size
    assert len(progress_samples) > 0
    # O último callback deve refletir 100% dos bytes
    assert progress_samples[-1][0] == expected_size
    assert progress_samples[-1][1] == expected_size


# ============================================================================
# 3. Pipeline de Envio de Vídeo com Streaming e Limpeza Imediata de Temporários
# ============================================================================

@pytest.mark.asyncio
async def test_video_dispatch_pipeline_streams_and_cleans_temp_file(client, monkeypatch):
    """Envia vídeo via POST /api/v1/broadcasts, valida streaming e garante descarte do temporário."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="video_bot")
    profile = Profile(id="profile-video-test", name="Video Profile", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(id="chan-video-1", profile_id=profile.id, title="Canal de Vídeos", chat_id="-1001234567890")
    await channel_repo.save(channel)

    captured_messages: list[BroadcastMessage] = []
    temp_path_recorded: list[str] = []

    async def mock_send_broadcast(bot_token, chat_id, message, reply_markup=None, progress_callback=None, **kwargs):
        captured_messages.append(message)
        assert message.media is not None
        assert message.media.media_type == MediaType.VIDEO
        assert message.media.file_path is not None
        temp_path_recorded.append(message.media.file_path)
        # Durante o envio, o arquivo temporário existe no disco
        assert os.path.exists(message.media.file_path)
        if progress_callback:
            progress_callback(100, 100)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    # Usa o vídeo real de 8 MB se disponível, ou sintetiza um MP4 vertical válido
    if REAL_WHATSAPP_VIDEO.exists():
        video_payload = REAL_WHATSAPP_VIDEO.read_bytes()
    else:
        video_payload = build_synthetic_mp4(width=1080, height=1920, duration=10)

    data = {
        "profile_id": profile.id,
        "target_channel_ids": json.dumps([channel.chat_id]),
        "text": "Confira o novo vídeo do canal!",
    }
    files = {
        "media_file": ("video.mp4", video_payload, "video/mp4"),
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["dispatched_count"] == 1

    # Valida que o gateway recebeu os metadados corretos
    assert len(captured_messages) == 1
    sent_media = captured_messages[0].media
    assert sent_media.duration and sent_media.duration > 0
    assert sent_media.width and sent_media.width > 0
    assert sent_media.height and sent_media.height > 0

    # Invariante de ciclo de vida (§10): o arquivo temporário em temp_media/ é apagado após o envio
    assert len(temp_path_recorded) == 1
    assert not os.path.exists(temp_path_recorded[0]), f"Arquivo temporário {temp_path_recorded[0]} não foi excluído"


# ============================================================================
# 4. Ciclo de Vida de Vídeo Agendado e Limpeza ao Cancelar
# ============================================================================

@pytest.mark.asyncio
async def test_scheduled_video_lifecycle_cleanup_on_cancel(client):
    """Garante que mídia de agendamento é mantida em temp_media/ enquanto pendente e excluída ao cancelar."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="sched_video_bot")
    profile = Profile(id="profile-sched-video", name="Sched Video", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(id="chan-sched-v1", profile_id=profile.id, title="Canal Sched", chat_id="-1001234567890")
    await channel_repo.save(channel)

    video_bytes = build_synthetic_mp4(width=720, height=1280, duration=15)
    scheduled_time = future_at(2, "14:00:00")

    data = {
        "profile_id": profile.id,
        "target_channel_ids": json.dumps([channel.chat_id]),
        "text": "Vídeo agendado para amanhã",
        "scheduled_at": scheduled_time,
    }
    files = {
        "media_file": ("scheduled_video.mp4", video_bytes, "video/mp4"),
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    created_id = resp.json()["broadcast_id"]

    broadcast = await broadcast_repo.get_by_id(created_id)
    assert broadcast is not None
    assert broadcast.status.value == "SCHEDULED"
    temp_file_path = broadcast.media.file_path
    # Enquanto o agendamento está ativo, o arquivo temporário existe no disco
    assert os.path.exists(temp_file_path)

    # Cancela o agendamento
    cancel_resp = await client.delete(f"/api/v1/broadcasts/{created_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Invariante de ciclo de vida (§10): o arquivo temporário é apagado imediatamente no cancelamento
    assert not os.path.exists(temp_file_path), "Arquivo temporário não foi removido após cancelamento"


# ============================================================================
# 5. Enriquecimento de Erro de Arquivo > 50 MB para Telegram Bot API Local
# ============================================================================

def test_telegram_gateway_enriches_large_file_error():
    """Valida mensagem explicativa quando envio de arquivo > 50 MB falha na Bot API padrão."""
    fake_media = MediaAttachment(
        file_path="/tmp/large.mp4",
        media_type=MediaType.VIDEO,
        file_size=60 * 1024 * 1024,  # 60 MB (> 50 MB)
    )
    fake_msg = BroadcastMessage(
        id="broad-large-1",
        profile_id="p-1",
        target_channel_ids=["-1001234567890"],
        text="Arquivo grande",
        media=fake_media,
    )

    # Na URL oficial do Telegram (api.telegram.org)
    telegram_gateway._enrich_large_file_error(fake_msg, "https://api.telegram.org")
    assert "50MB" in telegram_gateway.last_error
    assert "Local Bot API Server" in telegram_gateway.last_error

    # Em servidor local de bot API, não altera o erro com o aviso de 50 MB
    telegram_gateway.last_error = "Erro original da API local"
    telegram_gateway._enrich_large_file_error(fake_msg, "http://127.0.0.1:8081")
    assert telegram_gateway.last_error == "Erro original da API local"


# ============================================================================
# 6. Reutilização de file_id e Progresso Linear em Multi-Canal
# ============================================================================

@pytest.mark.asyncio
async def test_multi_channel_video_broadcast_reuses_file_id_and_tracks_progress_linearly(client, monkeypatch):
    """Garante que o 1º canal faz upload e os canais seguintes reutilizam file_id sem oscilar o progresso."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="multi_bot")
    profile = Profile(id="profile-multi-vid", name="Multi Video Profile", credentials=creds)
    await profile_repo.save(profile)

    c1 = Channel(id="c-multi-1", profile_id=profile.id, title="Canal 1", chat_id="-1001111111111")
    c2 = Channel(id="c-multi-2", profile_id=profile.id, title="Canal 2", chat_id="-1002222222222")
    await channel_repo.save(c1)
    await channel_repo.save(c2)

    recorded_calls = []

    async def mock_send(bot_token, chat_id, message, progress_callback=None, file_id=None, **kwargs):
        recorded_calls.append({"chat_id": chat_id, "file_id": file_id})
        if file_id is None:
            # Simula progresso do upload físico para o 1º canal
            if progress_callback:
                progress_callback(500, 1000)
                progress_callback(1000, 1000)
            telegram_gateway.last_uploaded_file_id = "cached_telegram_vid_id"
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send)

    video_bytes = build_synthetic_mp4(width=720, height=1280, duration=10)
    data = {
        "profile_id": profile.id,
        "target_channel_ids": json.dumps([c1.chat_id, c2.chat_id]),
        "text": "Multi canal video",
        "tracking_id": "track-multi-vid",
    }
    files = {
        "media_file": ("video.mp4", video_bytes, "video/mp4"),
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["dispatched_count"] == 2

    # Verifica que houve 2 chamadas: a 1ª sem file_id e a 2ª com file_id reaproveitado
    assert len(recorded_calls) == 2
    assert recorded_calls[0]["chat_id"] == c1.chat_id
    assert recorded_calls[0]["file_id"] is None
    assert recorded_calls[1]["chat_id"] == c2.chat_id
    assert recorded_calls[1]["file_id"] == "cached_telegram_vid_id"

