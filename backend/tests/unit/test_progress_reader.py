import io
import os
import pytest
from src.infrastructure.progress_reader import ProgressFileReader


def test_progress_file_reader_reads_chunks_and_calls_callback(tmp_path):
    """
    Testa se o ProgressFileReader ao ler pedaços de um arquivo dispara o
    callback de progresso informando sent_bytes e total_bytes progressivamente.
    """
    file_size = 1000
    test_content = b"x" * file_size
    test_file = tmp_path / "sample_video.mp4"
    test_file.write_bytes(test_content)

    progress_reports = []

    def progress_callback(sent_bytes: int, total_bytes: int):
        progress_reports.append((sent_bytes, total_bytes))

    with open(test_file, "rb") as f:
        reader = ProgressFileReader(f, progress_callback=progress_callback, total_bytes=file_size)
        
        chunk1 = reader.read(250)
        assert len(chunk1) == 250
        assert progress_reports[-1] == (250, 1000)

        chunk2 = reader.read(250)
        assert len(chunk2) == 250
        assert progress_reports[-1] == (500, 1000)

        chunk3 = reader.read(250)
        assert len(chunk3) == 250
        assert progress_reports[-1] == (750, 1000)

        chunk4 = reader.read(250)
        assert len(chunk4) == 250
        assert progress_reports[-1] == (1000, 1000)

        # EOF
        chunk_eof = reader.read(250)
        assert chunk_eof == b""
        assert progress_reports[-1] == (1000, 1000)

    assert len(progress_reports) == 4


def test_progress_file_reader_context_manager(tmp_path):
    """
    Testa o suporte a context manager ('with ...') garantindo que o arquivo
    subjacente seja fechado ao término do bloco with.
    """
    test_content = b"Context manager test bytes"
    test_file = tmp_path / "test_ctx.bin"
    test_file.write_bytes(test_content)

    reader = None
    with ProgressFileReader(str(test_file)) as r:
        reader = r
        content = reader.read()
        assert content == test_content
        assert not reader.closed

    assert reader.closed


def test_progress_file_reader_seek_and_tell(tmp_path):
    """
    Testa suporte a .seek() e .tell(), essenciais para que httpx calcule
    tamanho ou reposicione o cursor ao ler multipart payloads.
    """
    file_size = 500
    test_file = tmp_path / "seek_test.bin"
    test_file.write_bytes(b"A" * file_size)

    progress_reports = []

    def callback(sent: int, total: int):
        progress_reports.append((sent, total))

    with open(test_file, "rb") as f:
        reader = ProgressFileReader(f, progress_callback=callback)
        assert reader.tell() == 0

        # Lê 100 bytes
        part1 = reader.read(100)
        assert len(part1) == 100
        assert reader.tell() == 100
        assert progress_reports[-1] == (100, 500)

        # Seek de volta para o início
        new_pos = reader.seek(0)
        assert new_pos == 0
        assert reader.tell() == 0

        # Lê 200 bytes a partir do início
        part2 = reader.read(200)
        assert len(part2) == 200
        assert reader.tell() == 200
        assert progress_reports[-1] == (200, 500)

        # Seek para o final
        end_pos = reader.seek(0, os.SEEK_END)
        assert end_pos == 500
        assert reader.tell() == 500


def test_progress_file_reader_without_callback(tmp_path):
    """
    Testa comportamento robusto quando nenhum callback de progresso é fornecido.
    """
    test_content = b"No callback content"
    test_file = tmp_path / "no_cb.bin"
    test_file.write_bytes(test_content)

    with open(test_file, "rb") as f:
        reader = ProgressFileReader(f, progress_callback=None)
        data = reader.read()
        assert data == test_content


def test_progress_file_reader_len_reports_total_bytes(tmp_path):
    """
    Testa que len(reader) retorna o total_bytes para que httpx determine
    o Content-Length de uploads multipart sem carregar tudo na memória.
    """
    file_size = 2048
    test_file = tmp_path / "len_test.mp4"
    test_file.write_bytes(b"\x00" * file_size)

    with open(test_file, "rb") as f:
        reader = ProgressFileReader(f)
        assert len(reader) == file_size


def test_progress_file_reader_with_bytes_io():
    """
    Testa suporte a streams em memória (io.BytesIO) com total_bytes explícito.
    """
    data = b"In-memory stream data"
    stream = io.BytesIO(data)
    progress = []

    reader = ProgressFileReader(
        stream,
        progress_callback=lambda s, t: progress.append((s, t)),
        total_bytes=len(data)
    )

    read_data = reader.read(10)
    assert read_data == data[:10]
    assert progress[-1] == (10, len(data))

    read_rest = reader.read()
    assert read_rest == data[10:]
    assert progress[-1] == (len(data), len(data))
