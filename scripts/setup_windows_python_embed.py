#!/usr/bin/env python3
"""
setup_windows_python_embed.py

Utility script that downloads the official Python 3.12 64-bit embeddable package
from python.org, extracts it into 'dist/AutoSend-Portable/python', patches the
pth file to enable 'site-packages', downloads get-pip.py, and installs production
dependencies for Auto-Send.
"""

import argparse
import os
import shutil
import subprocess
import sys
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
DEFAULT_PYTHON_DIR = ROOT_DIR / "dist" / "AutoSend-Portable" / "python"
DEFAULT_REQ_FILE = ROOT_DIR / "dist" / "AutoSend-Portable" / "app" / "backend" / "requirements.txt"

PYTHON_VERSION = "3.12.8"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
# get-pip.py fixado num commit de pypa/get-pip (2026-10-20): a URL de bootstrap.pypa.io muda a cada release do pip.
GET_PIP_URL = "https://raw.githubusercontent.com/pypa/get-pip/37ae3c4daaf63a0c203176251fb99c0e238562b5/public/get-pip.py"

# SHA-256 fixados. Python: o MD5 do mesmo arquivo confere com o publicado pelo python.org (1e86b04b...).
PYTHON_EMBED_SHA256 = "8d3f33be9eb810f23c102f08475af2854e50484b8e4e06275e937be61ce3d2fb"
GET_PIP_SHA256 = "f4448a01e3ab2914c65f4ca59d4cacba6b2dbde19a483fbac46587f8bbaff424"

INSTALL_DEPS_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo     INSTALANDO PIP E DEPENDENCIAS NO PYTHON EMBARCADO
echo ========================================================
echo.

if not exist python.exe (
    echo [ERRO] python.exe nao encontrado nesta pasta!
    pause
    exit /b 1
)

if exist get-pip.py (
    echo [*] Instalando gerenciador de pacotes pip...
    python.exe get-pip.py --no-warn-script-location
) else (
    echo [i] get-pip.py nao encontrado. Verificando pip existente...
)

if exist "..\\app\\backend\\requirements.txt" (
    echo [*] Instalando dependencias de runtime do Auto-Send...
    python.exe -m pip install --no-warn-script-location -r "..\\app\\backend\\requirements.txt"
) else (
    echo [ERRO] Arquivo requirements.txt nao encontrado em app\\backend\\!
    pause
    exit /b 1
)

