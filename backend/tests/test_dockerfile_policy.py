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


def _compose_ports() -> dict[str, list[str]]:
    """Mapeamentos de `ports:` por serviço do docker-compose.yml (serviço em 2 espaços, chave em 4, item em 6)."""
    ports: dict[str, list[str]] = {}
    service, in_ports = None, False
    for line in (ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^  ([\w-]+):\s*$", line):
            service, in_ports = m.group(1), False
            ports[service] = []
        elif re.match(r"^    \S", line):
            in_ports = line.strip() == "ports:"
        elif in_ports and (m := re.match(r'^\s+-\s*"?([^"\s]+)"?\s*$', line)):
            ports[service].append(m.group(1))
    return ports


def test_compose_publishes_ports_only_on_loopback():
    # A API não tem autenticação (issue #35): "8000:8000" publicaria em todas as interfaces do host,
    # e o Docker passa por cima do firewall. Abrir para a rede exige autenticação antes.
    ports = _compose_ports()
    assert {"backend", "frontend"} <= ports.keys()
    for service, mappings in ports.items():
        for mapping in mappings:
            assert mapping.startswith("127.0.0.1:"), f"{service} publica {mapping} fora do loopback"


def test_internal_telegram_bot_api_is_not_published():
    # Só o backend consome o servidor local do Telegram, pela rede do Compose.
    assert _compose_ports()["telegram-bot-api"] == []
