import io
from pathlib import Path

import pytest

from src.infrastructure.temp_media_storage import MediaTooLarge, save_upload


def test_save_upload_copies_the_whole_file_and_returns_its_size(tmp_path: Path):
    dest = tmp_path / "media.mp4"
    payload = b"x" * 2500

    size = save_upload(io.BytesIO(payload), str(dest), max_bytes=2500, chunk_size=1000)

    assert size == 2500
    assert dest.read_bytes() == payload


def test_save_upload_above_the_limit_raises_and_removes_the_partial_file(tmp_path: Path):
    dest = tmp_path / "media.mp4"

    with pytest.raises(MediaTooLarge) as exc_info:
        save_upload(io.BytesIO(b"x" * 2501), str(dest), max_bytes=2500, chunk_size=1000)

    assert exc_info.value.max_bytes == 2500
    assert not dest.exists()


def test_save_upload_stops_reading_once_the_limit_is_passed(tmp_path: Path):
    # Um upload enorme não pode ser gravado inteiro antes de ser recusado.
    source = io.BytesIO(b"x" * 10_000)

    with pytest.raises(MediaTooLarge):
        save_upload(source, str(tmp_path / "media.mp4"), max_bytes=1000, chunk_size=500)

    assert source.tell() <= 1500


def test_save_upload_rejects_a_non_positive_limit(tmp_path: Path):
    with pytest.raises(ValueError):
        save_upload(io.BytesIO(b"x"), str(tmp_path / "media.mp4"), max_bytes=0)
