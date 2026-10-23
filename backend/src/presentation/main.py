import json
import logging
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    InlineButton,
    MediaAttachment,
    MediaType,
    BroadcastStatus,
    ensure_schedulable,
)
from src.application.discover_chats_use_case import DiscoverChatsUseCase
from src.application.errors import ProfileNotFoundError
from src.application.resolve_chat_use_case import ResolveChatUseCase
from src.domain.channels.channel import Channel
from src.domain.channels.chat_discovery import DiscoveredChat
from src.domain.ports.chat_discovery_gateway import ChatDiscoveryError, IChatDiscoveryGateway
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.infrastructure.in_memory_repositories import (
    InMemoryChannelRepository,
    InMemoryProfileRepository,
)
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.infrastructure.resilience import CircuitBreakerOpenException
from src.infrastructure.telegram_gateway_http import TelegramGatewayHttp
import sys
import threading
import webbrowser
import uvicorn
from src.infrastructure.scheduler_service import AutomationSchedulerService
from src.infrastructure.telegram_process_manager import (
    find_available_port,
    telegram_process_manager,
)

logger = logging.getLogger(__name__)

from src.infrastructure.sqlite_repositories import (
    Base,
    SqlAlchemyProfileRepository,
    SqlAlchemyChannelRepository,
    SqlAlchemyBroadcastRepository,
)
from sqlalchemy import event, text
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
telegram_gateway = TelegramGatewayHttp()

scheduler_service = AutomationSchedulerService(
    broadcast_repo=broadcast_repo,
    profile_repo=profile_repo,
    telegram_gateway=telegram_gateway,
)

async def init_db(target_engine=None) -> None:
    """Garante a criação de todas as tabelas no banco de dados SQLite e auto-migração de colunas."""
    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if conn.dialect.name == "sqlite":
            tables_migrations = {
                "broadcasts": [
                    ("media_duration", "INTEGER"),
                    ("media_width", "INTEGER"),
                    ("media_height", "INTEGER"),
                    ("media_thumbnail_path", "VARCHAR"),
                ],
                "channels": [
                    ("invite_link", "VARCHAR DEFAULT ''"),
                    ("is_active", "BOOLEAN DEFAULT 1"),
                ],
                "profiles": [
                    ("avatar_url", "VARCHAR"),
                    ("is_active", "BOOLEAN DEFAULT 1"),
                ],
            }

            for table_name, columns in tables_migrations.items():
                res = await conn.execute(text(f"PRAGMA table_info({table_name})"))
                existing_cols = {row[1] for row in res.fetchall()}
                for col_name, col_def in columns:
                    if col_name not in existing_cols:
                        try:
                            await conn.execute(
                                text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                            )
                        except Exception:
                            pass

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

app = FastAPI(title="Auto-Send Multi-Bot API", version="0.4.0", lifespan=lifespan)

cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas de Request/Response
class ProfileCreateRequest(BaseModel):
    name: str
    bot_token: str
    avatar_url: Optional[str] = None

class ChannelCreateRequest(BaseModel):
    title: str
    chat_id: str
    invite_link: Optional[str] = ""

class ChannelUpdateRequest(BaseModel):
    name: str
    telegram_channel_id: str

class BroadcastPatchRequest(BaseModel):
    text: Optional[str] = None
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    scheduled_at: Optional[str] = None

@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/v1/profiles")
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

