import asyncio
import os
import tempfile

# Isola o app num banco e diretório temporários antes de importá-lo: este módulo roda em processo próprio no CI.
_TMP_DIR = tempfile.mkdtemp(prefix="auto-send-contract-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR}/contract.db"
os.environ["TEMP_MEDIA_DIR"] = _TMP_DIR

import schemathesis  # noqa: E402
from schemathesis.checks import not_a_server_error  # noqa: E402

from src.presentation.main import app, init_db, telegram_gateway  # noqa: E402

asyncio.run(init_db())
# Porta fechada: nenhuma chamada sai para a Telegram API real durante o fuzzing.
telegram_gateway.base_url = "http://127.0.0.1:9"

schema = schemathesis.openapi.from_asgi("/openapi.json", app)


@schema.parametrize()
def test_payloads_never_cause_server_error(case):
    response = case.call()
    case.validate_response(response, checks=(not_a_server_error,))
