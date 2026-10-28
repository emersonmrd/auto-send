import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from scripts import bundle_portable_windows as bundle  # noqa: E402


def test_portable_package_leaves_out_local_bytecode_cache(tmp_path, monkeypatch):
    """Um build local não leva os .pyc do backend de quem gerou o pacote (kaizen de 2026-10-28: o preview saiu com 10 __pycache__)."""
    frontend_out = tmp_path / "frontend" / "out"
    frontend_out.mkdir(parents=True)
    (frontend_out / "index.html").write_text("<html></html>")
    backend = tmp_path / "backend"
    cache = backend / "src" / "domain" / "__pycache__"
    cache.mkdir(parents=True)
    (backend / "src" / "domain" / "profile.py").write_text("X = 1\n")
    (cache / "profile.cpython-312.pyc").write_bytes(b"\x00")
    (backend / "pyproject.toml").write_text("[project]\nname = 'auto-send'\n")
    monkeypatch.setattr(bundle, "FRONTEND_DIR", tmp_path / "frontend")
    monkeypatch.setattr(bundle, "BACKEND_DIR", backend)
    monkeypatch.setattr(bundle, "export_runtime_requirements", lambda: "")

    target = tmp_path / "AutoSend"
    bundle.setup_package_structure(target)

    assert (target / "app" / "backend" / "src" / "domain" / "profile.py").exists()
    assert list((target / "app" / "backend").rglob("__pycache__")) == []
    assert list((target / "app" / "backend").rglob("*.pyc")) == []
