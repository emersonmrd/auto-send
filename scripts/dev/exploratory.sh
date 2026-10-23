#!/usr/bin/env bash
# Teste exploratório do app real com o agent-browser (estilo akitaonrails/my-skills), dentro ou fora do ai-jail.
#
#   bash scripts/dev/exploratory.sh setup            # baixa agent-browser fixo + Chromium do Playwright (uma vez)
#   bash scripts/dev/exploratory.sh start            # sobe Chromium (CDP) e o app real na porta 8000
#   bash scripts/dev/exploratory.sh ab <args...>     # roda o agent-browser já conectado (open, snapshot -i, click @e3...)
#   bash scripts/dev/exploratory.sh fill-env @e5 E2E_BOT_TOKEN   # digita um segredo sem ele aparecer no comando
#   bash scripts/dev/exploratory.sh stop
#
# Tudo fica em .tools/ (ignorado pelo git). O app usa banco e mídia temporários, nunca o auto_send.db.
set -euo pipefail

AB_VERSION="0.38.2"
# Integridade publicada no registry do npm para agent-browser@0.38.2 (dist.integrity).
AB_INTEGRITY="sha512-b/7hvo2RrqocvybjB9kwpX12kGkxkFvtdJ4XPDoott5TLK2n3aPX+lYg7ALd+2YvPi2LrTKGzQYu/rxZC2Y7ZA=="
CDP_PORT=9333
APP_PORT=8000

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS="$ROOT/.tools"
RUN="$TOOLS/run"
AB_DIR="$TOOLS/agent-browser-$AB_VERSION"
AB_BIN="$AB_DIR/package/bin/agent-browser-linux-x64"
# O socket Unix do agent-browser tem limite de ~100 bytes no caminho: precisa de um diretório curto.
export AGENT_BROWSER_SOCKET_DIR="/tmp/ab-${UID}"
export AGENT_BROWSER_SKILLS_DIR="$AB_DIR/package/skill-data"
export PLAYWRIGHT_BROWSERS_PATH=0

chrome_bin() {
  ls -d "$ROOT"/frontend/node_modules/playwright-core/.local-browsers/chromium_headless_shell-*/chrome-*/chrome-headless-shell 2>/dev/null | head -1
}

ab() { "$AB_BIN" --cdp "$CDP_PORT" "$@"; }

setup() {
  mkdir -p "$TOOLS"
  if [[ ! -x "$AB_BIN" ]]; then
    local tgz="$TOOLS/agent-browser-$AB_VERSION.tgz"
    curl -fsSL -o "$tgz" "https://registry.npmjs.org/agent-browser/-/agent-browser-$AB_VERSION.tgz"
    local got="sha512-$(openssl dgst -sha512 -binary "$tgz" | base64 -w0)"
    if [[ "$got" != "$AB_INTEGRITY" ]]; then
      rm -f "$tgz"
      echo "integridade do agent-browser não confere; nada foi extraído" >&2
      exit 1
    fi
    mkdir -p "$AB_DIR" && tar -xzf "$tgz" -C "$AB_DIR" && rm -f "$tgz"
    chmod +x "$AB_BIN"
  fi
  [[ -n "$(chrome_bin)" ]] || (cd "$ROOT/frontend" && npx playwright install chromium)
  "$AB_BIN" --version
}

start() {
  mkdir -p "$RUN/media" "$AGENT_BROWSER_SOCKET_DIR"
  [[ -f "$ROOT/frontend/out/index.html" ]] || (cd "$ROOT/frontend" && NEXT_EXPORT=true npm run build)
  # Sem --no-sandbox o Chromium aborta no jail ("No usable sandbox"); o Playwright faz o mesmo por padrão.
  "$(chrome_bin)" --no-sandbox --headless --remote-debugging-port="$CDP_PORT" --no-first-run \
    --user-data-dir="$RUN/chrome-profile" about:blank >"$RUN/chrome.log" 2>&1 &
  echo $! >"$RUN/chrome.pid"
  (cd "$ROOT/backend" && \
    DATABASE_URL="sqlite+aiosqlite:///$RUN/exploratory.db" STATIC_DIR="$ROOT/frontend/out" \
    TEMP_MEDIA_DIR="$RUN/media" CORS_ORIGINS="http://localhost:$APP_PORT,http://127.0.0.1:$APP_PORT" \
    uv run uvicorn src.presentation.main:app --host 127.0.0.1 --port "$APP_PORT" >"$RUN/app.log" 2>&1 &
    echo $! >"$RUN/app.pid")
  for _ in $(seq 30); do
    curl -fs "http://127.0.0.1:$APP_PORT/api/v1/health" >/dev/null 2>&1 \
      && curl -fs "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fs "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null || { echo "Chromium não abriu a porta CDP; veja $RUN/chrome.log" >&2; exit 1; }
  curl -fs "http://127.0.0.1:$APP_PORT/api/v1/health" && echo
  echo "app: http://localhost:$APP_PORT  log: $RUN/app.log"
}

stop() {
  # O daemon do agent-browser sobrevive entre comandos; preso a um Chromium encerrado, ele perde as refs @eN.
  "$AB_BIN" close >/dev/null 2>&1 || true
  for pid in "$RUN/app.pid" "$RUN/chrome.pid"; do
    [[ -f "$pid" ]] && kill "$(cat "$pid")" 2>/dev/null || true
    rm -f "$pid"
  done
  echo "app e Chromium encerrados"
}

fill_env() {
  local ref="$1" var="$2"
  [[ -n "${!var:-}" ]] || { echo "variável $var vazia ou ausente" >&2; exit 1; }
  ab fill "$ref" "${!var}" >/dev/null
  echo "campo $ref preenchido com \$$var"
}

cmd="${1:-}"
shift || true
case "$cmd" in
  setup) setup ;;
  start) start ;;
  stop) stop ;;
  ab) ab "$@" ;;
  fill-env) fill_env "$@" ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
