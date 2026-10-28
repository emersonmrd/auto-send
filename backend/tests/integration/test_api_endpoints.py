import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from src.presentation.main import app, engine, profile_repo, channel_repo, telegram_gateway, broadcast_repo
from src.infrastructure.sqlite_repositories import Base
from src.domain.profiles.profile import Profile
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.channels.channel import Channel
from src.domain.broadcast.broadcast_message import BroadcastMessage
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone

# Base de datas futuras: 30 dias à frente da execução, para nenhum agendamento virar passado (issue #54).
_FUTURE_BASE = (_datetime.now(_timezone.utc) + _timedelta(days=30)).date()


def future_at(day: int, time: str) -> str:
    """Instante futuro em ISO-8601 com Z, `day` dias depois da base; a ordem entre os dias se mantém."""
    return f"{(_FUTURE_BASE + _timedelta(days=day)).isoformat()}T{time}Z"

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

async def test_should_list_profiles_empty_initially(client):
    resp = await client.get("/api/v1/profiles")
    assert resp.status_code == 200
    assert resp.json() == []

async def test_should_create_channel_for_existing_profile(client):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-1", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    payload = {
        "title": "Canal de Teste",
        "chat_id": "-1001234567890",
        "invite_link": "https://t.me/test",
    }
    resp = await client.post(f"/api/v1/profiles/{profile.id}/channels", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Canal de Teste"
    assert data["chat_id"] == "-1001234567890"

async def test_should_reject_broadcast_with_insecure_button_url(client):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-1", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    form_data = {
        "profile_id": "profile-test-1",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Check this internal link",
        "button_text": "Secret",
        "button_url": "http://127.0.0.1:8000/internal",
    }
    resp = await client.post("/api/v1/broadcasts", data=form_data)
    assert resp.status_code == 422

