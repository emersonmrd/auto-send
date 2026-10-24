import os
import tempfile

# Roda antes de qualquer módulo de teste importar o app: o engine e o diretório de mídia nascem no import de
# src.presentation.main, então sem isto a suíte usa (e o drop_all apaga) o auto_send.db real.
_TMP_DIR = tempfile.mkdtemp(prefix="auto-send-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR}/test.db"
os.environ["TEMP_MEDIA_DIR"] = _TMP_DIR
# Hosts dos clientes de teste do httpx ("test") e do Starlette ("testserver"), além do loopback padrão (#36).
os.environ["ALLOWED_HOSTS"] = "test,testserver"
