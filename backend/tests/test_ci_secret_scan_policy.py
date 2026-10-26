import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
VERIFY = ROOT / "scripts" / "dev" / "verify.sh"
# O binário pode vir entre aspas ("$RUNNER_TEMP/gitleaks" git ...).
GITLEAKS_GIT = re.compile(r'gitleaks"?\s+git\b')


def _secret_scan_steps() -> list[dict]:
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return workflow["jobs"]["security-scan"]["steps"]


def _verify_pin(name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', VERIFY.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{name} não encontrado em scripts/dev/verify.sh"
    return match.group(1)


def test_push_to_main_scans_the_whole_git_history():
    # Issue #41: no push, o gitleaks-action verificava 0 commits; o histórico nunca passava pelo scanner.
    full_scans = [
        step for step in _secret_scan_steps()
        if GITLEAKS_GIT.search(step.get("run", "")) and "--log-opts" not in step["run"]
    ]

    assert len(full_scans) == 1, "falta o passo que varre o histórico inteiro com o gitleaks"
    step = full_scans[0]
    assert step.get("if") == "github.event_name != 'pull_request'"
    assert "--redact" in step["run"]


def test_full_history_scan_uses_the_same_pinned_and_verified_gitleaks_as_verify_sh():
    step = next(s for s in _secret_scan_steps() if GITLEAKS_GIT.search(s.get("run", "")))
    env = step.get("env", {})

    assert env.get("GITLEAKS_VERSION") == _verify_pin("GITLEAKS_VERSION")
    assert env.get("GITLEAKS_SHA256") == _verify_pin("GITLEAKS_SHA256")
    assert "sha256sum -c" in step["run"]


def test_gitleaks_action_runs_only_on_pull_requests():
    # No PR a action varre só os commits do PR (rápido); fora dele ela não verifica nada.
    action_steps = [s for s in _secret_scan_steps() if s.get("uses", "").startswith("gitleaks/gitleaks-action@")]

    assert len(action_steps) == 1
    assert action_steps[0].get("if") == "github.event_name == 'pull_request'"


def test_security_scan_checks_out_the_full_history():
    checkout = next(s for s in _secret_scan_steps() if s.get("uses", "").startswith("actions/checkout@"))

    assert checkout.get("with", {}).get("fetch-depth") == 0