async def test_should_create_broadcast_with_photo_upload_and_dispatch_via_photo_gateway(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-photo", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    dispatched_messages = []
    async def mock_send_broadcast(bot_token: str, chat_id: str, message):
        dispatched_messages.append((bot_token, chat_id, message))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    file_bytes = b"\xff\xd8\xff\xe0" + b"fake-jpeg-content"
    files = {
        "media_file": ("banner.jpg", file_bytes, "image/jpeg")
    }
    data = {
        "profile_id": "profile-test-photo",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Novidades da semana!",
        "button_text": "Saiba mais",
        "button_url": "https://example.com/news",
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data["status"] == "COMPLETED"
    assert resp_data["dispatched_count"] == 1
    assert len(dispatched_messages) == 1

    bot_token, chat_id, msg = dispatched_messages[0]
    assert bot_token == creds.token
    assert chat_id == "-1001234567890"
    assert msg.media is not None
    assert msg.media.media_type.value == "PHOTO"


@pytest.mark.asyncio
async def test_should_create_broadcast_with_video_upload_and_pass_duration_and_dimensions(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-video-dur", name="Bruna Video", credentials=creds)
    await profile_repo.save(profile)

    dispatched_messages = []
    async def mock_send_broadcast(bot_token: str, chat_id: str, message):
        dispatched_messages.append((bot_token, chat_id, message))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    file_bytes = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-video-bytes"
    files = {
        "media_file": ("promo.mp4", file_bytes, "video/mp4")
    }
    data = {
        "profile_id": "profile-test-video-dur",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Vídeo liberado!",
        "video_duration": "128",
        "video_width": "1920",
        "video_height": "1080",
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    assert len(dispatched_messages) == 1
    _, _, msg = dispatched_messages[0]
    assert msg.media is not None
    assert msg.media.media_type.value == "VIDEO"
    assert msg.media.duration == 128
    assert msg.media.width == 1920
    assert msg.media.height == 1080


@pytest.mark.asyncio
async def test_should_create_broadcast_with_video_and_thumbnail_upload(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-video-thumb", name="Bruna Video Thumb", credentials=creds)
    await profile_repo.save(profile)

    dispatched_messages = []
    async def mock_send_broadcast(bot_token: str, chat_id: str, message):
        dispatched_messages.append((bot_token, chat_id, message))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    files = {
        "media_file": ("promo.mp4", b"\x00\x00\x00\x18ftypmp42" + b"fake-video-bytes", "video/mp4"),
        "thumbnail_file": ("thumb.jpg", b"\xff\xd8\xff\xe0" + b"fake-thumb-bytes", "image/jpeg"),
    }
    data = {
        "profile_id": "profile-test-video-thumb",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Vídeo com capa!",
    }

    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    assert len(dispatched_messages) == 1
    _, _, msg = dispatched_messages[0]
    assert msg.media is not None
    assert msg.media.media_type.value == "VIDEO"
    assert msg.media.thumbnail_path is not None
    assert msg.media.thumbnail_path.endswith(".jpg")

async def test_should_schedule_broadcast_when_scheduled_at_in_future(client):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-sched", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    future_iso = future_at(0, "15:30:00")
    data = {
        "profile_id": "profile-test-sched",
        "target_channel_ids": '["-1001234567890", "-1001987654321"]',
        "text": "Post agendado para o futuro",
        "scheduled_at": future_iso,
    }

    resp = await client.post("/api/v1/broadcasts", data=data)
    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data["status"] == "SCHEDULED"
    assert resp_data["scheduled_at"] is not None
    assert resp_data["channels_count"] == 2
    assert resp_data["dispatched_count"] == 0

async def test_should_return_clear_error_details_when_telegram_gateway_fails(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-fail", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    async def mock_failing_send_broadcast(bot_token: str, chat_id: str, message):
        return False

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_failing_send_broadcast)

    data = {
        "profile_id": "profile-test-fail",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Tentativa que vai falhar",
    }

    resp = await client.post("/api/v1/broadcasts", data=data)
    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data["status"] == "FAILED"
    assert resp_data["dispatched_count"] == 0
    assert "errors" in resp_data
    assert len(resp_data["errors"]) == 1
    assert "Failed to send to -1001234567890" in resp_data["errors"][0]

async def test_should_handle_gateway_exception_without_500_crash(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-test-exc", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    async def mock_crashing_send_broadcast(bot_token: str, chat_id: str, message):
        raise RuntimeError("Network socket timeout")

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_crashing_send_broadcast)

    data = {
        "profile_id": "profile-test-exc",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Tentativa que lanca excecao",
    }

    resp = await client.post("/api/v1/broadcasts", data=data)
    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data["status"] == "FAILED"
    assert resp_data["dispatched_count"] == 0
    assert len(resp_data["errors"]) == 1
    assert "Error sending to -1001234567890: Network socket timeout" in resp_data["errors"][0]


# =========================================================================
# FASE 3 (TDD RED): Fila de Agendamento, Cancelamento e Edição de Broadcast
# =========================================================================

async def test_get_scheduled_broadcasts_queue_order(client):
    """
    Cadastra 3 broadcasts com horários diferentes e valida a ordem ascendente
    via GET /api/v1/profiles/{profile_id}/scheduled-broadcasts.
    """
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-queue-order", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    # Cadastra mensagem agendada (segunda na ordem)
    resp2 = await client.post("/api/v1/broadcasts", data={
        "profile_id": "profile-queue-order",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Mensagem das 12h",
        "scheduled_at": future_at(1, "12:00:00"),
    })
    assert resp2.status_code == 201
    id2 = resp2.json()["broadcast_id"]

    # Cadastra mensagem agendada (primeira na ordem)
    resp1 = await client.post("/api/v1/broadcasts", data={
        "profile_id": "profile-queue-order",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Mensagem antecipada",
        "scheduled_at": future_at(0, "18:00:00"),
    })
    assert resp1.status_code == 201
    id1 = resp1.json()["broadcast_id"]

    # Cadastra mensagem agendada (terceira na ordem)
    resp3 = await client.post("/api/v1/broadcasts", data={
        "profile_id": "profile-queue-order",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Mensagem mais tardia",
        "scheduled_at": future_at(2, "08:00:00"),
    })
    assert resp3.status_code == 201
    id3 = resp3.json()["broadcast_id"]

    # Consulta a fila do perfil
    queue_resp = await client.get(f"/api/v1/profiles/{profile.id}/scheduled-broadcasts")
    assert queue_resp.status_code == 200
    queue = queue_resp.json()
    assert len(queue) == 3

    # Validação de ordem cronológica ascendente
    assert queue[0]["id"] == id1
    assert queue[0]["scheduled_at"] == future_at(0, "18:00:00")
    assert queue[1]["id"] == id2
    assert queue[1]["scheduled_at"] == future_at(1, "12:00:00")
    assert queue[2]["id"] == id3
    assert queue[2]["scheduled_at"] == future_at(2, "08:00:00")


async def test_cancel_scheduled_broadcast_success(client):
    """
    Cria agendamento com arquivo de mídia temporário, chama DELETE /api/v1/broadcasts/{id}/cancel,
    valida status 200, status CANCELLED no banco e remoção física do arquivo de mídia.
    """
    import os
    from src.presentation.main import broadcast_repo

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-cancel-success", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    file_bytes = b"\xff\xd8\xff\xe0" + b"fake-jpeg-cancel-test"
    files = {
        "media_file": ("cancel_me.jpg", file_bytes, "image/jpeg")
    }
    data = {
        "profile_id": "profile-cancel-success",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Post com mídia para ser cancelado",
        "scheduled_at": future_at(3, "10:00:00"),
    }
    resp = await client.post("/api/v1/broadcasts", data=data, files=files)
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    # Verifica que o broadcast existe e tem arquivo de mídia em disco
    saved_entity = await broadcast_repo.get_by_id(broadcast_id)
    assert saved_entity is not None
    assert saved_entity.media is not None
    temp_path = saved_entity.media.file_path
    assert os.path.exists(temp_path)

    # Executa o cancelamento
    del_resp = await client.delete(f"/api/v1/broadcasts/{broadcast_id}/cancel")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["id"] == broadcast_id
    assert del_data["status"] == "CANCELLED"

    # Valida no banco que status virou CANCELLED
    updated_entity = await broadcast_repo.get_by_id(broadcast_id)
    assert updated_entity.status.value == "CANCELLED"

    # Valida Zero Clutter Policy: arquivo físico foi deletado
    assert not os.path.exists(temp_path)


async def test_cancel_in_flight_or_completed_broadcast_fails(client, monkeypatch):
    """
    Valida que tentar cancelar um broadcast COMPLETED retorna 422 Unprocessable Entity.
    """
    from src.presentation.main import broadcast_repo

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-cancel-completed", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    async def mock_successful_broadcast(bot_token: str, chat_id: str, message):
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_successful_broadcast)

    # Criar um broadcast direto (disparo imediato com sucesso -> status COMPLETED)
    resp = await client.post("/api/v1/broadcasts", data={
        "profile_id": "profile-cancel-completed",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Broadcast que será completado",
    })
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    saved_entity = await broadcast_repo.get_by_id(broadcast_id)
    assert saved_entity.status.value == "COMPLETED"

    # Tentativa de cancelar broadcast já completado deve retornar 422
    del_resp = await client.delete(f"/api/v1/broadcasts/{broadcast_id}/cancel")
    assert del_resp.status_code == 422
    assert "Cannot cancel an in-flight or completed broadcast" in del_resp.json()["detail"]


async def test_patch_scheduled_broadcast_edit_and_reschedule(client):
    """
    Cria broadcast agendado, chama PATCH /api/v1/broadcasts/{id} com novo texto,
    novo botão e nova data futura, valida 200 e dados atualizados no banco e na resposta.
    """
    from src.presentation.main import broadcast_repo

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-patch-edit", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    init_data = {
        "profile_id": "profile-patch-edit",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Texto original",
        "scheduled_at": future_at(0, "14:00:00"),
    }
    resp = await client.post("/api/v1/broadcasts", data=init_data)
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    # Chamada PATCH com alterações
    patch_payload = {
        "text": "Texto atualizado da publicação",
        "button_text": "Novo Link",
        "button_url": "https://novolink.com",
        "scheduled_at": future_at(2, "18:30:00"),
    }
    patch_resp = await client.patch(f"/api/v1/broadcasts/{broadcast_id}", json=patch_payload)
    assert patch_resp.status_code == 200
    res_data = patch_resp.json()

    assert res_data["id"] == broadcast_id
    assert res_data["text"] == "Texto atualizado da publicação"
    assert res_data["button"]["text"] == "Novo Link"
    assert res_data["button"]["url"] == "https://novolink.com"
    assert res_data["scheduled_at"] == future_at(2, "18:30:00")
    assert res_data["status"] == "SCHEDULED"

    # Confirma no repositório persistido
    persisted = await broadcast_repo.get_by_id(broadcast_id)
    assert persisted.text == "Texto atualizado da publicação"
    assert persisted.button is not None
    assert persisted.button.text == "Novo Link"
    assert persisted.button.url == "https://novolink.com"
    assert persisted.scheduled_at.isoformat().startswith(future_at(2, "18:30:00")[:-1])


async def test_patch_scheduled_broadcast_past_date_fails(client):
    """
    Valida que passar data no passado no PATCH retorna 422 Unprocessable Entity.
    """
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-patch-past", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    init_data = {
        "profile_id": "profile-patch-past",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Agendamento futuro normal",
        "scheduled_at": future_at(4, "10:00:00"),
    }
    resp = await client.post("/api/v1/broadcasts", data=init_data)
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    # Tentativa de reagendar com data no passado (ex: 2020)
    past_payload = {
        "scheduled_at": "2020-01-01T00:00:00Z",
    }
    patch_resp = await client.patch(f"/api/v1/broadcasts/{broadcast_id}", json=past_payload)
    assert patch_resp.status_code == 422
    assert "scheduled_at cannot be in the past" in patch_resp.json()["detail"]


async def test_scheduled_broadcast_executes_automatically_after_1_second(client, monkeypatch):
    """
    Agenda um broadcast via POST /api/v1/broadcasts para daqui a 1 segundo com o
    scheduler_service real ativo, aguarda asyncio.sleep(2.5) e comprova que o status
    no banco muda de SCHEDULED para COMPLETED automaticamente e remove da fila.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import broadcast_repo, scheduler_service

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-auto-exec", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    dispatched = []
    async def mock_send(bot_token: str, chat_id: str, message):
        dispatched.append((bot_token, chat_id, message.id))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send)

    scheduler_service.start()
    try:
        run_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        resp = await client.post("/api/v1/broadcasts", data={
            "profile_id": "profile-auto-exec",
            "target_channel_ids": '["-1001234567890"]',
            "text": "Disparo automático em 1s",
            "scheduled_at": run_at,
        })
        assert resp.status_code == 201
        broadcast_id = resp.json()["broadcast_id"]
        assert resp.json()["status"] == "SCHEDULED"

        # Verifica que o status salvo inicialmente no banco é SCHEDULED
        initial_entity = await broadcast_repo.get_by_id(broadcast_id)
        assert initial_entity is not None
        assert initial_entity.status.value == "SCHEDULED"

        # Aguarda o disparo automático pelo APScheduler sem chamada manual
        await asyncio.sleep(2.5)

        final_entity = await broadcast_repo.get_by_id(broadcast_id)
        assert final_entity is not None
        assert final_entity.status.value == "COMPLETED"
        assert len(dispatched) == 1

        # Não deve mais constar na fila de agendamentos pendentes
        queue_resp = await client.get(f"/api/v1/profiles/{profile.id}/scheduled-broadcasts")
        assert queue_resp.status_code == 200
        assert queue_resp.json() == []
    finally:
        scheduler_service.shutdown(wait=False)


async def test_scheduled_broadcast_current_minute_misfire_tolerance(client, monkeypatch):
    """
    Simula o caso real do browser (input datetime-local tem precisão apenas de minuto):
    quando o usuário agenda para o minuto corrente ou poucos segundos atrás (ex: -15s),
    o broadcast não pode ser descartado silenciosamente pelo APScheduler e deve ser
    disparado automaticamente até ficar COMPLETED.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import broadcast_repo, scheduler_service

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-misfire-tol", name="Bruna", credentials=creds)
    await profile_repo.save(profile)

    dispatched = []
    async def mock_send(bot_token: str, chat_id: str, message):
        dispatched.append((bot_token, chat_id, message.id))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send)

    scheduler_service.start()
    try:
        # Data 15 segundos atrás (simulando truncamento de segundos do datetime-local)
        slightly_past_iso = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
        resp = await client.post("/api/v1/broadcasts", data={
            "profile_id": "profile-misfire-tol",
            "target_channel_ids": '["-1001234567890"]',
            "text": "Agendado no minuto corrente",
            "scheduled_at": slightly_past_iso,
        })
        assert resp.status_code == 201
        broadcast_id = resp.json()["broadcast_id"]

        await asyncio.sleep(1.5)

        final_entity = await broadcast_repo.get_by_id(broadcast_id)
        assert final_entity is not None
        assert final_entity.status.value == "COMPLETED"
        assert len(dispatched) == 1
    finally:
        scheduler_service.shutdown(wait=False)





# =========================================================================
# =========================================================================
# Fase 3 (TDD Red): Testes para Edição e Exclusão de Perfis / Bots
# =========================================================================

async def test_update_profile_success(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="original_bot")
    profile = Profile(id="profile-update-1", name="Original Bot", credentials=creds)
    await profile_repo.save(profile)
    profile_id = profile.id

    async def mock_validate(token):
        return {"username": "updated_bot"}
    monkeypatch.setattr(telegram_gateway, "validate_bot_token", mock_validate)

    update_res = await client.put(
        f"/api/v1/profiles/{profile_id}",
        json={"name": "Updated Bot Name", "bot_token": "1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Bot Name"

async def test_update_profile_not_found(client):
    res = await client.put(
        "/api/v1/profiles/non-existent-id",
        json={"name": "Nobody", "bot_token": "valid_token:123"}
    )
    assert res.status_code == 404

async def test_update_profile_telegram_token_rejected_422(client, monkeypatch):
    """Quando a Telegram API rejeita o novo token de bot, PUT deve responder 422 Unprocessable Entity."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="original_bot")
    profile = Profile(id="profile-update-rej", name="Bot Token Rejection", credentials=creds)
    await profile_repo.save(profile)

    async def mock_validate_fail(token):
        raise ValueError("Telegram Bot Token validation failed: Unauthorized (401)")

    monkeypatch.setattr(telegram_gateway, "validate_bot_token", mock_validate_fail)

    res = await client.put(
        f"/api/v1/profiles/{profile.id}",
        json={"name": "New Name", "bot_token": "9999999999:REJECTED_TOKEN_12345"}
    )
    assert res.status_code == 422
    assert "Telegram Bot Token validation failed" in res.json()["detail"]

async def test_delete_profile_success(client):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="delete_bot")
    profile = Profile(id="profile-delete-1", name="Bot to Delete", credentials=creds)
    await profile_repo.save(profile)
    profile_id = profile.id

    delete_res = await client.delete(f"/api/v1/profiles/{profile_id}")
    assert delete_res.status_code == 200

    list_res = await client.get("/api/v1/profiles")
    assert not any(m["id"] == profile_id for m in list_res.json())

async def test_delete_profile_cascades_and_removes_channels_and_broadcasts(client):
    """Ao deletar um perfil no SQLite, canais e broadcasts vinculados a ele devem ser removidos e não ficarem órfãos."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="cascade_bot")
    profile = Profile(id="profile-cascade-del", name="Cascade Delete Profile", credentials=creds)
    await profile_repo.save(profile)

    # Cria canal associado ao perfil
    channel = Channel(
        id="channel-cascade-1",
        profile_id=profile.id,
        title="Canal Vinculado",
        chat_id="-1001234567890",
    )
    await channel_repo.save(channel)

    # Cria broadcast associado ao perfil
    broadcast = BroadcastMessage(
        id="broadcast-cascade-1",
        profile_id=profile.id,
        target_channel_ids=["-1001234567890"],
        text="Broadcast vinculado ao perfil que será excluído",
    )
    await broadcast_repo.save(broadcast)

    # Assegura que ambos existem no banco SQLite antes da exclusão
    assert len(await channel_repo.list_by_profile(profile.id)) == 1
    assert len(await broadcast_repo.list_by_profile(profile.id)) == 1

    # Executa a exclusão do perfil
    del_res = await client.delete(f"/api/v1/profiles/{profile.id}")
    assert del_res.status_code == 200

    # Valida que o perfil, canais e broadcasts foram expurgados do banco
    assert await profile_repo.get_by_id(profile.id) is None
    assert await channel_repo.list_by_profile(profile.id) == []
    assert await broadcast_repo.list_by_profile(profile.id) == []

async def test_delete_profile_not_found(client):
    res = await client.delete("/api/v1/profiles/non-existent-id")
    assert res.status_code == 404

async def test_update_channel_success(client):
    """PUT /api/v1/channels/{channel_id} deve atualizar name e telegram_channel_id com sucesso."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="chan_bot")
    profile = Profile(id="profile-chan-update", name="Profile Update Test", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-to-update",
        profile_id=profile.id,
        title="Canal Original",
        chat_id="-1001111111111",
    )
    await channel_repo.save(channel)

    payload = {
        "name": "Canal Atualizado",
        "telegram_channel_id": "-1002222222222",
    }
    resp = await client.put(f"/api/v1/channels/{channel.id}", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == channel.id
    assert data.get("name") == "Canal Atualizado" or data.get("title") == "Canal Atualizado"
    assert data.get("telegram_channel_id") == "-1002222222222" or data.get("chat_id") == "-1002222222222"

    # Confere persistência no repositório
    persisted = await channel_repo.get_by_id(channel.id)
    assert persisted is not None
    assert persisted.title == "Canal Atualizado"
    assert persisted.chat_id == "-1002222222222"

async def test_update_channel_not_found(client):
    """PUT /api/v1/channels/{channel_id} com id inexistente deve retornar 404."""
    payload = {
        "name": "Canal Inexistente",
        "telegram_channel_id": "-1003333333333",
    }
    resp = await client.put("/api/v1/channels/non-existent-channel-id", json=payload)
    assert resp.status_code == 404

async def test_update_channel_invalid_chat_id(client):
    """PUT /api/v1/channels/{channel_id} com telegram_channel_id em formato inválido deve retornar 422."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="chan_bot_2")
    profile = Profile(id="profile-chan-inv", name="Profile Invalid ChatId", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-to-fail",
        profile_id=profile.id,
        title="Canal Valido",
        chat_id="-1001111111111",
    )
    await channel_repo.save(channel)

    payload = {
        "name": "Canal Falha",
        "telegram_channel_id": "12345",  # Invalido: canais devem começar com -100
    }
    resp = await client.put(f"/api/v1/channels/{channel.id}", json=payload)
    assert resp.status_code in [400, 422]

async def test_delete_channel_success(client):
    """DELETE /api/v1/channels/{channel_id} deve remover o canal do repositório."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="del_chan_bot")
    profile = Profile(id="profile-chan-del", name="Profile Del Channel", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-to-delete",
        profile_id=profile.id,
        title="Canal para Deletar",
        chat_id="-1004444444444",
    )
    await channel_repo.save(channel)
    assert await channel_repo.get_by_id(channel.id) is not None

    del_resp = await client.delete(f"/api/v1/channels/{channel.id}")
    assert del_resp.status_code == 200

    # Confere que o canal foi removido
    assert await channel_repo.get_by_id(channel.id) is None

async def test_delete_channel_not_found(client):
    """DELETE /api/v1/channels/{channel_id} com id inexistente deve retornar 404."""
    del_resp = await client.delete("/api/v1/channels/non-existent-channel-id")
    assert del_resp.status_code == 404


# ============================================================================
# TDD Red Tests: Rota de Progresso Real de Envio para o Telegram
# ============================================================================

async def test_get_broadcast_progress_not_found(client):
    """GET /api/v1/broadcasts/progress/{tracking_id} retorna 404 para tracking_id inexistente."""
    resp = await client.get("/api/v1/broadcasts/progress/non-existent-tracking-id")
    assert resp.status_code == 404
    assert resp.json().get("detail") == "Tracking ID not found"


async def test_get_broadcast_progress_in_progress(client):
    """GET /api/v1/broadcasts/progress/{tracking_id} retorna progresso ativo em JSON."""
    tracking_id = "track-upload-active-123"
    from src.presentation import main
    if hasattr(main, "upload_progress_tracker"):
        main.upload_progress_tracker[tracking_id] = {
            "tracking_id": tracking_id,
            "stage": "uploading_to_telegram",
            "percent": 45,
            "sent_bytes": 4718592,
            "total_bytes": 10485760,
            "status": "in_progress",
        }

    resp = await client.get(f"/api/v1/broadcasts/progress/{tracking_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracking_id"] == tracking_id
    assert data["stage"] == "uploading_to_telegram"
    assert data["percent"] == 45
    assert data["sent_bytes"] == 4718592
    assert data["total_bytes"] == 10485760
    assert data["status"] == "in_progress"


async def test_get_broadcast_progress_completed(client):
    """GET /api/v1/broadcasts/progress/{tracking_id} retorna status concluído."""
    tracking_id = "track-upload-completed-456"
    from src.presentation import main
    if hasattr(main, "upload_progress_tracker"):
        main.upload_progress_tracker[tracking_id] = {
            "tracking_id": tracking_id,
            "stage": "uploading_to_telegram",
            "percent": 100,
            "sent_bytes": 10485760,
            "total_bytes": 10485760,
            "status": "completed",
        }

    resp = await client.get(f"/api/v1/broadcasts/progress/{tracking_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracking_id"] == tracking_id
    assert data["stage"] == "uploading_to_telegram"
    assert data["percent"] == 100
    assert data["sent_bytes"] == 10485760
    assert data["total_bytes"] == 10485760
    assert data["status"] == "completed"


async def test_get_broadcast_progress_failed(client):
    """GET /api/v1/broadcasts/progress/{tracking_id} retorna status de falha."""
    tracking_id = "track-upload-failed-789"
    from src.presentation import main
    if hasattr(main, "upload_progress_tracker"):
        main.upload_progress_tracker[tracking_id] = {
            "tracking_id": tracking_id,
            "stage": "uploading_to_telegram",
            "percent": 25,
            "sent_bytes": 2621440,
            "total_bytes": 10485760,
            "status": "failed",
        }

    resp = await client.get(f"/api/v1/broadcasts/progress/{tracking_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracking_id"] == tracking_id
    assert data["stage"] == "uploading_to_telegram"
    assert data["status"] == "failed"


async def test_create_broadcast_registers_upload_progress(client, tmp_path):
    """POST /api/v1/broadcasts com tracking_id registra e permite consulta no endpoint de progresso."""
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="prog_bot")
    profile = Profile(id="profile-prog-1", name="Profile Prog", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-prog-1",
        profile_id=profile.id,
        title="Canal Progresso",
        chat_id="-1009988776655",
    )
    await channel_repo.save(channel)

    tracking_id = "track-auto-send-999"
    dummy_file = tmp_path / "video_prog.mp4"
    dummy_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"video payload" * 100)

    with open(dummy_file, "rb") as f:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps([channel.chat_id]),
                "text": "Broadcast com progresso",
                "tracking_id": tracking_id,
            },
            files={"media_file": ("video_prog.mp4", f, "video/mp4")},
        )
    assert resp.status_code == 201

    prog_resp = await client.get(f"/api/v1/broadcasts/progress/{tracking_id}")
    assert prog_resp.status_code == 200
    data = prog_resp.json()
    assert data["tracking_id"] == tracking_id
    assert data["stage"] in ["uploading_to_telegram", "processing_by_telegram"]
    assert data["status"] in ["in_progress", "completed"]


# ============================================================================
# TDD Red Tests: Extração Forçada e Normalização 4:5 de Dimensões MP4 (Vertical 1080x1920)
# ============================================================================

def test_normalize_video_dimensions_for_telegram_aspect_ratio():
    """
    Dimensões originais de vídeo (como vertical 1080x1920) não devem sofrer distorção artificial de aspecto,
    preservando os valores nativos para que o Telegram determine o layout natural do vídeo.
    """
    from src.presentation.main import normalize_video_dimensions

    assert normalize_video_dimensions(1080, 1920) == (1080, 1920)
    assert normalize_video_dimensions(720, 1280) == (720, 1280)
    assert normalize_video_dimensions(1920, 1080) == (1920, 1080)
    assert normalize_video_dimensions(1080, 1080) == (1080, 1080)
    assert normalize_video_dimensions(1080, 1350) == (1080, 1350)
    assert normalize_video_dimensions(None, None) == (None, None)


async def test_create_broadcast_vertical_video_fallback_dimensions(client, monkeypatch, tmp_path):
    """
    POST /api/v1/broadcasts com video vertical MP4 1080x1920 (tkhd 1080x1920) deve extrair as dimensões
    e preservar as dimensões reais e nativas (width=1080, height=1920) no MediaAttachment enviado ao telegram_gateway.send_broadcast,
    sem normalização artificial para 1350, permitindo que o Telegram determine o layout natural do vídeo.
    """
    from tests.helpers import build_synthetic_mp4

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="vert_bot")
    profile = Profile(id="profile-vert-1", name="Profile Vertical Video", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-vert-1",
        profile_id=profile.id,
        title="Canal Vertical",
        chat_id="-1007788990011",
    )
    await channel_repo.save(channel)

    dispatched_messages = []

    async def mock_send_broadcast(bot_token: str, chat_id: str, message, **kwargs):
        dispatched_messages.append(message)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    mp4_bytes = build_synthetic_mp4(width=1080, height=1920, duration=10)
    video_file = tmp_path / "vertical_video_1080x1920.mp4"
    video_file.write_bytes(mp4_bytes)

    with open(video_file, "rb") as f:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps([channel.chat_id]),
                "text": "Video Vertical Reels / Stories",
                # video_width e video_height omitidos propositalmente para forçar fallback de extração
            },
            files={"media_file": ("vertical_video_1080x1920.mp4", f, "video/mp4")},
        )
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    assert len(dispatched_messages) == 1
    dispatched_media = dispatched_messages[0].media
    assert dispatched_media is not None
    assert dispatched_media.width == 1080
    assert dispatched_media.height == 1920

    saved_broadcast = await broadcast_repo.get_by_id(broadcast_id)
    assert saved_broadcast is not None
    assert saved_broadcast.media is not None
    assert saved_broadcast.media.width == 1080
    assert saved_broadcast.media.height == 1920


async def test_create_broadcast_with_tracking_id_updates_progress_during_file_dispatch(client, monkeypatch, tmp_path):
    """
    Testa que ao criar broadcast com tracking_id e arquivo de mídia:
    1. upload_progress_tracker[tracking_id]["total_bytes"] é imediatamente preenchido com o tamanho real do arquivo.
    2. telegram_gateway.send_broadcast recebe progress_callback.
    3. O callback atualiza upload_progress_tracker em tempo real durante a transmissão.
    """
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="live_bot")
    profile = Profile(id="profile-live-prog-1", name="Profile Live Prog", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-live-prog-1",
        profile_id=profile.id,
        title="Canal Live Prog",
        chat_id="-1009988771122",
    )
    await channel_repo.save(channel)

    tracking_id = "track-live-upload-42"
    file_bytes = b"\x00\x00\x00\x18ftypmp42" + b"X" * 40000
    dummy_file = tmp_path / "live_video.mp4"
    dummy_file.write_bytes(file_bytes)
    file_size = len(file_bytes)

    captured = {}
    progress_history = []

    async def mock_send_broadcast(bot_token: str, chat_id: str, message, progress_callback=None):
        captured["called"] = True
        captured["progress_callback"] = progress_callback

        from src.presentation import main
        # total_bytes deve estar imediatamente preenchido com o tamanho do arquivo
        assert main.upload_progress_tracker[tracking_id]["total_bytes"] == file_size

        if progress_callback is not None:
            # Simula avanço de progresso a 50%
            progress_callback(file_size // 2, file_size)
            progress_history.append(dict(main.upload_progress_tracker[tracking_id]))

            # Simula conclusão de upload a 100%
            progress_callback(file_size, file_size)
            progress_history.append(dict(main.upload_progress_tracker[tracking_id]))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    with open(dummy_file, "rb") as f:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps([channel.chat_id]),
                "text": "Broadcast com progresso real em streaming",
                "tracking_id": tracking_id,
            },
            files={"media_file": ("live_video.mp4", f, "video/mp4")},
        )

    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data.get("errors") == []
    assert resp_data.get("dispatched_count") == 1
    assert captured.get("called") is True
    assert captured.get("progress_callback") is not None, "send_broadcast deve ser chamado com progress_callback quando tracking_id e media_file forem fornecidos"
    assert len(progress_history) == 2
    assert progress_history[0]["percent"] == 50
    assert progress_history[0]["sent_bytes"] == file_size // 2
    assert progress_history[0]["stage"] == "uploading_to_telegram"
    assert progress_history[1]["percent"] == 100
    assert progress_history[1]["sent_bytes"] == file_size
    assert progress_history[1]["stage"] == "processing_by_telegram"

    from src.presentation import main
    final_tracker = main.upload_progress_tracker[tracking_id]
    assert final_tracker["status"] == "completed"
    assert final_tracker["percent"] == 100
    assert final_tracker["sent_bytes"] == file_size
    assert final_tracker["total_bytes"] == file_size


async def test_create_broadcast_video_forces_mp4_metadata_extraction_even_if_form_has_dimensions_and_duration(
    client, monkeypatch, tmp_path
):
    """
    POST /api/v1/broadcasts com video MP4 deve SEMPRE executar extract_mp4_metadata,
    mesmo quando video_duration, video_width e video_height vierem informados no formulário,
    para certificar a orientação correta via matriz de rotação (ex: 1080x1920 portrait) e
    preservar as dimensões nativas (width=1080, height=1920) ao enviar para o Telegram.
    """
    from tests.helpers import build_synthetic_mp4

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="vert_bot_override")
    profile = Profile(id="profile-vert-override-1", name="Profile Vertical Video Override", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-vert-override-1",
        profile_id=profile.id,
        title="Canal Vertical Override",
        chat_id="-1007788990099",
    )
    await channel_repo.save(channel)

    dispatched_messages = []

    async def mock_send_broadcast(bot_token: str, chat_id: str, message, **kwargs):
        dispatched_messages.append(message)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    # Vídeo codificado como 1920x1080 horizontal mas com matriz de rotação de 90 graus (portrait 1080x1920)
    rot_90_matrix = [
        0, 0x00010000, 0,
        -0x00010000, 0, 0,
        0, 0, 0x40000000,
    ]
    mp4_bytes = build_synthetic_mp4(width=1920, height=1080, duration=10, matrix=rot_90_matrix)
    video_file = tmp_path / "rotated_90_portrait_override.mp4"
    video_file.write_bytes(mp4_bytes)

    with open(video_file, "rb") as f:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps([channel.chat_id]),
                "text": "Video com metadados enviados erroneamente pelo frontend",
                # Frontend passou dimensões brutas 1920x1080 e duration 10
                "video_duration": "10",
                "video_width": "1920",
                "video_height": "1080",
            },
            files={"media_file": ("rotated_90_portrait_override.mp4", f, "video/mp4")},
        )
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    assert len(dispatched_messages) == 1
    assert dispatched_messages[0].media is not None
    assert dispatched_messages[0].media.width == 1080
    assert dispatched_messages[0].media.height == 1920

    saved_broadcast = await broadcast_repo.get_by_id(broadcast_id)
    assert saved_broadcast is not None
    assert saved_broadcast.media is not None
    # A extração soberana de metadados corrige a rotação para 1080x1920 e preserva as dimensões nativas
    assert saved_broadcast.media.width == 1080
    assert saved_broadcast.media.height == 1920


async def test_upload_progress_tracker_transitions_to_processing_by_telegram_when_bytes_complete(
    client, monkeypatch, tmp_path
):
    """
    Quando sent_bytes >= total_bytes durante o envio do arquivo para o Telegram,
    o estágio no upload_progress_tracker deve transicionar para 'processing_by_telegram'
    para informar ao usuário que o envio dos bytes terminou e o Telegram está processando a mídia.
    """
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="proc_bot")
    profile = Profile(id="profile-proc-1", name="Profile Processing", credentials=creds)
    await profile_repo.save(profile)

    channel = Channel(
        id="channel-proc-1",
        profile_id=profile.id,
        title="Canal Proc",
        chat_id="-1009988776655",
    )
    await channel_repo.save(channel)

    tracking_id = "track-proc-stage-check"
    file_bytes = b"\x00\x00\x00\x18ftypmp42" + b"X" * 1024
    dummy_file = tmp_path / "proc_video.mp4"
    dummy_file.write_bytes(file_bytes)
    file_size = len(file_bytes)

    stage_at_100_percent = None

    async def mock_send_broadcast(bot_token: str, chat_id: str, message, progress_callback=None):
        nonlocal stage_at_100_percent
        from src.presentation import main
        if progress_callback is not None:
            progress_callback(file_size, file_size)
            stage_at_100_percent = main.upload_progress_tracker[tracking_id]["stage"]
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    with open(dummy_file, "rb") as f:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps([channel.chat_id]),
                "text": "Video test stage transition",
                "tracking_id": tracking_id,
            },
            files={"media_file": ("proc_video.mp4", f, "video/mp4")},
        )

    assert resp.status_code == 201
    assert stage_at_100_percent == "processing_by_telegram"


# =========================================================================
# Fase 3 (TDD Red): Guardrails Arquiteturais, Resiliência e Validação
# =========================================================================

async def test_create_broadcast_rejects_past_scheduled_date(client):
    """
    POST /api/v1/broadcasts deve rejeitar com HTTP 422 qualquer agendamento com data
    no passado, com a mesma mensagem do PATCH /api/v1/broadcasts/{id} (AGENTS.md §12).
    """
    from datetime import datetime, timedelta, timezone

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="past_test_bot")
    profile = Profile(id="profile-past-check", name="Profile Past Check", credentials=creds)
    await profile_repo.save(profile)

    past_date = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    payload = {
        "profile_id": "profile-past-check",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Broadcast com data no passado",
        "scheduled_at": past_date,
    }
    resp = await client.post("/api/v1/broadcasts", data=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "scheduled_at cannot be in the past"


async def test_create_broadcast_accepts_future_scheduled_date(client):
    """
    POST /api/v1/broadcasts deve aceitar normalmente agendamento com data no futuro.
    """
    from datetime import datetime, timedelta, timezone

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="future_test_bot")
    profile = Profile(id="profile-future-check", name="Profile Future Check", credentials=creds)
    await profile_repo.save(profile)

    future_date = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    payload = {
        "profile_id": "profile-future-check",
        "target_channel_ids": '["-1001234567890"]',
        "text": "Broadcast com data futura",
        "scheduled_at": future_date,
    }
    resp = await client.post("/api/v1/broadcasts", data=payload)
    assert resp.status_code == 201
    resp_data = resp.json()
    assert resp_data["status"] == "SCHEDULED"
    assert resp_data["scheduled_at"] is not None


async def test_sqlite_engine_has_wal_and_busy_timeout_pragmas():
    """
    O SQLite deve ser configurado com PRAGMA journal_mode=WAL e PRAGMA busy_timeout >= 5000
    para prevenir contenção de concorrência ('database is locked') em operações assíncronas.
    """
    from sqlalchemy import text
    from src.presentation.main import engine

    async with engine.connect() as conn:
        journal_mode_row = await conn.execute(text("PRAGMA journal_mode;"))
        journal_mode = journal_mode_row.scalar()
        busy_timeout_row = await conn.execute(text("PRAGMA busy_timeout;"))
        busy_timeout = busy_timeout_row.scalar()

    assert str(journal_mode).lower() in ("wal", "memory"), f"Expected WAL or memory journal mode, got {journal_mode}"
    assert busy_timeout is not None and int(busy_timeout) >= 5000, f"Expected busy_timeout >= 5000, got {busy_timeout}"


def test_cors_configuration_does_not_mix_wildcard_with_credentials():
    """
    Guardrail de Segurança: quando allow_credentials for True, allow_origins
    NÃO deve conter ['*'] para prevenir vulnerabilidades de CORS com credenciais.
    """
    from src.presentation.main import app

    cors_middlewares = [
        m for m in app.user_middleware
        if hasattr(m, "cls") and "cors" in m.cls.__name__.lower()
    ]
    assert len(cors_middlewares) > 0, "CORSMiddleware must be registered in app"

    for middleware in cors_middlewares:
        allow_credentials = middleware.kwargs.get("allow_credentials", False)
        allow_origins = middleware.kwargs.get("allow_origins", [])

        if allow_credentials:
            assert "*" not in allow_origins, (
                "CORS Security Violation: allow_origins=['*'] must not be used with allow_credentials=True"
            )


async def test_health_check_endpoint(client):
    """Verifica se o endpoint de health check /api/v1/health retorna status 200 e json saudável com app e version (#29)."""
    from src.presentation.main import app

    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "app": "auto-send", "version": app.version}


async def test_static_files_serving_and_api_route_precedence(tmp_path):
    """
    Valida que ao servir o frontend estático via FastApi:
    - GET / retorna o index.html com 200 OK.
    - Rotas de API como GET /api/v1/health e GET /api/v1/profiles mantêm precedência absoluta.
    """
    from fastapi.staticfiles import StaticFiles
    from src.presentation.main import app

    test_html_content = "<!DOCTYPE html><html><body><h1>Auto-Send Standalone Frontend</h1></body></html>"
    index_file = tmp_path / "index.html"
    index_file.write_text(test_html_content, encoding="utf-8")

    # Monta StaticFiles simulando o comportamento de standalone bundle
    app.mount("/", StaticFiles(directory=str(tmp_path), html=True), name="test_static_mount")

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. GET / deve servir o index.html
            root_resp = await ac.get("/")
            assert root_resp.status_code == 200
            assert "Auto-Send Standalone Frontend" in root_resp.text
            assert "text/html" in root_resp.headers.get("content-type", "")

            # 2. GET /api/v1/health deve manter precedência e retornar JSON
            health_resp = await ac.get("/api/v1/health")
            assert health_resp.status_code == 200
            assert health_resp.json() == {"status": "healthy", "app": "auto-send", "version": app.version}

            # 3. GET /api/v1/profiles deve manter precedência
            profiles_resp = await ac.get("/api/v1/profiles")
            assert profiles_resp.status_code == 200
            assert isinstance(profiles_resp.json(), list)
    finally:
        # Cleanup do mount para isolamento dos testes (Zero Clutter Policy)
        app.routes[:] = [r for r in app.routes if getattr(r, "name", None) != "test_static_mount"]







async def test_post_and_patch_share_the_same_clock_tolerance(client):
    from datetime import datetime, timedelta, timezone

    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    await profile_repo.save(Profile(id="profile-tolerance", name="Bruna", credentials=creds))

    def iso(delta: timedelta) -> str:
        return (datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")

    resp = await client.post(
        "/api/v1/broadcasts",
        data={"profile_id": "profile-tolerance", "target_channel_ids": '["-1001234567890"]', "text": "x", "scheduled_at": iso(timedelta(hours=2))},
    )
    assert resp.status_code == 201
    broadcast_id = resp.json()["broadcast_id"]

    # 30s atrás está dentro da tolerância: aceito nos dois verbos
    patch_ok = await client.patch(f"/api/v1/broadcasts/{broadcast_id}", json={"scheduled_at": iso(timedelta(seconds=-30))})
    assert patch_ok.status_code == 200

    # 5 min atrás está fora: 422 com a mesma mensagem nos dois verbos
    patch_old = await client.patch(f"/api/v1/broadcasts/{broadcast_id}", json={"scheduled_at": iso(timedelta(minutes=-5))})
    post_old = await client.post(
        "/api/v1/broadcasts",
        data={"profile_id": "profile-tolerance", "target_channel_ids": '["-1001234567890"]', "text": "x", "scheduled_at": iso(timedelta(minutes=-5))},
    )
    assert patch_old.status_code == post_old.status_code == 422
    assert patch_old.json()["detail"] == post_old.json()["detail"] == "scheduled_at cannot be in the past"


async def test_partial_dispatch_responds_and_persists_the_same_status(client, monkeypatch):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    await profile_repo.save(Profile(id="profile-partial", name="Bruna", credentials=creds))

    async def send_only_to_first_channel(bot_token: str, chat_id: str, message):
        return chat_id == "-1001111111111"

    monkeypatch.setattr(telegram_gateway, "send_broadcast", send_only_to_first_channel)

    resp = await client.post(
        "/api/v1/broadcasts",
        data={
            "profile_id": "profile-partial",
            "target_channel_ids": '["-1001111111111", "-1002222222222"]',
            "text": "Metade chega",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "PARTIALLY_COMPLETED"
    assert body["dispatched_count"] == 1
    persisted = await broadcast_repo.get_by_id(body["broadcast_id"])
    assert persisted.status.value == "PARTIALLY_COMPLETED"


# Issue #39: a mídia é conferida pela assinatura do arquivo e pelo tamanho, e nada sobra em temp_media/.
MP4_HEADER = b"\x00\x00\x00\x18ftypmp42"
JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"


async def _profile_for_upload(monkeypatch, profile_id: str) -> list:
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    await profile_repo.save(Profile(id=profile_id, name="Acme Upload", credentials=creds))
    sent: list = []

    async def fake_send(bot_token: str, chat_id: str, message, **kwargs):
        sent.append(message)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", fake_send)
    return sent


def _temp_media_files() -> set:
    from src.presentation.main import TEMP_MEDIA_DIR
    import os
    return set(os.listdir(TEMP_MEDIA_DIR))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, filename, content",
    [
        ("media_file", "promo.jpg", b"<html>not an image</html>"),
        ("media_file", "promo.mp4", JPEG_HEADER + b"photo pretending to be a video"),
        ("thumbnail_file", "thumb.jpg", b"<html>not an image</html>"),
    ],
)
async def test_upload_whose_content_does_not_match_the_extension_is_rejected(client, monkeypatch, field, filename, content):
    sent = await _profile_for_upload(monkeypatch, "profile-upload-mismatch")
    files = {field: (filename, content, "application/octet-stream")}
    if field == "thumbnail_file":
        files["media_file"] = ("promo.mp4", MP4_HEADER + b"video", "video/mp4")
    before = _temp_media_files()

    resp = await client.post(
        "/api/v1/broadcasts",
        data={"profile_id": "profile-upload-mismatch", "target_channel_ids": '["-1001234567890"]', "text": "x"},
        files=files,
    )

    assert resp.status_code == 422
    assert resp.json() == {"detail": "Unsupported media format"}
    assert sent == []
    assert _temp_media_files() == before


@pytest.mark.asyncio
async def test_upload_above_the_size_limit_is_rejected_with_413(client, monkeypatch):
    sent = await _profile_for_upload(monkeypatch, "profile-upload-too-large")
    monkeypatch.setenv("MAX_MEDIA_UPLOAD_MB", "1")
    before = _temp_media_files()

    resp = await client.post(
        "/api/v1/broadcasts",
        data={"profile_id": "profile-upload-too-large", "target_channel_ids": '["-1001234567890"]', "text": "x"},
        files={"media_file": ("big.mp4", MP4_HEADER + b"\x00" * (1024 * 1024), "video/mp4")},
    )

    assert resp.status_code == 413
    assert resp.json() == {"detail": "Media file too large (limit: 1 MB)"}
    assert sent == []
    assert _temp_media_files() == before


@pytest.mark.parametrize(
    "env, expected_mb",
    [
        ({"MAX_MEDIA_UPLOAD_MB": "300"}, 300),
        ({"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "fake-api-hash"}, 2000),
        ({}, 50),
        ({"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": " "}, 50),
    ],
)
def test_media_upload_limit_follows_the_telegram_api_in_use(monkeypatch, env, expected_mb):
    from src.presentation.main import media_upload_limit_bytes

    for name in ("MAX_MEDIA_UPLOAD_MB", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    assert media_upload_limit_bytes() == expected_mb * 1024 * 1024


@pytest.mark.parametrize("value", ["0", "-5", "abc"])
def test_invalid_media_upload_limit_env_falls_back_to_the_default(monkeypatch, value):
    from src.presentation.main import media_upload_limit_bytes

    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.setenv("MAX_MEDIA_UPLOAD_MB", value)

    assert media_upload_limit_bytes() == 50 * 1024 * 1024


# Issue #1: Agendamentos MISFIRED (Enviar agora, Reagendar via PATCH, Descartar via cancel)
@pytest.mark.asyncio
async def test_misfired_broadcast_appears_first_in_queue_and_supports_dispatch_now_reschedule_and_discard(
    client, monkeypatch, tmp_path
):
    from datetime import datetime, timedelta, timezone
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        MediaAttachment,
        MediaType,
    )

    sent = await _profile_for_upload(monkeypatch, "profile-misfire-actions")
    now = datetime.now(timezone.utc)

    media_1 = tmp_path / "misfired_dispatch.mp4"
    media_1.write_bytes(b"video-1")
    thumb_1 = tmp_path / "misfired_dispatch_thumb.jpg"
    thumb_1.write_bytes(b"thumb-1")

    media_2 = tmp_path / "misfired_discard.mp4"
    media_2.write_bytes(b"video-2")
    thumb_2 = tmp_path / "misfired_discard_thumb.jpg"
    thumb_2.write_bytes(b"thumb-2")

    b_scheduled = BroadcastMessage(
        id="b-sched-future",
        profile_id="profile-misfire-actions",
        target_channel_ids=["-1001234567890"],
        text="Futuro normal",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=now + timedelta(hours=1),
    )
    b_misfired_send = BroadcastMessage(
        id="b-misfired-send",
        profile_id="profile-misfire-actions",
        target_channel_ids=["-1001234567890"],
        text="Expirado enviar agora",
        media=MediaAttachment(
            file_path=str(media_1),
            media_type=MediaType.VIDEO,
            file_size=7,
            thumbnail_path=str(thumb_1),
        ),
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now - timedelta(hours=2),
    )
    b_misfired_resched = BroadcastMessage(
        id="b-misfired-resched",
        profile_id="profile-misfire-actions",
        target_channel_ids=["-1001234567890"],
        text="Expirado reagendar",
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now - timedelta(hours=1),
    )
    b_misfired_discard = BroadcastMessage(
        id="b-misfired-discard",
        profile_id="profile-misfire-actions",
        target_channel_ids=["-1001234567890"],
        text="Expirado descartar",
        media=MediaAttachment(
            file_path=str(media_2),
            media_type=MediaType.VIDEO,
            file_size=7,
            thumbnail_path=str(thumb_2),
        ),
        status=BroadcastStatus.MISFIRED,
        scheduled_at=now - timedelta(minutes=45),
    )

    for b in (b_scheduled, b_misfired_send, b_misfired_resched, b_misfired_discard):
        await broadcast_repo.save(b)

    # 1. Na listagem da fila, os MISFIRED vêm antes dos SCHEDULED
    queue_resp = await client.get("/api/v1/profiles/profile-misfire-actions/scheduled-broadcasts")
    assert queue_resp.status_code == 200
    ids = [item["id"] for item in queue_resp.json()]
    assert ids == ["b-misfired-send", "b-misfired-resched", "b-misfired-discard", "b-sched-future"]

    # 2. Enviar agora (dispatch-now): envia para o canal, muda para COMPLETED e apaga mídia + capa
    dispatch_resp = await client.post("/api/v1/broadcasts/b-misfired-send/dispatch-now")
    assert dispatch_resp.status_code == 200
    assert dispatch_resp.json()["status"] == "COMPLETED"
    assert dispatch_resp.json()["dispatched_count"] == 1
    assert len(sent) == 1
    assert not media_1.exists()
    assert not thumb_1.exists()

    # Tentar dispatch-now de novo em um broadcast já COMPLETED deve retornar 422
    dup_resp = await client.post("/api/v1/broadcasts/b-misfired-send/dispatch-now")
    assert dup_resp.status_code == 422

    # 3. Reagendar via PATCH: aceita MISFIRED e volta para SCHEDULED
    new_future = (now + timedelta(hours=3)).isoformat()
    patch_resp = await client.patch(
        "/api/v1/broadcasts/b-misfired-resched",
        json={"text": "Expirado reagendado", "scheduled_at": new_future},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "SCHEDULED"
    assert patch_resp.json()["text"] == "Expirado reagendado"

    # 4. Descartar via DELETE /cancel: muda para CANCELLED e apaga mídia + capa
    cancel_resp = await client.delete("/api/v1/broadcasts/b-misfired-discard/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"
    assert not media_2.exists()
    assert not thumb_2.exists()


# Issue #28: Exclusões e edições de canal/perfil não deixam agendamentos órfãos
@pytest.mark.asyncio
async def test_channel_delete_and_edit_update_pending_broadcasts_and_block_on_dispatching(
    client, monkeypatch, tmp_path
):
    from datetime import datetime, timedelta, timezone
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        MediaAttachment,
        MediaType,
    )
    from src.presentation.main import scheduler_service

    await _profile_for_upload(monkeypatch, "p-orphan-28")
    now = datetime.now(timezone.utc)

    chan_a = Channel(id="chan-a", profile_id="p-orphan-28", title="Canal A", chat_id="-1001111111111")
    chan_b = Channel(id="chan-b", profile_id="p-orphan-28", title="Canal B", chat_id="-1002222222222")
    await channel_repo.save(chan_a)
    await channel_repo.save(chan_b)

    media_only_a = tmp_path / "only_a.mp4"
    media_only_a.write_bytes(b"video-a")

    # b1: só Canal A -> será cancelado ao excluir Canal A
    b_only_a = BroadcastMessage(
        id="b-only-a",
        profile_id="p-orphan-28",
        target_channel_ids=["-1001111111111"],
        text="Só para o Canal A",
        media=MediaAttachment(file_path=str(media_only_a), media_type=MediaType.VIDEO, file_size=7),
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=now + timedelta(hours=1),
    )
    # b2: Canal A e Canal B -> perde o Canal A e continua só com o Canal B
    b_a_and_b = BroadcastMessage(
        id="b-a-and-b",
        profile_id="p-orphan-28",
        target_channel_ids=["-1001111111111", "-1002222222222"],
        text="Para A e B",
        status=BroadcastStatus.SCHEDULED,
        scheduled_at=now + timedelta(hours=2),
    )
    # b3: histórico COMPLETED -> não muda
    b_history = BroadcastMessage(
        id="b-history",
        profile_id="p-orphan-28",
        target_channel_ids=["-1001111111111"],
        text="Já enviado",
        status=BroadcastStatus.COMPLETED,
    )
    for b in (b_only_a, b_a_and_b, b_history):
        await broadcast_repo.save(b)

    scheduler_service.start()
    try:
        scheduler_service.schedule_broadcast("b-only-a", b_only_a.scheduled_at)
        assert scheduler_service.scheduler.get_job("broadcast_b-only-a") is not None

        # 1. Consulta agendamentos afetados para o modal de exclusão do Canal A
        aff_resp = await client.get("/api/v1/channels/chan-a/affected-broadcasts")
        assert aff_resp.status_code == 200
        aff_data = aff_resp.json()
        assert [i["id"] for i in aff_data["will_be_cancelled"]] == ["b-only-a"]
        assert [i["id"] for i in aff_data["will_lose_target"]] == ["b-a-and-b"]

        # 2. Se houver envio DISPATCHING para o Canal A, excluir ou trocar ID é bloqueado com 422
        b_disp = BroadcastMessage(
            id="b-disp-a",
            profile_id="p-orphan-28",
            target_channel_ids=["-1001111111111"],
            text="Enviando agora",
            status=BroadcastStatus.DISPATCHING,
        )
        await broadcast_repo.save(b_disp)

        del_blocked = await client.delete("/api/v1/channels/chan-a")
        assert del_blocked.status_code == 422
        assert del_blocked.json() == {
            "detail": "There is a broadcast currently dispatching. Wait for it to finish and try again."
        }
        put_blocked = await client.put(
            "/api/v1/channels/chan-a",
            json={"name": "Canal A", "telegram_channel_id": "-1003333333333"},
        )
        assert put_blocked.status_code == 422
        prof_blocked = await client.delete("/api/v1/profiles/p-orphan-28")
        assert prof_blocked.status_code == 422

        # Finaliza o envio em andamento
        b_disp.finish_dispatch(delivered=1, total=1)
        await broadcast_repo.save(b_disp)

        # 3. Confirma exclusão do Canal A: b-only-a é cancelado (job removido, mídia apagada) e b-a-and-b fica só com B
        del_ok = await client.delete("/api/v1/channels/chan-a")
        assert del_ok.status_code == 200
        assert (await broadcast_repo.get_by_id("b-only-a")).status is BroadcastStatus.CANCELLED
        assert scheduler_service.scheduler.get_job("broadcast_b-only-a") is None
        assert not media_only_a.exists()

        updated_ab = await broadcast_repo.get_by_id("b-a-and-b")
        assert updated_ab.status is BroadcastStatus.SCHEDULED
        assert updated_ab.target_channel_ids == ["-1002222222222"]

        # Histórico continua intacto
        assert (await broadcast_repo.get_by_id("b-history")).target_channel_ids == ["-1001111111111"]

        # 4. Trocar o ID do Canal B atualiza os agendamentos pendentes para o ID novo
        put_b = await client.put(
            "/api/v1/channels/chan-b",
            json={"name": "Canal B Novo", "telegram_channel_id": "-1005555555555"},
        )
        assert put_b.status_code == 200
        assert (await broadcast_repo.get_by_id("b-a-and-b")).target_channel_ids == ["-1005555555555"]

        # 5. Excluir o perfil cancela os agendamentos pendentes restantes e remove jobs/mídia
        scheduler_service.schedule_broadcast("b-a-and-b", b_a_and_b.scheduled_at)
        prof_aff = await client.get("/api/v1/profiles/p-orphan-28/affected-broadcasts")
        assert prof_aff.status_code == 200
        assert [i["id"] for i in prof_aff.json()["will_be_cancelled"]] == ["b-a-and-b"]

        del_prof = await client.delete("/api/v1/profiles/p-orphan-28")
        assert del_prof.status_code == 200
        assert scheduler_service.scheduler.get_job("broadcast_b-a-and-b") is None
    finally:
        scheduler_service.shutdown(wait=False)


@pytest.mark.asyncio
async def test_broadcast_delivery_results_per_channel_in_immediate_response_and_history(monkeypatch):
    """
    Issue #31:
    - Envio para Canal A e Canal B com o bot sem permissão em B -> PARTIALLY_COMPLETED,
      A entregue e B com NO_POST_PERMISSION.
    - Envio antigo sem delivery_results aparece no histórico com delivery_results=[].
    """
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        DeliveryFailureCategory,
    )
    from src.presentation.main import broadcast_repo, profile_repo, telegram_gateway
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials

    await profile_repo.save(
        Profile(
            id="p-31",
            name="Acme 31",
            credentials=BotCredentials(
                token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
                bot_username="acme31_bot",
            ),
        )
    )

    # Envio antigo sem delivery_results salvo direto no repositório
    old_broadcast = BroadcastMessage(
        id="b-old-31",
        profile_id="p-31",
        target_channel_ids=["-1001111111111"],
        text="Envio antigo sem delivery_results",
        status=BroadcastStatus.COMPLETED,
    )
    await broadcast_repo.save(old_broadcast)

    async def fake_send_broadcast(*, bot_token: str, chat_id: str, message, **kwargs) -> bool:
        if chat_id == "-1001111111111":
            telegram_gateway.last_error = None
            telegram_gateway.last_failure_category = None
            telegram_gateway.last_failure_detail = None
            return True
        telegram_gateway.last_error = (
            "Telegram API error (400): Bad Request: not enough rights to send text messages to the chat"
        )
        telegram_gateway.last_failure_category = DeliveryFailureCategory.NO_POST_PERMISSION
        telegram_gateway.last_failure_detail = (
            "Bad Request: not enough rights to send text messages to the chat"
        )
        return False

    monkeypatch.setattr(telegram_gateway, "send_broadcast", fake_send_broadcast)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": "p-31",
                "target_channel_ids": json.dumps(["-1001111111111", "-1002222222222"]),
                "text": "Disparo para A e B",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "PARTIALLY_COMPLETED"
        assert body["dispatched_count"] == 1
        assert body["delivery_results"] == [
            {
                "chat_id": "-1001111111111",
                "delivered": True,
                "failure_category": None,
                "detail": None,
            },
            {
                "chat_id": "-1002222222222",
                "delivered": False,
                "failure_category": "NO_POST_PERMISSION",
                "detail": "Bad Request: not enough rights to send text messages to the chat",
            },
        ]

        hist_resp = await client.get("/api/v1/profiles/p-31/broadcasts")
        assert hist_resp.status_code == 200
        hist = hist_resp.json()
        by_id = {item["id"]: item for item in hist}
        assert by_id[body["broadcast_id"]]["delivery_results"] == body["delivery_results"]
        assert by_id["b-old-31"]["delivery_results"] == []


@pytest.mark.asyncio
async def test_broadcast_escapes_plain_symbols_and_rejects_unsupported_html_or_http_links_with_422(monkeypatch):
    """
    Issue #16:
    - Texto com <, > ou & é escapado antes de chegar ao Telegram.
    - Texto com tag não suportada (<script>) ou link http:// enviado direto à API (POST ou PATCH) retorna 422.
    """
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import profile_repo, telegram_gateway
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials

    await profile_repo.save(
        Profile(
            id="p-16",
            name="Acme 16",
            credentials=BotCredentials(
                token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
                bot_username="acme16_bot",
            ),
        )
    )

    dispatched_texts: list[str] = []

    async def fake_send_broadcast(*, bot_token: str, chat_id: str, message, **kwargs) -> bool:
        dispatched_texts.append(message.text)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", fake_send_broadcast)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        # 1. Símbolos <, > e & escapados no envio imediato
        ok_resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": "p-16",
                "target_channel_ids": json.dumps(["-1001111111111"]),
                "text": '2 < 3 & Tom & Jerry > 1 com <a href="https://example.com/p?x=1&y=2">link</a>',
            },
        )
        assert ok_resp.status_code == 201
        assert dispatched_texts == [
            '2 &lt; 3 &amp; Tom &amp; Jerry &gt; 1 com <a href="https://example.com/p?x=1&amp;y=2">link</a>'
        ]

        # 2. Tag não suportada e link http:// recusados com 422 no POST
        for invalid_text in (
            "<script>alert(1)</script>",
            '<a href="http://example.com">link</a>',
            "<b>sem fechar",
        ):
            bad_post = await client.post(
                "/api/v1/broadcasts",
                data={
                    "profile_id": "p-16",
                    "target_channel_ids": json.dumps(["-1001111111111"]),
                    "text": invalid_text,
                },
            )
            assert bad_post.status_code == 422

        # 3. Também no PATCH de agendamento
        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        sched_resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": "p-16",
                "target_channel_ids": json.dumps(["-1001111111111"]),
                "text": "<b>Original</b>",
                "scheduled_at": future_iso,
            },
        )
        assert sched_resp.status_code == 201
        broadcast_id = sched_resp.json()["broadcast_id"]

        bad_patch = await client.patch(
            f"/api/v1/broadcasts/{broadcast_id}",
            json={"text": '<a href="http://example.com">inseguro</a>'},
        )
        assert bad_patch.status_code == 422


@pytest.mark.asyncio
async def test_broadcast_edit_lock_workflow_routes_and_scheduler_suppression(monkeypatch, tmp_path):
    """
    Issue #15:
    - POST /api/v1/broadcasts/{id}/edit-lock trava o agendamento;
    - O job do scheduler no horário NÃO posta enquanto a trava estiver ativa;
    - Com a trava expirada depois do horário, vira CANCELLED, remove job e apaga mídia;
    - PATCH atualiza target_channel_ids e texto sem duplicar, liberando a trava;
    - DELETE /api/v1/broadcasts/{id}/edit-lock antes do horário libera a trava sem cancelar;
    - DELETE /api/v1/broadcasts/{id}/edit-lock depois do horário cancela o agendamento.
    """
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import broadcast_repo, profile_repo, scheduler_service, telegram_gateway
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials

    await profile_repo.save(
        Profile(
            id="p-15",
            name="Acme 15",
            credentials=BotCredentials(
                token="123456789:ABCdefGhIJKlmNoPQRstuVWXyz",
                bot_username="acme15_bot",
            ),
        )
    )

    dispatched: list[str] = []

    async def fake_send_broadcast(*, bot_token: str, chat_id: str, message, **kwargs) -> bool:
        dispatched.append(chat_id)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", fake_send_broadcast)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        # 1. Cria agendamento futuro dentro da janela da trava (90s)
        sched_time = datetime.now(timezone.utc) + timedelta(seconds=30)
        resp = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": "p-15",
                "target_channel_ids": json.dumps(["-1001111111111"]),
                "text": "Agendamento original",
                "scheduled_at": sched_time.isoformat(),
            },
        )
        assert resp.status_code == 201
        b_id = resp.json()["broadcast_id"]

        # 2. Adquire a trava de edição (POST /edit-lock com TTL de 90s)
        lock_resp = await client.post(f"/api/v1/broadcasts/{b_id}/edit-lock")
        assert lock_resp.status_code == 200
        lock_data = lock_resp.json()
        assert lock_data["id"] == b_id
        assert lock_data["edit_locked_until"] is not None
        assert lock_data["cancelled"] is False

        # 3. No horário (30s depois, ainda dentro dos 90s da trava), o scheduler NÃO posta
        clock_at_schedule = sched_time + timedelta(seconds=1)
        monkeypatch.setattr(scheduler_service, "_clock", lambda: clock_at_schedule)
        await scheduler_service.execute_scheduled_broadcast(b_id)
        assert dispatched == []
        b_locked = await broadcast_repo.get_by_id(b_id)
        assert b_locked.status.value == "SCHEDULED"

        # 4. PATCH atualiza texto e target_channel_ids (salva o mesmo item sem duplicar)
        new_future = datetime.now(timezone.utc) + timedelta(hours=1)
        patch_resp = await client.patch(
            f"/api/v1/broadcasts/{b_id}",
            json={
                "text": "Texto atualizado via PATCH",
                "scheduled_at": new_future.isoformat(),
                "target_channel_ids": ["-1002222222222", "-1003333333333"],
            },
        )
        assert patch_resp.status_code == 200
        b_patched = await broadcast_repo.get_by_id(b_id)
        assert b_patched.text == "Texto atualizado via PATCH"
        assert b_patched.target_channel_ids == ["-1002222222222", "-1003333333333"]
        assert b_patched.edit_locked_until is None

        # 5. Sai sem salvar antes do horário: continua igual
        lock_resp2 = await client.post(f"/api/v1/broadcasts/{b_id}/edit-lock")
        assert lock_resp2.status_code == 200
        rel_resp = await client.delete(f"/api/v1/broadcasts/{b_id}/edit-lock")
        assert rel_resp.status_code == 200
        assert rel_resp.json()["cancelled"] is False
        b_rel = await broadcast_repo.get_by_id(b_id)
        assert b_rel.status.value == "SCHEDULED"
        assert b_rel.edit_locked_until is None

        # 6. Trava ativa cujo horário já passou: liberar ou expirar cancela
        past_sched = datetime.now(timezone.utc) + timedelta(minutes=5)
        resp_past = await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": "p-15",
                "target_channel_ids": json.dumps(["-1001111111111"]),
                "text": "Agendamento para expirar em edicao",
                "scheduled_at": past_sched.isoformat(),
            },
        )
        assert resp_past.status_code == 201
        b_past_id = resp_past.json()["broadcast_id"]

        await client.post(f"/api/v1/broadcasts/{b_past_id}/edit-lock")
        # Simula tempo após past_sched
        monkeypatch.setattr(scheduler_service, "_clock", lambda: past_sched + timedelta(minutes=2))
        rel_past = await client.delete(f"/api/v1/broadcasts/{b_past_id}/edit-lock")
        assert rel_past.status_code == 200
        assert rel_past.json()["cancelled"] is True
        b_cancelled = await broadcast_repo.get_by_id(b_past_id)
        assert b_cancelled.status.value == "CANCELLED"


