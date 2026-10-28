#!/usr/bin/env bash
# Verificação local completa: os mesmos checks do ci.yml, rodados antes de abrir o PR.
# Cole o resumo final na descrição do PR (AGENTS.md, Ciclo de Trabalho §3).
#
#   bash scripts/dev/verify.sh          # tudo; a mutação só roda se o domínio mudou em relação à origin/main
#   bash scripts/dev/verify.sh --all    # força a mutação também
#
# Não cobre o smoke Windows (container Windows não roda no WSL): ele roda no release.yml antes de publicar.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS="$ROOT/.tools"
GITLEAKS_VERSION="8.24.3"
# sha256 publicado em gitleaks_8.24.3_checksums.txt para o tarball linux_x64.
GITLEAKS_SHA256="9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c"
# Chromium do Playwright dentro de node_modules (persiste entre sessões do ai-jail).
export PLAYWRIGHT_BROWSERS_PATH=0

FORCE_MUTATION=false
[[ "${1:-}" == "--all" ]] && FORCE_MUTATION=true

results=()
failed=0

step() {
  local name="$1"
  shift
  echo -e "\n===== $name"
  if (cd "$ROOT" && "$@"); then
    results+=("PASS  $name")
  else
    results+=("FAIL  $name")
    failed=1
  fi
}

gitleaks_bin() {
  local bin="$TOOLS/gitleaks-$GITLEAKS_VERSION/gitleaks"
  if [[ ! -x "$bin" ]]; then
    local tgz
    tgz="$(mktemp)"
    curl -fsSL -o "$tgz" "https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VERSION/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" || return 1
    if [[ "$(sha256sum "$tgz" | cut -d' ' -f1)" != "$GITLEAKS_SHA256" ]]; then
      echo "gitleaks: sha256 não confere, download descartado" >&2
      rm -f "$tgz"
      return 1
    fi
    mkdir -p "$(dirname "$bin")"
    tar -xzf "$tgz" -C "$(dirname "$bin")" gitleaks
    rm -f "$tgz"
  fi
  echo "$bin"
}

# Arquivos que o mutmut deve mutar (scripts/dev/mutation_targets.py): ALL, lista separada por vírgula ou vazio.
# Como o CI, mas olhando também o que ainda não foi commitado (mudanças e arquivos novos).
mutation_targets() {
  local flags=()
  $FORCE_MUTATION && flags=(--full)
  git -C "$ROOT" fetch -q origin main 2>/dev/null
  {
    git -C "$ROOT" diff --name-only origin/main...
    git -C "$ROOT" diff --name-only HEAD
    git -C "$ROOT" ls-files --others --exclude-standard
  } | sort -u | python3 "$ROOT/scripts/dev/mutation_targets.py" "${flags[@]}"
}

run_mutation() {
  bash "$ROOT/scripts/dev/mutation.sh" "$1"
}

run_gitleaks() {
  local bin
  bin="$(gitleaks_bin)" || return 1
  git fetch -q origin main 2>/dev/null
  # Como no CI: só os commits da branch que ainda não estão na main.
  "$bin" git --no-banner --redact --log-opts="origin/main..HEAD" .
}

step "Backend: cobertura 100% (domínio e aplicação)" \
  bash -c 'cd backend && uv run pytest -q --cov=src/domain --cov=src/application --cov-fail-under=100 tests/unit'
step "Backend: suíte completa (unit, integração, contrato OpenAPI)" bash -c 'cd backend && uv run pytest -q'
targets="$(mutation_targets)"
if [[ -n "$targets" ]]; then
  step "Backend: mutação do domínio (0 sobreviventes; ${targets})" run_mutation "$targets"
else
  results+=("SKIP  Backend: mutação do domínio (nenhum arquivo de domínio alterado; --all força)")
fi
step "Frontend: lint" bash -c 'cd frontend && npm run lint'
step "Frontend: build de produção" bash -c 'cd frontend && npm run build'
step "Frontend: E2E (Playwright)" bash -c 'cd frontend && npx playwright test'
step "Aplicação real (Playwright + backend real)" bash -c 'cd frontend && npm run test:real-app'
run_pip_audit() {
  local req rc
  req="$(mktemp)"
  (cd backend && uv export --frozen --no-hashes --no-dev --format requirements-txt > "$req" && uvx pip-audit@2.10.1 -r "$req")
  rc=$?
  rm -f "$req"
  return $rc
}

step "Segurança: pip-audit" run_pip_audit
step "Segurança: bandit" bash -c 'cd backend && uvx bandit@1.9.4 -q -r src -ll'
step "Segurança: npm audit" bash -c 'cd frontend && npm audit --omit=dev --audit-level=high'
step "Segurança: gitleaks (commits da branch)" run_gitleaks

# Artefatos gerados pelos passos acima (AGENTS.md §6).
rm -rf "$ROOT/frontend/test-results" "$ROOT/frontend/out"

echo -e "\n===== Resumo ($(git -C "$ROOT" rev-parse --short HEAD))"
printf '%s\n' "${results[@]}"
exit $failed
