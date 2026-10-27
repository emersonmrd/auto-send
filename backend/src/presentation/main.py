import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import parse_host_header
from pydantic import BaseModel, Field, field_validator

from src.domain.broadcast.media_format import classify_media
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    InlineButton,
    MediaAttachment,
    MediaType,
    BroadcastStatus,
    ensure_schedulable,
    validate_and_escape_telegram_html,
)
from src.application.discover_chats_use_case import DiscoverChatsUseCase
from src.application.errors import ProfileNotFoundError
from src.application.resolve_chat_use_case import ResolveChatUseCase
from src.domain.channels.channel import Channel
from src.domain.channels.chat_discovery import DiscoveredChat
from src.domain.ports.chat_discovery_gateway import (
    BotNotChannelAdminError,
    ChatDiscoveryError,
    IChatDiscoveryGateway,
    TelegramUnavailableError,
)
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_repositories import (
    InMemoryChannelRepository,
    InMemoryProfileRepository,
)
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.infrastructure.resilience import CircuitBreakerOpenException
from src.infrastructure.telegram_gateway_http import (
    PUBLIC_API_MAX_BYTES,
    TelegramGatewayHttp,
    dispatch_broadcast_to_channel,
    redact_bot_token,
)
from src.infrastructure.upload_progress_store import UploadProgressStore
from src.infrastructure.temp_media_storage import MediaTooLarge, save_upload
from src.infrastructure.sqlite_migrations import (
    DatabaseMigrationError,
    MIGRATIONS,
    MigrationStep,
    has_user_tables,
    run_pending_migrations,
    sqlite_file_from_url,
)
from src.infrastructure.portable_data import (
    import_legacy_data_if_needed,
    open_data_directory,
    resolve_data_dir,
)
from src.infrastructure.instance_lock import (
    APP_IDENTIFIER,
    remove_lock_pid,
    resolve_startup_instance,
    write_lock_pid,
)
import atexit
import sys
import threading
import webbrowser
import uvicorn
from src.infrastructure.scheduler_service import AutomationSchedulerService
from src.infrastructure.telegram_process_manager import (
    find_available_port,
    telegram_process_manager,
)
from src.infrastructure.telegram_api_credentials import (
    get_env_file_path,
    load_telegram_credentials_from_data_dir,
    save_telegram_credentials_to_data_dir,
)

logger = logging.getLogger(__name__)

from src.infrastructure.sqlite_repositories import (
    Base,
    SqlAlchemyProfileRepository,
    SqlAlchemyChannelRepository,
    SqlAlchemyBroadcastRepository,
    SqlAlchemyMessageTemplateRepository,
)
from src.application.create_message_template_use_case import (
    CreateMessageTemplateDTO,
    CreateMessageTemplateUseCase,
)
from src.application.list_message_templates_use_case import ListMessageTemplatesUseCase
from src.application.delete_message_template_use_case import DeleteMessageTemplateUseCase
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from pathlib import Path

def _get_base_dir() -> Path:
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        if (ancestor / "backend").is_dir():
            return ancestor
    # Fallback para ambiente isolado/container onde /app é a raiz
    return current.parent.parent.parent

BASE_DIR = _get_base_dir()
DEFAULT_TEMP_DIR = str(BASE_DIR / "temp_media")
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{BASE_DIR / 'auto_send.db'}"

TEMP_MEDIA_DIR = os.getenv("TEMP_MEDIA_DIR", DEFAULT_TEMP_DIR)
os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

try:
    load_telegram_credentials_from_data_dir()
except Exception as exc:
    logger.warning(f"Erro ao inicializar credenciais da Telegram API: {exc}")

# O servidor local do Telegram aceita até 2.000 MB; a API pública, 50 MB.
LOCAL_API_MAX_BYTES = 2000 * 1024 * 1024


def media_upload_limit_bytes() -> int:
    """Limite de cada arquivo de upload: MAX_MEDIA_UPLOAD_MB, ou o limite do Telegram em uso."""
    try:
        configured_mb = int(os.getenv("MAX_MEDIA_UPLOAD_MB", ""))
    except ValueError:
        configured_mb = 0
    if configured_mb > 0:
        return configured_mb * 1024 * 1024
    if os.getenv("TELEGRAM_API_ID", "").strip() and os.getenv("TELEGRAM_API_HASH", "").strip():
        return LOCAL_API_MAX_BYTES
    return PUBLIC_API_MAX_BYTES


def read_upload_header(upload: UploadFile) -> bytes:
    """Primeiros bytes do upload, para conferir a assinatura, sem consumir o arquivo."""
    header = upload.file.read(16)
    upload.file.seek(0)
    return header

DB_PATH = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
engine = create_async_engine(DB_PATH, echo=False)

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()

session_factory = async_sessionmaker(engine, expire_on_commit=False)

profile_repo = SqlAlchemyProfileRepository(session_factory)
channel_repo = SqlAlchemyChannelRepository(session_factory)
broadcast_repo = SqlAlchemyBroadcastRepository(session_factory)
message_template_repo = SqlAlchemyMessageTemplateRepository(session_factory)
telegram_gateway = TelegramGatewayHttp()

scheduler_service = AutomationSchedulerService(
    broadcast_repo=broadcast_repo,
    profile_repo=profile_repo,
    telegram_gateway=telegram_gateway,
)

async def init_db(target_engine=None, migration_steps: tuple[MigrationStep, ...] = MIGRATIONS) -> None:
    """Garante a criação de todas as tabelas no SQLite e aplica migrações numeradas com backup (#24)."""
    eng = target_engine or engine
    db_file = sqlite_file_from_url(str(eng.url))
    had_existing_tables = has_user_tables(db_file) if db_file is not None else False

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if db_file is not None:
        run_pending_migrations(
            db_file,
            steps=migration_steps,
            had_existing_tables=had_existing_tables,
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia Telegram Bot API local se binário estiver disponível
    try:
        if telegram_process_manager.start(gateway=telegram_gateway):
            telegram_gateway.base_url = f"http://127.0.0.1:{telegram_process_manager.port}"
    except Exception as exc:
        logger.warning(f"Não foi possível iniciar Telegram Bot API local: {exc}")

    # Inicializa tabelas SQLite
    await init_db()
    scheduler_service.start()
    await scheduler_service.reconcile_due_broadcasts()
    try:
        yield
    finally:
        scheduler_service.shutdown(wait=False)
        try:
            telegram_process_manager.stop()
        except Exception as exc:
            logger.warning(f"Erro ao finalizar Telegram Bot API local: {exc}")

def _resolve_app_version() -> str:
    try:
        import tomllib
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.is_file():
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("auto-send-backend")
    except Exception:
        pass
    return "0.6.0"

app = FastAPI(title="Auto-Send Multi-Bot API", version=_resolve_app_version(), lifespan=lifespan)

def allowed_hosts(extra: str) -> set[str]:
    """Nomes pelos quais a API aceita ser chamada: loopback, mais os de ALLOWED_HOSTS (proxy reverso, VPS)."""
    return {"127.0.0.1", "localhost", "[::1]"} | {h.strip().lower() for h in extra.split(",") if h.strip()}


cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()]

ALLOWED_HOSTS = allowed_hosts(os.getenv("ALLOWED_HOSTS", ""))


@app.middleware("http")
async def reject_untrusted_host(request: Request, call_next):
    # Anti DNS rebinding (#36): uma página maliciosa pode fazer o navegador chamar 127.0.0.1 com o próprio domínio
    # no Host. O TrustedHostMiddleware do Starlette responde em texto puro; aqui o erro segue o {"detail"} da API.
    parsed = parse_host_header(request.headers.get("host"))
    if parsed is None or parsed.host.lower() not in ALLOWED_HOSTS:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Invalid host header"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas de Request/Response
