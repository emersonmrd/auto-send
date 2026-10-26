"""Trava de instância (PID) e decisão de inicialização do pacote portátil (#29).

Regras:
1. O navegador abre sempre em `http://127.0.0.1:<porta>` (nunca `localhost`, que no Windows pode resolver para `::1`).
2. Uma porta só é considerada livre se estiver livre em `127.0.0.1` e em `::1`.
3. `/api/v1/health` informa `{"status": "healthy", "app": "auto-send", "version": "<versão>"}`.
4. `autosend.pid` na pasta de dados guarda o PID da instância ativa e é removido ao encerrar.
5. Se a porta 8000 estiver ocupada ou o PID da trava estiver vivo sem responder:
   - Auto-Send da mesma versão respondendo -> avisa que já está aberto e abre o navegador nele, sem subir outra instância.
   - Auto-Send de outra versão, ou PID da trava vivo sem responder (travado) -> pergunta "Encerrar a instância antiga e continuar? (S/N)".
     Com S, encerra somente o PID gravado na trava e sobe a nova; com N, sai explicando.
   - Outro programa -> escolhe a próxima porta livre (IPv4 e IPv6) e avisa qual.
6. O app nunca encerra um processo que não seja o PID gravado na própria trava.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from src.infrastructure.telegram_process_manager import _is_port_in_use, find_available_port

LOCK_FILENAME = "autosend.pid"
APP_IDENTIFIER = "auto-send"


@dataclass(frozen=True)
class StartupDecision:
    action: Literal["start", "reuse_existing", "abort"]
    port: int | None
    url: str | None


def lock_file_path(data_dir: Path) -> Path:
    return data_dir.resolve() / LOCK_FILENAME


def read_lock_pid(data_dir: Path) -> int | None:
    path = lock_file_path(data_dir)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


def write_lock_pid(data_dir: Path, pid: int | None = None) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = lock_file_path(data_dir)
    actual_pid = pid if pid is not None else os.getpid()
    path.write_text(f"{actual_pid}\n", encoding="utf-8")
    return path


def remove_lock_pid(data_dir: Path, expected_pid: int | None = None) -> None:
    path = lock_file_path(data_dir)
    if not path.is_file():
        return
    if expected_pid is not None:
        current = read_lock_pid(data_dir)
        if current is not None and current != expected_pid:
            return
    try:
        path.unlink()
    except OSError:
        pass


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def terminate_locked_pid(pid: int) -> bool:
    """Encerra exclusivamente o PID gravado na trava."""
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_TERMINATE = 0x0001
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not handle:
                return False
            try:
                return bool(kernel32.TerminateProcess(handle, 1))
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def probe_local_health(port: int = 8000, timeout: float = 1.5) -> dict[str, Any] | None:
    """Consulta /api/v1/health em 127.0.0.1 e [::1] na porta informada."""
    for host in ("127.0.0.1", "[::1]"):
        url = f"http://{host}:{port}/api/v1/health"
        req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{port}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                if resp.status != 200:
                    continue
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(payload, dict):
                    return payload
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    return None


def _is_dual_stack_port_in_use(port: int) -> bool:
    return _is_port_in_use(port, host="127.0.0.1") or _is_port_in_use(port, host="::1")


def resolve_startup_instance(
    data_dir: Path,
    current_version: str,
    *,
    default_port: int = 8000,
    max_attempts: int = 20,
    probe_health_fn: Callable[[int], dict[str, Any] | None] = probe_local_health,
    is_port_busy_fn: Callable[[int], bool] = _is_dual_stack_port_in_use,
    find_port_fn: Callable[[int, int], int | None] = lambda start, attempts: find_available_port(
        start, max_attempts=attempts, host="127.0.0.1"
    ),
    is_pid_alive_fn: Callable[[int], bool] = is_pid_alive,
    kill_pid_fn: Callable[[int], bool] = terminate_locked_pid,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> StartupDecision:
    locked_pid = read_lock_pid(data_dir)
    if locked_pid == os.getpid():
        locked_pid = None
    locked_alive = bool(locked_pid and is_pid_alive_fn(locked_pid))
    port_busy = is_port_busy_fn(default_port)
    health = probe_health_fn(default_port) if port_busy else None

    is_autosend_health = bool(
        isinstance(health, dict)
        and (
            health.get("app") == APP_IDENTIFIER
            or (health.get("status") == "healthy" and "app" not in health)
        )
    )

    # 1. Auto-Send da mesma versão já aberto e respondendo
    if is_autosend_health and health.get("version") == current_version:
        url = f"http://127.0.0.1:{default_port}"
        output_fn(f"[i] O Auto-Send já está aberto em {url}.")
        return StartupDecision(action="reuse_existing", port=default_port, url=url)

    # 2. Auto-Send de outra versão respondendo, ou processo da trava vivo sem responder (travado)
    if is_autosend_health or locked_alive:
        try:
            answer = input_fn("Encerrar a instância antiga e continuar? (S/N): ").strip().lower()
        except EOFError:
            answer = "n"

        if answer not in ("s", "sim", "y", "yes"):
            output_fn("[i] Inicialização cancelada pelo usuário. A instância anterior foi mantida.")
            return StartupDecision(action="abort", port=None, url=None)

        # Regra 6: nunca encerrar um processo que não seja o PID gravado na própria trava.
        if locked_pid is not None and locked_alive:
            kill_pid_fn(locked_pid)
            remove_lock_pid(data_dir, expected_pid=locked_pid)
            sleep_fn(0.3)
        elif locked_pid is not None:
            remove_lock_pid(data_dir, expected_pid=locked_pid)

        chosen_port = find_port_fn(default_port, max_attempts)
        if chosen_port is None:
            return StartupDecision(action="abort", port=None, url=None)
        return StartupDecision(
            action="start",
            port=chosen_port,
            url=f"http://127.0.0.1:{chosen_port}",
        )

    # 3. Porta 8000 ocupada por outro programa (não é Auto-Send e não há trava ativa)
    if port_busy:
        chosen_port = find_port_fn(default_port + 1, max_attempts - 1)
        if chosen_port is None:
            return StartupDecision(action="abort", port=None, url=None)
        url = f"http://127.0.0.1:{chosen_port}"
        output_fn(f"[i] Porta {default_port} ocupada por outro programa; usando a porta {chosen_port} ({url}).")
        return StartupDecision(action="start", port=chosen_port, url=url)

    # 4. Porta 8000 livre em IPv4 e IPv6
    if locked_pid is not None:
        remove_lock_pid(data_dir, expected_pid=locked_pid)
    chosen_port = find_port_fn(default_port, max_attempts)
    if chosen_port is None:
        return StartupDecision(action="abort", port=None, url=None)
    return StartupDecision(
        action="start",
        port=chosen_port,
        url=f"http://127.0.0.1:{chosen_port}",
    )
