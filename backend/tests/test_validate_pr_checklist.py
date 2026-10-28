import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "validate_pr_checklist.py"

# Importa a função diretamente adicionando ao path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dev.validate_pr_checklist import validate_pr_body  # noqa: E402


def test_empty_or_none_body_fails():
    ok, msg = validate_pr_body("")
    assert not ok
    assert "vazia" in msg

    ok, msg = validate_pr_body(None)
    assert not ok
    assert "vazia" in msg


def test_missing_checklist_heading_fails():
    body = """
    ## Contexto
    Esta PR faz uma melhoria.
    
    ## O que foi feito
    - Mudança X
    """
    ok, msg = validate_pr_body(body)
    assert not ok
    assert "## Checklist" in msg


def test_missing_user_merge_checkbox_fails():
    body = """
    ## Contexto
    Melhoria importante.
    
    ## Checklist
    - [x] test-driven-development: RED -> GREEN
    - [x] verification-before-completion: verify.sh
    """
    ok, msg = validate_pr_body(body)
    assert not ok
    assert "merge pelo usuário" in msg


def test_missing_checked_skills_fails():
    body = """
    ## Contexto
    Melhoria importante.
    
    ## Checklist
    - [ ] test-driven-development: não feito
    - [ ] merge pelo usuário
    """
    ok, msg = validate_pr_body(body)
    assert not ok
    assert "ao menos uma skill" in msg


def test_valid_checklist_with_skills_and_merge_passes():
    body = """
    ## Contexto
    Melhoria importante.
    
    ## Checklist
    Type: feat
    Scan: none
    - [x] test-driven-development: teste de migração adicionado
    - [x] verification-before-completion: verify.sh 100% PASS
    - [ ] merge pelo usuário
    """
    ok, msg = validate_pr_body(body)
    assert ok
    assert "validado com sucesso" in msg.lower()


def test_cli_execution_via_env_var_returns_correct_exit_codes():
    valid_body = "## Checklist\n- [x] verification-before-completion: PASS\n- [ ] merge pelo usuário"
    res = subprocess.run([sys.executable, str(SCRIPT)], env={"PR_BODY": valid_body}, capture_output=True, text=True)
    assert res.returncode == 0
    assert "validado com sucesso" in res.stdout.lower()

    invalid_body = "## Contexto sem checklist"
    res = subprocess.run([sys.executable, str(SCRIPT)], env={"PR_BODY": invalid_body}, capture_output=True, text=True)
    assert res.returncode == 1
    assert "::error::" in res.stderr
