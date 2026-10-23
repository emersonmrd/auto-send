from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    InlineButton,
    MediaAttachment,
    MediaType,
)
from src.domain.channels.channel import Channel
from src.domain.profiles.bot_credentials import BotCredentials
from src.domain.profiles.profile import Profile
from src.domain.ports.broadcast_repository import IBroadcastRepository
from src.domain.ports.channel_repository import IChannelRepository
from src.domain.ports.profile_repository import IProfileRepository

Base = declarative_base()

class ProfileModel(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    bot_token = Column(String, nullable=False)
    bot_username = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ChannelModel(Base):
    __tablename__ = "channels"

    id = Column(String, primary_key=True)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    title = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    invite_link = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class BroadcastModel(Base):
    __tablename__ = "broadcasts"

    id = Column(String, primary_key=True)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    target_channel_ids = Column(Text, nullable=False) # JSON encoded
    text = Column(Text, default="")
    media_file_path = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    media_file_size = Column(Integer, nullable=True)
    media_duration = Column(Integer, nullable=True)
    media_width = Column(Integer, nullable=True)
    media_height = Column(Integer, nullable=True)
    media_thumbnail_path = Column(String, nullable=True)
    button_text = Column(String, nullable=True)
    button_url = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# Repositórios SQLAlchemy com aiosqlite
class SqlAlchemyProfileRepository(IProfileRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def save(self, profile: Profile) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                existing = await session.get(ProfileModel, profile.id)
                if existing:
                    existing.name = profile.name
                    existing.bot_token = profile.credentials.token
                    existing.bot_username = profile.credentials.bot_username
                    existing.avatar_url = profile.avatar_url
                    existing.is_active = profile.is_active
                else:
                    db_obj = ProfileModel(
                        id=profile.id,
                        name=profile.name,
                        bot_token=profile.credentials.token,
                        bot_username=profile.credentials.bot_username,
                        avatar_url=profile.avatar_url,
                        is_active=profile.is_active,
                        created_at=profile.created_at,
                    )
                    session.add(db_obj)

    async def get_by_id(self, profile_id: str) -> Optional[Profile]:
        async with self.session_factory() as session:
            obj = await session.get(ProfileModel, profile_id)
            if not obj:
                return None
            return Profile(
                id=obj.id,
                name=obj.name,
                credentials=BotCredentials(token=obj.bot_token, bot_username=obj.bot_username),
                avatar_url=obj.avatar_url,
                is_active=obj.is_active,
                created_at=obj.created_at,
            )

    async def list_all(self) -> List[Profile]:
        from sqlalchemy import select
        async with self.session_factory() as session:
            res = await session.execute(select(ProfileModel).order_by(ProfileModel.created_at.desc()))
            objs = res.scalars().all()
            return [
                Profile(
                    id=obj.id,
                    name=obj.name,
                    credentials=BotCredentials(token=obj.bot_token, bot_username=obj.bot_username),
                    avatar_url=obj.avatar_url,
                    is_active=obj.is_active,
                    created_at=obj.created_at,
                )
                for obj in objs
            ]

    async def delete(self, profile_id: str) -> bool:
        from sqlalchemy import delete
        async with self.session_factory() as session:
            async with session.begin():
                # Remove broadcasts e canais vinculados ao perfil
                await session.execute(delete(BroadcastModel).where(BroadcastModel.profile_id == profile_id))
                await session.execute(delete(ChannelModel).where(ChannelModel.profile_id == profile_id))
                res = await session.execute(delete(ProfileModel).where(ProfileModel.id == profile_id))
                return res.rowcount > 0

class SqlAlchemyChannelRepository(IChannelRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def save(self, channel: Channel) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                existing = await session.get(ChannelModel, channel.id)
                if existing:
                    existing.title = channel.title
                    existing.chat_id = channel.chat_id
                    existing.invite_link = channel.invite_link
                    existing.is_active = channel.is_active
                else:
                    db_obj = ChannelModel(
                        id=channel.id,
                        profile_id=channel.profile_id,
                        title=channel.title,
                        chat_id=channel.chat_id,
                        invite_link=channel.invite_link,
                        is_active=channel.is_active,
                        created_at=channel.created_at,
                    )
                    session.add(db_obj)

    async def get_by_id(self, channel_id: str) -> Optional[Channel]:
        async with self.session_factory() as session:
            obj = await session.get(ChannelModel, channel_id)
            if not obj:
                return None
            return Channel(
                id=obj.id,
                profile_id=obj.profile_id,
                title=obj.title,
                chat_id=obj.chat_id,
                invite_link=obj.invite_link,
                is_active=obj.is_active,
                created_at=obj.created_at,
            )

    async def list_by_profile(self, profile_id: str) -> List[Channel]:
        from sqlalchemy import select
        async with self.session_factory() as session:
            res = await session.execute(
                select(ChannelModel).where(ChannelModel.profile_id == profile_id)
            )
            objs = res.scalars().all()
            return [
                Channel(
                    id=obj.id,
                    profile_id=obj.profile_id,
                    title=obj.title,
                    chat_id=obj.chat_id,
                    invite_link=obj.invite_link,
                    is_active=obj.is_active,
                    created_at=obj.created_at,
                )
                for obj in objs
            ]

    async def delete(self, channel_id: str) -> bool:
        from sqlalchemy import delete
        async with self.session_factory() as session:
            async with session.begin():
                res = await session.execute(
                    delete(ChannelModel).where(ChannelModel.id == channel_id)
                )
                return res.rowcount > 0

class SqlAlchemyBroadcastRepository(IBroadcastRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def save(self, broadcast: BroadcastMessage) -> None:
        import json
        async with self.session_factory() as session:
            async with session.begin():
                existing = await session.get(BroadcastModel, broadcast.id)
                channels_json = json.dumps(broadcast.target_channel_ids)
                m_path = broadcast.media.file_path if broadcast.media else None
                m_type = broadcast.media.media_type.value if broadcast.media else None
                m_size = broadcast.media.file_size if broadcast.media else None
                m_duration = broadcast.media.duration if broadcast.media else None
                m_width = broadcast.media.width if broadcast.media else None
                m_height = broadcast.media.height if broadcast.media else None
                m_thumb = broadcast.media.thumbnail_path if broadcast.media else None
                b_text = broadcast.button.text if broadcast.button else None
                b_url = broadcast.button.url if broadcast.button else None

                if existing:
                    existing.status = broadcast.status.value
                    existing.text = broadcast.text
                    existing.media_file_path = m_path
                    existing.media_type = m_type
                    existing.media_file_size = m_size
                    existing.media_duration = m_duration
                    existing.media_width = m_width
                    existing.media_height = m_height
                    existing.media_thumbnail_path = m_thumb
                    existing.scheduled_at = broadcast.scheduled_at
                    existing.button_text = b_text
                    existing.button_url = b_url
                else:
                    db_obj = BroadcastModel(
                        id=broadcast.id,
                        profile_id=broadcast.profile_id,
                        target_channel_ids=channels_json,
                        text=broadcast.text,
                        media_file_path=m_path,
                        media_type=m_type,
                        media_file_size=m_size,
                        media_duration=m_duration,
                        media_width=m_width,
                        media_height=m_height,
                        media_thumbnail_path=m_thumb,
                        button_text=b_text,
                        button_url=b_url,
                        status=broadcast.status.value,
                        scheduled_at=broadcast.scheduled_at,
                        created_at=broadcast.created_at,
                    )
                    session.add(db_obj)

    async def get_by_id(self, broadcast_id: str) -> Optional[BroadcastMessage]:
        import json
        async with self.session_factory() as session:
            obj = await session.get(BroadcastModel, broadcast_id)
            if not obj:
                return None
            return self._to_entity(obj)

    async def list_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        from sqlalchemy import select
        async with self.session_factory() as session:
            res = await session.execute(
                select(BroadcastModel)
                .where(BroadcastModel.profile_id == profile_id)
                .order_by(BroadcastModel.created_at.desc())
            )
            objs = res.scalars().all()
            return [self._to_entity(o) for o in objs]

    async def get_scheduled_by_profile(self, profile_id: str) -> List[BroadcastMessage]:
        from sqlalchemy import select
        async with self.session_factory() as session:
            res = await session.execute(
                select(BroadcastModel)
                .where(BroadcastModel.profile_id == profile_id)
                .where(BroadcastModel.status.in_(["PENDING", "SCHEDULED"]))
                .where(BroadcastModel.scheduled_at.is_not(None))
                .order_by(BroadcastModel.scheduled_at.asc())
            )
            objs = res.scalars().all()
            return [self._to_entity(o) for o in objs]

    async def list_pending_scheduled(self) -> List[BroadcastMessage]:
        from sqlalchemy import select
        async with self.session_factory() as session:
            res = await session.execute(
                select(BroadcastModel)
                .where(BroadcastModel.status.in_(["PENDING", "SCHEDULED"]))
                .where(BroadcastModel.scheduled_at.is_not(None))
            )
            objs = res.scalars().all()
            return [self._to_entity(o) for o in objs]

    def _to_entity(self, obj: BroadcastModel) -> BroadcastMessage:
        import json
        media = None
        if obj.media_file_path:
            media = MediaAttachment(
                file_path=obj.media_file_path,
                media_type=MediaType(obj.media_type) if obj.media_type else MediaType.VIDEO,
                file_size=obj.media_file_size or 0,
                duration=obj.media_duration,
                width=obj.media_width,
                height=obj.media_height,
                thumbnail_path=obj.media_thumbnail_path,
            )
        button = None
        if obj.button_text and obj.button_url:
            button = InlineButton(text=obj.button_text, url=obj.button_url)

        scheduled_dt = obj.scheduled_at
        if scheduled_dt is not None and scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)

        created_dt = obj.created_at
        if created_dt is not None and created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)

        return BroadcastMessage(
            id=obj.id,
            profile_id=obj.profile_id,
            target_channel_ids=json.loads(obj.target_channel_ids),
            text=obj.text or "",
            media=media,
            button=button,
            status=BroadcastStatus(obj.status),
            scheduled_at=scheduled_dt,
            created_at=created_dt,
        )
