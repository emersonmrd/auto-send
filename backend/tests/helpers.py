import struct

def build_synthetic_mp4(width: int, height: int, duration: int = 5, matrix: list[int] = None) -> bytes:
    """Constrói um payload binário MP4 sintético mínimo e válido com ftyp, moov, mvhd e tkhd."""
    if matrix is None:
        matrix = [
            0x00010000, 0, 0,
            0, 0x00010000, 0,
            0, 0, 0x40000000,
        ]
    ftyp_data = b"mp42" + struct.pack(">I", 0) + b"mp42isom"
    ftyp = struct.pack(">I4s", len(ftyp_data) + 8, b"ftyp") + ftyp_data

    timescale = 1000
    dur = duration * timescale
    mvhd_payload = (
        struct.pack(">BBBBIIII", 0, 0, 0, 0, 0, 0, timescale, dur)
        + struct.pack(">IH10s", 0x00010000, 0x0100, b"\x00" * 10)
        + struct.pack(">9i", *matrix)
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    mvhd = struct.pack(">I4s", len(mvhd_payload) + 8, b"mvhd") + mvhd_payload

    tkhd_payload = (
        struct.pack(">BBBBIIIII", 0, 0, 0, 7, 0, 0, 1, 0, dur)
        + b"\x00" * 8
        + struct.pack(">hhhh", 0, 0, 0x0100, 0)
        + struct.pack(">9i", *matrix)
        + struct.pack(">II", width << 16, height << 16)
    )
    tkhd = struct.pack(">I4s", len(tkhd_payload) + 8, b"tkhd") + tkhd_payload

    trak = struct.pack(">I4s", len(tkhd) + 8, b"trak") + tkhd
    moov = struct.pack(">I4s", len(mvhd + trak) + 8, b"moov") + mvhd + trak
    return ftyp + moov
