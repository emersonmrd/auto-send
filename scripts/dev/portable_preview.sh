#!/usr/bin/env bash
# Preview do pacote portátil Windows gerado no WSL, para o usuário testar antes da release.
# Reaproveita python/ e bin/ (Python embutido com dependências, runtime do VC++, telegram-bot-api, FFmpeg)
# do .zip publicado na última tag, que foi gerado e testado no Windows, e troca só o app/ pelo código atual.
#
#   bash scripts/dev/portable_preview.sh           # base: última tag
#   bash scripts/dev/portable_preview.sh v0.6.1    # base: tag escolhida
#
# Se as dependências ou o setup do Python embutido e dos binários mudaram desde a tag, python/ e bin/ não servem mais:
# o script recusa, e o pacote sai do CI pelo label windows-build (AGENTS.md, Ciclo de Trabalho §3).
# Não passa pelo smoke test num Windows limpo; esse roda só no CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="${1:-$(git describe --tags --abbrev=0)}"
# python/ e bin/ saem destes scripts; as dependências são conferidas adiante pelo requirements.txt.
BASE_INPUTS=(
  scripts/setup_windows_binaries.py
  scripts/setup_windows_python_embed.py
)
# Compara com a árvore de trabalho, para pegar também o que ainda não foi commitado.
if ! git diff --quiet "$TAG" -- "${BASE_INPUTS[@]}"; then
  echo "❌ Dependências ou build do pacote mudaram desde $TAG:" >&2
  git diff --stat "$TAG" -- "${BASE_INPUTS[@]}" >&2
  echo "   python/ e bin/ de $TAG não servem; gere o pacote no CI com o label windows-build." >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "📥 Baixando o pacote de $TAG..."
gh release download "$TAG" -p AutoSend-Portable.zip -D "$WORK"

echo "🏗️  Gerando app/ do código atual..."
python3 scripts/bundle_portable_windows.py --skip-binaries --skip-python --output-dir "$WORK/new/AutoSend-Portable"

PKG="$WORK/out/AutoSend-Portable"
mkdir -p "$WORK/out"
unzip -q "$WORK/AutoSend-Portable.zip" -d "$WORK/out"
# O Python embutido de $TAG precisa ter exatamente as dependências que o app novo pede.
if ! diff "$PKG/app/backend/requirements.txt" "$WORK/new/AutoSend-Portable/app/backend/requirements.txt" >&2; then
  echo "❌ Dependências mudaram desde $TAG; gere o pacote no CI com o label windows-build." >&2
  exit 1
fi
rm -rf "$PKG/app"
cp -r "$WORK/new/AutoSend-Portable/app" "$PKG/app"
cp "$WORK/new/AutoSend-Portable/"{Iniciar-AutoSend.bat,COMO_USAR.txt,LICENSE,THIRD_PARTY_NOTICES.md} "$PKG/"

OUT="dist/AutoSend-Portable-preview-$(git rev-parse --short HEAD).zip"
mkdir -p dist
python3 -I - "$WORK/out" "$OUT" <<'EOF'
import os
import sys
import zipfile

root, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for d, _, files in os.walk(os.path.join(root, "AutoSend-Portable")):
        z.write(d, os.path.relpath(d, root))
        for f in files:
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, root))
with zipfile.ZipFile(out) as z:
    if z.testzip() is not None:
        sys.exit(f"❌ {out} corrompido")
EOF
echo "✅ Preview: $OUT (base $TAG; sem o smoke test Windows, que roda só no CI)"
