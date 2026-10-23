import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISO_DATE = re.compile(r"[\"'](\d{4}-\d{2}-\d{2})T")
SUITES = [ROOT / "backend" / "tests", ROOT / "frontend" / "tests-e2e"]


def test_tests_never_hardcode_a_future_date():
    # Uma data literal no futuro vira passado um dia e quebra a suíte inteira (ex.: scheduled_at fixo).
    today = date.today()
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}: {match}"
        for suite in SUITES
        for path in suite.rglob("*")
        if path.suffix in {".py", ".ts"}
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in ISO_DATE.findall(line)
        if date.fromisoformat(match) > today
    ]
    assert offenders == []
