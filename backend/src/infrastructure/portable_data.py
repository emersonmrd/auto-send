"""Pasta de dados do usuário e importação única de versões antigas no pacote portátil (#24).

No pacote portátil para Windows, os dados moram em `%LOCALAPPDATA%\\Auto-Send\\` para sobreviverem
quando o usuário extrai uma versão nova em outra pasta. Na primeira inicialização, se ainda não
existir banco em `%LOCALAPPDATA%\\Auto-Send\\autosend.db`, procura `data\\autosend.db` na própria
pasta da release, na pasta pai e em Downloads, Área de Trabalho e Documentos.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from src.infrastructure.sqlite_migrations import sqlite_file_from_url

DB_FILENAME = "autosend.db"
_VERSION_RE = re.compile(r"(v?\d+\.\d+\.\d+)", re.IGNORECASE)


def resolve_data_dir(default_db_url: str | None = None) -> Path:
    """Determina a pasta de dados ativa do Auto-Send."""
    explicit = os.getenv("AUTOSEND_DATA_DIR", "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    db_path_env = os.getenv("DB_PATH", "").strip()
    if db_path_env:
        path = Path(db_path_env).expanduser().resolve().parent
        path.mkdir(parents=True, exist_ok=True)
        return path

    db_url = os.getenv("DATABASE_URL", "") or (default_db_url or "")
    sqlite_file = sqlite_file_from_url(db_url)
    if sqlite_file is not None:
        sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        return sqlite_file.parent

    fallback = Path.cwd().resolve() / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _extract_version_label(folder: Path) -> str:
    for part in (folder.name, folder.parent.name):
        match = _VERSION_RE.search(part)
        if match:
            ver = match.group(1)
            return ver if ver.lower().startswith("v") else f"v{ver}"
    return "v0.4.0"


def find_legacy_databases(
    release_dir: Path,
    target_data_dir: Path,
    user_home: Path | None = None,
) -> list[Path]:
    """
    Procura `data/autosend.db` (com tamanho > 0) na pasta da release, na pasta pai e nas
    pastas conhecidas do usuário (Downloads, Área de Trabalho/Desktop, Documentos/Documents).
    """
    release_dir = release_dir.resolve()
    target_db = (target_data_dir / DB_FILENAME).resolve()
    seen: set[Path] = set()
    found: list[Path] = []

    def _add_if_valid(db_candidate: Path) -> None:
        try:
            resolved = db_candidate.resolve()
        except OSError:
            return
        if resolved == target_db or resolved in seen:
            return
        if resolved.is_file() and resolved.stat().st_size > 0:
            seen.add(resolved)
            found.append(resolved)

    # 1. Na própria pasta de onde a versão foi extraída
    _add_if_valid(release_dir / "data" / DB_FILENAME)

    # 2. Pastas vizinhas e pastas conhecidas do usuário
    search_roots: list[Path] = []
    if release_dir.parent != release_dir:
        search_roots.append(release_dir.parent)

    home = (user_home or Path.home()).resolve()
    for folder_name in (
        "Downloads",
        "Desktop",
        "Área de Trabalho",
        "Area de Trabalho",
        "Documents",
        "Documentos",
    ):
        candidate_root = home / folder_name
        if candidate_root.is_dir():
            search_roots.append(candidate_root)

    for root in search_roots:
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            low = entry.name.lower()
            if low.startswith("auto-send") or low.startswith("autosend"):
                _add_if_valid(entry / "data" / DB_FILENAME)

    return found


def import_legacy_data_if_needed(
    target_data_dir: Path,
    release_dir: Path,
    *,
    user_home: Path | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Path | None:
    """
    Se `target_data_dir/autosend.db` ainda não existir, procura um banco anterior.
    - Se `release_dir/data/autosend.db` existir na própria pasta da release e o console não for
      interativo (EOF), importa direto preservando o original.
    - Se encontrar em outra pasta (ou com console interativo), pergunta:
      `Encontrei dados da versão X em <pasta>. Importar? (S/N)`
    - Com S, copia `autosend.db` (e `media_temp`, se houver) mantendo os originais intactos.
    - Com N ou sem achar, explica como copiar a pasta `data` e começa vazio.
    """
    target_data_dir = target_data_dir.resolve()
    target_data_dir.mkdir(parents=True, exist_ok=True)
    target_db = target_data_dir / DB_FILENAME
    if target_db.is_file() and target_db.stat().st_size > 0:
        return None

    candidates = find_legacy_databases(release_dir, target_data_dir, user_home=user_home)
    if not candidates:
        output_fn(
            f"[i] Nenhum banco anterior encontrado. Pasta de dados: {target_data_dir}\n"
            f"    Se você tinha dados de uma versão antiga em outra pasta, copie o arquivo "
            f"'data\\{DB_FILENAME}' dela para '{target_data_dir}'."
        )
        return None

    chosen_db = candidates[0]
    source_data_dir = chosen_db.parent
    source_root = source_data_dir.parent
    version_label = _extract_version_label(source_root)
    is_in_release_dir = source_root.resolve() == release_dir.resolve()

    prompt = f"Encontrei dados da versão {version_label} em {source_root}. Importar? (S/N): "
    try:
        answer = input_fn(prompt).strip().lower()
    except EOFError:
        answer = "s" if is_in_release_dir else "n"

    if answer == "" and is_in_release_dir:
        answer = "s"

    if answer in ("s", "sim", "y", "yes"):
        shutil.copy2(chosen_db, target_db)
        src_media = source_data_dir / "media_temp"
        dst_media = target_data_dir / "media_temp"
        if src_media.is_dir():
            dst_media.mkdir(parents=True, exist_ok=True)
            for item in src_media.iterdir():
                if item.is_file() and item.name != ".gitkeep":
                    shutil.copy2(item, dst_media / item.name)
        output_fn(f"[OK] Dados importados de {source_data_dir} para {target_data_dir} (original preservado).")
        return chosen_db

    output_fn(
        f"[i] Importação ignorada. Para importar depois, copie '{chosen_db}' para '{target_db}'."
    )
    return None


def open_data_directory(data_dir: Path) -> bool:
    """Abre a pasta de dados no explorador de arquivos do sistema, quando suportado."""
    data_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32" and hasattr(os, "startfile"):
        try:
            os.startfile(str(data_dir))  # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", str(data_dir)])
            return True
        except OSError:
            return False
    return False


def main() -> None:
    data_dir = resolve_data_dir()
    import_legacy_data_if_needed(data_dir, Path.cwd())


if __name__ == "__main__":
    main()
