"""Autoverificação do pacote portátil para Windows.

O Iniciar-AutoSend.bat roda este módulo a cada início, antes do servidor: confere se os binários
auxiliares abrem nesta máquina e grava o resultado em data/diagnostico.txt. Nunca impede o servidor
de subir; sem o telegram-bot-api local o backend usa a API pública do Telegram.
"""

import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

STATUS_DLL_NOT_FOUND = 0xC0000135
BINARIES = (
    ("telegram-bot-api.exe", "--version"),
    ("ffmpeg.exe", "-version"),
    ("ffprobe.exe", "-version"),
)
REPORT = Path("data") / "diagnostico.txt"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_binary(path: Path, arg: str, run: Callable = subprocess.run) -> CheckResult:
    if not path.is_file():
        return CheckResult(path.name, False, "arquivo ausente")
    try:
        result = run([str(path), arg], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(path.name, False, f"não executou: {exc}")
    # O Windows devolve NTSTATUS como inteiro sem sinal; o mascaramento cobre as duas representações.
    if result.returncode & 0xFFFFFFFF == STATUS_DLL_NOT_FOUND:
        return CheckResult(path.name, False, "DLL ausente (0xC0000135): falta um runtime nesta máquina")
    if result.returncode != 0:
        return CheckResult(path.name, False, f"saiu com código {result.returncode}")
    first_line = result.stdout.decode(errors="replace").strip().splitlines()[:1]
    return CheckResult(path.name, True, first_line[0] if first_line else "abriu")


def check_install_path(root: Path) -> CheckResult:
    # Acento no caminho (ex.: "Área de Trabalho") quebra programas que não usam a API Unicode do Windows.
    return CheckResult("caminho da pasta", str(root).isascii(), str(root))


def run_preflight(root: Path, run: Callable = subprocess.run, now: datetime | None = None) -> list[CheckResult]:
    results = [check_install_path(root)]
    results += [check_binary(root / "bin" / name, arg, run) for name, arg in BINARIES]
    write_report(root / REPORT, results, now or datetime.now(timezone.utc))
    return results


def write_report(path: Path, results: list[CheckResult], now: datetime) -> None:
    status = "OK" if all(r.ok for r in results) else "AVISO"
    lines = [
        "Auto-Send - diagnostico do ambiente",
        f"Data (UTC): {now.isoformat()}",
        f"Windows: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        "",
        *(f"[{'OK' if r.ok else 'FALHA'}] {r.name}: {r.detail}" for r in results),
        "",
        f"RESULTADO: {status}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_line(results: list[CheckResult]) -> str:
    # ASCII: a janela do launcher pode estar em qualquer code page.
    if all(r.ok for r in results):
        return "[OK] Verificacao do ambiente"
    failed = ", ".join(r.name for r in results if not r.ok).encode("ascii", "replace").decode()
    return f"[AVISO] Verificacao do ambiente: {failed}. Detalhes em data\\diagnostico.txt"


def main() -> None:
    print(summary_line(run_preflight(Path.cwd())))


if __name__ == "__main__":
    main()