class ErrorResponse(BaseModel):
    detail: Union[str, List[Any]]

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str

class OpenDataDirResponse(BaseModel):
    path: str
    opened: bool

class TelegramApiConfigResponse(BaseModel):
    configured: bool
    api_id: str
    has_api_hash: bool
    max_upload_mb: int
    env_file_path: str

class UpdateTelegramApiConfigRequest(BaseModel):
    api_id: str = Field(..., description="API ID from my.telegram.org")
    api_hash: str = Field(..., description="API Hash from my.telegram.org")

    @field_validator("api_id", "api_hash")
    @classmethod
    def validate_characters(cls, v: str) -> str:
        if "\x00" in v or "\r" in v or "\n" in v:
            raise ValueError("Value cannot contain null bytes or control characters")
        return v.strip()

class ProfileCreateRequest(BaseModel):
    name: str
    bot_token: str
    avatar_url: Optional[str] = None

class ProfileResponse(BaseModel):
    id: str
    name: str
    bot_username: str
    avatar_url: Optional[str] = None
    is_active: bool

class ProfileListItemResponse(ProfileResponse):
    created_at: str

class DeleteResourceResponse(BaseModel):
    message: str
    id: str

class MessageTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1, max_length=4096)
    button_text: Optional[str] = Field(None, max_length=100)
    button_url: Optional[str] = Field(None, max_length=500)

    @field_validator("name", "text", "button_text", "button_url")
    @classmethod
    def reject_null_bytes(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "\x00" in v:
            raise ValueError("Null bytes are not allowed")
        return v

class MessageTemplateResponse(BaseModel):
    id: str
    profile_id: str
    name: str
    text: str
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    created_at: str
    updated_at: str

class ChannelCreateRequest(BaseModel):
    title: str
    chat_id: str
    invite_link: Optional[str] = ""

class ChannelCreateResponse(BaseModel):
    id: str
    profile_id: str
    title: str
    chat_id: str
    invite_link: str

class ChannelListItemResponse(ChannelCreateResponse):
    is_active: bool

class ChannelUpdateRequest(BaseModel):
    name: str
    telegram_channel_id: str

class ChannelUpdateResponse(BaseModel):
    id: str
    profile_id: str
    name: str
    title: str
    telegram_channel_id: str
    chat_id: str

class BroadcastPatchRequest(BaseModel):
    text: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    target_channel_ids: Optional[List[str]] = None

class EditLockResponse(BaseModel):
    id: str
    status: str
    edit_locked_until: Optional[str] = None
    cancelled: bool = False

class ChannelDeliveryResultResponse(BaseModel):
    chat_id: str
    delivered: bool
    failure_category: Optional[str] = None
    detail: Optional[str] = None


class BroadcastHistoryItemResponse(BaseModel):
    id: str
    profile_id: str
    text: str
    status: str
    channels_count: int
    scheduled_at: Optional[str] = None
    created_at: str
    delivery_results: List[ChannelDeliveryResultResponse] = []

class BroadcastProgressResponse(BaseModel):
    tracking_id: str
    stage: str
    percent: int
    sent_bytes: int
    total_bytes: int
    status: str
    created_at: Optional[float] = None
    updated_at: Optional[float] = None

class ScheduledBroadcastCreateResponse(BaseModel):
    broadcast_id: str
    status: str
    scheduled_at: str
    channels_count: int
    dispatched_count: int

class ImmediateBroadcastCreateResponse(BaseModel):
    broadcast_id: str
    status: str
    dispatched_count: int
    total_targets: int
    errors: List[str]
    delivery_results: List[ChannelDeliveryResultResponse] = []

class BroadcastMediaResponse(BaseModel):
    media_type: str
    file_size: Optional[int] = None

class BroadcastButtonResponse(BaseModel):
    text: str
    url: str

class ScheduledBroadcastResponse(BaseModel):
    id: str
    profile_id: str
    target_channel_ids: List[str]
    text: str
    media: Optional[BroadcastMediaResponse] = None
    button: Optional[BroadcastButtonResponse] = None
    status: str
    scheduled_at: Optional[str] = None
    created_at: Optional[str] = None

class CancelBroadcastResponse(BaseModel):
    id: str
    status: str
    message: str


class AffectedBroadcastItemResponse(BaseModel):
    id: str
    text_preview: str
    scheduled_at: Optional[str] = None
    status: str
    target_channel_ids: List[str]


class AffectedBroadcastsResponse(BaseModel):
    will_be_cancelled: List[AffectedBroadcastItemResponse]
    will_lose_target: List[AffectedBroadcastItemResponse]
    in_flight_count: int


def _cleanup_broadcast_media(broadcast: BroadcastMessage) -> None:
    if broadcast.media:
        for path in (broadcast.media.file_path, broadcast.media.thumbnail_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _to_affected_item(b: BroadcastMessage) -> dict:
    preview = (b.text or "").strip().replace("\n", " ")
    if len(preview) > 60:
        preview = preview[:60] + "…"
    return {
        "id": b.id,
        "text_preview": preview,
        "scheduled_at": _format_datetime_utc(b.scheduled_at),
        "status": b.status.value,
        "target_channel_ids": list(b.target_channel_ids),
    }

_ERR_400 = {400: {"model": ErrorResponse, "description": "External rule or Telegram validation failed"}}
_ERR_404 = {404: {"model": ErrorResponse, "description": "Resource not found"}}
_ERR_409 = {409: {"model": ErrorResponse, "description": "Resource conflict (e.g. channel already registered)"}}
_ERR_413 = {413: {"model": ErrorResponse, "description": "Media file exceeds upload limit"}}
_ERR_422 = {422: {"model": ErrorResponse, "description": "Invalid payload or forbidden state transition"}}
_ERR_503 = {503: {"model": ErrorResponse, "description": "Could not reach Telegram, try again"}}

def get_chat_discovery_gateway() -> IChatDiscoveryGateway:
    return telegram_gateway

@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check():
    return {"status": "healthy", "app": APP_IDENTIFIER, "version": app.version}

@app.post("/api/v1/system/open-data-dir", response_model=OpenDataDirResponse)
async def open_system_data_dir():
    data_dir = resolve_data_dir(default_db_url=DB_PATH)
    opened = open_data_directory(data_dir)
    return {"path": str(data_dir), "opened": opened}

@app.get("/api/v1/system/telegram-api-config", response_model=TelegramApiConfigResponse)
async def get_system_telegram_api_config():
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    configured = bool(api_id and api_hash)
    max_mb = media_upload_limit_bytes() // (1024 * 1024)
    env_path = str(get_env_file_path())
    return TelegramApiConfigResponse(
        configured=configured,
        api_id=api_id,
        has_api_hash=bool(api_hash),
        max_upload_mb=max_mb,
        env_file_path=env_path,
    )

@app.post(
    "/api/v1/system/telegram-api-config",
    response_model=TelegramApiConfigResponse,
    responses={**_ERR_422},
)
async def update_system_telegram_api_config(req: UpdateTelegramApiConfigRequest):
    save_telegram_credentials_to_data_dir(req.api_id, req.api_hash)
    try:
        telegram_process_manager.stop()
        if req.api_id.strip() and req.api_hash.strip():
            if telegram_process_manager.start(gateway=telegram_gateway):
                telegram_gateway.base_url = f"http://127.0.0.1:{telegram_process_manager.port}"
    except Exception as exc:
        logger.warning(f"Erro ao reiniciar Telegram Bot API local: {exc}")

    return await get_system_telegram_api_config()

@app.get("/api/v1/profiles", response_model=List[ProfileListItemResponse])
async def list_profiles():
    profiles = await profile_repo.list_all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "bot_username": m.credentials.bot_username,
            "avatar_url": m.avatar_url,
            "is_active": m.is_active,
            "created_at": m.created_at.isoformat(),
        }
        for m in profiles
    ]

