"""Escolhe o que o mutmut muta a partir dos arquivos alterados (um caminho por linha, na entrada padrão).

Imprime "ALL" (domínio inteiro), os arquivos de domínio alterados separados por vírgula, relativos a backend/
(o formato de `mutmut run --paths-to-mutate`), ou nada quando não há o que mutar. Usado pelo CI e pelo verify.sh.
    git diff --name-only origin/main... | python3 scripts/dev/mutation_targets.py [--full]
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# Mudanças que podem enfraquecer a morte de mutantes em qualquer módulo: muta tudo.
MUTATE_ALL = re.compile(r"^backend/(pyproject\.toml|tests/unit/test_.*_domain\.py|tests/test_mutation_audit\.py)$")


def mutated_dirs() -> list[str]:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]
    return [p.strip().rstrip("/") + "/" for p in config["paths_to_mutate"].split(",") if p.strip()]


def select(changed: list[str], full: bool) -> str:
    if full or any(MUTATE_ALL.match(path) for path in changed):
        return "ALL"
    dirs = mutated_dirs()
    files = {
        path.removeprefix("backend/")
        for path in changed
        if path.startswith("backend/")
        and path.endswith(".py")
        and any(path.removeprefix("backend/").startswith(d) for d in dirs)
        and (ROOT / path).is_file()
    }
    return ",".join(sorted(files))


if __name__ == "__main__":
    changed = [line.strip() for line in sys.stdin if line.strip()]
    print(select(changed, full="--full" in sys.argv[1:]))
