import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.infrastructure.sqlite_repositories import Base, SqlAlchemyChannelRepository
from src.infrastructure.in_memory_repositories import InMemoryChannelRepository
from src.domain.channels.channel import Channel, ChatType

@pytest.mark.asyncio
async def test_in_memory_channel_repo_save_and_update():
    repo = InMemoryChannelRepository()
    channel = Channel(
        id="c-mem-1",
        profile_id="p-1",
        title="Canal Original",
        chat_id="-1001111111111",
    )
    # 1. Salva canal novo
    await repo.save(channel)
    fetched = await repo.get_by_id("c-mem-1")
    assert fetched is not None
    assert fetched.title == "Canal Original"
    assert fetched.chat_id == "-1001111111111"

    # 2. Atualiza dados do canal existente
    channel.title = "Canal Atualizado"
    channel.chat_id = "-1002222222222"
    await repo.save(channel)

    updated = await repo.get_by_id("c-mem-1")
    assert updated is not None
    assert updated.title == "Canal Atualizado"
    assert updated.chat_id == "-1002222222222"
    channels = await repo.list_by_profile("p-1")
    assert len(channels) == 1

@pytest.mark.asyncio
async def test_in_memory_channel_repo_delete():
    repo = InMemoryChannelRepository()
    channel = Channel(
        id="c-mem-del",
        profile_id="p-1",
        title="Canal para Deletar",
        chat_id="-1001111111111",
    )
    await repo.save(channel)
    assert await repo.get_by_id("c-mem-del") is not None

    # Deleta canal existente
    result = await repo.delete("c-mem-del")
    assert result is True
    assert await repo.get_by_id("c-mem-del") is None

    # Deleta canal inexistente retorna False
    result_non_existent = await repo.delete("c-mem-del")
    assert result_non_existent is False

@pytest.fixture
def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_factory

@pytest.mark.asyncio
async def test_sqlalchemy_channel_repo_save_and_update(sqlite_session_factory):
    engine, session_factory = sqlite_session_factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = SqlAlchemyChannelRepository(session_factory)
    channel = Channel(
        id="c-sql-1",
        profile_id="m-sql-1",
        title="Canal SQLite Original",
        chat_id="-1001234567890",
    )
    # 1. Salva novo canal
    await repo.save(channel)
    fetched = await repo.get_by_id("c-sql-1")
    assert fetched is not None
    assert fetched.title == "Canal SQLite Original"
    assert fetched.chat_id == "-1001234567890"

    # 2. Atualiza canal existente
    channel.title = "Canal SQLite Atualizado"
    channel.chat_id = "-1009876543210"
    await repo.save(channel)

    updated = await repo.get_by_id("c-sql-1")
    assert updated is not None
    assert updated.title == "Canal SQLite Atualizado"
    assert updated.chat_id == "-1009876543210"

    channels = await repo.list_by_profile("m-sql-1")
    assert len(channels) == 1

@pytest.mark.asyncio
async def test_sqlalchemy_channel_repo_delete(sqlite_session_factory):
    engine, session_factory = sqlite_session_factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    repo = SqlAlchemyChannelRepository(session_factory)
    channel = Channel(
        id="c-sql-del",
        profile_id="m-sql-1",
        title="Canal SQLite para Deletar",
        chat_id="-1001234567890",
    )
    await repo.save(channel)
    assert await repo.get_by_id("c-sql-del") is not None

    # Deleta canal existente
    result = await repo.delete("c-sql-del")
    assert result is True
    assert await repo.get_by_id("c-sql-del") is None

    # Deleta canal inexistente retorna False
    result_non_existent = await repo.delete("c-sql-del")
    assert result_non_existent is False


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_channel_repositories_keep_chat_type_and_forum(backend, sqlite_session_factory):
    # Os dois repositórios cumprem o mesmo contrato (#99).
    if backend == "sqlite":
        engine, session_factory = sqlite_session_factory
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        repo = SqlAlchemyChannelRepository(session_factory)
    else:
        repo = InMemoryChannelRepository()

    forum = Channel(id="c-forum", profile_id="p-1", title="Grupo", chat_id="-1001234567890",
                    chat_type=ChatType.SUPERGROUP, is_forum=True)
    unknown = Channel(id="c-unknown", profile_id="p-1", title="Canal antigo", chat_id="-1009876543210")
    await repo.save(forum)
    await repo.save(unknown)

    loaded = {c.id: (c.chat_type, c.is_forum) for c in await repo.list_by_profile("p-1")}
    assert loaded == {"c-forum": (ChatType.SUPERGROUP, True), "c-unknown": (None, False)}

    forum.classify(ChatType.CHANNEL, is_forum=False)
    await repo.save(forum)
    updated = await repo.get_by_id("c-forum")
    assert updated is not None
    assert (updated.chat_type, updated.is_forum) == (ChatType.CHANNEL, False)
