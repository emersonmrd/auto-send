from typing import Optional

from src.domain.broadcast.broadcast_message import MediaType

_IMAGE_FORMAT_BY_EXTENSION = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}
_VIDEO_EXTENSIONS = (".mp4", ".mov")
# MP4 e MOV modernos começam pela caixa ftyp; QuickTime antigo começa direto por um destes átomos.
_ISO_MEDIA_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")


def sniff_format(header: bytes) -> Optional[str]:
    """Formato pela assinatura dos primeiros bytes do arquivo (12 bastam), ou None se desconhecido."""
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    if header[4:8] in _ISO_MEDIA_BOXES:
        return "isobmff"
    return None


def classify_media(extension: str, header: bytes) -> MediaType:
    """Tipo da mídia, exigindo que o conteúdo bata com a extensão (AGENTS.md §9)."""
    extension = extension.lower()
    detected = sniff_format(header)
    if extension in _VIDEO_EXTENSIONS and detected == "isobmff":
        return MediaType.VIDEO
    if detected is not None and _IMAGE_FORMAT_BY_EXTENSION.get(extension) == detected:
        return MediaType.PHOTO
    raise ValueError("Unsupported media format")
