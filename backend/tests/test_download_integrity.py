import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import setup_windows_binaries as binaries  # noqa: E402
from scripts import setup_windows_python_embed as embed  # noqa: E402
from scripts.download_integrity import IntegrityError, verify_sha256  # noqa: E402

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_verify_sha256_accepts_the_expected_digest(tmp_path):
    artifact = tmp_path / "a.zip"
    artifact.write_bytes(b"conteudo")
    verify_sha256(artifact, hashlib.sha256(b"conteudo").hexdigest())
    assert artifact.exists()


def test_verify_sha256_rejects_and_deletes_a_tampered_file(tmp_path):
    artifact = tmp_path / "a.zip"
    artifact.write_bytes(b"trocado na origem")
    with pytest.raises(IntegrityError, match="a.zip"):
        verify_sha256(artifact, hashlib.sha256(b"conteudo").hexdigest())
    assert not artifact.exists()


def test_every_download_has_a_pinned_checksum():
    for digest in (binaries.TELEGRAM_API_SHA256, binaries.FFMPEG_SHA256, embed.PYTHON_EMBED_SHA256, embed.GET_PIP_SHA256):
        assert SHA256.match(digest)
    # get-pip.py fixado num commit: a URL "bootstrap.pypa.io/get-pip.py" muda a cada release do pip
    assert re.search(r"/pypa/get-pip/[0-9a-f]{40}/", embed.GET_PIP_URL)


def _fake_download(*args, **kwargs):
    dest = next(a for a in args if isinstance(a, Path))
    dest.write_bytes(b"binario adulterado")


def test_binaries_are_not_extracted_when_the_checksum_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(binaries, "download_with_progress", _fake_download)
    with pytest.raises(IntegrityError):
        binaries.setup_windows_binaries(bin_dir=tmp_path / "bin", force=True)
    assert not any((tmp_path / "bin").iterdir())


def test_embedded_python_is_not_extracted_when_the_checksum_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "download_file", _fake_download)
    with pytest.raises(IntegrityError):
        embed.setup_embed_python(tmp_path / "python", install_pip=False)
    assert not (tmp_path / "python" / "python.exe").exists()
