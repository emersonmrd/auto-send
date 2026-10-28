from pathlib import Path
import sys

from httpx import ASGITransport, AsyncClient
import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.bundle_portable_windows import COMO_USAR_TXT, LAUNCHER_BAT  # noqa: E402
from src.infrastructure.portable_data import (  # noqa: E402
    import_legacy_data_if_needed,
    open_data_directory,
    resolve_data_dir,
)
from src.presentation.main import app  # noqa: E402


def test_launcher_bat_stores_data_in_localappdata_auto_send():
    assert r"%LOCALAPPDATA%\Auto-Send" in LAUNCHER_BAT
    assert r'set "DB_PATH=%AUTOSEND_DATA_DIR%\autosend.db"' in LAUNCHER_BAT
    assert r'set "TEMP_MEDIA_DIR=%AUTOSEND_DATA_DIR%\media_temp"' in LAUNCHER_BAT
    assert r'set "TELEGRAM_BOT_API_DIR=%AUTOSEND_DATA_DIR%\telegram_bot_api"' in LAUNCHER_BAT


def test_como_usar_explains_localappdata_and_how_to_copy_legacy_data():
    assert r"%LOCALAPPDATA%\Auto-Send" in COMO_USAR_TXT
    assert "v0.4.0" in COMO_USAR_TXT
    assert r"data\autosend.db" in COMO_USAR_TXT
    assert "modelos de mensagem" in COMO_USAR_TXT


def test_import_legacy_data_from_current_release_folder_without_interactive_prompt(tmp_path: Path):
    """Dado a v0.4.0 com data\\autosend.db na pasta e nada em %LOCALAPPDATA%, o banco é importado e o original fica intacto."""
    release_dir = tmp_path / "AutoSend-Portable"
    legacy_data = release_dir / "data"
    legacy_data.mkdir(parents=True)
    legacy_db = legacy_data / "autosend.db"
    legacy_db.write_bytes(b"sqlite-v040-bytes")

    target_data_dir = tmp_path / "localappdata" / "Auto-Send"

    def _eof_input(_prompt: str) -> str:
        raise EOFError

    imported = import_legacy_data_if_needed(
        target_data_dir,
        release_dir,
        user_home=tmp_path,
        input_fn=_eof_input,
        output_fn=lambda _msg: None,
    )

    assert imported == legacy_db.resolve()
    assert (target_data_dir / "autosend.db").read_bytes() == b"sqlite-v040-bytes"
    assert legacy_db.read_bytes() == b"sqlite-v040-bytes"


def test_import_legacy_data_from_downloads_v040_when_user_answers_s(tmp_path: Path):
    """Dado a v0.4.0 extraída em Downloads\\Auto-Send-v0.4.0 e a nova em outra pasta, quando responde S,
    os dados são importados para %LOCALAPPDATA%\\Auto-Send\\ e o original fica intacto."""
    home = tmp_path / "user"
    v040_data = home / "Downloads" / "Auto-Send-v0.4.0" / "data"
    (v040_data / "media_temp").mkdir(parents=True)
    legacy_db = v040_data / "autosend.db"
    legacy_db.write_bytes(b"v040-profile-db")
    legacy_media = v040_data / "media_temp" / "clip.mp4"
    legacy_media.write_bytes(b"mp4-bytes")

    new_release_dir = home / "Desktop" / "Auto-Send-v0.5.0"
    new_release_dir.mkdir(parents=True)
    target_data_dir = tmp_path / "localappdata" / "Auto-Send"

    prompts: list[str] = []
    messages: list[str] = []

    imported = import_legacy_data_if_needed(
        target_data_dir,
        new_release_dir,
        user_home=home,
        input_fn=lambda p: (prompts.append(p), "S")[1],
        output_fn=messages.append,
    )

    assert imported == legacy_db.resolve()
    assert prompts and "v0.4.0" in prompts[0] and "Importar? (S/N)" in prompts[0]
    assert (target_data_dir / "autosend.db").read_bytes() == b"v040-profile-db"
    assert (target_data_dir / "media_temp" / "clip.mp4").read_bytes() == b"mp4-bytes"
    assert legacy_db.read_bytes() == b"v040-profile-db"
    assert legacy_media.read_bytes() == b"mp4-bytes"


