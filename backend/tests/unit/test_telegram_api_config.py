import os
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from src.infrastructure.portable_data import resolve_data_dir
from src.infrastructure.telegram_api_credentials import (
    get_env_file_path,
    load_telegram_credentials_from_data_dir,
    save_telegram_credentials_to_data_dir,
)
from src.presentation.main import app, media_upload_limit_bytes, LOCAL_API_MAX_BYTES, PUBLIC_API_MAX_BYTES


def test_save_and_load_telegram_credentials_in_data_dir(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "custom-data"
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(data_dir))
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)

    env_path = get_env_file_path()
    assert env_path == data_dir / ".env"
    assert not env_path.exists()

    # Salva credenciais
    save_telegram_credentials_to_data_dir("9876543", "test-fake-api-hash")
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_API_ID=9876543" in content
    assert "TELEGRAM_API_HASH=test-fake-api-hash" in content

    # Carrega credenciais para o os.environ
    loaded_id, loaded_hash = load_telegram_credentials_from_data_dir()
    assert loaded_id == "9876543"
    assert loaded_hash == "test-fake-api-hash"
    assert os.getenv("TELEGRAM_API_ID") == "9876543"
    assert os.getenv("TELEGRAM_API_HASH") == "test-fake-api-hash"


@pytest.mark.asyncio
async def test_get_telegram_api_config_endpoint_when_not_configured(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data-empty"
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(data_dir))
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("MAX_MEDIA_UPLOAD_MB", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.get("/api/v1/system/telegram-api-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["api_id"] == ""
    assert body["has_api_hash"] is False
    assert body["max_upload_mb"] == 50
    assert "env_file_path" in body


@pytest.mark.asyncio
async def test_post_telegram_api_config_endpoint_saves_and_updates_limit(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data-active"
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(data_dir))
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("MAX_MEDIA_UPLOAD_MB", raising=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post(
            "/api/v1/system/telegram-api-config",
            json={"api_id": "11223344", "api_hash": "test-fake-api-hash"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["api_id"] == "11223344"
    assert body["has_api_hash"] is True
    assert body["max_upload_mb"] == 2000

    # Verifica persistência no arquivo .env
    env_file = data_dir / ".env"
    assert env_file.exists()
    assert "TELEGRAM_API_ID=11223344" in env_file.read_text(encoding="utf-8")
    assert os.getenv("TELEGRAM_API_ID") == "11223344"
    assert os.getenv("TELEGRAM_API_HASH") == "test-fake-api-hash"


@pytest.mark.asyncio
async def test_post_telegram_api_config_endpoint_rejects_null_bytes_with_422():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post(
            "/api/v1/system/telegram-api-config",
            json={"api_id": "\x00invalid", "api_hash": "valid-hash"},
        )

    assert resp.status_code == 422
