import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.infrastructure.sqlite_repositories import Base, SqlAlchemyBroadcastRepository, SqlAlchemyProfileRepository
from src.infrastructure.in_memory_broadcast_repository import InMemoryBroadcastRepository
from src.domain.broadcast.broadcast_message import BroadcastMessage, BroadcastStatus
from src.domain.profiles.profile import Profile
from src.domain.profiles.bot_credentials import BotCredentials


@pytest.mark.asyncio
async def test_in_memory_broadcast_repo_reconcile_orphan_dispatching():
    repo = InMemoryBroadcastRepository()
    b1 = BroadcastMessage(
        id="b-orphan-1",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        status=BroadcastStatus.DISPATCHING,
    )
    b2 = BroadcastMessage(
        id="b-normal-2",
        profile_id="p-1",
        target_channel_ids=["-1001111111111"],
        status=BroadcastStatus.COMPLETED,
    )
    await repo.save(b1)
    await repo.save(b2)

    count = await repo.reconcile_orphan_dispatching()
    assert count == 1

    fetched1 = await repo.get_by_id("b-orphan-1")
    assert fetched1 is not None
    assert fetched1.status == BroadcastStatus.FAILED

    fetched2 = await repo.get_by_id("b-normal-2")
    assert fetched2 is not None
    assert fetched2.status == BroadcastStatus.COMPLETED


@pytest.mark.asyncio
async def test_sqlalchemy_broadcast_repo_reconcile_orphan_dispatching():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    prof_repo = SqlAlchemyProfileRepository(session_factory)
    b_repo = SqlAlchemyBroadcastRepository(session_factory)

    try:
        prof = Profile(id="p-sqla-1", name="Profile 1", credentials=BotCredentials(token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", bot_username="testbot"))
        await prof_repo.save(prof)

        b1 = BroadcastMessage(
            id="b-sqla-orphan",
            profile_id="p-sqla-1",
            target_channel_ids=["-1001111111111"],
            status=BroadcastStatus.DISPATCHING,
        )
        b2 = BroadcastMessage(
            id="b-sqla-normal",
            profile_id="p-sqla-1",
            target_channel_ids=["-1001111111111"],
            status=BroadcastStatus.PENDING,
        )
        await b_repo.save(b1)
        await b_repo.save(b2)

        count = await b_repo.reconcile_orphan_dispatching()
        assert count == 1

        f1 = await b_repo.get_by_id("b-sqla-orphan")
        assert f1 is not None
        assert f1.status == BroadcastStatus.FAILED

        f2 = await b_repo.get_by_id("b-sqla-normal")
        assert f2 is not None
        assert f2.status == BroadcastStatus.PENDING
    finally:
        await engine.dispose()
