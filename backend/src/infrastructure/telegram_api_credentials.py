"""Gerenciamento e persistência das credenciais da Telegram Bot API (#56).

Salva e carrega TELEGRAM_API_ID e TELEGRAM_API_HASH no arquivo .env dentro da pasta de
dados ativa (no Windows: %LOCALAPPDATA%\\Auto-Send\\.env), garantindo sobrevivência
a atualizações de versão e novas pastas de extração do pacote portátil.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

from src.infrastructure.portable_data import resolve_data_dir

logger = logging.getLogger(__name__)


def get_env_file_path() -> Path:
    """Retorna o caminho do arquivo .env dentro da pasta de dados ativa."""
    return resolve_data_dir() / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    res: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k:
                    res[k] = v
    except OSError as exc:
        logger.warning(f"Erro ao ler arquivo .env em {path}: {exc}")
    return res


def load_telegram_credentials_from_data_dir() -> Tuple[str, str]:
    """
    Carrega TELEGRAM_API_ID e TELEGRAM_API_HASH do arquivo .env da pasta de dados.
    Caso não exista na pasta de dados, tenta encontrar na raiz do projeto (desenvolvimento).
    Atualiza os.environ caso encontrados.
    """
    env_path = get_env_file_path()
    vars_dict = _parse_env_file(env_path)

    # Fallback para desenvolvimento na raiz do projeto
    if not vars_dict:
        fallback_roots = [Path.cwd(), Path.cwd().parent]
        for root in fallback_roots:
            candidate = root / ".env"
            if candidate.is_file():
                vars_dict = _parse_env_file(candidate)
                if vars_dict:
                    break

    api_id = vars_dict.get("TELEGRAM_API_ID", "").strip()
    api_hash = vars_dict.get("TELEGRAM_API_HASH", "").strip()

    if api_id:
        os.environ["TELEGRAM_API_ID"] = api_id
    if api_hash:
        os.environ["TELEGRAM_API_HASH"] = api_hash

    return api_id, api_hash


def save_telegram_credentials_to_data_dir(api_id: str, api_hash: str) -> Path:
    """
    Grava TELEGRAM_API_ID e TELEGRAM_API_HASH no .env da pasta de dados ativa,
    preservando outras variáveis que já existiam no arquivo.
    Atualiza os.environ imediatamente.
    """
    env_path = get_env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    keys_updated = {"TELEGRAM_API_ID": False, "TELEGRAM_API_HASH": False}

    if env_path.is_file():
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = raw_line.strip()
                if stripped.startswith("TELEGRAM_API_ID="):
                    lines.append(f"TELEGRAM_API_ID={api_id.strip()}")
                    keys_updated["TELEGRAM_API_ID"] = True
                elif stripped.startswith("TELEGRAM_API_HASH="):
                    lines.append(f"TELEGRAM_API_HASH={api_hash.strip()}")
                    keys_updated["TELEGRAM_API_HASH"] = True
                else:
                    lines.append(raw_line)
        except OSError as exc:
            logger.warning(f"Erro ao ler .env existente em {env_path}: {exc}")
            lines = []

    if not lines:
        lines = [
            "# Auto-Send - Credenciais da Telegram API para Local Bot API (Upload até 2 GB)",
            "# Obtidas em https://my.telegram.org",
        ]

    if not keys_updated["TELEGRAM_API_ID"]:
        lines.append(f"TELEGRAM_API_ID={api_id.strip()}")
    if not keys_updated["TELEGRAM_API_HASH"]:
        lines.append(f"TELEGRAM_API_HASH={api_hash.strip()}")

    content = "\n".join(lines).strip() + "\n"
    env_path.write_text(content, encoding="utf-8")

    # Atualiza variáveis em memória
    if api_id.strip():
        os.environ["TELEGRAM_API_ID"] = api_id.strip()
    else:
        os.environ.pop("TELEGRAM_API_ID", None)

    if api_hash.strip():
        os.environ["TELEGRAM_API_HASH"] = api_hash.strip()
    else:
        os.environ.pop("TELEGRAM_API_HASH", None)

    return env_path
