import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted(p for p in ROOT.glob("**/Dockerfile") if "node_modules" not in p.parts)
# Registros e imagens oficiais aceitos (AGENTS.md §8): Docker Official Images, Microsoft e o uv da Astral.
TRUSTED = re.compile(r"^(python|node|mcr\.microsoft\.com/windows/(servercore|server|nanoserver)|ghcr\.io/astral-sh/uv)[:@]")
ROOT_USERS = {"root", "0", "containeradministrator"}


def _images(dockerfile: Path) -> list[str]:
    text = dockerfile.read_text(encoding="utf-8")
    stages = {m.group(1).lower() for m in re.finditer(r"^FROM\s+\S+\s+AS\s+(\S+)", text, re.M | re.I)}
    refs = re.findall(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", text, re.M | re.I)
    refs += re.findall(r"COPY\s+--from=(\S+)", text, re.I)
    return [ref for ref in refs if ref.lower() not in stages]


def test_repository_has_dockerfiles():
    assert len(DOCKERFILES) >= 3


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_images_are_official_and_pinned(dockerfile):
    for image in _images(dockerfile):
        assert TRUSTED.match(image), f"imagem fora da lista de oficiais: {image}"
        tag = image.split("@")[0].rpartition(":")[2] if ":" in image.split("@")[0] else ""
        assert tag and tag != "latest", f"imagem sem tag fixa: {image}"
        # A tag diz a versão para quem lê; o digest garante que é a mesma imagem (o Dependabot atualiza os dois).
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"imagem sem digest: {image}"


def test_compose_images_are_pinned_by_tag_and_digest():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    images = re.findall(r"^\s*image:\s*(\S+)", compose, re.M)

    assert images
    for image in images:
        assert re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", image), f"imagem sem tag + digest: {image}"


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_final_stage_runs_without_admin_rights(dockerfile):
    text = dockerfile.read_text(encoding="utf-8")
    final_stage = re.split(r"^FROM\s", text, flags=re.M | re.I)[-1]
    users = re.findall(r"^USER\s+(\S+)", final_stage, re.M | re.I)

    assert users, "o estágio final não declara USER e roda como root/administrador"
    assert users[-1].split(":")[0].lower() not in ROOT_USERS
