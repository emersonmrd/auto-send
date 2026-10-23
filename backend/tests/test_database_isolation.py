from pathlib import Path

from src.presentation import main


def test_suite_never_uses_the_app_database():
    assert Path(main.engine.url.database).resolve() != (main.BASE_DIR / "auto_send.db").resolve()


def test_suite_never_uses_the_app_media_dir():
    assert Path(main.TEMP_MEDIA_DIR).resolve() != Path(main.DEFAULT_TEMP_DIR).resolve()
