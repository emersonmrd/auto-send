from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
# Pacote portátil (~100 MB por execução): 1 dia. Diagnóstico pequeno (resultado do Playwright numa falha, ~1 MB):
# até 7, para dar tempo de baixar com `gh run download` (AGENTS.md §3).
MAX_RETENTION_DAYS = {"AutoSend-Portable": 1, "playwright-test-results": 7}


def _upload_steps():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                    yield f"{path.name}:{job_name}", step.get("with") or {}


def test_every_uploaded_artifact_has_a_short_known_retention():
    # Os .zip do pacote portátil por 7 dias encheram 90% do storage do Actions (2026-10-29). A release baixa o .zip
    # na mesma execução e anexa uma cópia permanente à GitHub Release, então 1 dia basta. A retenção do repositório
    # (Settings → Actions) fica em 90: ela também guarda o histórico de execuções, que a trava
    # "Require green CI on the tagged commit" do release.yml consulta.
    steps = list(_upload_steps())
    assert steps, "nenhum actions/upload-artifact encontrado nos workflows"
    found = {(where, w.get("name")): w.get("retention-days") for where, w in steps}
    wrong = {k: days for k, days in found.items() if days is None or days > MAX_RETENTION_DAYS.get(k[1], 0)}
    assert wrong == {}, "artefato sem retenção conhecida, ou acima do teto de MAX_RETENTION_DAYS"