@pytest.mark.asyncio
async def test_broadcast_media_get_preview_and_security(client, tmp_path):
    import os
    import uuid
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import app, profile_repo, broadcast_repo, TEMP_MEDIA_DIR
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        MediaAttachment,
        MediaType,
    )

    p = Profile(id="p-media-get", name="P Media", credentials=BotCredentials(token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", bot_username="p_media_bot"))
    await profile_repo.save(p)

    # Cria arquivo real em TEMP_MEDIA_DIR
    img_filename = f"{uuid.uuid4()}.jpg"
    img_path = os.path.join(TEMP_MEDIA_DIR, img_filename)
    with open(img_path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"A" * 64)

    sched_dt = datetime.now(timezone.utc) + timedelta(hours=2)
    b_with_media = BroadcastMessage(
        id="b-with-media",
        profile_id="p-media-get",
        target_channel_ids=["-1001234567890"],
        text="Com imagem",
        media=MediaAttachment(
            file_path=img_path,
            media_type=MediaType.PHOTO,
            file_size=68,
        ),
        scheduled_at=sched_dt,
        status=BroadcastStatus.SCHEDULED,
    )
    b_without_media = BroadcastMessage(
        id="b-without-media",
        profile_id="p-media-get",
        target_channel_ids=["-1001234567890"],
        text="Sem imagem",
        scheduled_at=sched_dt,
        status=BroadcastStatus.SCHEDULED,
    )
    await broadcast_repo.save(b_with_media)
    await broadcast_repo.save(b_without_media)

    try:
        # 1. Sucesso: busca mídia para preview
        resp = await client.get("/api/v1/broadcasts/b-with-media/media")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == "inline"
        assert resp.headers["content-type"].startswith("image/jpeg")
        assert len(resp.content) == 68

        # 2. 404 quando broadcast não existe
        resp404_b = await client.get("/api/v1/broadcasts/non-existent/media")
        assert resp404_b.status_code == 404
        assert resp404_b.json()["detail"] == "Broadcast not found"

        # 3. 404 quando broadcast não possui mídia
        resp404_m = await client.get("/api/v1/broadcasts/b-without-media/media")
        assert resp404_m.status_code == 404
        assert resp404_m.json()["detail"] == "Media not found"

        # 4. 404 quando o arquivo físico foi removido do disco
        os.remove(img_path)
        resp404_f = await client.get("/api/v1/broadcasts/b-with-media/media")
        assert resp404_f.status_code == 404
        assert resp404_f.json()["detail"] == "Media not found"

        # 5. Segurança Anti-Path-Traversal (§9): arquivo fora de TEMP_MEDIA_DIR
        outside_file = tmp_path / "outside.jpg"
        outside_file.write_bytes(b"\xff\xd8\xff\xe0" + b"outside")
        b_traversal = BroadcastMessage(
            id="b-traversal",
            profile_id="p-media-get",
            target_channel_ids=["-1001234567890"],
            text="Traversal",
            media=MediaAttachment(
                file_path=str(outside_file),
                media_type=MediaType.PHOTO,
                file_size=11,
            ),
            scheduled_at=sched_dt,
            status=BroadcastStatus.SCHEDULED,
        )
        await broadcast_repo.save(b_traversal)
        resp_trav = await client.get("/api/v1/broadcasts/b-traversal/media")
        assert resp_trav.status_code == 404
    finally:
        if os.path.exists(img_path):
            os.remove(img_path)


@pytest.mark.asyncio
async def test_broadcast_media_put_replace_and_delete_workflow(client, tmp_path):
    import io
    import os
    import uuid
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import app, profile_repo, broadcast_repo, TEMP_MEDIA_DIR
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        MediaAttachment,
        MediaType,
    )

    p = Profile(id="p-media-ops", name="P Media Ops", credentials=BotCredentials(token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", bot_username="p_media_ops_bot"))
    await profile_repo.save(p)

    sched_dt = datetime.now(timezone.utc) + timedelta(hours=2)
    b = BroadcastMessage(
        id="b-media-ops",
        profile_id="p-media-ops",
        target_channel_ids=["-1001234567890"],
        text="Mensagem para trocar midia",
        scheduled_at=sched_dt,
        status=BroadcastStatus.SCHEDULED,
    )
    await broadcast_repo.save(b)

    # 1. Adicionar imagem via PUT
    img_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"X" * 100
    put_resp1 = await client.put(
        "/api/v1/broadcasts/b-media-ops/media",
        files={"media_file": ("test.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert put_resp1.status_code == 200
    data1 = put_resp1.json()
    assert data1["media"] is not None
    assert data1["media"]["media_type"] == "PHOTO"
    assert "file_path" not in data1["media"]  # Não vaza caminho interno (§9, #18)

    b_db1 = await broadcast_repo.get_by_id("b-media-ops")
    assert b_db1.media is not None
    assert b_db1.media.media_type == MediaType.PHOTO
    first_file_path = b_db1.media.file_path
    assert os.path.exists(first_file_path)

    # 2. Trocar imagem por vídeo via PUT: verifica que arquivo antigo é deletado (Zero Clutter Policy §6)
    # Assinatura ftyp para vídeo mp4
    vid_header = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
    vid_bytes = vid_header + b"V" * 200
    put_resp2 = await client.put(
        "/api/v1/broadcasts/b-media-ops/media",
        files={"media_file": ("video.mp4", io.BytesIO(vid_bytes), "video/mp4")},
        data={"video_duration": 12, "video_width": 1280, "video_height": 720},
    )
    assert put_resp2.status_code == 200
    data2 = put_resp2.json()
    assert data2["media"]["media_type"] == "VIDEO"

    b_db2 = await broadcast_repo.get_by_id("b-media-ops")
    assert b_db2.media.media_type == MediaType.VIDEO
    second_file_path = b_db2.media.file_path
    assert os.path.exists(second_file_path)
    assert not os.path.exists(first_file_path)  # Arquivo antigo foi apagado!

    # 3. Remover mídia via DELETE
    del_resp = await client.delete("/api/v1/broadcasts/b-media-ops/media")
    assert del_resp.status_code == 200
    data_del = del_resp.json()
    assert data_del["media"] is None

    b_db3 = await broadcast_repo.get_by_id("b-media-ops")
    assert b_db3.media is None
    assert not os.path.exists(second_file_path)  # Arquivo de vídeo também foi apagado!

    # 4. Segundo DELETE retorna 404 (já removida)
    del_resp2 = await client.delete("/api/v1/broadcasts/b-media-ops/media")
    assert del_resp2.status_code == 404
    assert del_resp2.json()["detail"] == "Media not found"

    # 5. Não permite editar mídia de broadcast em estado terminal (ex: COMPLETED)
    b_db3.status = BroadcastStatus.COMPLETED
    await broadcast_repo.save(b_db3)
    put_term = await client.put(
        "/api/v1/broadcasts/b-media-ops/media",
        files={"media_file": ("test.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert put_term.status_code == 422
    del_term = await client.delete("/api/v1/broadcasts/b-media-ops/media")
    assert del_term.status_code == 422


@pytest.mark.asyncio
async def test_broadcast_media_replaced_dispatches_with_correct_gateway_endpoint(client, monkeypatch):
    import io
    import os
    from datetime import datetime, timedelta, timezone
    from src.presentation.main import app, profile_repo, broadcast_repo, scheduler_service, telegram_gateway
    from src.domain.profiles.profile import Profile
    from src.domain.profiles.bot_credentials import BotCredentials
    from src.domain.broadcast.broadcast_message import (
        BroadcastMessage,
        BroadcastStatus,
        MediaAttachment,
        MediaType,
    )

    p = Profile(
        id="p-dispatch-check",
        name="P Dispatch",
        credentials=BotCredentials(token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", bot_username="p_dispatch_bot"),
    )
    await profile_repo.save(p)

    now_utc = datetime.now(timezone.utc)
    sched_dt = now_utc - timedelta(seconds=10)
    b = BroadcastMessage(
        id="b-dispatch-check",
        profile_id="p-dispatch-check",
        target_channel_ids=["-1001234567890"],
        text="Legenda curta para video",
        scheduled_at=sched_dt,
        status=BroadcastStatus.SCHEDULED,
    )
    await broadcast_repo.save(b)

    # 1. Adiciona foto
    img_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"X" * 100
    put_img = await client.put(
        "/api/v1/broadcasts/b-dispatch-check/media",
        files={"media_file": ("foto.jpg", io.BytesIO(img_bytes), "image/jpeg")},
    )
    assert put_img.status_code == 200

    # 2. Troca foto por vídeo
    vid_header = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
    vid_bytes = vid_header + b"V" * 200
    put_vid = await client.put(
        "/api/v1/broadcasts/b-dispatch-check/media",
        files={"media_file": ("video.mp4", io.BytesIO(vid_bytes), "video/mp4")},
        data={"video_duration": 10, "video_width": 1920, "video_height": 1080},
    )
    assert put_vid.status_code == 200
    assert put_vid.json()["media"]["media_type"] == "VIDEO"

    # 3. Intercepta envio no telegram_gateway para validar que recebe o vídeo e não a foto
    sent_messages = []

    async def mock_send_broadcast(bot_token, chat_id, message, **kwargs):
        sent_messages.append((bot_token, chat_id, message))
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", mock_send_broadcast)

    # Executa o disparo agendado
    await scheduler_service.execute_scheduled_broadcast("b-dispatch-check")

    assert len(sent_messages) == 1
    _, chat_id, dispatched_msg = sent_messages[0]
    assert chat_id == "-1001234567890"
    assert dispatched_msg.media is not None
    assert dispatched_msg.media.media_type == MediaType.VIDEO
    assert dispatched_msg.get_dispatch_strategy().value == "SINGLE_MEDIA_WITH_CAPTION"

    # Confirma que após a execução, a mídia temporária foi limpa do disco
    assert not os.path.exists(dispatched_msg.media.file_path)


async def test_message_templates_crud_flow(client):
    """Testa criação, listagem, validações e exclusão de modelos de mensagens reutilizáveis (#63)."""
    # 1. 404 para perfil inexistente
    resp_404 = await client.post(
        "/api/v1/profiles/unknown-profile/templates",
        json={"name": "Aviso", "text": "Texto do modelo"},
    )
    assert resp_404.status_code == 404

    # 2. Cria perfil para associar modelos
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="tmpl_bot")
    profile = Profile(id="profile-tmpl-1", name="Acme Promos", credentials=creds)
    await profile_repo.save(profile)

    # 3. 422 para URL insegura (http)
    resp_insecure = await client.post(
        f"/api/v1/profiles/{profile.id}/templates",
        json={
            "name": "Link Inseguro",
            "text": "Clique aqui",
            "button_text": "Link",
            "button_url": "http://exemplo.com",
        },
    )
    assert resp_insecure.status_code == 422

    # 4. 201 sucesso criando modelo com botão inline
    resp_created = await client.post(
        f"/api/v1/profiles/{profile.id}/templates",
        json={
            "name": "Boas-vindas",
            "text": "Seja muito bem-vindo ao nosso canal oficial!",
            "button_text": "Acessar Site",
            "button_url": "https://exemplo.com/site",
        },
    )
    assert resp_created.status_code == 201
    created_data = resp_created.json()
    assert created_data["id"]
    assert created_data["profile_id"] == profile.id
    assert created_data["name"] == "Boas-vindas"
    assert created_data["text"] == "Seja muito bem-vindo ao nosso canal oficial!"
    assert created_data["button_text"] == "Acessar Site"
    assert created_data["button_url"] == "https://exemplo.com/site"
    tmpl_id = created_data["id"]

    # 5. 200 listagem de modelos do perfil
    resp_list = await client.get(f"/api/v1/profiles/{profile.id}/templates")
    assert resp_list.status_code == 200
    templates = resp_list.json()
    assert len(templates) == 1
    assert templates[0]["id"] == tmpl_id

    # 6. 200 exclusão do modelo
    resp_del = await client.delete(f"/api/v1/profiles/{profile.id}/templates/{tmpl_id}")
    assert resp_del.status_code == 200

    # 7. 404 ao tentar deletar novamente
    resp_del_again = await client.delete(f"/api/v1/profiles/{profile.id}/templates/{tmpl_id}")
    assert resp_del_again.status_code == 404

    # 8. Listagem agora vazia
    resp_list_after = await client.get(f"/api/v1/profiles/{profile.id}/templates")
    assert resp_list_after.status_code == 200
    assert resp_list_after.json() == []


async def test_abort_broadcast_upload_endpoint_returns_200_and_records_status(client):
    tracking_id = "test-track-abort-1"
    resp = await client.post(f"/api/v1/broadcasts/abort-upload/{tracking_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracking_id"] == tracking_id
    assert data["status"] == "aborted"


async def test_create_broadcast_aborts_immediately_when_cancelled_in_advance(client):
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-abort-early", name="Test Early", credentials=creds)
    await profile_repo.save(profile)

    tracking_id = "test-track-early-abort"
    # Cancela antes de iniciar
    await client.post(f"/api/v1/broadcasts/abort-upload/{tracking_id}")

    # Tenta criar o broadcast com o mesmo tracking_id
    resp = await client.post(
        "/api/v1/broadcasts",
        data={
            "profile_id": profile.id,
            "target_channel_ids": json.dumps(["-1001234567890"]),
            "text": "Mensagem que não deve ser enviada",
            "tracking_id": tracking_id,
        },
    )
    assert resp.status_code == 499
    assert resp.json()["detail"] == "Broadcast cancelled by user"


async def test_create_broadcast_aborts_in_flight_when_abort_endpoint_called(client, monkeypatch):
    import asyncio
    creds = BotCredentials(token="1234567890:ABCdefGhIJKlmNoPQRstuVWXyz12345", bot_username="test_bot")
    profile = Profile(id="profile-abort-inflight", name="Test Inflight", credentials=creds)
    await profile_repo.save(profile)

    started_event = asyncio.Event()

    async def _mock_slow_send(*args, **kwargs):
        started_event.set()
        await asyncio.sleep(5.0)
        return True

    monkeypatch.setattr(telegram_gateway, "send_broadcast", _mock_slow_send)

    tracking_id = "test-track-inflight-abort"

    async def _do_broadcast():
        return await client.post(
            "/api/v1/broadcasts",
            data={
                "profile_id": profile.id,
                "target_channel_ids": json.dumps(["-1001234567890"]),
                "text": "Mensagem cancelada em voo",
                "tracking_id": tracking_id,
            },
        )

    task = asyncio.create_task(_do_broadcast())
    await started_event.wait()

    # Dispara o cancelamento
    abort_resp = await client.post(f"/api/v1/broadcasts/abort-upload/{tracking_id}")
    assert abort_resp.status_code == 200

    broadcast_resp = await task
    assert broadcast_resp.status_code == 499
    assert broadcast_resp.json()["detail"] == "Broadcast cancelled by user"