@app.post(
    "/api/v1/profiles",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileResponse,
    responses={**_ERR_400, **_ERR_422},
)
async def create_profile(req: ProfileCreateRequest):
    try:
        # Validação do Bot no Telegram
        bot_info = await telegram_gateway.validate_bot_token(req.bot_token)
        bot_username = bot_info.get("username", "")

        creds = BotCredentials(token=req.bot_token, bot_username=bot_username)
        profile = Profile(
            id=str(uuid.uuid4()),
            name=req.name,
            credentials=creds,
            avatar_url=req.avatar_url,
        )
        await profile_repo.save(profile)
        return {
            "id": profile.id,
            "name": profile.name,
            "bot_username": bot_username,
            "avatar_url": profile.avatar_url,
            "is_active": profile.is_active,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact_bot_token(str(e), bot_token=req.bot_token),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_bot_token(str(e), bot_token=req.bot_token),
        )

@app.put(
    "/api/v1/profiles/{profile_id}",
    response_model=ProfileResponse,
    responses={**_ERR_400, **_ERR_404, **_ERR_422},
)
async def update_profile(profile_id: str, req: ProfileCreateRequest):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    try:
        # Se o token mudou, revalida no Telegram
        bot_username = profile.credentials.bot_username
        if req.bot_token != profile.credentials.token:
            bot_info = await telegram_gateway.validate_bot_token(req.bot_token)
            bot_username = bot_info.get("username", "")

        profile.name = req.name
        profile.credentials = BotCredentials(token=req.bot_token, bot_username=bot_username)
        if req.avatar_url is not None:
            profile.avatar_url = req.avatar_url

        await profile_repo.save(profile)
        return {
            "id": profile.id,
            "name": profile.name,
            "bot_username": bot_username,
            "avatar_url": profile.avatar_url,
            "is_active": profile.is_active,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact_bot_token(str(e), bot_token=req.bot_token),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_bot_token(str(e), bot_token=req.bot_token),
        )

