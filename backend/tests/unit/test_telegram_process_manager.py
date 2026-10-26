import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

try:
    from src.infrastructure.telegram_process_manager import (
        TelegramProcessManager,
        _is_port_in_use,
        _assign_to_windows_job_object,
        find_available_port,
    )
except ImportError:
    from src.infrastructure.telegram_process_manager import (
        TelegramProcessManager,
        _is_port_in_use,
        _assign_to_windows_job_object,
    )
    find_available_port = None  # type: ignore


@pytest.fixture(autouse=True)
def api_credentials(monkeypatch: pytest.MonkeyPatch):
    # O servidor local só sobe com credenciais do my.telegram.org; quem testa o caso sem elas as remove.
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_API_HASH", "fake-api-hash")


def test_is_port_in_use_detects_listening_and_free_port():
    # A porta vem do sistema e é liberada pelo próprio teste, em vez de supor que uma porta fixa esteja livre.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert _is_port_in_use(port)
    assert not _is_port_in_use(port)


def test_telegram_process_manager_custom_data_dir(tmp_path: Path):
    custom_dir = tmp_path / "custom_data"
    mgr = TelegramProcessManager(data_dir=custom_dir)
    assert mgr.get_data_dir() == custom_dir.resolve()


def test_find_binary_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()
    monkeypatch.setenv("TELEGRAM_BOT_API_BIN", str(fake_bin))

    mgr = TelegramProcessManager()
    found = mgr.find_binary()
    assert found == fake_bin.resolve()


def test_find_binary_not_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TELEGRAM_BOT_API_BIN", raising=False)
    with patch("shutil.which", return_value=None):
        with patch.object(Path, "is_file", return_value=False):
            mgr = TelegramProcessManager()
            assert mgr.find_binary() is None


def test_start_returns_false_when_binary_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TELEGRAM_BOT_API_BIN", raising=False)
    with patch.object(TelegramProcessManager, "find_binary", return_value=None):
        with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
            mgr = TelegramProcessManager()
            assert mgr.start() is False
            assert not mgr.is_running()


def test_start_returns_true_when_port_already_in_use():
    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=True):
        mgr = TelegramProcessManager(port=8081)
        assert mgr.start() is True
        assert not mgr.is_running()


def test_start_and_stop_success(tmp_path: Path):
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.side_effect = [None, None, 0]

    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch("src.infrastructure.telegram_process_manager._assign_to_windows_job_object") as mock_job:
                mgr = TelegramProcessManager(bin_path=fake_bin, port=8081, data_dir=tmp_path)
                started = mgr.start()

                assert started is True
                assert mgr.is_running()
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                cmd = args[0]
                assert str(fake_bin.resolve()) in cmd
                assert "--local" in cmd
                assert "--http-port=8081" in cmd
                # Só o backend usa o servidor local: sem isso ele aceita conexões de toda a rede (#37).
                assert "--http-ip-address=127.0.0.1" in cmd

                # Agora testa parada graciosa
                mgr.stop()
                mock_proc.terminate.assert_called_once()
                mock_proc.wait.assert_called_once()
                assert not mgr.is_running()


def test_start_log_masks_api_credentials(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    # O comando logado não pode levar o api_hash nem o api_id do my.telegram.org (#40).
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()

    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
        with patch("subprocess.Popen", return_value=MagicMock(pid=1)) as mock_popen:
            with patch("src.infrastructure.telegram_process_manager._assign_to_windows_job_object"):
                with caplog.at_level("INFO", logger="src.infrastructure.telegram_process_manager"):
                    assert TelegramProcessManager(bin_path=fake_bin, data_dir=tmp_path).start() is True

    cmd = mock_popen.call_args[0][0]
    assert "--api-id=123456" in cmd
    assert "--api-hash=fake-api-hash" in cmd
    assert "fake-api-hash" not in caplog.text
    assert "123456" not in caplog.text
    assert "--api-id=*** --api-hash=***" in caplog.text


def test_stop_force_kill_on_timeout(tmp_path: Path):
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.terminate.side_effect = None
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="bin", timeout=2.0), 0]

    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
        with patch("subprocess.Popen", return_value=mock_proc):
            mgr = TelegramProcessManager(bin_path=fake_bin, port=8081, data_dir=tmp_path)
            mgr.start()
            mgr.stop()

            mock_proc.terminate.assert_called_once()
            mock_proc.kill.assert_called_once()


def test_assign_to_windows_job_object_non_win32():
    with patch("sys.platform", "linux"):
        res = _assign_to_windows_job_object(MagicMock())
        assert res is None


def test_find_available_port_returns_start_port_when_free():
    assert callable(find_available_port), "find_available_port must be implemented and callable"
    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
        port = find_available_port(start_port=8081, max_attempts=5)
        assert port == 8081


def test_find_available_port_skips_occupied_port():
    assert callable(find_available_port), "find_available_port must be implemented and callable"
    # Portas ocupadas simuladas: o teste não depende das portas livres da máquina.
    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", side_effect=lambda port, host="127.0.0.1": port in {8081, 8082}):
        assert find_available_port(start_port=8081, max_attempts=5) == 8083


def test_find_available_port_raises_or_returns_none_when_all_occupied():
    assert callable(find_available_port), "find_available_port must be implemented and callable"
    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=True):
        try:
            port = find_available_port(start_port=8081, max_attempts=5)
            assert port is None
        except (RuntimeError, ValueError, OSError):
            pass


def test_telegram_process_manager_uses_dynamic_port(tmp_path: Path):
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.side_effect = [None, None, 0]

    def fake_is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        # Porta 8081 ocupada por outro serviço; 8082 está livre
        return port == 8081

    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", side_effect=fake_is_port_in_use):
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch("src.infrastructure.telegram_process_manager._assign_to_windows_job_object"):
                mgr = TelegramProcessManager(bin_path=fake_bin, port=8081, data_dir=tmp_path)
                started = mgr.start()

                assert started is True
                assert mgr.port == 8082
                assert mgr.is_running()
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                cmd = args[0]
                assert "--http-port=8082" in cmd



def test_start_skips_local_server_without_api_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Sem --api-id/--api-hash o telegram-bot-api encerra logo ao subir; o pacote portátil cadastrava bots
    # contra 127.0.0.1:8081 vazio ("All connection attempts failed").
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    fake_bin = tmp_path / "fake-telegram-bot-api"
    fake_bin.touch()

    with patch("src.infrastructure.telegram_process_manager._is_port_in_use", return_value=False):
        with patch("subprocess.Popen") as mock_popen:
            mgr = TelegramProcessManager(bin_path=fake_bin, port=8081, data_dir=tmp_path)

            assert mgr.start() is False
            mock_popen.assert_not_called()
