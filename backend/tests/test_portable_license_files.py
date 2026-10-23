import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from scripts import bundle_portable_windows as bundle  # noqa: E402


def test_portable_package_ships_license_and_third_party_notices(tmp_path, monkeypatch):
    """O .zip redistribui Python, bibliotecas, ffmpeg e telegram-bot-api: a licença do projeto e os avisos de terceiros vão junto."""
    frontend_out = tmp_path / "frontend" / "out"
    frontend_out.mkdir(parents=True)
    (frontend_out / "index.html").write_text("<html></html>")
    monkeypatch.setattr(bundle, "FRONTEND_DIR", tmp_path / "frontend")
    monkeypatch.setattr(bundle, "export_runtime_requirements", lambda: "")

    target = tmp_path / "AutoSend"
    bundle.setup_package_structure(target)

    assert (target / "LICENSE").read_text(encoding="utf-8") == (ROOT_DIR / "LICENSE").read_text(encoding="utf-8")
    notices = (target / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "FFmpeg" in notices and "GPL" in notices
    assert "telegram-bot-api" in notices
