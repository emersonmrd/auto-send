"""Verificação de integridade dos artefatos baixados para o pacote portátil (issue #10)."""

import hashlib
from pathlib import Path


class IntegrityError(RuntimeError):
    """O arquivo baixado não tem o SHA-256 fixado no código."""


def verify_sha256(path: Path, expected: str) -> None:
    """Confere o SHA-256 antes de qualquer extração; em divergência apaga o arquivo e falha."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected.lower():
        path.unlink(missing_ok=True)
        raise IntegrityError(f"SHA-256 divergente para {path.name}: esperado {expected}, obtido {actual}")
