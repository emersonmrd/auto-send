#!/usr/bin/env python3
"""
setup_windows_binaries.py

Automated download and installation of Windows x64 helper binaries:
- Telegram Bot API Server v10.3 (telegram-bot-api.exe + OpenSSL 3 & zlib DLLs)
- FFmpeg 7.1 Essentials (ffmpeg.exe + ffprobe.exe)

Extracts all executables and required DLLs directly into 'dist/AutoSend-Portable/bin/'.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    from scripts.console_encoding import use_utf8_console
    from scripts.download_integrity import verify_sha256
except ImportError:
    from console_encoding import use_utf8_console
    from download_integrity import verify_sha256

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BIN_DIR = ROOT_DIR / "dist" / "AutoSend-Portable" / "bin"

TELEGRAM_API_URL = "https://github.com/SwissCore92/telegram-bot-api-bin/releases/download/v10.3/telegram-bot-api-v10.3-windows-amd64.zip"
FFMPEG_URL = "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip"

# SHA-256 fixados. Telegram: confere com o SHA256SUMS.txt da release e com o digest do asset no GitHub.
# FFmpeg: a release não publica checksum; hash do asset de 2024-09-30, fixado na primeira verificação.
TELEGRAM_API_SHA256 = "fa04d68d1693f47e79c85ed62ce64b68e27ac0ca9b06e2a71540dca3746896cc"
FFMPEG_SHA256 = "fa7d4d7e795db0e2503f49f105f46ed5852386f0cfdd819899be3b65ebde24fc"

TELEGRAM_FILES = [
    "telegram-bot-api.exe",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "z.dll",
]

FFMPEG_FILES = [
    "ffmpeg.exe",
    "ffprobe.exe",
]

# Minimum file sizes for integrity verification
MINIMUM_SIZES = {
    "telegram-bot-api.exe": 10 * 1024 * 1024,  # > 10 MB
    "ffmpeg.exe": 10 * 1024 * 1024,            # > 10 MB
    "ffprobe.exe": 5 * 1024 * 1024,            # > 5 MB
    "libcrypto-3-x64.dll": 1 * 1024 * 1024,    # > 1 MB
    "libssl-3-x64.dll": 200 * 1024,            # > 200 KB
    "z.dll": 50 * 1024,                        # > 50 KB
}


def download_with_progress(url: str, dest_path: Path, description: str, timeout: int = 120) -> None:
    """Baixa um arquivo via HTTP com exibição amigável de progresso, velocidade e timeout."""
    print(f"   -> Baixando {description}...")
    print(f"      URL: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutoSend-Installer/1.0"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            block_size = 64 * 1024  # 64 KB

            with open(dest_path, "wb") as f:
                while True:
                    chunk = response.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = min(100, int(downloaded * 100 / total_size))
                        mb_down = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        elapsed = max(0.1, time.time() - start_time)
                        speed = mb_down / elapsed
                        bar_len = 25
                        filled_len = int(bar_len * percent // 100)
                        bar = "=" * filled_len + "-" * (bar_len - filled_len)
                        sys.stdout.write(f"\r      [{bar}] {percent:3d}% ({mb_down:.1f}/{mb_total:.1f} MB, {speed:.1f} MB/s)")
                        sys.stdout.flush()
                    else:
                        mb_down = downloaded / (1024 * 1024)
                        sys.stdout.write(f"\r      Baixado: {mb_down:.1f} MB")
                        sys.stdout.flush()

        sys.stdout.write("\n")
        print(f"      ✅ Download concluído: {dest_path.name} ({dest_path.stat().st_size / (1024 * 1024):.1f} MB)")
    except urllib.error.URLError as e:
        sys.stdout.write("\n")
        print(f"❌ Erro de rede ao baixar {description}: {e.reason}")
        if dest_path.exists():
            dest_path.unlink()
        raise
    except Exception as e:
        sys.stdout.write("\n")
        print(f"❌ Erro inesperado ao baixar {description}: {e}")
        if dest_path.exists():
            dest_path.unlink()
        raise


def extract_telegram_binaries(zip_path: Path, target_dir: Path) -> None:
    """Extrai telegram-bot-api.exe e DLLs diretamente para a pasta de destino."""
    print("   -> Extraindo Telegram Bot API Server e bibliotecas auxiliares...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        for filename in TELEGRAM_FILES:
            matches = [n for n in namelist if Path(n).name.lower() == filename.lower()]
            if not matches:
                raise FileNotFoundError(f"Arquivo '{filename}' não encontrado no arquivo {zip_path.name}")
            source_arcname = matches[0]
            target_file = target_dir / filename
            with zf.open(source_arcname) as src, open(target_file, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"      + Extraído: {filename} ({target_file.stat().st_size / (1024 * 1024):.2f} MB)")


def extract_ffmpeg_binaries(zip_path: Path, target_dir: Path) -> None:
    """Extrai ffmpeg.exe e ffprobe.exe diretamente para a pasta de destino."""
    print("   -> Extraindo executáveis do FFmpeg (ffmpeg.exe e ffprobe.exe)...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        for filename in FFMPEG_FILES:
            matches = [n for n in namelist if Path(n).name.lower() == filename.lower()]
            if not matches:
                raise FileNotFoundError(f"Arquivo '{filename}' não encontrado no arquivo {zip_path.name}")
            source_arcname = matches[0]
            target_file = target_dir / filename
            with zf.open(source_arcname) as src, open(target_file, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"      + Extraído: {filename} ({target_file.stat().st_size / (1024 * 1024):.2f} MB)")


def validate_installed_binaries(bin_dir: Path) -> bool:
    """Valida se todos os binários esperados existem e atendem ao tamanho mínimo."""
    all_files = TELEGRAM_FILES + FFMPEG_FILES
    missing = []
    too_small = []

    for f in all_files:
        p = bin_dir / f
        if not p.exists():
            missing.append(f)
        else:
            min_size = MINIMUM_SIZES.get(f, 1024)
            if p.stat().st_size < min_size:
                too_small.append(f"{f} ({p.stat().st_size} bytes < {min_size} bytes)")

    if missing or too_small:
        if missing:
            print(f"❌ Arquivos ausentes: {missing}")
        if too_small:
            print(f"❌ Arquivos corrompidos ou pequenos demais: {too_small}")
        return False

    print("✅ Todos os binários e DLLs foram validados com sucesso:")
    for f in all_files:
        p = bin_dir / f
        print(f"   - {f:<22} ({p.stat().st_size / (1024 * 1024):.2f} MB)")
    return True


def setup_windows_binaries(bin_dir: Path = DEFAULT_BIN_DIR, force: bool = False) -> bool:
    """
    Coordena o download, extração e validação do Telegram Bot API e FFmpeg.
    Retorna True em caso de sucesso.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    all_files = TELEGRAM_FILES + FFMPEG_FILES

    if not force and all((bin_dir / f).exists() for f in all_files):
        print(f"ℹ️ Todos os binários já estão presentes em {bin_dir}.")
        if validate_installed_binaries(bin_dir):
            print("💡 Use --force para forçar o re-download dos binários se necessário.")
            return True

    print("=" * 65)
    print("   INSTALADOR DE BINÁRIOS PORTÁTEIS WINDOWS - AUTO-SEND")
    print("=" * 65)
    print(f"📂 Diretório de destino: {bin_dir}\n")

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # 1. Telegram Bot API
        telegram_zip = tmp_dir / "telegram-bot-api.zip"
        download_with_progress(
            TELEGRAM_API_URL,
            telegram_zip,
            "Telegram Bot API Server v10.3 (SwissCore92)",
            timeout=180,
        )
        verify_sha256(telegram_zip, TELEGRAM_API_SHA256)
        extract_telegram_binaries(telegram_zip, bin_dir)

        print()

        # 2. FFmpeg Essentials
        ffmpeg_zip = tmp_dir / "ffmpeg.zip"
        download_with_progress(
            FFMPEG_URL,
            ffmpeg_zip,
            "FFmpeg 7.1 Essentials Build (GyanD)",
            timeout=180,
        )
        verify_sha256(ffmpeg_zip, FFMPEG_SHA256)
        extract_ffmpeg_binaries(ffmpeg_zip, bin_dir)

    print("\n🔍 Validando integridade dos arquivos extraídos...")
    if not validate_installed_binaries(bin_dir):
        print("❌ Falha na validação dos binários instalados!")
        return False

    print("\n🎉 Instalação dos binários auxiliares concluída com sucesso!")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa e instala automaticamente o Telegram Bot API e FFmpeg no Auto-Send Portable."
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=DEFAULT_BIN_DIR,
        help="Diretório de destino dos binários (padrão: dist/AutoSend-Portable/bin)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força o download e extração mesmo que os arquivos já existam",
    )
    args = parser.parse_args()

    success = setup_windows_binaries(bin_dir=args.bin_dir, force=args.force)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    use_utf8_console()
    main()
