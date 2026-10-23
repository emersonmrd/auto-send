import io
import os
from typing import Any, BinaryIO, Callable, Optional, Union


class ProgressFileReader:
    """
    File-like wrapper que monitora o envio de bytes (streaming) e notifica
    um callback de progresso com (sent_bytes, total_bytes).
    Compatível com streaming multipart do httpx e context managers.
    """

    def __init__(
        self,
        file_path_or_stream: Union[str, os.PathLike, BinaryIO, io.BytesIO, Any],
        callback: Optional[Callable[[int, int], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        total_bytes: Optional[int] = None,
    ) -> None:
        self._callback = progress_callback if progress_callback is not None else callback
        self._bytes_read = 0

        if isinstance(file_path_or_stream, (str, os.PathLike)):
            self._file = open(file_path_or_stream, "rb")
            self._should_close = True
            if total_bytes is None:
                self.total_bytes = os.path.getsize(file_path_or_stream)
            else:
                self.total_bytes = total_bytes
        else:
            self._file = file_path_or_stream
            self._should_close = False
            if total_bytes is None:
                if hasattr(self._file, "name") and isinstance(self._file.name, (str, bytes)) and os.path.exists(self._file.name):
                    self.total_bytes = os.path.getsize(self._file.name)
                elif hasattr(self._file, "seek") and hasattr(self._file, "tell"):
                    cur_pos = self._file.tell()
                    self._file.seek(0, os.SEEK_END)
                    self.total_bytes = self._file.tell()
                    self._file.seek(cur_pos)
                else:
                    self.total_bytes = 0
            else:
                self.total_bytes = total_bytes

    def read(self, size: int = -1) -> bytes:
        chunk = self._file.read(size)
        if chunk:
            self._bytes_read = self._file.tell()
            if self._callback is not None and self.total_bytes > 0:
                self._callback(self._bytes_read, self.total_bytes)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        res = self._file.seek(offset, whence)
        self._bytes_read = self._file.tell()
        return res

    def tell(self) -> int:
        return self._file.tell()

    def __len__(self) -> int:
        return self.total_bytes or 0

    @property
    def closed(self) -> bool:
        return getattr(self._file, "closed", False)

    def close(self) -> None:
        if self._should_close and hasattr(self._file, "close"):
            self._file.close()

    def __enter__(self) -> "ProgressFileReader":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