echo.
echo ========================================================
echo  Todas as dependencias foram instaladas com sucesso!
echo ========================================================
pause
"""


def download_file(url: str, dest_path: Path) -> None:
    """Baixa um arquivo via HTTP exibindo o progresso básico."""
    print(f"   -> Baixando: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    def _report_progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            percent = min(100, int(block_num * block_size * 100 / total_size))
            sys.stdout.write(f"\r      Progresso: {percent}% [{block_num * block_size // 1024} KB / {total_size // 1024} KB]")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest_path, reporthook=_report_progress)
    sys.stdout.write("\n")


def patch_pth_file(python_dir: Path) -> None:
    """Habilita site-packages e import site no arquivo ._pth do Python embeddable."""
    pth_files = list(python_dir.glob("*._pth"))
    if not pth_files:
        print("⚠️ Aviso: Nenhum arquivo *._pth encontrado para patch em", python_dir)
        return

    for pth_file in pth_files:
        print(f"   -> Patching {pth_file.name} para habilitar 'import site' e 'site-packages'...")
        with open(pth_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        has_site_packages = False
        for line in lines:
            stripped = line.strip()
            if stripped == "#import site" or stripped == "import site":
                new_lines.append("import site\n")
            elif stripped == "Lib\\site-packages" or stripped == "Lib/site-packages":
                has_site_packages = True
                new_lines.append(line)
            else:
                new_lines.append(line)

        if not has_site_packages:
            new_lines.insert(len(new_lines) - 1, "Lib\\site-packages\n")
        # Com ._pth o PYTHONPATH do launcher é ignorado: o código do backend entra no sys.path por aqui.
        if not any(line.strip() == "..\\app\\backend" for line in new_lines):
            new_lines.insert(len(new_lines) - 1, "..\\app\\backend\n")

        with open(pth_file, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(new_lines)

    # Cria a pasta Lib/site-packages se ainda não existir
    (python_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    print("   -> Diretório Lib/site-packages criado e habilitado.")


def setup_embed_python(target_dir: Path, install_pip: bool = True, req_file: Path = DEFAULT_REQ_FILE) -> None:
    """Orquestra o download, extração, configuração e instalação de dependências."""
    print("=" * 60)
    print(f"CONFIGURADOR DO PYTHON EMBEDDABLE ({PYTHON_VERSION}) PARA WINDOWS")
    print("=" * 60)

    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / f"python-{PYTHON_VERSION}-embed-amd64.zip"

    # 1. Download do Python Embeddable se python.exe não existir
    if not (target_dir / "python.exe").exists():
        print("\n📥 [1/4] Baixando Python Embeddable oficial...")
        download_file(PYTHON_EMBED_URL, zip_path)
        verify_sha256(zip_path, PYTHON_EMBED_SHA256)

        print("\n📦 [2/4] Descompactando binários do Python...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)

        # Remove o zip após extrair
        if zip_path.exists():
            zip_path.unlink()
        print("   -> Python extraído com sucesso.")
    else:
        print("\nℹ️ [1/4] python.exe já existe na pasta de destino. Pulando download do zip.")

    # 2. Patch no arquivo ._pth
    print("\n⚙️ [3/4] Configurando suporte a pacotes externos (._pth)...")
    patch_pth_file(target_dir)

    # 3. Baixar get-pip.py
    get_pip_path = target_dir / "get-pip.py"
    if not get_pip_path.exists():
        print("\n📥 [4/4] Baixando get-pip.py...")
        download_file(GET_PIP_URL, get_pip_path)
        verify_sha256(get_pip_path, GET_PIP_SHA256)

    # 4. Criar script batch de instalação de dependências
    bat_path = target_dir / "instalar_dependencias.bat"
    with open(bat_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(INSTALL_DEPS_BAT)
    print(f"   -> Script auxiliar criado: {bat_path}")

    # 5. Se estiver rodando no Windows, executa a instalação imediatamente
    if sys.platform == "win32" and install_pip:
        python_exe = target_dir / "python.exe"
        print("\n🚀 Executando instalação no Windows...")
        print("   -> Instalando pip...")
        subprocess.run([str(python_exe), str(get_pip_path), "--no-warn-script-location"], check=True)

        if req_file.exists():
            print(f"   -> Instalando dependências de {req_file}...")
            subprocess.run([str(python_exe), "-m", "pip", "install", "--no-warn-script-location", "-r", str(req_file)], check=True)
    else:
        print("\n💡 Ambiente não-Windows ou instalação diferida:")
        print("   -> Os binários do Python e get-pip.py foram preparados com sucesso.")
        print("   -> No Windows, execute 'instalar_dependencias.bat' para instalar os pacotes.")

    print("\n" + "=" * 60)
    print("✅ PYTHON EMBEDDABLE CONFIGURADO COM SUCESSO!")
    print(f"📂 Diretório: {target_dir}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configurador do Python Embeddable para Windows.")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=DEFAULT_PYTHON_DIR,
        help="Diretório de destino do Python (padrão: dist/AutoSend-Portable/python)",
    )
    parser.add_argument(
        "--no-pip",
        action="store_true",
        help="Não tenta executar instalação de pip automática mesmo no Windows",
    )
    args = parser.parse_args()

    setup_embed_python(args.target_dir, install_pip=not args.no_pip)


if __name__ == "__main__":
    use_utf8_console()
    main()
