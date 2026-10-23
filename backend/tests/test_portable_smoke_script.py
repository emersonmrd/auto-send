from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_test_portable.ps1"


def test_smoke_script_is_ascii_so_windows_powershell_reads_it_as_written():
    # O Windows PowerShell 5.1 do servercore lê .ps1 sem BOM como ANSI: acento vira lixo.
    data = SMOKE_SCRIPT.read_bytes()

    assert not data.startswith(b"\xef\xbb\xbf")
    assert all(byte < 128 for byte in data), [
        (n, line) for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1) if not line.isascii()
    ]
