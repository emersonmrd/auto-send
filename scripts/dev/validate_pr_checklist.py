#!/usr/bin/env python3
"""
Validador de checklist de Pull Requests do Auto-Send.
Usado no CI (job 'Decide what to run') para garantir que nenhum PR seja aberto
ou atualizado sem a seção '## Checklist' e as skills utilizadas (AGENTS.md Ciclo de Trabalho).
"""
import os
import re
import sys


def validate_pr_body(body: str | None) -> tuple[bool, str]:
    if not body or not body.strip():
        return False, "A descrição do Pull Request está vazia."

    # Verifica presença da seção ## Checklist (permitindo indentação opcional)
    if not re.search(r"^\s*##\s+Checklist\b", body, re.MULTILINE | re.IGNORECASE):
        return False, "A descrição do Pull Request não contém a seção obrigatória '## Checklist'."

    checklist_match = re.search(r"^\s*##\s+Checklist\b.*", body, re.MULTILINE | re.IGNORECASE | re.DOTALL)
    checklist_text = checklist_match.group(0) if checklist_match else ""

    # Verifica item de merge pelo usuário
    if not re.search(r"-\s*\[[ xX]\]\s*merge\s+pelo\s+usu[áa]rio", checklist_text, re.IGNORECASE):
        return (
            False,
            "O checklist da PR deve conter o item obrigatório '- [ ] merge pelo usuário'.",
        )

    # Verifica se há pelo menos um item de skill/verificação marcado
    checked_items = re.findall(r"-\s*\[[xX]\]\s*(.+)", checklist_text)
    # Filtra o próprio 'merge pelo usuário' para garantir que há ao menos uma skill/ação técnica marcada
    skills_checked = [
        item for item in checked_items if not re.search(r"merge\s+pelo\s+usu[áa]rio", item, re.IGNORECASE)
    ]

    if not skills_checked:
        return (
            False,
            "O checklist da PR deve registrar ao menos uma skill ou verificação marcada com '- [x]' "
            "(ex.: '- [x] test-driven-development: ...', '- [x] verification-before-completion: ...').",
        )

    return True, "Checklist da PR validado com sucesso."


def main() -> int:
    body = os.environ.get("PR_BODY")
    if body is None:
        if len(sys.argv) > 1:
            body = sys.argv[1]
        elif not sys.stdin.isatty():
            body = sys.stdin.read()
        else:
            body = ""

    ok, message = validate_pr_body(body)
    if not ok:
        print(f"::error::{message}", file=sys.stderr)
        print(f"FALHA: {message}", file=sys.stderr)
        return 1

    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
