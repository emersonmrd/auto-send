import json
from pathlib import Path
import sqlite3
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import src.presentation.main as main_module
from src.infrastructure.sqlite_repositories import (
    SqlAlchemyBroadcastRepository,
    SqlAlchemyChannelRepository,
    SqlAlchemyProfileRepository,
)
from src.infrastructure.sqlite_migrations import (
    CURRENT_SCHEMA_VERSION,
    DatabaseMigrationError,
    MIGRATIONS,
    MigrationStep,
    get_user_version,
    sqlite_file_from_url,
)
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
    ChannelDeliveryResult,
    DeliveryFailureCategory,
    MediaAttachment,
    MediaType,
)
from src.domain.profiles.profile import Profile
from src.domain.profiles.bot_credentials import BotCredentials


def get_table_columns(sqlite_db_path: str, table_name: str) -> set[str]:
    """Retorna os nomes das colunas de uma tabela SQLite usando PRAGMA."""
    conn = sqlite3.connect(sqlite_db_path)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    return columns


def create_legacy_sqlite_db(sqlite_db_path: str) -> None:
    """Cria uma base SQLite simulando a versão anterior sem as novas colunas de vídeo."""
    conn = sqlite3.connect(sqlite_db_path)
    cursor = conn.cursor()

    # Tabela profiles
    cursor.execute("""
        CREATE TABLE profiles (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            bot_token VARCHAR NOT NULL,
            bot_username VARCHAR NOT NULL,
            avatar_url VARCHAR,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        )
    """)

    # Tabela channels
    cursor.execute("""
        CREATE TABLE channels (
            id VARCHAR PRIMARY KEY,
            profile_id VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            chat_id VARCHAR NOT NULL,
            invite_link VARCHAR DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            FOREIGN KEY(profile_id) REFERENCES profiles (id)
        )
    """)

    # Tabela broadcasts LEGADA: sem media_duration, media_width, media_height, media_thumbnail_path
    cursor.execute("""
        CREATE TABLE broadcasts (
            id VARCHAR PRIMARY KEY,
            profile_id VARCHAR NOT NULL,
            target_channel_ids TEXT NOT NULL,
            text TEXT,
            media_file_path VARCHAR,
            media_type VARCHAR,
            media_file_size INTEGER,
            button_text VARCHAR,
            button_url VARCHAR,
            status VARCHAR DEFAULT 'PENDING',
            scheduled_at DATETIME,
            created_at DATETIME,
            FOREIGN KEY(profile_id) REFERENCES profiles (id)
        )
    """)

    # Inserção de dados prévios para garantir que a migração não perde dados existentes
    cursor.execute("""
        INSERT INTO profiles (id, name, bot_token, bot_username, avatar_url, is_active, created_at)
        VALUES ('profile-1', 'Alice', '12345:TOKEN', 'alice_bot', NULL, 1, '2026-01-01 12:00:00')
    """)

    cursor.execute("""
        INSERT INTO broadcasts (
            id, profile_id, target_channel_ids, text, media_file_path, media_type, media_file_size,
            button_text, button_url, status, scheduled_at, created_at
        ) VALUES (
            'legacy-bc-1', 'profile-1', '["-100123"]', 'Mensagem antiga preservada',
            '/tmp/legacy_photo.jpg', 'PHOTO', 1024,
            NULL, NULL, 'PENDING', NULL, '2026-01-01 12:00:00'
        )
    """)

    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_init_db_migrates_legacy_broadcasts_table_and_adds_missing_columns(tmp_path, monkeypatch):
    """
    Testa a migração do SQLite na inicialização:
    1. Base legada sem media_duration, media_width, media_height, media_thumbnail_path.
    2. Ao chamar init_db(), as 4 colunas devem ser adicionadas via ALTER TABLE sem perder dados.
    3. PRAGMA table_info deve confirmar as colunas.
    4. Dados legados devem permanecer inalterados.
    """
    db_file = str(tmp_path / "legacy_auto_send.db")
    create_legacy_sqlite_db(db_file)

    # Verifica que antes do init_db() as colunas NÃO existem
    initial_columns = get_table_columns(db_file, "broadcasts")
    assert "media_duration" not in initial_columns
    assert "media_width" not in initial_columns
    assert "media_height" not in initial_columns
    assert "media_thumbnail_path" not in initial_columns

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        # Executa init_db()
        await main_module.init_db()

        # Valida que as colunas foram criadas na tabela SQLite existente
        migrated_columns = get_table_columns(db_file, "broadcasts")
        assert "media_duration" in migrated_columns
        assert "media_width" in migrated_columns
        assert "media_height" in migrated_columns
        assert "media_thumbnail_path" in migrated_columns

        # Valida que os dados prévios foram preservados
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, status FROM broadcasts WHERE id = 'legacy-bc-1'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "legacy-bc-1"
        assert row[1] == "Mensagem antiga preservada"
        assert row[2] == "PENDING"

    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_legacy_broadcast_retrieval_and_save_without_operational_error(tmp_path, monkeypatch):
    """
    Valida que após o init_db(), operações de leitura e escrita com o repositório SQLAlchemy
    não disparam sqlite3.OperationalError: table broadcasts has no column named media_duration.
    """
    db_file = str(tmp_path / "legacy_auto_send.db")
    create_legacy_sqlite_db(db_file)

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(main_module, "session_factory", session_factory)

    try:
        await main_module.init_db()

        broadcast_repo = SqlAlchemyBroadcastRepository(session_factory)

        # 1. Leitura de broadcast legado existente
        legacy_bc = await broadcast_repo.get_by_id("legacy-bc-1")
        assert legacy_bc is not None
        assert legacy_bc.id == "legacy-bc-1"
        assert legacy_bc.text == "Mensagem antiga preservada"
        assert legacy_bc.media is not None
        assert legacy_bc.media.duration is None
        assert legacy_bc.media.width is None
        assert legacy_bc.media.height is None
        assert legacy_bc.media.thumbnail_path is None

        # 2. Criação de novo broadcast com metadados de vídeo nas novas colunas
        new_bc = BroadcastMessage(
            id="new-video-bc",
            profile_id="profile-1",
            target_channel_ids=["-100123"],
            text="Novo vídeo publicado",
            media=MediaAttachment(
                file_path="/tmp/video.mp4",
                media_type=MediaType.VIDEO,
                file_size=204800,
                duration=45,
                width=1920,
                height=1080,
                thumbnail_path="/tmp/thumb.jpg",
            ),
            status=BroadcastStatus.PENDING,
        )
        await broadcast_repo.save(new_bc)

        # 3. Leitura do novo broadcast persistido
        saved_bc = await broadcast_repo.get_by_id("new-video-bc")
        assert saved_bc is not None
        assert saved_bc.text == "Novo vídeo publicado"
        assert saved_bc.media is not None
        assert saved_bc.media.duration == 45
        assert saved_bc.media.width == 1920
        assert saved_bc.media.height == 1080
        assert saved_bc.media.thumbnail_path == "/tmp/thumb.jpg"

    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_init_db_idempotency_does_not_fail_on_already_migrated_db(tmp_path, monkeypatch):
    """
    Valida que chamar init_db() repetidas vezes não gera erro de coluna duplicada.
    """
    db_file = str(tmp_path / "legacy_auto_send.db")
    create_legacy_sqlite_db(db_file)

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        # Primeira execução: aplica migração
        await main_module.init_db()

        # Segunda execução: idempotente
        await main_module.init_db()

        migrated_columns = get_table_columns(db_file, "broadcasts")
        assert "media_duration" in migrated_columns
        assert "media_width" in migrated_columns
        assert "media_height" in migrated_columns
        assert "media_thumbnail_path" in migrated_columns

    finally:
        await test_engine.dispose()