@app.post("/api/v1/profiles", status_code=status.HTTP_201_CREATED)
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.put("/api/v1/profiles/{profile_id}")
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.delete("/api/v1/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    
    await profile_repo.delete(profile_id)
    return {"message": "Profile deleted successfully", "id": profile_id}

@app.get("/api/v1/profiles/{profile_id}/channels")
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

@app.post("/api/v1/profiles/{profile_id}/channels", status_code=status.HTTP_201_CREATED)
async def create_channel(profile_id: str, req: ChannelCreateRequest):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    try:
        channel = Channel(
            id=str(uuid.uuid4()),
            profile_id=profile_id,
            title=req.title,
            chat_id=req.chat_id,
            invite_link=req.invite_link or "",
        )
        await channel_repo.save(channel)
        return {
            "id": channel.id,
            "profile_id": channel.profile_id,
            "title": channel.title,
            "chat_id": channel.chat_id,
            "invite_link": channel.invite_link,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.put("/api/v1/channels/{channel_id}")
async def update_channel(channel_id: str, req: ChannelUpdateRequest):
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

@app.delete("/api/v1/channels/{channel_id}")
async def delete_channel(channel_id: str):
    channel = await channel_repo.get_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_repo.delete(channel_id)
    return {"message": "Channel deleted successfully", "id": channel_id}

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
    400: {"description": "Telegram refused the request (bot without access, active webhook, rate limit or network)"},
    404: {"description": "Profile not found"},
}

def get_chat_discovery_gateway() -> IChatDiscoveryGateway:
    return telegram_gateway

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
    responses=_CHAT_DISCOVERY_ERRORS,
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
    responses={**_CHAT_DISCOVERY_ERRORS, 422: {"description": "Invalid public chat identifier"}},
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

@app.get("/api/v1/profiles/{profile_id}/broadcasts")
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
        }
        for b in broadcasts
    ]

upload_progress_tracker: dict[str, dict] = {}
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

def prune_upload_progress_tracker(max_age_seconds: int = 1800) -> int:
    now = time.time()
    expired_keys = [
        k for k, v in upload_progress_tracker.items()
        if now - v.get("updated_at", v.get("created_at", now)) > max_age_seconds
    ]
    for k in expired_keys:
        upload_progress_tracker.pop(k, None)
    return len(expired_keys)

@app.get("/api/v1/broadcasts/progress/{tracking_id}")
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


@app.post("/api/v1/broadcasts", status_code=status.HTTP_201_CREATED)
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

    # Mídia temporária
    media_attachment = None
    temp_file_path = None
    temp_thumb_path = None

    if thumbnail_file and thumbnail_file.filename:
        safe_thumb_filename = os.path.basename(thumbnail_file.filename)
        thumb_ext = os.path.splitext(safe_thumb_filename)[1].lower()
        if thumb_ext in [".jpg", ".jpeg", ".png", ".webp"]:
            temp_thumb_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}_thumb{thumb_ext}")
            with open(temp_thumb_path, "wb") as buffer:
                shutil.copyfileobj(thumbnail_file.file, buffer)

    if media_file and media_file.filename:
        # Prevenção de Path Traversal
        safe_filename = os.path.basename(media_file.filename)
        file_ext = os.path.splitext(safe_filename)[1].lower()
        if file_ext not in [".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp"]:
            if temp_thumb_path and os.path.exists(temp_thumb_path):
                os.remove(temp_thumb_path)
            if tracking_id:
                upload_progress_tracker[tracking_id]["status"] = "failed"
            raise HTTPException(status_code=422, detail="Unsupported media format")

        temp_file_path = os.path.join(TEMP_MEDIA_DIR, f"{uuid.uuid4()}{file_ext}")
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)
        
        file_size = os.path.getsize(temp_file_path)
        if tracking_id:
            upload_progress_tracker[tracking_id]["total_bytes"] = file_size

        media_type = MediaType.VIDEO if file_ext in [".mp4", ".mov"] else MediaType.PHOTO
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
    try:
        broadcast.status = BroadcastStatus.DISPATCHING
        await broadcast_repo.save(broadcast)

        total_channels = len(channels_list)
        for idx, chat_id in enumerate(channels_list):
            channel_cb = None
            if tracking_id and media_attachment:
                def channel_progress_cb(sent_bytes: int, total_bytes: int, current_idx=idx):
                    if tracking_id in upload_progress_tracker:
                        ratio = (sent_bytes / total_bytes) if total_bytes > 0 else 0
                        pct = int(((current_idx + ratio) / total_channels) * 100)
                        upload_progress_tracker[tracking_id]["percent"] = min(100, max(0, pct))
                        upload_progress_tracker[tracking_id]["sent_bytes"] = sent_bytes
                        upload_progress_tracker[tracking_id]["total_bytes"] = total_bytes
                        if sent_bytes >= total_bytes:
                            upload_progress_tracker[tracking_id]["stage"] = "processing_by_telegram"
                            upload_progress_tracker[tracking_id]["percent"] = 100
                        else:
                            upload_progress_tracker[tracking_id]["stage"] = "uploading_to_telegram"
                channel_cb = channel_progress_cb

            try:
                send_kwargs = {}
                if channel_cb is not None:
                    send_kwargs["progress_callback"] = channel_cb

                success = await telegram_gateway.send_broadcast(
                    bot_token=profile.credentials.token,
                    chat_id=chat_id,
                    message=broadcast,
                    **send_kwargs,
                )
                if success:
                    dispatched_count += 1
                else:
                    detail = getattr(telegram_gateway, "last_error", None)
                    if detail:
                        errors.append(f"Failed to send to {chat_id}: {detail}")
                    else:
                        errors.append(f"Failed to send to {chat_id}")
            except Exception as e:
                errors.append(f"Error sending to {chat_id}: {str(e)}")

            if tracking_id and not media_attachment:
                pct = int(((idx + 1) / total_channels) * 100)
                tot = upload_progress_tracker[tracking_id]["total_bytes"]
                upload_progress_tracker[tracking_id]["percent"] = pct
                upload_progress_tracker[tracking_id]["sent_bytes"] = int(tot * (pct / 100))

        broadcast.finish_dispatch(delivered=dispatched_count, total=len(channels_list))
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
    }

