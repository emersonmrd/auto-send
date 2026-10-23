import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.infrastructure import portable_preflight as preflight


def _package(root: Path) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "data").mkdir()
    for name in ("telegram-bot-api.exe", "ffmpeg.exe", "ffprobe.exe"):
        (root / "bin" / name).write_bytes(b"MZ")
    return root


def _runner(returncodes: dict[str, int]):
    def run(cmd, **kwargs):
        name = Path(cmd[0]).name
        return subprocess.CompletedProcess(cmd, returncodes.get(name, 0), stdout=f"{name} 1.0\n".encode(), stderr=b"")
    return run


NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def test_all_binaries_open_gives_ok_report(tmp_path):
    root = _package(tmp_path / "AutoSend-Portable")

    results = preflight.run_preflight(root, run=_runner({}), now=NOW)

    assert all(r.ok for r in results)
    report = (root / "data" / "diagnostico.txt").read_text(encoding="utf-8")
    assert "RESULTADO: OK" in report
    assert "2026-01-15T12:00:00+00:00" in report
    assert "[OK] telegram-bot-api.exe" in report


def test_missing_dll_exit_code_is_named_in_the_report(tmp_path):
    # O Windows devolve 0xC0000135 como inteiro sem sinal (3221225781) quando falta uma DLL.
    root = _package(tmp_path / "AutoSend-Portable")

    results = preflight.run_preflight(root, run=_runner({"telegram-bot-api.exe": 0xC0000135}), now=NOW)

    failed = [r for r in results if not r.ok]
    assert [r.name for r in failed] == ["telegram-bot-api.exe"]
    assert "DLL ausente" in failed[0].detail
    report = (root / "data" / "diagnostico.txt").read_text(encoding="utf-8")
    assert "RESULTADO: AVISO" in report


def test_missing_binary_and_crash_are_reported(tmp_path):
    root = _package(tmp_path / "AutoSend-Portable")
    (root / "bin" / "ffprobe.exe").unlink()

    results = {r.name: r for r in preflight.run_preflight(root, run=_runner({"ffmpeg.exe": 1}), now=NOW)}

    assert results["ffprobe.exe"].detail == "arquivo ausente"
    assert "código 1" in results["ffmpeg.exe"].detail


def test_binary_that_cannot_start_is_reported(tmp_path):
    root = _package(tmp_path / "AutoSend-Portable")

    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    results = preflight.run_preflight(root, run=run, now=NOW)

    assert not any(r.ok for r in results if r.name.endswith(".exe"))


def test_install_path_with_accents_is_flagged(tmp_path):
    root = _package(tmp_path / "Área de Trabalho" / "AutoSend-Portable")

    results = {r.name: r for r in preflight.run_preflight(root, run=_runner({}), now=NOW)}

    assert not results["caminho da pasta"].ok


def test_summary_line_is_ascii_for_any_console():
    ok = [preflight.CheckResult("ffmpeg.exe", True, "1.0")]
    warn = [preflight.CheckResult("ffmpeg.exe", False, "DLL ausente")]

    assert preflight.summary_line(ok).isascii()
    assert preflight.summary_line(warn).isascii()
    assert "diagnostico.txt" in preflight.summary_line(warn)
