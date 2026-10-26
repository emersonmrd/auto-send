"""Migrações numeradas do SQLite com versão em PRAGMA user_version e backup automático (#24).

Regras (AGENTS.md):
- Nenhuma release pode perder ou corromper o banco de quem atualiza.
- Toda mudança de esquema é um passo numerado e idempotente que roda em transação.
- Antes de cada migração num banco existente, grava `<banco>.bak-<versão anterior>`;
  mantém os 3 backups mais recentes e só apaga os antigos após a migração concluir com sucesso.
- Se um passo falhar, a transação é desfeita (banco continua na versão anterior) e
  DatabaseMigrationError é levantada para impedir o app de abrir com esquema inconsistente.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import unquote

MAX_BACKUPS = 3


class DatabaseMigrationError(RuntimeError):
    """Falha ao aplicar uma migração numerada; o banco permanece na versão anterior."""

    def __init__(self, target_version: int, previous_version: int, cause: BaseException) -> None:
        super().__init__(
            f"Falha ao migrar o banco para a versão {target_version} "
            f"(mantido na versão {previous_version}): {cause}"
        )
        self.target_version = target_version
        self.previous_version = previous_version
        self.cause = cause


@dataclass(frozen=True)
class MigrationStep:
    version: int
    description: str
    apply: Callable[[sqlite3.Cursor], None]


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _add_column_if_missing(cursor: sqlite3.Cursor, table_name: str, col_name: str, col_def: str) -> None:
    if col_name not in _table_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")


def _migration_001_broadcast_video_metadata(cursor: sqlite3.Cursor) -> None:
    for col_name, col_def in (
        ("media_duration", "INTEGER"),
        ("media_width", "INTEGER"),
        ("media_height", "INTEGER"),
        ("media_thumbnail_path", "VARCHAR"),
    ):
        _add_column_if_missing(cursor, "broadcasts", col_name, col_def)


def _migration_002_channel_invite_link_and_active(cursor: sqlite3.Cursor) -> None:
    for col_name, col_def in (
        ("invite_link", "VARCHAR DEFAULT ''"),
        ("is_active", "BOOLEAN DEFAULT 1"),
    ):
        _add_column_if_missing(cursor, "channels", col_name, col_def)


def _migration_003_profile_avatar_and_active(cursor: sqlite3.Cursor) -> None:
    for col_name, col_def in (
        ("avatar_url", "VARCHAR"),
        ("is_active", "BOOLEAN DEFAULT 1"),
    ):
        _add_column_if_missing(cursor, "profiles", col_name, col_def)


def _migration_004_broadcast_delivery_results(cursor: sqlite3.Cursor) -> None:
    _add_column_if_missing(cursor, "broadcasts", "delivery_results", "TEXT")


def _migration_005_broadcast_edit_locked_until(cursor: sqlite3.Cursor) -> None:
    _add_column_if_missing(cursor, "broadcasts", "edit_locked_until", "DATETIME")


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(
        version=1,
        description="Metadados de vídeo e miniatura em broadcasts",
        apply=_migration_001_broadcast_video_metadata,
    ),
    MigrationStep(
        version=2,
        description="Campos invite_link e is_active em channels",
        apply=_migration_002_channel_invite_link_and_active,
    ),
    MigrationStep(
        version=3,
        description="Campos avatar_url e is_active em profiles",
        apply=_migration_003_profile_avatar_and_active,
    ),
    MigrationStep(
        version=4,
        description="Resultados de entrega por canal em broadcasts (#31)",
        apply=_migration_004_broadcast_delivery_results,
    ),
    MigrationStep(
        version=5,
        description="Trava de edição em broadcasts (#15)",
        apply=_migration_005_broadcast_edit_locked_until,
    ),
)

CURRENT_SCHEMA_VERSION: int = MIGRATIONS[-1].version


def sqlite_file_from_url(database_url: str) -> Path | None:
    """Extrai o caminho do arquivo SQLite de uma URL SQLAlchemy, ou None para :memory:."""
    prefix = "sqlite+aiosqlite:///"
    alt_prefix = "sqlite:///"
    raw = None
    if database_url.startswith(prefix):
        raw = database_url[len(prefix) :]
    elif database_url.startswith(alt_prefix):
        raw = database_url[len(alt_prefix) :]
    if not raw or raw == ":memory:" or raw.startswith("file::memory:"):
        return None
    raw = unquote(raw)
    return Path(raw).resolve()


def get_user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def has_user_tables(db_path: Path) -> bool:
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return cursor.fetchone() is not None
    finally:
        conn.close()


def _backup_database(db_path: Path, previous_version: int) -> Path:
    backup_path = db_path.with_name(f"{db_path.name}.bak-{previous_version}")
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def _prune_old_backups(db_path: Path, keep: int = MAX_BACKUPS) -> None:
    prefix = f"{db_path.name}.bak-"
    backups: list[tuple[int, Path]] = []
    for candidate in db_path.parent.glob(f"{prefix}*"):
        suffix = candidate.name[len(prefix) :]
        try:
            ver = int(suffix)
        except ValueError:
            continue
        backups.append((ver, candidate))
    backups.sort(key=lambda item: item[0])
    while len(backups) > keep:
        _, oldest = backups.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


def run_pending_migrations(
    db_path: Path,
    steps: Sequence[MigrationStep] = MIGRATIONS,
    *,
    had_existing_tables: bool = True,
    max_backups: int = MAX_BACKUPS,
) -> int:
    """
    Aplica as migrações pendentes em db_path.
    Se had_existing_tables for False (banco recém-criado do zero pelo create_all),
    apenas grava PRAGMA user_version na versão mais recente sem gerar arquivos .bak.
    """
    ordered = sorted(steps, key=lambda s: s.version)
    if not ordered:
        return 0
    latest_version = ordered[-1].version

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version")
        current_version = int(cursor.fetchone()[0])

        if not had_existing_tables and current_version == 0:
            cursor.execute(f"PRAGMA user_version = {latest_version}")
            return latest_version

        pending: Iterable[MigrationStep] = [s for s in ordered if s.version > current_version]
        for step in pending:
            prev_version = current_version
            _backup_database(db_path, prev_version)
            try:
                cursor.execute("BEGIN IMMEDIATE")
                step.apply(cursor)
                cursor.execute(f"PRAGMA user_version = {step.version}")
                cursor.execute("COMMIT")
            except BaseException as exc:
                try:
                    cursor.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise DatabaseMigrationError(step.version, prev_version, exc) from exc
            current_version = step.version
            _prune_old_backups(db_path, keep=max_backups)

        return current_version
    finally:
        conn.close()
