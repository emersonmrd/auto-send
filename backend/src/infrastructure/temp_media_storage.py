import os
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 1024 * 1024


class MediaTooLarge(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"Media file larger than {max_bytes} bytes")
        self.max_bytes = max_bytes


def save_upload(source: BinaryIO, dest_path: str, max_bytes: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    """
    Copia o upload para dest_path em blocos e devolve o tamanho gravado.
    Passou de max_bytes: para de ler, apaga o arquivo parcial e levanta MediaTooLarge.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    written = 0
    try:
        with open(dest_path, "wb") as buffer:
            while chunk := source.read(chunk_size):
                written += len(chunk)
                if written > max_bytes:
                    raise MediaTooLarge(max_bytes)
                buffer.write(chunk)
    except BaseException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    return written
