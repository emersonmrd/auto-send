import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "mutation_targets.py"


def targets(*changed: str, full: bool = False) -> str:
    args = [sys.executable, str(SCRIPT)] + (["--full"] if full else [])
    result = subprocess.run(args, input="\n".join(changed), capture_output=True, text=True, check=True, cwd=ROOT)
    return result.stdout.strip()


def test_pr_touching_one_domain_file_mutates_only_that_file():
    assert targets("backend/src/domain/channels/chat_discovery.py", "frontend/src/app/page.tsx") == "src/domain/channels/chat_discovery.py"


def test_several_domain_files_are_joined_with_commas_in_a_stable_order():
    assert targets(
        "backend/src/domain/profiles/profile.py",
        "backend/src/domain/channels/channel.py",
    ) == "src/domain/channels/channel.py,src/domain/profiles/profile.py"


def test_pr_without_domain_changes_skips_mutation():
    assert targets("frontend/src/app/page.tsx", "backend/src/presentation/main.py", "CHANGELOG.md") == ""


@pytest.mark.parametrize(
    "changed",
    [
        "backend/pyproject.toml",  # configuração do mutmut ou dependências
        "backend/tests/unit/test_chat_discovery_domain.py",  # teste mais fraco pode deixar mutante vivo em qualquer módulo
        "backend/tests/test_mutation_audit.py",
    ],
)
def test_changes_that_can_weaken_any_module_mutate_everything(changed):
    assert targets(changed) == "ALL"


def test_full_flag_mutates_everything():
    assert targets(full=True) == "ALL"
    assert targets("frontend/src/app/page.tsx", full=True) == "ALL"


def test_files_outside_the_mutated_paths_are_ignored():
    # As portas são ABCs sem comportamento e ficam fora de [tool.mutmut] paths_to_mutate.
    assert targets("backend/src/domain/ports/chat_discovery_gateway.py") == ""


def test_deleted_or_non_python_files_are_ignored():
    assert targets("backend/src/domain/channels/removido.py", "backend/src/domain/channels/README.md") == ""