def create_v040_sqlite_db(sqlite_db_path: str) -> None:
    """Cria um banco no formato da v0.4.0 (PRAGMA user_version = 0) com perfil, canal e agendamento fictícios."""
    conn = sqlite3.connect(sqlite_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE profiles (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            bot_token VARCHAR NOT NULL,
            bot_username VARCHAR NOT NULL,
            avatar_url VARCHAR,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME
        )
    """)
    cursor.execute("""
        CREATE TABLE channels (
            id VARCHAR PRIMARY KEY,
            profile_id VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            chat_id VARCHAR NOT NULL,
            invite_link VARCHAR DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME,
            FOREIGN KEY(profile_id) REFERENCES profiles (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE broadcasts (
            id VARCHAR PRIMARY KEY,
            profile_id VARCHAR NOT NULL,
            target_channel_ids TEXT NOT NULL,
            text TEXT,
            media_file_path VARCHAR,
            media_type VARCHAR,
            media_file_size INTEGER,
            media_duration INTEGER,
            media_width INTEGER,
            media_height INTEGER,
            media_thumbnail_path VARCHAR,
            button_text VARCHAR,
            button_url VARCHAR,
            status VARCHAR DEFAULT 'PENDING',
            scheduled_at DATETIME,
            created_at DATETIME,
            FOREIGN KEY(profile_id) REFERENCES profiles (id)
        )
    """)
    cursor.execute("""
        INSERT INTO profiles (id, name, bot_token, bot_username, avatar_url, is_active, created_at)
        VALUES ('prof-acme', 'Acme', '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef', 'acme_bot', NULL, 1, '2026-10-23 10:00:00')
    """)
    cursor.execute("""
        INSERT INTO channels (id, profile_id, title, chat_id, invite_link, is_active, created_at)
        VALUES ('ch-novidades', 'prof-acme', 'Canal de Novidades', '-1001234567890', '', 1, '2026-10-23 10:05:00')
    """)
    cursor.execute("""
        INSERT INTO broadcasts (
            id, profile_id, target_channel_ids, text, status, scheduled_at, created_at
        ) VALUES (
            'bc-v040', 'prof-acme', '["-1001234567890"]', 'Comunicado da v0.4.0',
            'SCHEDULED', '2026-12-01 15:00:00', '2026-10-23 10:10:00'
        )
    """)
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_upgrade_from_v040_preserves_data_sets_schema_version_and_creates_backup(tmp_path, monkeypatch):
    """Dado um banco da v0.4.0 com perfis, canais e agendamentos fictícios, quando a versão nova inicia,
    os dados continuam lá, o esquema fica na versão atual e existe o backup."""
    db_path = tmp_path / "autosend.db"
    create_v040_sqlite_db(str(db_path))
    assert get_user_version(db_path) == 0

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db()

        assert get_user_version(db_path) == CURRENT_SCHEMA_VERSION
        # Os 3 backups mais recentes são mantidos após a sequência de migrações
        backups = sorted(p.name for p in tmp_path.glob("autosend.db.bak-*"))
        assert len(backups) == 3

        profiles = await SqlAlchemyProfileRepository(session_factory).list_all()
        channels = await SqlAlchemyChannelRepository(session_factory).list_by_profile("prof-acme")
        broadcasts = await SqlAlchemyBroadcastRepository(session_factory).list_by_profile("prof-acme")

        assert [p.name for p in profiles] == ["Acme"]
        assert [c.title for c in channels] == ["Canal de Novidades"]
        assert [b.text for b in broadcasts] == ["Comunicado da v0.4.0"]
        assert broadcasts[0].delivery_results == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_already_migrated_db_does_not_rerun_migrations_on_restart(tmp_path, monkeypatch):
    """Dado um banco já migrado, quando o app reinicia, nenhuma migração roda de novo."""
    db_path = tmp_path / "autosend.db"
    create_v040_sqlite_db(str(db_path))

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    calls: list[int] = []
    tracked_steps = tuple(
        MigrationStep(
            version=step.version,
            description=step.description,
            apply=lambda cur, s=step: (calls.append(s.version), s.apply(cur))[1],
        )
        for step in MIGRATIONS
    )

    try:
        await main_module.init_db(migration_steps=tracked_steps)
        assert calls == [s.version for s in MIGRATIONS]

        calls.clear()
        await main_module.init_db(migration_steps=tracked_steps)
        assert calls == []
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_four_consecutive_migrations_keep_only_the_three_most_recent_backups(tmp_path, monkeypatch):
    """Dado quatro migrações seguidas, quando a quarta termina, restam os 3 backups mais recentes."""
    db_path = tmp_path / "autosend.db"
    create_legacy_sqlite_db(str(db_path))

    four_steps = MIGRATIONS[:4]

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db(migration_steps=four_steps)

        backups = sorted(p.name for p in tmp_path.glob("autosend.db.bak-*"))
        assert backups == ["autosend.db.bak-1", "autosend.db.bak-2", "autosend.db.bak-3"]
        assert get_user_version(db_path) == 4
        assert "delivery_results" in get_table_columns(str(db_path), "broadcasts")
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_repository_persists_and_loads_delivery_results_column(tmp_path, monkeypatch):
    db_path = tmp_path / "autosend.db"
    create_v040_sqlite_db(str(db_path))

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db()
        repo = SqlAlchemyBroadcastRepository(session_factory)
        bc = BroadcastMessage(
            id="bc-with-results",
            profile_id="prof-acme",
            target_channel_ids=["-1001111111111", "-1002222222222"],
            text="Resultado por canal",
            status=BroadcastStatus.DISPATCHING,
        )
        bc.finish_dispatch_with_results(
            [
                ChannelDeliveryResult.success("-1001111111111"),
                ChannelDeliveryResult.failure(
                    "-1002222222222",
                    category=DeliveryFailureCategory.NO_POST_PERMISSION,
                    detail="Bad Request: not enough rights to send text messages to the chat",
                ),
            ]
        )
        await repo.save(bc)

        loaded = await repo.get_by_id("bc-with-results")
        assert loaded is not None
        assert loaded.status is BroadcastStatus.PARTIALLY_COMPLETED
        assert len(loaded.delivery_results) == 2
        assert loaded.delivery_results[0].delivered is True
        assert loaded.delivery_results[1].delivered is False
        assert loaded.delivery_results[1].failure_category is DeliveryFailureCategory.NO_POST_PERMISSION
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_and_keeps_previous_version(tmp_path, monkeypatch):
    """Dado uma migração que falha no meio, o banco continua na versão anterior."""
    db_path = tmp_path / "autosend.db"
    create_legacy_sqlite_db(str(db_path))

    def _broken_step(cur: sqlite3.Cursor) -> None:
        cur.execute("ALTER TABLE profiles ADD COLUMN temp_broken_col VARCHAR")
        raise sqlite3.OperationalError("falha simulada no meio da migração")

    steps_with_failure = (
        MIGRATIONS[0],
        MigrationStep(version=2, description="Migração quebrada", apply=_broken_step),
    )

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        with pytest.raises(DatabaseMigrationError) as exc_info:
            await main_module.init_db(migration_steps=steps_with_failure)

        assert exc_info.value.previous_version == 1
        assert exc_info.value.target_version == 2
        assert get_user_version(db_path) == 1
        assert "temp_broken_col" not in get_table_columns(str(db_path), "profiles")
        assert (tmp_path / "autosend.db.bak-0").is_file()
        assert (tmp_path / "autosend.db.bak-1").is_file()
    finally:
        await test_engine.dispose()


def test_run_app_aborts_startup_without_opening_browser_when_migration_fails(tmp_path, monkeypatch, capsys):
    """Quando uma migração falha no início do app, o app avisa e sai sem abrir o navegador."""
    opened_urls: list[str] = []
    monkeypatch.setattr(main_module.webbrowser, "open", lambda url: opened_urls.append(url))
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: opened_urls.append("uvicorn"))

    async def _failing_init_db():
        raise DatabaseMigrationError(2, 1, RuntimeError("erro simulado"))

    monkeypatch.setattr(main_module, "init_db", _failing_init_db)
    monkeypatch.setenv("AUTOSEND_DATA_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as sys_exit:
        main_module.run_app()

    assert sys_exit.value.code == 1
    assert opened_urls == []
    err = capsys.readouterr().err
    assert "versão 1" in err


def test_sqlite_file_from_url_unquotes_percent_encoded_paths(tmp_path):
    assert sqlite_file_from_url("sqlite+aiosqlite:///:memory:") is None
    assert sqlite_file_from_url("sqlite:///:memory:") is None
    assert sqlite_file_from_url("sqlite+aiosqlite:///file::memory:?cache=shared") is None
    assert sqlite_file_from_url("postgres://user:pass@localhost/db") is None

    f = tmp_path / "test.db"
    assert sqlite_file_from_url(f"sqlite+aiosqlite:///{f}") == f.resolve()
    assert sqlite_file_from_url(f"sqlite:///{f}") == f.resolve()

    # Percent-encoded path (ex: SQLAlchemy on Windows with drive letter C%3A)
    encoded = "sqlite+aiosqlite:///C%3A/Users/ContainerUser/AppData/Local/Temp/autosend.db"
    expected = Path("C:/Users/ContainerUser/AppData/Local/Temp/autosend.db").resolve()
    assert sqlite_file_from_url(encoded) == expected


@pytest.mark.asyncio
async def test_legacy_profiles_without_created_at_migrated_and_queryable(tmp_path, monkeypatch):
    """Bancos legados com tabela profiles sem created_at são migrados com sucesso."""
    db_path = tmp_path / "autosend.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE profiles (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, bot_token VARCHAR NOT NULL, bot_username VARCHAR NOT NULL)"
    )
    conn.execute(
        "INSERT INTO profiles VALUES ('p-v040', 'Acme', '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef', 'acme_bot')"
    )
    conn.commit()
    conn.close()

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db()
        repo = SqlAlchemyProfileRepository(session_factory)
        profiles = await repo.list_all()
        assert len(profiles) == 1
        assert profiles[0].id == "p-v040"
        assert profiles[0].name == "Acme"
        assert profiles[0].created_at is not None
        assert profiles[0].created_at.tzinfo == timezone.utc

        # O endpoint GET /api/v1/profiles consegue serializar sem erro
        assert profiles[0].created_at.isoformat()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_migration_006_creates_message_templates_table(tmp_path, monkeypatch):
    """A migração versão 6 cria a tabela message_templates e permite operações do repositório."""
    from src.infrastructure.sqlite_repositories import SqlAlchemyMessageTemplateRepository
    from src.domain.broadcast.message_template import MessageTemplate

    assert CURRENT_SCHEMA_VERSION >= 6

    db_path = tmp_path / "autosend_v6.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db()

        # Garante que user_version é CURRENT_SCHEMA_VERSION (>= 6)
        assert get_user_version(db_path) == CURRENT_SCHEMA_VERSION

        # Garante colunas de message_templates
        columns = get_table_columns(str(db_path), "message_templates")
        assert {"id", "profile_id", "name", "text", "button_text", "button_url", "created_at", "updated_at"}.issubset(columns)

        # Testa CRUD via SqlAlchemyMessageTemplateRepository
        profile_repo = SqlAlchemyProfileRepository(session_factory)
        profile = Profile(
            id="p-test",
            name="Perfil Teste",
            credentials=BotCredentials(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", bot_username="p_bot"),
        )
        await profile_repo.save(profile)

        repo = SqlAlchemyMessageTemplateRepository(session_factory)
        tmpl = MessageTemplate(
            id="tmpl-1",
            profile_id="p-test",
            name="Modelo Promo",
            text="Promoção relâmpago!",
            button_text="Comprar",
            button_url="https://loja.exemplo.com",
        )
        await repo.save(tmpl)

        loaded = await repo.get_by_id("tmpl-1")
        assert loaded is not None
        assert loaded.name == "Modelo Promo"
        assert loaded.text == "Promoção relâmpago!"
        assert loaded.button_text == "Comprar"
        assert loaded.button_url == "https://loja.exemplo.com"

        all_tmpls = await repo.list_by_profile("p-test")
        assert len(all_tmpls) == 1
        assert all_tmpls[0].id == "tmpl-1"

        deleted = await repo.delete("tmpl-1")
        assert deleted is True
        assert await repo.get_by_id("tmpl-1") is None
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_message_templates_survive_future_database_migrations(tmp_path, monkeypatch):
    """Dado um banco no schema atual com perfil e modelo de mensagem salvos,
    quando uma nova migração futura é executada, o modelo e seus campos permanecem intactos."""
    from src.infrastructure.sqlite_repositories import SqlAlchemyMessageTemplateRepository
    from src.domain.broadcast.message_template import MessageTemplate

    db_path = tmp_path / "autosend.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        # 1. Inicia o banco com o schema atual
        await main_module.init_db()
        curr_ver = CURRENT_SCHEMA_VERSION
        assert get_user_version(db_path) == curr_ver

        # 2. Insere um perfil 'Acme' e um modelo 'Canal de Novidades'
        profile_repo = SqlAlchemyProfileRepository(session_factory)
        profile = Profile(
            id="prof-acme",
            name="Acme",
            credentials=BotCredentials(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", bot_username="acme_bot"),
        )
        await profile_repo.save(profile)

        template_repo = SqlAlchemyMessageTemplateRepository(session_factory)
        tmpl = MessageTemplate(
            id="tmpl-novidades",
            profile_id="prof-acme",
            name="Canal de Novidades",
            text="Texto do modelo preservado",
            button_text="Acessar",
            button_url="https://canal.exemplo.com",
        )
        await template_repo.save(tmpl)

        # 3. Define uma migração futura simulada
        next_ver = curr_ver + 1
        def _migration_future_simulated(cur: sqlite3.Cursor) -> None:
            cur.execute("ALTER TABLE profiles ADD COLUMN dummy_future_setting VARCHAR DEFAULT ''")

        simulated_step = MigrationStep(
            version=next_ver,
            description="Migração futura simulada para teste de sobrevivência de dados",
            apply=_migration_future_simulated,
        )

        steps_future = (*MIGRATIONS, simulated_step)

        # 4. Executa init_db com a nova migração
        await main_module.init_db(migration_steps=steps_future)

        # 5. Valida nova versão e backup criado
        assert get_user_version(db_path) == next_ver
        assert (tmp_path / f"autosend.db.bak-{curr_ver}").is_file()

        # 6. Valida que o modelo sobreviveu com exatamente os mesmos campos
        loaded = await template_repo.get_by_id("tmpl-novidades")
        assert loaded is not None
        assert loaded.id == "tmpl-novidades"
        assert loaded.profile_id == "prof-acme"
        assert loaded.name == "Canal de Novidades"
        assert loaded.text == "Texto do modelo preservado"
        assert loaded.button_text == "Acessar"
        assert loaded.button_url == "https://canal.exemplo.com"
        assert loaded.created_at is not None
        assert loaded.updated_at is not None

        by_profile = await template_repo.list_by_profile("prof-acme")
        assert len(by_profile) == 1
        assert by_profile[0].id == "tmpl-novidades"

        # E o perfil continua íntegro
        loaded_profile = await profile_repo.get_by_id("prof-acme")
        assert loaded_profile is not None
        assert loaded_profile.name == "Acme"
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_migration_007_creates_poll_data_column_and_persists_polls(tmp_path, monkeypatch):
    """A migração versão 7 adiciona a coluna poll_data em broadcasts e permite persistir e carregar enquetes."""
    from src.domain.broadcast.broadcast_message import BroadcastPoll, PollType
    from src.infrastructure.sqlite_repositories import SqlAlchemyBroadcastRepository

    assert CURRENT_SCHEMA_VERSION == 7

    db_path = tmp_path / "autosend_v7.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        await main_module.init_db()

        assert get_user_version(db_path) == 7

        columns = get_table_columns(str(db_path), "broadcasts")
        assert "poll_data" in columns

        profile_repo = SqlAlchemyProfileRepository(session_factory)
        profile = Profile(
            id="p-poll-test",
            name="Perfil Enquetes",
            credentials=BotCredentials(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", bot_username="poll_bot"),
        )
        await profile_repo.save(profile)

        broadcast_repo = SqlAlchemyBroadcastRepository(session_factory)
        poll = BroadcastPoll(
            question="Qual o melhor framework?",
            options=["Next.js", "Vue", "Svelte"],
            is_anonymous=False,
            allows_multiple_answers=True,
            poll_type=PollType.REGULAR,
        )
        b_msg = BroadcastMessage(
            id="b-poll-1",
            profile_id="p-poll-test",
            target_channel_ids=["-1001234567890"],
            poll=poll,
        )
        await broadcast_repo.save(b_msg)

        loaded = await broadcast_repo.get_by_id("b-poll-1")
        assert loaded is not None
        assert loaded.poll is not None
        assert loaded.poll.question == "Qual o melhor framework?"
        assert loaded.poll.options == ["Next.js", "Vue", "Svelte"]
        assert loaded.poll.is_anonymous is False
        assert loaded.poll.allows_multiple_answers is True
        assert loaded.poll.poll_type == PollType.REGULAR
        assert loaded.poll.correct_option_id is None
        assert loaded.poll.explanation is None

        # Testa atualização para modo Quiz
        quiz_poll = BroadcastPoll(
            question="Quanto é 1 + 1?",
            options=["1", "2", "3"],
            poll_type=PollType.QUIZ,
            correct_option_id=1,
            explanation="1 mais 1 é igual a 2.",
            is_closed=True,
        )
        b_msg.poll = quiz_poll
        await broadcast_repo.save(b_msg)

        reloaded = await broadcast_repo.get_by_id("b-poll-1")
        assert reloaded is not None
        assert reloaded.poll is not None
        assert reloaded.poll.poll_type == PollType.QUIZ
        assert reloaded.poll.correct_option_id == 1
        assert reloaded.poll.explanation == "1 mais 1 é igual a 2."
        assert reloaded.poll.is_closed is True
    finally:
        await test_engine.dispose()



