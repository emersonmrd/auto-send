import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bundle_portable_windows import export_runtime_requirements  # noqa: E402


def _locked_version(package: str) -> str:
    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text())
    return next(p["version"] for p in lock["package"] if p["name"] == package)


def test_portable_requirements_pin_the_lockfile_versions():
    requirements = export_runtime_requirements()

    assert f"fastapi=={_locked_version('fastapi')}" in requirements
    assert f"pydantic-core=={_locked_version('pydantic-core')}" in requirements
    pinned = [line for line in requirements.splitlines() if line and not line.startswith(("#", " "))]
    assert pinned and all("==" in line for line in pinned)


def test_portable_requirements_leave_out_dev_dependencies():
    requirements = export_runtime_requirements()

    assert "pytest" not in requirements
    assert "schemathesis" not in requirements


def test_backend_keeps_no_hand_maintained_requirements_file():
    assert not (ROOT / "backend" / "requirements.txt").exists()
