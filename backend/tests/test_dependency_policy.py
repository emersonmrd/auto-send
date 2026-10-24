import re
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "src").rglob("*.py"))
# Pacotes cujo nome de import difere do nome de distribuição.
IMPORT_NAMES = {"python-multipart": "multipart"}


def _runtime_dependencies() -> list[str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return [re.match(r"[A-Za-z0-9_.-]+", spec).group(0).lower() for spec in project["dependencies"]]


@pytest.mark.parametrize("package", _runtime_dependencies())
def test_runtime_dependency_is_used_by_the_backend(package):
    # Dependência de runtime parada vai para a imagem Docker e para o pacote portátil sem uso (issue #4).
    module = IMPORT_NAMES.get(package, package.replace("-", "_"))
    assert re.search(rf"\b{re.escape(module)}\b", SOURCE), f"{package} está em [project.dependencies], mas src/ não o usa"
