"""Console em UTF-8 para os scripts do pacote portátil.

No Windows o stdout costuma abrir em cp1252, que não tem os emojis das mensagens de progresso.
"""

import sys


def use_utf8_console() -> None:
    """Troca stdout e stderr para UTF-8; sem isso o primeiro emoji derruba o build no Windows."""
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
