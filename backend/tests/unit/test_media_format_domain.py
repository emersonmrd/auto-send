import pytest

from src.domain.broadcast.broadcast_message import MediaType
from src.domain.broadcast.media_format import classify_media, sniff_format

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00"
OLD_QUICKTIME = b"\x00\x00\x00\x08wide\x00\x00\x00\x00"


@pytest.mark.parametrize(
    "header, expected",
    [
        (JPEG, "jpeg"),
        (PNG, "png"),
        (WEBP, "webp"),
        (MP4, "isobmff"),
        (MOV, "isobmff"),
        (OLD_QUICKTIME, "isobmff"),
        (b"\x00\x00\x00\x08moov", "isobmff"),
        (b"\x00\x00\x00\x08mdat", "isobmff"),
        (b"\x00\x00\x00\x08free", "isobmff"),
        (b"\x00\x00\x00\x08skip", "isobmff"),
    ],
)
def test_sniff_format_recognizes_supported_signatures(header: bytes, expected: str):
    assert sniff_format(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        b"",
        b"fake-video-bytes",
        b"<html><body>x</body></html>",
        b"\xff\xd8",  # JPEG cortado antes do terceiro byte
        b"\x89PNG\r\n\x1a",  # PNG sem o último byte da assinatura
        b"RIFF\x24\x00\x00\x00WAVEfmt ",  # RIFF de áudio, não WebP
        b"XIFF\x24\x00\x00\x00WEBPVP8 ",  # WEBP sem o RIFF no começo
        b"\x00\x00\x00\x18ftyx",
        b"ftypmp42\x00\x00\x00\x00",  # ftyp fora da posição 4
    ],
)
def test_sniff_format_rejects_unknown_content(header: bytes):
    assert sniff_format(header) is None


@pytest.mark.parametrize(
    "extension, header",
    [(".jpg", JPEG), (".jpeg", JPEG), (".JPG", JPEG), (".png", PNG), (".webp", WEBP)],
)
def test_classify_media_accepts_images_whose_content_matches_the_extension(extension: str, header: bytes):
    assert classify_media(extension, header) is MediaType.PHOTO


@pytest.mark.parametrize(
    "extension, header",
    [(".mp4", MP4), (".mov", MOV), (".MOV", OLD_QUICKTIME), (".mp4", MOV), (".mov", MP4)],
)
def test_classify_media_accepts_iso_media_videos_as_mp4_or_mov(extension: str, header: bytes):
    # Celulares gravam MOV com ftyp de MP4 e vice-versa; os dois são ISO BMFF para o Telegram.
    assert classify_media(extension, header) is MediaType.VIDEO


@pytest.mark.parametrize(
    "extension, header",
    [
        (".jpg", b"fake-thumb-bytes"),  # extensão de imagem, conteúdo qualquer
        (".mp4", b"fake-video-bytes"),
        (".png", JPEG),  # imagem com extensão de outra
        (".jpg", PNG),
        (".webp", PNG),
        (".jpg", MP4),  # vídeo com extensão de imagem
        (".mp4", JPEG),  # imagem com extensão de vídeo
        (".gif", b"GIF89a\x01\x00\x01\x00\x00\x00"),
        (".exe", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"),
        ("", JPEG),
    ],
)
def test_classify_media_rejects_content_that_does_not_match_the_extension(extension: str, header: bytes):
    with pytest.raises(ValueError, match="^Unsupported media format$"):
        classify_media(extension, header)