def _format_datetime_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

@app.get("/api/v1/profiles/{profile_id}/scheduled-broadcasts")
async def list_profile_scheduled_broadcasts(profile_id: str):
    profile = await profile_repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    broadcasts = await broadcast_repo.get_scheduled_by_profile(profile_id)
    return [
        {
            "id": b.id,
            "profile_id": b.profile_id,
            "target_channel_ids": b.target_channel_ids,
            "text": b.text,
            "media": {
                "file_path": b.media.file_path,
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
        for b in broadcasts
    ]

@app.delete("/api/v1/broadcasts/{broadcast_id}/cancel")
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

    # Remove arquivo de mídia temporária se existir
    if broadcast.media and broadcast.media.file_path:
        path = broadcast.media.file_path
        if os.path.exists(path):
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

@app.patch("/api/v1/broadcasts/{broadcast_id}")
async def patch_broadcast(broadcast_id: str, req: BroadcastPatchRequest):
    broadcast = await broadcast_repo.get_by_id(broadcast_id)
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if broadcast.status in [BroadcastStatus.DISPATCHING, BroadcastStatus.COMPLETED, BroadcastStatus.CANCELLED]:
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

    # Atualiza conteúdo se texto ou botão foram alterados
    updated_text = req.text if req.text is not None else broadcast.text
    try:
        broadcast.update_content(text=updated_text, button=updated_button)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Reagendamento
    if new_run_date is not None:
        try:
            broadcast.reschedule(new_run_date)
            scheduler_service.reschedule_broadcast(broadcast.id, new_run_date)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    await broadcast_repo.save(broadcast)

    return {
        "id": broadcast.id,
        "profile_id": broadcast.profile_id,
        "target_channel_ids": broadcast.target_channel_ids,
        "text": broadcast.text,
        "media": {
            "file_path": broadcast.media.file_path,
            "media_type": broadcast.media.media_type.value,
            "file_size": broadcast.media.file_size,
        } if broadcast.media else None,
        "button": {
            "text": broadcast.button.text,
            "url": broadcast.button.url,
        } if broadcast.button else None,
        "status": broadcast.status.value,
        "scheduled_at": _format_datetime_utc(broadcast.scheduled_at),
        "created_at": _format_datetime_utc(broadcast.created_at),
    }

from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.getenv(
    "STATIC_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
)

if os.path.exists(STATIC_DIR) and os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def run_app():
    backend_port = find_available_port(8000, max_attempts=20, host="127.0.0.1")
    if backend_port is None:
        print(
            "[ERRO] Nenhuma porta livre encontrada entre 8000 e 8020. Feche alguns programas e tente novamente.",
            file=sys.stderr,
        )
        sys.exit(1)

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{backend_port}")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=backend_port, log_level="info")


if __name__ == "__main__":
    run_app()
