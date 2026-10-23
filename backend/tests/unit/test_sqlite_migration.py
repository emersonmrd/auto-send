import json
import sqlite3
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import src.presentation.main as main_module
from src.infrastructure.sqlite_repositories import (
    SqlAlchemyBroadcastRepository,
    SqlAlchemyProfileRepository,
)
from src.domain.broadcast.broadcast_message import (
    BroadcastMessage,
    BroadcastStatus,
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

