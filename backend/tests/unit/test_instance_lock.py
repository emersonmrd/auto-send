import os
import socket
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

import src.presentation.main as main_module
from src.infrastructure.instance_lock import (
    lock_file_path,
    read_lock_pid,
    remove_lock_pid,
    resolve_startup_instance,
    write_lock_pid,
)
from src.infrastructure.telegram_process_manager import _is_port_in_use, find_available_port
from src.presentation.main import app


def test_find_available_port_skips_port_occupied_only_in_ipv6(monkeypatch):
    """Dado um programa escutando em [::1]:8000, quando o app procura porta, escolhe a próxima livre nos dois endereços."""
    def _fake_in_use(port: int, host: str = "127.0.0.1") -> bool:
        return port == 8000 and host == "::1"

    monkeypatch.setattr("src.infrastructure.telegram_process_manager._is_port_in_use", _fake_in_use)
    assert find_available_port(8000, max_attempts=5, host="127.0.0.1") == 8001


def test_is_port_in_use_supports_real_ipv6_loopback_socket():
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("IPv6 indisponível neste ambiente")
    with sock:
        try:
            sock.bind(("::1", 0))
        except OSError:
            pytest.skip("Loopback IPv6 indisponível neste ambiente")
        sock.listen(1)
        port = sock.getsockname()[1]
        assert _is_port_in_use(port, host="::1") is True
    assert _is_port_in_use(port, host="::1") is False


def test_same_version_already_running_reuses_existing_instance(tmp_path: Path):
    """Dado um Auto-Send da mesma versão já aberto, não sobe outra instância e abre na existente."""
    killed: list[int] = []
    messages: list[str] = []

    decision = resolve_startup_instance(
        tmp_path,
        current_version="0.4.0",
        is_port_busy_fn=lambda _p: True,
        probe_health_fn=lambda _p: {"status": "healthy", "app": "auto-send", "version": "0.4.0"},
        kill_pid_fn=lambda pid: (killed.append(pid), True)[1],
        output_fn=messages.append,
    )

    assert decision.action == "reuse_existing"
    assert decision.port == 8000
    assert decision.url == "http://127.0.0.1:8000"
    assert killed == []
    assert any("já está aberto" in m for m in messages)


def test_older_version_or_hung_instance_with_lock_kills_only_locked_pid_when_confirmed(tmp_path: Path):
    """Dado uma instância antiga ou travada com a trava gravada, quando responde S,
    só aquele PID é encerrado e a nova sobe na porta 8000."""
    write_lock_pid(tmp_path, 42424)
    killed: list[int] = []
    prompts: list[str] = []

    decision = resolve_startup_instance(
        tmp_path,
        current_version="0.5.0",
        is_port_busy_fn=lambda _p: True,
        probe_health_fn=lambda _p: {"status": "healthy", "app": "auto-send", "version": "0.4.0"},
        is_pid_alive_fn=lambda pid: pid == 42424,
        kill_pid_fn=lambda pid: (killed.append(pid), True)[1],
        find_port_fn=lambda start, _attempts: start,
        input_fn=lambda p: (prompts.append(p), "S")[1],
        output_fn=lambda _m: None,
        sleep_fn=lambda _s: None,
    )

    assert decision.action == "start"
    assert decision.port == 8000
    assert decision.url == "http://127.0.0.1:8000"
    assert killed == [42424]
    assert read_lock_pid(tmp_path) is None
    assert prompts and "Encerrar a instância antiga e continuar? (S/N)" in prompts[0]


def test_hung_instance_with_lock_is_not_killed_when_user_answers_n(tmp_path: Path):
    """Com N, nada é encerrado e a inicialização é abortada."""
    write_lock_pid(tmp_path, 42424)
    killed: list[int] = []

    decision = resolve_startup_instance(
        tmp_path,
        current_version="0.5.0",
        is_port_busy_fn=lambda _p: False,
        probe_health_fn=lambda _p: None,
        is_pid_alive_fn=lambda pid: pid == 42424,
        kill_pid_fn=lambda pid: (killed.append(pid), True)[1],
        input_fn=lambda _p: "N",
        output_fn=lambda _m: None,
    )

    assert decision.action == "abort"
    assert killed == []
    assert read_lock_pid(tmp_path) == 42424


def test_other_program_on_port_8000_picks_next_free_port_without_prompting(tmp_path: Path):
    """Quando outro programa ocupa a porta 8000, usa a próxima porta livre e avisa qual."""
    messages: list[str] = []
    killed: list[int] = []

    decision = resolve_startup_instance(
        tmp_path,
        current_version="0.4.0",
        is_port_busy_fn=lambda p: p == 8000,
        probe_health_fn=lambda _p: None,
        find_port_fn=lambda start, _attempts: start,
        kill_pid_fn=lambda pid: (killed.append(pid), True)[1],
        output_fn=messages.append,
    )

    assert decision.action == "start"
    assert decision.port == 8001
    assert decision.url == "http://127.0.0.1:8001"
    assert killed == []
    assert any("8001" in m for m in messages)


def test_run_app_opens_127_0_0_1_and_creates_and_removes_lock_file(tmp_path: Path, monkeypatch):
    """Dado o pacote iniciado, o navegador abre em http://127.0.0.1:<porta>, e a trava é criada e removida."""
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(tmp_path))
    opened_urls: list[str] = []
    lock_during_run: list[int | None] = []

    class ImmediateThread:
        def __init__(self, target, daemon=True):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(main_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(main_module.webbrowser, "open", lambda url: opened_urls.append(url))
    monkeypatch.setattr("src.infrastructure.instance_lock._is_dual_stack_port_in_use", lambda _p: False)
    monkeypatch.setattr(main_module, "find_available_port", lambda start, max_attempts=20, host="127.0.0.1": 8000)

    async def _noop_init_db():
        return None

    monkeypatch.setattr(main_module, "init_db", _noop_init_db)
    monkeypatch.setattr(
        main_module.uvicorn,
        "run",
        lambda *_a, **_kw: lock_during_run.append(read_lock_pid(tmp_path)),
    )

    main_module.run_app()

    assert opened_urls == ["http://127.0.0.1:8000"]
    assert lock_during_run == [os.getpid()]
    assert not lock_file_path(tmp_path).exists()
    remove_lock_pid(tmp_path)


@pytest.mark.asyncio
async def test_health_endpoint_includes_app_and_version():
    """Dado o /api/v1/health, quando consultado, traz status, app e version."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "healthy",
        "app": "auto-send",
        "version": app.version,
    }
