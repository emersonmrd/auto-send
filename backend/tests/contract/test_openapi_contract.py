import asyncio
import os
import tempfile

# Isola o app num banco e diretório temporários antes de importá-lo: este módulo roda em processo próprio no CI.
_TMP_DIR = tempfile.mkdtemp(prefix="auto-send-contract-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR}/contract.db"
os.environ["TEMP_MEDIA_DIR"] = _TMP_DIR

import re
from pathlib import Path

import schemathesis  # noqa: E402
from schemathesis.checks import not_a_server_error, response_schema_conformance  # noqa: E402

from src.presentation.main import (  # noqa: E402
    AffectedBroadcastItemResponse,
    AffectedBroadcastsResponse,
    BroadcastButtonResponse,
    BroadcastHistoryItemResponse,
    BroadcastMediaResponse,
    BroadcastProgressResponse,
    CancelBroadcastResponse,
    ChannelCreateResponse,
    ChannelListItemResponse,
    ChannelUpdateResponse,
    DeleteResourceResponse,
    DiscoverChatsResponse,
    DiscoveredChatListItem,
    DiscoveredChatResponse,
    EditLockResponse,
    HealthResponse,
    ImmediateBroadcastCreateResponse,
    OpenDataDirResponse,
    ProfileListItemResponse,
    ProfileResponse,
    ScheduledBroadcastCreateResponse,
    ScheduledBroadcastResponse,
    app,
    init_db,
    telegram_gateway,
)

asyncio.run(init_db())
# Porta fechada: nenhuma chamada sai para a Telegram API real durante o fuzzing.
telegram_gateway.base_url = "http://127.0.0.1:9"

schema = schemathesis.openapi.from_asgi("/openapi.json", app)

_MODEL_TO_FRONTEND_INTERFACE = {
    HealthResponse: "HealthResponse",
    OpenDataDirResponse: "OpenDataDirResponse",
    ProfileResponse: "Profile",
    ProfileListItemResponse: "ProfileListItem",
    DeleteResourceResponse: "DeleteResourceResponse",
    ChannelCreateResponse: "ChannelCreateResponse",
    ChannelListItemResponse: "Channel",
    ChannelUpdateResponse: "ChannelUpdateResponse",
    DiscoveredChatResponse: "DiscoveredChat",
    DiscoveredChatListItem: "DiscoveredChatListItem",
    DiscoverChatsResponse: "DiscoverChatsResponse",
    BroadcastHistoryItemResponse: "BroadcastHistoryItem",
    BroadcastProgressResponse: "BroadcastProgressResponse",
    ScheduledBroadcastCreateResponse: "ScheduledBroadcastCreateResponse",
    ImmediateBroadcastCreateResponse: "BroadcastResponse",
    BroadcastMediaResponse: "BroadcastMedia",
    BroadcastButtonResponse: "BroadcastButton",
    ScheduledBroadcastResponse: "ScheduledBroadcast",
    CancelBroadcastResponse: "CancelBroadcastResponse",
    EditLockResponse: "EditLockResponse",
    AffectedBroadcastItemResponse: "AffectedBroadcastItem",
    AffectedBroadcastsResponse: "AffectedBroadcastsResponse",
}


def test_every_2xx_response_in_openapi_declares_a_schema():
    spec = app.openapi()
    missing = []
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            for status_code, response in operation.get("responses", {}).items():
                if not str(status_code).startswith("2"):
                    continue
                json_schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                if not json_schema:
                    missing.append(f"{method.upper()} {path} -> {status_code}")
    assert missing == [], f"Rotas 2xx sem response_model no OpenAPI: {missing}"


def test_frontend_types_mirror_backend_response_models():
    ts_path = Path(__file__).resolve().parents[3] / "frontend" / "src" / "types" / "index.ts"
    ts_source = ts_path.read_text(encoding="utf-8")
    interfaces: dict[str, set[str]] = {}
    inherits: dict[str, str] = {}
    for match in re.finditer(
        r"export\s+interface\s+(\w+)(?:\s+extends\s+(\w+))?\s*\{([^}]*)\}",
        ts_source,
    ):
        name, parent, body = match.groups()
        fields = set(re.findall(r"^\s*(\w+)\??\s*:", body, flags=re.MULTILINE))
        interfaces[name] = fields
        if parent:
            inherits[name] = parent
    for name, parent in inherits.items():
        interfaces[name] |= interfaces.get(parent, set())

    for model_cls, ts_name in _MODEL_TO_FRONTEND_INTERFACE.items():
        assert ts_name in interfaces, f"Interface {ts_name} ausente em frontend/src/types/index.ts"
        backend_fields = set(model_cls.model_fields.keys())
        assert backend_fields <= interfaces[ts_name], (
            f"{ts_name} não declara todos os campos de {model_cls.__name__}: "
            f"faltando {backend_fields - interfaces[ts_name]}"
        )


@schema.parametrize()
def test_payloads_never_cause_server_error(case):
    response = case.call()
    case.validate_response(response, checks=(not_a_server_error, response_schema_conformance))
