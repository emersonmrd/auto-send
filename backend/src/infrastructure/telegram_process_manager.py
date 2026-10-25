import atexit
import logging
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Verifica se uma porta de rede já está em uso."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False


def find_available_port(
    start_port: int, max_attempts: int = 20, host: str = "127.0.0.1"
) -> Optional[int]:
    """
    Busca a primeira porta TCP livre a partir de start_port até start_port + max_attempts - 1.
    Retorna a porta encontrada ou None se todas estiverem em uso.
    """
    for port in range(start_port, start_port + max_attempts):
        if not _is_port_in_use(port, host=host):
            return port
    return None


def _assign_to_windows_job_object(process: subprocess.Popen) -> Optional[Any]:
    """
    Associa o processo a um Windows Job Object configurado com JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000).
    Isso assegura que se o processo pai (Python/Uvicorn) for finalizado pelo usuário
    fechando a janela no [X], o kernel do Windows encerra automaticamente todos os processos
    filhos associados ao Job Object sem deixar processos órfãos.
    """
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            logger.warning("Falha ao criar Windows Job Object: código de erro %d", ctypes.get_last_error())
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        success = kernel32.SetInformationJobObject(
            job_handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not success:
            logger.warning("Falha ao configurar SetInformationJobObject: código de erro %d", ctypes.get_last_error())
            kernel32.CloseHandle(job_handle)
            return None

        proc_handle = getattr(process, "_handle", None)
        if proc_handle is None:
            return job_handle

        assigned = kernel32.AssignProcessToJobObject(job_handle, int(proc_handle))
        if not assigned:
            logger.warning("Falha ao associar processo ao Job Object: código de erro %d", ctypes.get_last_error())
            kernel32.CloseHandle(job_handle)
            return None

        logger.info("Processo %d associado com sucesso ao Windows Job Object (KILL_ON_JOB_CLOSE).", process.pid)
        return job_handle
    except Exception as exc:
        logger.warning("Exceção ao configurar Windows Job Object: %s", exc)
        return None


class TelegramProcessManager:
    """
    Gerenciador de ciclo de vida do servidor local Telegram Bot API.
    Inicia o binário local em porta dedicada (default: 8081) e garante seu encerramento
    quando o processo principal termina (via lifespan, atexit ou fechamento abrupto no [X] pelo Windows Job Object).
    """

    def __init__(
        self,
        bin_path: Optional[Path] = None,
        port: int = 8081,
        data_dir: Optional[Path] = None,
        gateway: Optional[Any] = None,
    ):
        self._custom_bin_path = bin_path
        self.port = int(os.getenv("TELEGRAM_BOT_API_PORT", str(port)))
        self._custom_data_dir = data_dir
        self.gateway = gateway
        self._process: Optional[subprocess.Popen] = None
        self._job_handle: Optional[Any] = None
        self._atexit_registered = False

    def find_binary(self) -> Optional[Path]:
        """Localiza o binário do Telegram Bot API no ambiente."""
        if self._custom_bin_path and self._custom_bin_path.is_file():
            return self._custom_bin_path.resolve()

        env_bin = os.getenv("TELEGRAM_BOT_API_BIN")
        if env_bin and Path(env_bin).is_file():
            return Path(env_bin).resolve()

        bin_name = "telegram-bot-api.exe" if sys.platform == "win32" else "telegram-bot-api"

        cwd = Path.cwd()
        current_file = Path(__file__).resolve()

        # Procura em locais candidatos relativos ao CWD e ao arquivo atual
        candidates = [
            cwd / "bin" / bin_name,
            cwd / bin_name,
            current_file.parent.parent.parent / "bin" / bin_name,
            current_file.parent.parent.parent.parent / "bin" / bin_name,
        ]

        for cand in candidates:
            if cand.is_file():
                return cand.resolve()

        # Procura no PATH do sistema operacional
        which_path = shutil.which(bin_name) or shutil.which("telegram-bot-api")
        if which_path:
            return Path(which_path).resolve()

        return None

    def get_data_dir(self) -> Path:
        """Determina o diretório de dados para o telegram-bot-api."""
        if self._custom_data_dir:
            return self._custom_data_dir.resolve()

        env_dir = os.getenv("TELEGRAM_BOT_API_DIR")
        if env_dir:
            return Path(env_dir).resolve()

        # Padrão: pasta 'data' no diretório de trabalho atual
        return (Path.cwd() / "data").resolve()

    def start(self, gateway: Optional[Any] = None) -> bool:
        """
        Inicia o servidor local se o binário existir e aloca porta dinâmica se houver colisão.
        Retorna True se o servidor estiver operacional (ou já em execução externamente),
        ou False se o binário não for encontrado ou não houver portas livres.
        """
        if self.is_running():
            return True

        # Sem --api-id/--api-hash o telegram-bot-api encerra logo ao subir; o gateway fica na API pública.
        if not (os.getenv("TELEGRAM_API_ID", "").strip() and os.getenv("TELEGRAM_API_HASH", "").strip()):
            logger.info("TELEGRAM_API_ID/TELEGRAM_API_HASH ausentes: servidor local desativado, usando a API pública.")
            return False

        binary = self.find_binary()
        if not binary:
            if _is_port_in_use(self.port):
                logger.info("Porta %d já está em uso e binário local não encontrado. Assumindo Telegram Bot API pré-existente.", self.port)
                target_gw = gateway or self.gateway
                if target_gw is not None and hasattr(target_gw, "base_url"):
                    target_gw.base_url = f"http://127.0.0.1:{self.port}"
                return True
            logger.info("Binário telegram-bot-api não encontrado. Execução em modo direto/oficial.")
            return False

        if _is_port_in_use(self.port):
            allocated_port = find_available_port(self.port, max_attempts=20)
            if allocated_port is None:
                logger.error("Nenhuma porta livre encontrada para Telegram Bot API a partir de %d.", self.port)
                return False
            self.port = allocated_port

        data_directory = self.get_data_dir()
        data_directory.mkdir(parents=True, exist_ok=True)

        cmd: List[str] = [
            str(binary),
            "--local",
            # Só o backend usa o servidor, por 127.0.0.1; sem isso ele escuta em todas as interfaces.
            "--http-ip-address=127.0.0.1",
            f"--http-port={self.port}",
            f"--dir={data_directory}",
        ]

        api_id = os.getenv("TELEGRAM_API_ID", "").strip()
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        if api_id and api_hash:
            cmd.extend([f"--api-id={api_id}", f"--api-hash={api_hash}"])

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NO_WINDOW = 0x08000000 para não abrir console adicional
            creationflags = 0x08000000

        try:
            logger.info("Iniciando Telegram Bot API local: %s", " ".join(cmd))
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )

            # No Windows, vincula ao Job Object para garantir morte com a janela [X]
            self._job_handle = _assign_to_windows_job_object(self._process)

            if not self._atexit_registered:
                atexit.register(self.stop)
                self._atexit_registered = True

            target_gw = gateway or self.gateway
            if target_gw is not None and hasattr(target_gw, "base_url"):
                target_gw.base_url = f"http://127.0.0.1:{self.port}"

            logger.info("Telegram Bot API local iniciado com sucesso (PID: %d na porta %d).", self._process.pid, self.port)
            return True
        except Exception as exc:
            logger.error("Falha ao iniciar subprocesso Telegram Bot API: %s", exc)
            self._process = None
            return False

    def stop(self) -> None:
        """Encerra o processo do Telegram Bot API graciosamente."""
        proc = self._process
        if proc is None:
            return

        self._process = None
        if proc.poll() is None:
            logger.info("Encerrando Telegram Bot API local (PID: %d)...", proc.pid)
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass

        if self._job_handle and sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle(self._job_handle)
            except Exception:
                pass
            self._job_handle = None

        logger.info("Telegram Bot API local finalizado.")

    def is_running(self) -> bool:
        """Verifica se o processo gerenciado está ativo."""
        return self._process is not None and self._process.poll() is None


telegram_process_manager = TelegramProcessManager()