@app.get(
    "/api/v1/profiles/{profile_id}/affected-broadcasts",
    response_model=AffectedBroadcastsResponse,
    responses=_ERR_404,
)
async def get_profile_affected_broadcasts(profile_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    all_broadcasts = await broadcast_repo.list_by_profile(profile_id)
    in_flight_count = sum(1 for b in all_broadcasts if b.status == BroadcastStatus.DISPATCHING)
    pending = [b for b in all_broadcasts if b.is_pending_or_scheduled()]
    pending.sort(key=lambda b: (b.scheduled_at or b.created_at))
    return {
        "will_be_cancelled": [_to_affected_item(b) for b in pending],
        "will_lose_target": [],
        "in_flight_count": in_flight_count,
    }


@app.delete(
    "/api/v1/profiles/{profile_id}",
    response_model=DeleteResourceResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def delete_profile(profile_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    all_broadcasts = await broadcast_repo.list_by_profile(profile_id)
    if any(b.status == BroadcastStatus.DISPATCHING for b in all_broadcasts):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="There is a broadcast currently dispatching. Wait for it to finish and try again.",
        )

    for b in all_broadcasts:
        if b.is_pending_or_scheduled():
            b.cancel()
            scheduler_service.cancel_scheduled_broadcast(b.id)
            _cleanup_broadcast_media(b)
            await broadcast_repo.save(b)

    await profile_repo.delete(profile_id)
    return {"message": "Profile deleted successfully", "id": profile_id}

@app.get("/api/v1/profiles/{profile_id}/channels", response_model=List[ChannelListItemResponse])
async def list_channels(profile_id: str):
    channels = await channel_repo.list_by_profile(profile_id)
    return [
        {
            "id": c.id,
            "profile_id": c.profile_id,
            "title": c.title,
            "chat_id": c.chat_id,
            "invite_link": c.invite_link,
            "is_active": c.is_active,
        }
        for c in channels
    ]

@app.post(
    "/api/v1/profiles/{profile_id}/channels",
    status_code=status.HTTP_201_CREATED,
    response_model=ChannelCreateResponse,
    responses={**_ERR_400, **_ERR_404, **_ERR_409, **_ERR_422, **_ERR_503},
)
async def create_channel(
    profile_id: str,
    req: ChannelCreateRequest,
    gateway: IChatDiscoveryGateway = Depends(get_chat_discovery_gateway),
):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    existing_channels = await channel_repo.list_by_profile(profile_id)
    if any(c.chat_id == req.chat_id for c in existing_channels):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Channel already registered for this profile",
        )

    try:
        channel = Channel(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            title=req.title,
            chat_id=req.chat_id,
            invite_link=req.invite_link or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        await gateway.ensure_bot_can_post(profile.credentials.token, channel.chat_id)
    except BotNotChannelAdminError:
        raise HTTPException(status_code=400, detail="Bot is not administrator in the channel")
    except (TelegramUnavailableError, CircuitBreakerOpenException):
        raise HTTPException(status_code=503, detail="Could not reach Telegram, try again")

    await channel_repo.save(channel)
    return {
        "id": channel.id,
        "profile_id": channel.profile_id,
        "title": channel.title,
        "chat_id": channel.chat_id,
        "invite_link": channel.invite_link,
    }


@app.get(
    "/api/v1/channels/{channel_id}/affected-broadcasts",
    response_model=AffectedBroadcastsResponse,
    responses=_ERR_404,
)
async def get_channel_affected_broadcasts(channel_id: str):
    channel = await channel_repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    all_broadcasts = await broadcast_repo.list_by_profile(channel.profile_id)
    in_flight_count = sum(
        1
        for b in all_broadcasts
        if b.status == BroadcastStatus.DISPATCHING and channel.chat_id in b.target_channel_ids
    )
    will_be_cancelled = []
    will_lose_target = []
    pending = [
        b
        for b in all_broadcasts
        if b.is_pending_or_scheduled() and channel.chat_id in b.target_channel_ids
    ]
    pending.sort(key=lambda b: (b.scheduled_at or b.created_at))
    for b in pending:
        remaining = [cid for cid in b.target_channel_ids if cid != channel.chat_id]
        if not remaining:
            will_be_cancelled.append(_to_affected_item(b))
        else:
            will_lose_target.append(_to_affected_item(b))
    return {
        "will_be_cancelled": will_be_cancelled,
        "will_lose_target": will_lose_target,
        "in_flight_count": in_flight_count,
    }


@app.put(
    "/api/v1/channels/{channel_id}",
    response_model=ChannelUpdateResponse,
    responses={**_ERR_400, **_ERR_404, **_ERR_409, **_ERR_422, **_ERR_503},
)
async def update_channel(
    channel_id: str,
    req: ChannelUpdateRequest,
    gateway: IChatDiscoveryGateway = Depends(get_chat_discovery_gateway),
):
    channel = await channel_repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    import re
    chat_id_pattern = r"^-100\d{9,}$"
    if not re.match(chat_id_pattern, req.telegram_channel_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)",
        )

    old_chat_id = channel.chat_id
    if req.telegram_channel_id != old_chat_id:
        existing_channels = await channel_repo.list_by_profile(channel.profile_id)
        if any(c.id != channel_id and c.chat_id == req.telegram_channel_id for c in existing_channels):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Channel already registered for this profile",
            )
        all_broadcasts = await broadcast_repo.list_by_profile(channel.profile_id)
        if any(
            b.status == BroadcastStatus.DISPATCHING and old_chat_id in b.target_channel_ids
            for b in all_broadcasts
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="There is a broadcast currently dispatching. Wait for it to finish and try again.",
            )

        profile = await profile_repo.get_by_id(channel.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        try:
            await gateway.ensure_bot_can_post(profile.credentials.token, req.telegram_channel_id)
        except BotNotChannelAdminError:
            raise HTTPException(status_code=400, detail="Bot is not administrator in the channel")
        except (TelegramUnavailableError, CircuitBreakerOpenException):
            raise HTTPException(status_code=503, detail="Could not reach Telegram, try again")

        for b in all_broadcasts:
            if b.is_pending_or_scheduled() and b.replace_target_channel(old_chat_id, req.telegram_channel_id):
                await broadcast_repo.save(b)

    channel.title = req.name
    channel.chat_id = req.telegram_channel_id
    await channel_repo.save(channel)
    return {
        "id": channel.id,
        "profile_id": channel.profile_id,
        "name": channel.title,
        "title": channel.title,
        "telegram_channel_id": channel.chat_id,
        "chat_id": channel.chat_id,
    }

@app.delete(
    "/api/v1/channels/{channel_id}",
    response_model=DeleteResourceResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def delete_channel(channel_id: str):
    channel = await channel_repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    all_broadcasts = await broadcast_repo.list_by_profile(channel.profile_id)
    if any(
        b.status == BroadcastStatus.DISPATCHING and channel.chat_id in b.target_channel_ids
        for b in all_broadcasts
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="There is a broadcast currently dispatching. Wait for it to finish and try again.",
        )

    for b in all_broadcasts:
        if b.is_pending_or_scheduled() and b.remove_target_channel(channel.chat_id):
            if b.status == BroadcastStatus.CANCELLED:
                scheduler_service.cancel_scheduled_broadcast(b.id)
                _cleanup_broadcast_media(b)
            await broadcast_repo.save(b)

    await channel_repo.delete(channel_id)
    return {"message": "Channel deleted successfully", "id": channel_id}


@app.post(
    "/api/v1/profiles/{profile_id}/templates",
    response_model=MessageTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**_ERR_400, **_ERR_404, **_ERR_422},
)
async def create_message_template(profile_id: str, req: MessageTemplateCreateRequest):
    try:
        dto = CreateMessageTemplateDTO(
            profile_id=profile_id,
            name=req.name,
            text=req.text,
            button_text=req.button_text,
            button_url=req.button_url,
        )
        use_case = CreateMessageTemplateUseCase(message_template_repo, profile_repo)
        template = await use_case.execute(dto)
        return {
            "id": template.id,
            "profile_id": template.profile_id,
            "name": template.name,
            "text": template.text,
            "button_text": template.button_text,
            "button_url": template.button_url,
            "created_at": template.created_at.isoformat(),
            "updated_at": template.updated_at.isoformat(),
        }
    except ProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.get(
    "/api/v1/profiles/{profile_id}/templates",
    response_model=List[MessageTemplateResponse],
    responses=_ERR_404,
)
async def list_message_templates(profile_id: str):
    try:
        use_case = ListMessageTemplatesUseCase(message_template_repo, profile_repo)
        templates = await use_case.execute(profile_id)
        return [
            {
                "id": t.id,
                "profile_id": t.profile_id,
                "name": t.name,
                "text": t.text,
                "button_text": t.button_text,
                "button_url": t.button_url,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }
            for t in templates
        ]
    except ProfileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")


@app.delete(
    "/api/v1/profiles/{profile_id}/templates/{template_id}",
    response_model=DeleteResourceResponse,
    responses=_ERR_404,
)
async def delete_message_template(profile_id: str, template_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    use_case = DeleteMessageTemplateUseCase(message_template_repo)
    deleted = await use_case.execute(template_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    return {"message": "Template deleted successfully", "id": template_id}

class DiscoveredChatResponse(BaseModel):
    chat_id: str
    title: str
    type: str
    username: Optional[str] = None
    # Canal ou supergrupo (-100...); grupo comum aparece, mas não pode ser vinculado.
    registrable: bool

class DiscoveredChatListItem(DiscoveredChatResponse):
    already_registered: bool

class DiscoverChatsResponse(BaseModel):
    chats: List[DiscoveredChatListItem]

class ResolveChatRequest(BaseModel):
    identifier: str

_CHAT_DISCOVERY_ERRORS = {
    400: {"model": ErrorResponse, "description": "Telegram refused the request (bot without access, active webhook, rate limit or network)"},
    404: {"model": ErrorResponse, "description": "Profile not found"},
}

def _chat_response(chat: DiscoveredChat) -> dict:
    return {
        "chat_id": chat.chat_id,
        "title": chat.title,
        "type": chat.chat_type,
        "username": chat.username,
        "registrable": chat.is_registrable,
    }

@app.post(
    "/api/v1/profiles/{profile_id}/discover-chats",
    response_model=DiscoverChatsResponse,
    responses={**_CHAT_DISCOVERY_ERRORS, **_ERR_422},
)
async def discover_chats(profile_id: str, gateway: IChatDiscoveryGateway = Depends(get_chat_discovery_gateway)):
    try:
        views = await DiscoverChatsUseCase(profile_repo, channel_repo, gateway).execute(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")
    except (ChatDiscoveryError, CircuitBreakerOpenException) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"chats": [{**_chat_response(v.chat), "already_registered": v.already_registered} for v in views]}

@app.post(
    "/api/v1/profiles/{profile_id}/resolve-chat",
    response_model=DiscoveredChatResponse,
    responses={**_CHAT_DISCOVERY_ERRORS, 422: {"model": ErrorResponse, "description": "Invalid chat identifier or invite link"}},
)
async def resolve_chat(
    profile_id: str,
    req: ResolveChatRequest,
    gateway: IChatDiscoveryGateway = Depends(get_chat_discovery_gateway),
):
    try:
        chat = await ResolveChatUseCase(profile_repo, gateway).execute(profile_id, req.identifier)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (ChatDiscoveryError, CircuitBreakerOpenException) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _chat_response(chat)

def _format_legacy_channel_error(chat_id: str, res: ChannelDeliveryResult, raised_exc: bool, raw_last: Any, bot_token: str) -> str:
    err_msg = (
        redact_bot_token(raw_last, bot_token=bot_token)
        if isinstance(raw_last, str) and raw_last
        else res.detail
    )
    if raised_exc:
        return f"Error sending to {chat_id}: {res.detail or err_msg or 'Unknown error'}"
    if err_msg:
        return f"Failed to send to {chat_id}: {err_msg}"
    return f"Failed to send to {chat_id}"


async def _dispatch_and_record(
    gateway,
    bot_token: str,
    chat_id: str,
    message: BroadcastMessage,
    progress_callback=None,
    file_id: Optional[str] = None,
) -> tuple[ChannelDeliveryResult, Optional[str]]:
    raised_exc = False
    send_kwargs = {}
    if progress_callback is not None:
        send_kwargs["progress_callback"] = progress_callback
    if file_id is not None:
        send_kwargs["file_id"] = file_id
    try:
        ok = await gateway.send_broadcast(
            bot_token=bot_token,
            chat_id=chat_id,
            message=message,
            **send_kwargs,
        )
    except CircuitBreakerOpenException as exc:
        raised_exc = True
        res = ChannelDeliveryResult.failure(
            chat_id,
            category=DeliveryFailureCategory.TELEGRAM_UNAVAILABLE,
            detail=redact_bot_token(str(exc), bot_token=bot_token),
        )
        return res, _format_legacy_channel_error(chat_id, res, raised_exc, None, bot_token)
    except Exception as exc:
        import httpx as _httpx
        raised_exc = True
        if isinstance(exc, _httpx.RequestError):
            res = ChannelDeliveryResult.failure(
                chat_id,
                category=DeliveryFailureCategory.TELEGRAM_UNAVAILABLE,
                detail=redact_bot_token(str(exc), bot_token=bot_token) or f"Network error ({type(exc).__name__})",
            )
        else:
            res = ChannelDeliveryResult.failure(
                chat_id,
                category=DeliveryFailureCategory.OTHER,
                detail=redact_bot_token(str(exc), bot_token=bot_token),
            )
        return res, _format_legacy_channel_error(chat_id, res, raised_exc, None, bot_token)

    if ok:
        return ChannelDeliveryResult.success(chat_id), None

    from src.infrastructure.telegram_gateway_http import classify_telegram_error
    raw_cat = getattr(gateway, "last_failure_category", None)
    raw_detail = getattr(gateway, "last_failure_detail", None)
    raw_error = getattr(gateway, "last_error", None)

    detail: Optional[str] = None
    if isinstance(raw_detail, str) and raw_detail:
        detail = redact_bot_token(raw_detail, bot_token=bot_token)
    elif isinstance(raw_error, str) and raw_error:
        detail = redact_bot_token(raw_error, bot_token=bot_token)

    if isinstance(raw_cat, DeliveryFailureCategory):
        category = raw_cat
    elif detail:
        category, _ = classify_telegram_error(None, detail, bot_token=bot_token)
    else:
        category = DeliveryFailureCategory.OTHER

    res = ChannelDeliveryResult.failure(chat_id, category=category, detail=detail)
    return res, _format_legacy_channel_error(chat_id, res, False, raw_error, bot_token)
def _serialize_delivery_results(results: List[ChannelDeliveryResult]) -> List[dict]:
    return [
        {
            "chat_id": r.chat_id,
            "delivered": r.delivered,
            "failure_category": r.failure_category.value if r.failure_category else None,
            "detail": r.detail,
        }
        for r in results
    ]


@app.get(
    "/api/v1/profiles/{profile_id}/broadcasts",
    response_model=List[BroadcastHistoryItemResponse],
)
async def list_profile_broadcasts(profile_id: str):
    broadcasts = await broadcast_repo.list_by_profile(profile_id)
    return [
        {
            "id": b.id,
            "profile_id": b.profile_id,
            "text": b.text,
            "status": b.status.value,
            "channels_count": len(b.target_channel_ids),
            "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
            "created_at": b.created_at.isoformat(),
            "delivery_results": _serialize_delivery_results(b.delivery_results),
        }
        for b in broadcasts
    ]

UPLOAD_PROGRESS_TTL_SECONDS = 1800
UPLOAD_PROGRESS_MAX_ITEMS = 1000

upload_progress_tracker = UploadProgressStore(
    ttl_seconds=UPLOAD_PROGRESS_TTL_SECONDS,
    max_items=UPLOAD_PROGRESS_MAX_ITEMS,
)
progress_tracker = upload_progress_tracker

def update_progress(
    tracking_id: str,
    *,
    stage: str = "uploading_to_telegram",
    percent: int = 0,
    sent_bytes: int = 0,
    total_bytes: int = 0,
    status: str = "in_progress",
) -> None:
    now = time.time()
    existing = upload_progress_tracker.get(tracking_id, {})
    created_at = existing.get("created_at", now)
    upload_progress_tracker[tracking_id] = {
        "tracking_id": tracking_id,
        "stage": stage,
        "percent": percent,
        "sent_bytes": sent_bytes,
        "total_bytes": total_bytes,
        "status": status,
        "created_at": created_at,
        "updated_at": now,
    }

@app.get(
    "/api/v1/broadcasts/progress/{tracking_id}",
    response_model=BroadcastProgressResponse,
    responses=_ERR_404,
)
async def get_broadcast_progress(tracking_id: str):
    if tracking_id not in upload_progress_tracker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking ID not found",
        )
    return upload_progress_tracker[tracking_id]

def extract_mp4_metadata(file_path: str) -> dict:
    import struct
    meta = {"duration": None, "width": None, "height": None}
    try:
        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                size, name = struct.unpack(">I4s", header)
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0] - 8
                elif size == 0:
                    size = file_size - f.tell() + 8
                if size < 8:
                    break
                if name == b"moov":
                    moov_data = f.read(size - 8)
                    mvhd_idx = moov_data.find(b"mvhd")
                    if mvhd_idx != -1 and len(moov_data) >= mvhd_idx + 8:
                        version = moov_data[mvhd_idx + 4]
                        if version == 0 and len(moov_data) >= mvhd_idx + 24:
                            timescale, duration = struct.unpack(">II", moov_data[mvhd_idx + 16 : mvhd_idx + 24])
                        elif version != 0 and len(moov_data) >= mvhd_idx + 36:
                            timescale, duration = struct.unpack(">IQ", moov_data[mvhd_idx + 24 : mvhd_idx + 36])
                        else:
                            timescale, duration = 0, 0
                        if timescale > 0:
                            meta["duration"] = int(duration / timescale)

                    # Varre as caixas tkhd para encontrar a faixa de vídeo e aplicar rotação de matriz
                    tkhd_idx = 0
                    while True:
                        tkhd_idx = moov_data.find(b"tkhd", tkhd_idx)
                        if tkhd_idx == -1:
                            break
                        payload_start = tkhd_idx + 4
                        if len(moov_data) >= payload_start + 1:
                            ver = moov_data[payload_start]
                            matrix_offset = payload_start + (40 if ver == 0 else 52)
                            if len(moov_data) >= matrix_offset + 44:
                                matrix = struct.unpack(">9i", moov_data[matrix_offset : matrix_offset + 36])
                                w, h = struct.unpack(">II", moov_data[matrix_offset + 36 : matrix_offset + 44])
                                width = int(w >> 16)
                                height = int(h >> 16)
                                if matrix[1] != 0 or matrix[3] != 0:
                                    width, height = height, width
                                if width > 0 and height > 0:
                                    meta["width"] = width
                                    meta["height"] = height
                                    break
                        tkhd_idx += 4
                    break
                else:
                    f.seek(size - 8, 1)
    except Exception:
        pass
    return meta


def normalize_video_dimensions(
    width: Optional[int], height: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    return width, height


@app.post(
    "/api/v1/broadcasts",
    status_code=status.HTTP_201_CREATED,
    response_model=Union[ScheduledBroadcastCreateResponse, ImmediateBroadcastCreateResponse],
    responses={**_ERR_404, **_ERR_413, **_ERR_422},
)
async def create_broadcast(
    profile_id: str = Form(...),
    target_channel_ids: str = Form(...), # JSON string lista de chat_ids
    text: Optional[str] = Form(""),
    button_text: Optional[str] = Form(None),
    button_url: Optional[str] = Form(None),
    scheduled_at: Optional[str] = Form(None), # ISO-8601 string
    media_file: Optional[UploadFile] = File(None),
    thumbnail_file: Optional[UploadFile] = File(None),
    video_duration: Optional[int] = Form(None),
    video_width: Optional[int] = Form(None),
    video_height: Optional[int] = Form(None),
    tracking_id: Optional[str] = Form(None),
):
    if tracking_id:
        update_progress(
            tracking_id,
            stage="uploading_to_telegram",
            percent=0,
            sent_bytes=0,
            total_bytes=0,
            status="in_progress",
        )

    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "failed"
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        channels_list = json.loads(target_channel_ids)
        if not isinstance(channels_list, list) or len(channels_list) == 0:
            raise ValueError("target_channel_ids must be a non-empty list")
    except Exception:
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "failed"
        raise HTTPException(status_code=422, detail="Invalid target_channel_ids format")

    # Botão inline seguro
    button = None
    if button_text and button_url:
        try:
            button = InlineButton(text=button_text, url=button_url)
        except ValueError as e:
            if tracking_id:
                upload_progress_tracker[tracking_id]["status"] = "failed"
            raise HTTPException(status_code=422, detail=str(e))

    # Sanitização e validação de HTML do Telegram (Issue #16)
    try:
        text = validate_and_escape_telegram_html(text or "")
    except ValueError as e:
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "failed"
        raise HTTPException(status_code=422, detail=str(e))

    # Mídia temporária
    media_attachment = None
    temp_file_path = None
    temp_thumb_path = None

    def reject_upload(status_code: int, detail: str):
        for path in (temp_thumb_path, temp_file_path):
            if path and os.path.exists(path):
                os.remove(path)
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "failed"
        raise HTTPException(status_code=status_code, detail=detail)

    # Tipo real pela assinatura do arquivo, antes de gravar qualquer coisa em temp_media/ (#39).
    has_media = bool(media_file and media_file.filename)
    # Capa sem vídeo não tem uso: não é gravada (antes ficava esquecida em temp_media/).
    has_thumb = has_media and bool(thumbnail_file and thumbnail_file.filename)
    try:
        if has_media:
            # basename: prevenção de path traversal
            file_ext = os.path.splitext(os.path.basename(media_file.filename))[1].lower()
            media_type = classify_media(file_ext, read_upload_header(media_file))
        if has_thumb:
            thumb_ext = os.path.splitext(os.path.basename(thumbnail_file.filename))[1].lower()
            if classify_media(thumb_ext, read_upload_header(thumbnail_file)) is not MediaType.PHOTO:
                raise ValueError("Unsupported media format")
    except ValueError as e:
        reject_upload(422, str(e))

    max_bytes = media_upload_limit_bytes()
    try:
        if has_thumb:
            temp_thumb_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}_thumb{thumb_ext}")
            save_upload(thumbnail_file.file, temp_thumb_path, max_bytes)
        if has_media:
            temp_file_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}{file_ext}")
            file_size = save_upload(media_file.file, temp_file_path, max_bytes)
    except MediaTooLarge:
        reject_upload(413, f"Media file too large (limit: {max_bytes // (1024 * 1024)} MB)")

    if has_media:
        if tracking_id:
            upload_progress_tracker[tracking_id]["total_bytes"] = file_size

        final_duration = video_duration
        final_width = video_width
        final_height = video_height

        if media_type == MediaType.VIDEO:
            extracted = extract_mp4_metadata(temp_file_path)
            if extracted.get("duration"):
                final_duration = extracted["duration"]
            if extracted.get("width") and extracted.get("height"):
                final_width = extracted["width"]
                final_height = extracted["height"]

            final_width, final_height = normalize_video_dimensions(final_width, final_height)

        media_attachment = MediaAttachment(
            file_path=temp_file_path,
            media_type=media_type,
            file_size=file_size,
            duration=final_duration,
            width=final_width,
            height=final_height,
            thumbnail_path=temp_thumb_path,
        )

    parsed_scheduled_at: Optional[datetime] = None
    if scheduled_at and scheduled_at.strip():
        try:
            parsed_scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if parsed_scheduled_at.tzinfo is None:
                parsed_scheduled_at = parsed_scheduled_at.replace(tzinfo=timezone.utc)
            else:
                parsed_scheduled_at = parsed_scheduled_at.astimezone(timezone.utc)
        except Exception:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if temp_thumb_path and os.path.exists(temp_thumb_path):
                os.remove(temp_thumb_path)
            if tracking_id and tracking_id in upload_progress_tracker:
                upload_progress_tracker[tracking_id]["status"] = "failed"
                upload_progress_tracker[tracking_id]["updated_at"] = time.time()
            raise HTTPException(status_code=422, detail="Invalid scheduled_at ISO-8601 format")

        try:
            ensure_schedulable(parsed_scheduled_at, now=datetime.now(timezone.utc))
        except ValueError as schedule_error:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if temp_thumb_path and os.path.exists(temp_thumb_path):
                os.remove(temp_thumb_path)
            if tracking_id and tracking_id in upload_progress_tracker:
                upload_progress_tracker[tracking_id]["status"] = "failed"
                upload_progress_tracker[tracking_id]["updated_at"] = time.time()
            raise HTTPException(status_code=422, detail=str(schedule_error))

    broadcast = BroadcastMessage(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        target_channel_ids=channels_list,
        text=text or "",
        media=media_attachment,
        button=button,
        scheduled_at=parsed_scheduled_at,
        status=BroadcastStatus.SCHEDULED if parsed_scheduled_at else BroadcastStatus.PENDING,
    )
    await broadcast_repo.save(broadcast)

    # Cenário de Agendamento Futuro
    if parsed_scheduled_at:
        scheduler_service.schedule_broadcast(broadcast.id, parsed_scheduled_at)
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "completed"
            upload_progress_tracker[tracking_id]["percent"] = 100
            upload_progress_tracker[tracking_id]["sent_bytes"] = upload_progress_tracker[tracking_id]["total_bytes"]
        return {
            "broadcast_id": broadcast.id,
            "status": "SCHEDULED",
            "scheduled_at": parsed_scheduled_at.isoformat(),
            "channels_count": len(channels_list),
            "dispatched_count": 0,
        }

    # Cenário de Disparo Imediato
    dispatched_count = 0
    errors = []
    delivery_results: List[ChannelDeliveryResult] = []
    try:
        broadcast.status = BroadcastStatus.DISPATCHING
        await broadcast_repo.save(broadcast)

        total_channels = len(channels_list)
        cached_file_id: Optional[str] = None
        for idx, chat_id in enumerate(channels_list):
            channel_cb = None
            if tracking_id and media_attachment and not cached_file_id:
                def channel_progress_cb(sent_bytes: int, total_bytes: int):
                    if tracking_id in upload_progress_tracker:
                        ratio = (sent_bytes / total_bytes) if total_bytes > 0 else 0
                        pct = int(ratio * 100)
                        upload_progress_tracker[tracking_id]["percent"] = min(100, max(0, pct))
                        upload_progress_tracker[tracking_id]["sent_bytes"] = sent_bytes
                        upload_progress_tracker[tracking_id]["total_bytes"] = total_bytes
                        if sent_bytes >= total_bytes:
                            upload_progress_tracker[tracking_id]["stage"] = "processing_by_telegram"
                            upload_progress_tracker[tracking_id]["percent"] = 100
                        else:
                            upload_progress_tracker[tracking_id]["stage"] = "uploading_to_telegram"
                channel_cb = channel_progress_cb

            res, legacy_err = await _dispatch_and_record(
                gateway=telegram_gateway,
                bot_token=profile.credentials.token,
                chat_id=chat_id,
                message=broadcast,
                progress_callback=channel_cb,
                file_id=cached_file_id,
            )
            delivery_results.append(res)
            if res.delivered:
                dispatched_count += 1
                if not cached_file_id:
                    cached_file_id = getattr(telegram_gateway, "last_uploaded_file_id", None)
            elif legacy_err:
                errors.append(legacy_err)

            if tracking_id and not media_attachment:
                pct = int(((idx + 1) / total_channels) * 100)
                tot = upload_progress_tracker[tracking_id]["total_bytes"]
                upload_progress_tracker[tracking_id]["percent"] = pct
                upload_progress_tracker[tracking_id]["sent_bytes"] = int(tot * (pct / 100))

        broadcast.finish_dispatch_with_results(delivery_results)
        await broadcast_repo.save(broadcast)
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "completed"
            upload_progress_tracker[tracking_id]["percent"] = 100
            upload_progress_tracker[tracking_id]["sent_bytes"] = upload_progress_tracker[tracking_id]["total_bytes"]
    except Exception:
        if tracking_id:
            upload_progress_tracker[tracking_id]["status"] = "failed"
        raise
    finally:
        # Invariante de ciclo de vida: descarte imediato do arquivo temporário após disparo
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if temp_thumb_path and os.path.exists(temp_thumb_path):
            os.remove(temp_thumb_path)

    return {
        "broadcast_id": broadcast.id,
        "status": broadcast.status.value,
        "dispatched_count": dispatched_count,
        "total_targets": len(channels_list),
        "errors": errors,
        "delivery_results": _serialize_delivery_results(broadcast.delivery_results),
    }

