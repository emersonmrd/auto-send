import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import bundle_portable_windows as bundle  # noqa: E402
from scripts import setup_windows_python_embed as embed  # noqa: E402


def _stub_bundle_steps(monkeypatch, output_dir: Path):
    calls = {}
    monkeypatch.setattr(bundle, "build_frontend_static", lambda: None)
    monkeypatch.setattr(bundle, "setup_package_structure", lambda target: None)
    monkeypatch.setattr(bundle, "setup_windows_binaries", lambda bin_dir: True)
    monkeypatch.setattr(bundle, "write_launcher_and_docs", lambda target: None)
    monkeypatch.setattr(bundle, "validate_bundle", lambda target: None)
    monkeypatch.setattr(
        bundle,
        "setup_embed_python",
        lambda target_dir, req_file: calls.setdefault("embed", (target_dir, req_file)),
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["bundle", "--output-dir", str(output_dir), "--skip-binaries"])
    return calls


def test_bundle_embeds_python_with_the_bundle_requirements_by_default(tmp_path, monkeypatch):
    # O pacote promete rodar "100% autônomo": sem o Python embutido o launcher depende do Python do sistema.
    calls = _stub_bundle_steps(monkeypatch, tmp_path)

    bundle.main()

    assert calls["embed"] == (tmp_path / "python", tmp_path / "app" / "backend" / "requirements.txt")


def test_bundle_skips_python_on_request(tmp_path, monkeypatch):
    calls = _stub_bundle_steps(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", sys.argv + ["--skip-python"])

    bundle.main()

    assert "embed" not in calls


def test_embedded_pip_installs_the_given_requirements_file(tmp_path, monkeypatch):
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "get-pip.py").write_text("")
    req_file = tmp_path / "custom-requirements.txt"
    req_file.write_text("fastapi==0.150.0\n")
    monkeypatch.setattr(embed.sys, "platform", "win32")
    monkeypatch.setattr(embed, "patch_pth_file", lambda python_dir: None)
    commands = []
    monkeypatch.setattr(
        embed.subprocess, "run", lambda cmd, **kw: commands.append(cmd) or subprocess.CompletedProcess(cmd, 0)
    )

    embed.setup_embed_python(tmp_path, req_file=req_file)

    assert commands[-1][-2:] == ["-r", str(req_file)]


def test_pth_file_puts_the_bundled_backend_on_sys_path(tmp_path):
    # Com ._pth o Python embutido ignora o PYTHONPATH do launcher; sem esta linha, "No module named 'src'".
    pth = tmp_path / "python312._pth"
    pth.write_text("python312.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")

    embed.patch_pth_file(tmp_path)

    lines = pth.read_text().splitlines()
    assert "..\\app\\backend" in lines
    assert "Lib\\site-packages" in lines
    assert "import site" in lines


def test_vc_runtime_is_copied_next_to_the_bundled_binaries(tmp_path, monkeypatch):
    # telegram-bot-api.exe importa VCRUNTIME140/MSVCP140; num Windows sem o VC++ Redistributable ele não abre.
    crt = tmp_path / "VS" / "VC" / "Redist" / "MSVC" / "14.44.35112" / "x64" / "Microsoft.VC143.CRT"
    crt.mkdir(parents=True)
    for dll in bundle.VC_RUNTIME_DLLS:
        (crt / dll).write_bytes(b"MZ")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(bundle.sys, "platform", "win32")
    monkeypatch.setattr(bundle, "find_vc_runtime_dir", lambda: crt)

    bundle.bundle_vc_runtime(bin_dir)

    assert sorted(p.name for p in bin_dir.iterdir()) == sorted(bundle.VC_RUNTIME_DLLS)


def test_vc_runtime_missing_on_windows_fails_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle.sys, "platform", "win32")
    monkeypatch.setattr(bundle, "find_vc_runtime_dir", lambda: None)

    with pytest.raises(SystemExit):
        bundle.bundle_vc_runtime(tmp_path)


def test_launcher_runs_the_environment_check_before_the_server():
    # A autoverificação roda sozinha a cada início: quem usa o pacote só dá dois cliques no .bat.
    launcher = bundle.LAUNCHER_BAT

    check = launcher.index('"%PYTHON_BIN%" -m src.infrastructure.portable_preflight')
    server = launcher.index('"%PYTHON_BIN%" -m src.presentation.main')
    assert check < server
