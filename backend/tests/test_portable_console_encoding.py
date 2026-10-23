import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPTS = [
    ROOT / "scripts" / "bundle_portable_windows.py",
    ROOT / "scripts" / "setup_windows_binaries.py",
    ROOT / "scripts" / "setup_windows_python_embed.py",
]


def _non_cp1252_chars(source: str) -> str:
    chars = []
    for ch in sorted(set(source)):
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            chars.append(ch)
    return "".join(chars)


def test_build_scripts_print_their_messages_on_a_cp1252_console():
    # O runner windows-latest abre o stdout em cp1252; o v0.1.0 morreu no primeiro "📦".
    text = "".join(_non_cp1252_chars(p.read_text(encoding="utf-8")) for p in BUILD_SCRIPTS)
    assert text, "os scripts imprimem emojis; sem eles este teste não reproduz nada"
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from scripts.console_encoding import use_utf8_console;"
        "use_utf8_console(); print(sys.argv[2])"
    )
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}

    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT), text], env=env, capture_output=True
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.decode("utf-8").strip() == text


def test_every_build_script_switches_the_console_before_main():
    for script in BUILD_SCRIPTS:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        guard = next(
            node
            for node in tree.body
            if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)
        )
        calls = [ast.unparse(stmt) for stmt in guard.body]
        assert calls[:2] == ["use_utf8_console()", "main()"], f"{script.name}: {calls}"