def _format_datetime_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _serialize_scheduled_broadcast(b: BroadcastMessage) -> dict:
    return {
        "id": b.id,
        "profile_id": b.profile_id,
        "target_channel_ids": b.target_channel_ids,
        "text": b.text,
        "media": {
            "media_type": b.media.media_type.value,
            "file_size": b.media.file_size,
        } if b.media else None,
        "button": {
            "text": b.button.text,
            "url": b.button.url,
        } if b.button else None,
        "status": b.status.value,
        "scheduled_at": _format_datetime_utc(b.scheduled_at),
        "created_at": _format_datetime_utc(b.created_at),
    }


@app.get(
    "/api/v1/profiles/{profile_id}/scheduled-broadcasts",
    response_model=List[ScheduledBroadcastResponse],
    responses=_ERR_404,
)
async def list_profile_scheduled_broadcasts(profile_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    broadcasts = await broadcast_repo.get_scheduled_by_profile(profile_id)
    return [_serialize_scheduled_broadcast(b) for b in broadcasts]

@app.delete(
    "/api/v1/broadcasts/{broadcast_id}/cancel",
    response_model=CancelBroadcastResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def cancel_broadcast(broadcast_id: str):
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    try:
        broadcast.cancel()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Remove o agendamento no APScheduler
    scheduler_service.cancel_scheduled_broadcast(broadcast.id)

    # Remove arquivos de mídia temporária (principal e capa) se existirem
    if broadcast.media:
        for path in (broadcast.media.file_path, broadcast.media.thumbnail_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    await broadcast_repo.save(broadcast)
    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "message": "Broadcast successfully cancelled and resources released",
    }


@app.post(
    "/api/v1/broadcasts/{broadcast_id}/dispatch-now",
    response_model=ImmediateBroadcastCreateResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def dispatch_broadcast_now(broadcast_id: str):
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    profile = await profile_repo.get_by_id(broadcast.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        broadcast.start_dispatch()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    scheduler_service.cancel_scheduled_broadcast(broadcast.id)
    await broadcast_repo.save(broadcast)

    dispatched_count = 0
    errors: List[str] = []
    delivery_results: List[ChannelDeliveryResult] = []
    try:
        for chat_id in broadcast.target_channel_ids:
            res, legacy_err = await _dispatch_and_record(
                gateway=telegram_gateway,
                bot_token=profile.credentials.token,
                chat_id=chat_id,
                message=broadcast,
            )
            delivery_results.append(res)
            if res.delivered:
                dispatched_count += 1
            elif legacy_err:
                errors.append(legacy_err)

        broadcast.finish_dispatch_with_results(delivery_results)
        await broadcast_repo.save(broadcast)
    finally:
        if broadcast.media:
            for path in (broadcast.media.file_path, broadcast.media.thumbnail_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    return {
        "broadcast_id": broadcast.id,
        "status": broadcast.status.value,
        "dispatched_count": dispatched_count,
        "total_targets": len(broadcast.target_channel_ids),
        "errors": errors,
        "delivery_results": _serialize_delivery_results(broadcast.delivery_results),
    }


@app.patch(
    "/api/v1/broadcasts/{broadcast_id}",
    response_model=ScheduledBroadcastResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def patch_broadcast(broadcast_id: str, req: BroadcastPatchRequest):
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if broadcast.status not in [
        BroadcastStatus.PENDING,
        BroadcastStatus.SCHEDULED,
        BroadcastStatus.MISFIRED,
    ]:
        raise HTTPException(status_code=422, detail="Cannot edit an in-flight, completed, or cancelled broadcast")

    # Validação e montagem de Button
    updated_button = broadcast.button
    if req.button_text is not None or req.button_url is not None:
        if req.button_text == "" and req.button_url == "":
            updated_button = None
        elif req.button_text is None or req.button_url is None or not req.button_text.strip() or not req.button_url.strip():
            raise HTTPException(
                status_code=422,
                detail="Both button_text and button_url are required when defining an inline button",
            )
        else:
            try:
                updated_button = InlineButton(text=req.button_text, url=req.button_url)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

    # Validação de Data/Hora (scheduled_at)
    new_run_date = None
    if req.scheduled_at is not None:
        try:
            parsed_dt = datetime.fromisoformat(req.scheduled_at.replace("Z", "+00:00"))
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid scheduled_at ISO-8601 format")

        try:
            ensure_schedulable(parsed_dt, now=datetime.now(timezone.utc))
        except ValueError as schedule_error:
            raise HTTPException(status_code=422, detail=str(schedule_error))
        new_run_date = parsed_dt

    now_utc = datetime.now(timezone.utc)
    was_edit_locked = broadcast.edit_locked_until is not None
    # Salvar no modo edição sem novo horário, depois que o horário passou, exige um horário futuro (#15).
    if (
        new_run_date is None
        and was_edit_locked
        and broadcast.scheduled_at is not None
        and broadcast.status != BroadcastStatus.MISFIRED
    ):
        try:
            ensure_schedulable(broadcast.scheduled_at, now=now_utc)
        except ValueError as schedule_error:
            raise HTTPException(status_code=422, detail=str(schedule_error))

    # Atualiza conteúdo se texto ou botão foram alterados
    updated_text = req.text if req.text is not None else broadcast.text
    try:
        broadcast.update_content(text=updated_text, button=updated_button)
        if req.target_channel_ids is not None:
            broadcast.update_target_channels(req.target_channel_ids)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Reagendamento
    if new_run_date is not None:
        try:
            broadcast.reschedule(new_run_date)
            scheduler_service.reschedule_broadcast(broadcast.id, new_run_date)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    elif was_edit_locked:
        broadcast.release_edit_lock(now_utc)
        if broadcast.scheduled_at is not None and broadcast.status in (
            BroadcastStatus.PENDING,
            BroadcastStatus.SCHEDULED,
        ):
            scheduler_service.reschedule_broadcast(broadcast.id, broadcast.scheduled_at)

    await broadcast_repo.save(broadcast)

    return _serialize_scheduled_broadcast(broadcast)


def _remove_broadcast_media_files(broadcast: BroadcastMessage) -> None:
    if broadcast.media:
        for path in (broadcast.media.file_path, broadcast.media.thumbnail_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


@app.post(
    "/api/v1/broadcasts/{broadcast_id}/edit-lock",
    response_model=EditLockResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def acquire_broadcast_edit_lock(broadcast_id: str):
    """Trava (ou renova) a edição do agendamento: o job não posta enquanto a trava vale (#15)."""
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    try:
        broadcast.acquire_edit_lock(scheduler_service._clock())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await broadcast_repo.save(broadcast)
    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "edit_locked_until": _format_datetime_utc(broadcast.edit_locked_until),
        "cancelled": False,
    }


@app.delete(
    "/api/v1/broadcasts/{broadcast_id}/edit-lock",
    response_model=EditLockResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def release_broadcast_edit_lock(broadcast_id: str):
    """Sai do modo edição sem salvar: se o horário já passou, o agendamento é cancelado (#15)."""
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    try:
        cancelled = broadcast.release_edit_lock(scheduler_service._clock())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if cancelled:
        scheduler_service.cancel_scheduled_broadcast(broadcast.id)
        _remove_broadcast_media_files(broadcast)
    elif broadcast.scheduled_at is not None and broadcast.status in (
        BroadcastStatus.PENDING,
        BroadcastStatus.SCHEDULED,
    ):
        scheduler_service.reschedule_broadcast(broadcast.id, broadcast.scheduled_at)
    await broadcast_repo.save(broadcast)
    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "edit_locked_until": None,
        "cancelled": cancelled,
    }


@app.get(
    "/api/v1/broadcasts/{broadcast_id}/media",
    responses={
        200: {
            "content": {
                "image/*": {"schema": {"type": "string", "format": "binary"}},
                "video/*": {"schema": {"type": "string", "format": "binary"}},
            },
            "description": "Media file stream for preview",
        },
        **_ERR_404,
        **_ERR_422,
    },
)
async def get_broadcast_media(broadcast_id: str):
    """Devolve o arquivo de mídia para exibição no preview sem expor caminhos internos (§9, #18)."""
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if not broadcast.media or not broadcast.media.file_path:
        raise HTTPException(status_code=404, detail="Media not found")

    file_path = os.path.abspath(broadcast.media.file_path)
    temp_dir_abs = os.path.abspath(TEMP_MEDIA_DIR)
    try:
        common = os.path.commonpath([temp_dir_abs, file_path])
        if common != temp_dir_abs:
            raise HTTPException(status_code=404, detail="Media not found")
    except ValueError:
        raise HTTPException(status_code=404, detail="Media not found")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Media not found")

    ext = os.path.splitext(file_path)[1].lower()
    media_type = "video/mp4" if broadcast.media.media_type == MediaType.VIDEO else "image/jpeg"
    if ext in (".png", ".webp", ".gif"):
        media_type = f"image/{ext[1:]}"
    elif ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={"Content-Disposition": "inline"},
    )


@app.put(
    "/api/v1/broadcasts/{broadcast_id}/media",
    response_model=ScheduledBroadcastResponse,
    responses={**_ERR_404, **_ERR_413, **_ERR_422},
)
async def replace_broadcast_media(
    broadcast_id: str,
    media_file: UploadFile = File(...),
    thumbnail_file: Optional[UploadFile] = File(None),
    video_duration: Optional[int] = Form(None),
    video_width: Optional[int] = Form(None),
    video_height: Optional[int] = Form(None),
):
    """Substitui ou adiciona mídia a um agendamento existente em modo edição (#18)."""
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if not broadcast.is_pending_or_scheduled():
        raise HTTPException(
            status_code=422,
            detail="Cannot edit media of an in-flight, completed, or cancelled broadcast",
        )

    temp_file_path = None
    temp_thumb_path = None

    def reject_upload(status_code: int, detail: str):
        for path in (temp_thumb_path, temp_file_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        raise HTTPException(status_code=status_code, detail=detail)

    has_media = bool(media_file and media_file.filename)
    if not has_media:
        raise HTTPException(status_code=422, detail="No media file provided")

    has_thumb = bool(thumbnail_file and thumbnail_file.filename)
    try:
        file_ext = os.path.splitext(os.path.basename(media_file.filename))[1].lower()
        media_type = classify_media(file_ext, read_upload_header(media_file))
        if has_thumb:
            thumb_ext = os.path.splitext(os.path.basename(thumbnail_file.filename))[1].lower()
            if classify_media(thumb_ext, read_upload_header(thumbnail_file)) is not MediaType.PHOTO:
                raise ValueError("Unsupported media format")
    except ValueError as e:
        reject_upload(422, str(e))

    max_bytes = media_upload_limit_bytes()
    try:
        if has_thumb:
            temp_thumb_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}_thumb{thumb_ext}")
            save_upload(thumbnail_file.file, temp_thumb_path, max_bytes)
        temp_file_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}{file_ext}")
        file_size = save_upload(media_file.file, temp_file_path, max_bytes)
    except MediaTooLarge:
        reject_upload(413, f"Media file too large (limit: {max_bytes // (1024 * 1024)} MB)")

    final_duration = video_duration
    final_width = video_width
    final_height = video_height

    if media_type == MediaType.VIDEO:
        extracted = extract_mp4_metadata(temp_file_path)
        if extracted.get("duration"):
            final_duration = extracted["duration"]
        if extracted.get("width") and extracted.get("height"):
            final_width = extracted["width"]
            final_height = extracted["height"]
        final_width, final_height = normalize_video_dimensions(final_width, final_height)

    new_attachment = MediaAttachment(
        file_path=temp_file_path,
        media_type=media_type,
        file_size=file_size,
        duration=final_duration,
        width=final_width,
        height=final_height,
        thumbnail_path=temp_thumb_path,
    )

    # Limpa mídia antiga no disco com segurança
    _remove_broadcast_media_files(broadcast)

    try:
        broadcast.replace_media(new_attachment)
    except ValueError as e:
        reject_upload(422, str(e))

    await broadcast_repo.save(broadcast)
    return _serialize_scheduled_broadcast(broadcast)


@app.delete(
    "/api/v1/broadcasts/{broadcast_id}/media",
    response_model=ScheduledBroadcastResponse,
    responses={**_ERR_404, **_ERR_422},
)
async def delete_broadcast_media(broadcast_id: str):
    """Remove a mídia do agendamento e apaga o arquivo temporário do servidor (#18)."""
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if not broadcast.is_pending_or_scheduled():
        raise HTTPException(
            status_code=422,
            detail="Cannot edit media of an in-flight, completed, or cancelled broadcast",
        )

    if not broadcast.media:
        raise HTTPException(status_code=404, detail="Media not found")

    _remove_broadcast_media_files(broadcast)

    try:
        broadcast.remove_media()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await broadcast_repo.save(broadcast)
    return _serialize_scheduled_broadcast(broadcast)

from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.getenv(
    "STATIC_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
)

if os.path.exists(STATIC_DIR) and os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def run_app():
    data_dir = resolve_data_dir(default_db_url=DB_PATH)
    import_legacy_data_if_needed(data_dir, Path.cwd())

    decision = resolve_startup_instance(
        data_dir,
        app.version,
        find_port_fn=lambda start, attempts: find_available_port(start, max_attempts=attempts, host="127.0.0.1"),
    )
    if decision.action == "reuse_existing":
        if decision.url:
            webbrowser.open(decision.url)
        return
    if decision.action == "abort" or decision.port is None:
        print(
            "[ERRO] Nenhuma porta livre encontrada entre 8000 e 8020 (ou inicialização cancelada).",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        asyncio.run(init_db())
    except DatabaseMigrationError as exc:
        print(
            f"[ERRO] Não foi possível atualizar o banco de dados: {exc}. "
            f"O banco permaneceu na versão {exc.previous_version} e o backup foi preservado em {data_dir}.",
            file=sys.stderr,
        )
        sys.exit(1)

    backend_port = decision.port
    browser_url = f"http://127.0.0.1:{backend_port}"
    current_pid = os.getpid()
    write_lock_pid(data_dir, current_pid)
    atexit.register(remove_lock_pid, data_dir, current_pid)

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(browser_url)

    threading.Thread(target=_open_browser, daemon=True).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=backend_port, log_level="info")
    finally:
        remove_lock_pid(data_dir, current_pid)


if __name__ == "__main__":
    run_app()
