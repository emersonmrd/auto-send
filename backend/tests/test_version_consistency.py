import json
import tomllib
from pathlib import Path

from src.presentation.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_version_matches_every_version_source():
    backend = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text())["project"]["version"]
    frontend = json.loads((REPO_ROOT / "frontend" / "package.json").read_text())["version"]

    assert app.version == backend == frontend
