import pytest
from src.presentation.main import extract_mp4_metadata
from tests.helpers import build_synthetic_mp4


# ============================================================================
# TDD Red Tests: Extração Forçada de Dimensões MP4 (Vertical 1080x1920 e Rotação)
# ============================================================================

def test_extract_mp4_metadata_vertical_native(tmp_path):
    """Extrai dimensões verticais nativas 1080x1920 de MP4 com tkhd normal (portrait)."""
    data = build_synthetic_mp4(width=1080, height=1920, duration=15)
    fpath = tmp_path / "native_vertical_1080x1920.mp4"
    fpath.write_bytes(data)

    meta = extract_mp4_metadata(str(fpath))
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["duration"] == 15


def test_extract_mp4_metadata_vertical_with_90deg_rotation_matrix(tmp_path):
    """Extrai dimensões verticais 1080x1920 quando codificado a 1920x1080 com matriz de rotação 90 graus (portrait smartphone)."""
    rot_90_matrix = [
        0, 0x00010000, 0,
        -0x00010000, 0, 0,
        0, 0, 0x40000000,
    ]
    data = build_synthetic_mp4(width=1920, height=1080, duration=8, matrix=rot_90_matrix)
    fpath = tmp_path / "rotated_90_vertical.mp4"
    fpath.write_bytes(data)

    meta = extract_mp4_metadata(str(fpath))
    # A rotação de 90 graus inverte os eixos para exibição correta vertical
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["duration"] == 8


def test_extract_mp4_metadata_vertical_with_270deg_rotation_matrix(tmp_path):
    """Extrai dimensões verticais 1080x1920 quando codificado a 1920x1080 com matriz de rotação 270 graus."""
    rot_270_matrix = [
        0, -0x00010000, 0,
        0x00010000, 0, 0,
        0, 0, 0x40000000,
    ]
    data = build_synthetic_mp4(width=1920, height=1080, duration=12, matrix=rot_270_matrix)
    fpath = tmp_path / "rotated_270_vertical.mp4"
    fpath.write_bytes(data)

    meta = extract_mp4_metadata(str(fpath))
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert meta["duration"] == 12