def test_import_legacy_data_skipped_when_user_answers_n(tmp_path: Path):
    home = tmp_path / "user"
    v040_data = home / "Downloads" / "Auto-Send-v0.4.0" / "data"
    v040_data.mkdir(parents=True)
    (v040_data / "autosend.db").write_bytes(b"v040-profile-db")

    new_release_dir = home / "Desktop" / "Auto-Send-v0.5.0"
    new_release_dir.mkdir(parents=True)
    target_data_dir = tmp_path / "localappdata" / "Auto-Send"
    messages: list[str] = []

    imported = import_legacy_data_if_needed(
        target_data_dir,
        new_release_dir,
        user_home=home,
        input_fn=lambda _p: "N",
        output_fn=messages.append,
    )

    assert imported is None
    assert not (target_data_dir / "autosend.db").exists()
    assert any("copie" in m.lower() for m in messages)


@pytest.mark.asyncio
async def test_open_data_dir_endpoint_returns_resolved_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(tmp_path / "custom-data"))
    resolved = resolve_data_dir()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post("/api/v1/system/open-data-dir")

    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == str(resolved)
    assert isinstance(body["opened"], bool)


def test_subsequent_release_preserves_existing_data_in_localappdata(tmp_path: Path):
    """Quando o usuário extrai uma nova release em outra pasta mas já possui dados em %LOCALAPPDATA%\\Auto-Send,
    a inicialização não pergunta nada e preserva os dados existentes sem alteração."""
    target_data_dir = tmp_path / "localappdata" / "Auto-Send"
    target_data_dir.mkdir(parents=True)
    existing_db = target_data_dir / "autosend.db"
    existing_db.write_bytes(b"existing-production-data")

    # Nova release extraída em outra pasta
    new_release_dir = tmp_path / "Downloads" / "Auto-Send-v0.5.1"
    new_release_dir.mkdir(parents=True)
    (new_release_dir / "data").mkdir()
    (new_release_dir / "data" / "autosend.db").write_bytes(b"stale-v040-db")

    input_called = False

    def _unexpected_input(_prompt: str) -> str:
        nonlocal input_called
        input_called = True
        return "S"

    imported = import_legacy_data_if_needed(
        target_data_dir,
        new_release_dir,
        user_home=tmp_path,
        input_fn=_unexpected_input,
    )

    assert imported is None
    assert not input_called
    assert existing_db.read_bytes() == b"existing-production-data"


def test_resolve_data_dir_creates_missing_directory(tmp_path: Path, monkeypatch):
    custom_dir = tmp_path / "non_existent_yet" / "Auto-Send"
    assert not custom_dir.exists()
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(custom_dir))

    resolved = resolve_data_dir()
    assert resolved == custom_dir.resolve()
    assert custom_dir.is_dir()


def test_open_data_directory_windows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[str] = []

    def fake_startfile(path: str):
        calls.append(path)

    monkeypatch.setattr("os.startfile", fake_startfile, raising=False)
    assert open_data_directory(tmp_path) is True
    assert calls == [str(tmp_path)]

    def failing_startfile(_path: str):
        raise OSError("Permission denied")

    monkeypatch.setattr("os.startfile", failing_startfile, raising=False)
    assert open_data_directory(tmp_path) is False


def test_open_data_directory_darwin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls: list[list[str]] = []

    def fake_popen(cmd: list[str]):
        calls.append(cmd)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    assert open_data_directory(tmp_path) is True
    assert calls == [["open", str(tmp_path)]]

    def failing_popen(_cmd: list[str]):
        raise OSError("Executable not found")

    monkeypatch.setattr("subprocess.Popen", failing_popen)
    assert open_data_directory(tmp_path) is False


def test_open_data_directory_linux_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert open_data_directory(tmp_path) is False


@pytest.mark.asyncio
async def test_open_data_dir_endpoint_reports_opened_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(tmp_path / "data"))

    # Cenário 1: open_data_directory retorna True
    monkeypatch.setattr("src.presentation.main.open_data_directory", lambda _p: True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post("/api/v1/system/open-data-dir")
    assert resp.status_code == 200
    assert resp.json()["opened"] is True

    # Cenário 2: open_data_directory retorna False
    monkeypatch.setattr("src.presentation.main.open_data_directory", lambda _p: False)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post("/api/v1/system/open-data-dir")
    assert resp.status_code == 200
    assert resp.json()["opened"] is False
