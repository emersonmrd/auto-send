import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import bundle_portable_windows as bundle  # noqa: E402


def test_frontend_build_runs_npm_by_its_resolved_path_with_export_env(tmp_path, monkeypatch):
    # No Windows "npm" é npm.cmd: CreateProcess só o acha pelo caminho resolvido (v0.1.1 morreu aqui).
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(bundle, "FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(bundle.shutil, "which", lambda name: rf"C:\Program Files\nodejs\{name}.cmd")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bundle.subprocess, "run", fake_run)

    bundle.build_frontend_static()

    (cmd, kwargs), = calls
    assert cmd[0] == r"C:\Program Files\nodejs\npm.cmd"
    assert cmd[-2:] == ["run", "build"]
    assert kwargs["env"]["NEXT_EXPORT"] == "true"


def test_frontend_npm_scripts_do_not_use_posix_only_env_prefixes():
    # O npm roda os scripts pelo cmd.exe no Windows, que não entende "VAR=valor comando".
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text())["scripts"]

    posix_only = {name: cmd for name, cmd in scripts.items() if re.match(r"^\s*[A-Z_][A-Z0-9_]*=", cmd)}

    assert posix_only == {}
