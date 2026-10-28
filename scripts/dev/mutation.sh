#!/usr/bin/env bash
# Mutação do domínio com mutmut 2 (AGENTS.md, Ciclo de Trabalho §3). Único caminho local: o verify.sh chama este script.
#
#   bash scripts/dev/mutation.sh src/domain/channels/channel.py,src/domain/channels/chat_discovery.py
#   bash scripts/dev/mutation.sh ALL
#
# Não rode `mutmut run` direto: sem o .mutmut-cache em WAL com busy_timeout, a execução morre no meio em silêncio e
# deixa mutantes sem testar (kaizen de 2026-10-28, #99: 40 mutantes "Untested/skipped" depois de 15 min de espera).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
targets="${1:?uso: mutation.sh <arquivos separados por vírgula | ALL>}"
args=()
[[ "$targets" != ALL ]] && args=(--paths-to-mutate "$targets")

# O mutmut roda sem saída; sem este aviso, quem acompanha o log acha que travou (kaizen de 2026-10-28).
if [[ "$targets" == ALL ]]; then
  echo "Mutando o domínio inteiro; leva ~20 min sem imprimir nada até o fim."
else
  echo "Mutando: $targets (sem saída até o fim)."
fi
cd "$ROOT/backend" || exit 1
rm -f .mutmut-cache*
python3 -c "import sqlite3; c = sqlite3.connect('.mutmut-cache'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=60000'); c.close()"
uvx --from mutmut==2.5.1 mutmut run --no-progress "${args[@]}" >/dev/null
rc=$?
results="$(uvx --from mutmut==2.5.1 mutmut results)"
rm -f .mutmut-cache*
echo "$results" | sed -n '/Survived\|Timed out\|Untested/,$p'
# Código de saída do mutmut 2 é bitmask: 1 fatal, 2 sobreviventes, 4 timeout, 8 suspeito (morto, só lento).
if (( (rc & 7) != 0 )); then
  echo "mutmut terminou com código $rc." >&2
  exit 1
fi
# Execução que morre no meio sai com 0 e deixa mutantes sem rodar: isso também reprova.
if grep -q "Untested/skipped" <<<"$results"; then
  echo "Há mutantes sem testar: a execução parou no meio. Rode de novo; não conte como 0 sobreviventes." >&2
  exit 1
fi
echo "0 sobreviventes, 0 timeouts, 0 sem testar."
