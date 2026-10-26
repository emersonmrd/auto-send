#!/usr/bin/env python3
"""
bundle_portable_windows.py

Automated packaging script for Auto-Send Portable Windows distribution.
Compiles static frontend, structures the portable application folder,
generates clean requirements.txt, creates data/bin/python directories,
and produces the 1-click launcher 'Iniciar-AutoSend.bat' and 'COMO_USAR.txt'.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
BACKEND_DIR = ROOT_DIR / "backend"
DIST_DIR = ROOT_DIR / "dist"
PORTABLE_DIR = DIST_DIR / "AutoSend-Portable"

# Add project root to sys.path
sys.path.insert(0, str(ROOT_DIR))
try:
    from scripts.console_encoding import use_utf8_console
    from scripts.setup_windows_binaries import setup_windows_binaries
    from scripts.setup_windows_python_embed import setup_embed_python
except ImportError:
    from console_encoding import use_utf8_console
    from setup_windows_binaries import setup_windows_binaries
    from setup_windows_python_embed import setup_embed_python


def export_runtime_requirements() -> str:
    """Pins de runtime exatamente como no backend/uv.lock (sem dev), para o pip do Python embutido."""
    result = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--no-header", "--no-annotate"],
        cwd=BACKEND_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return "# Auto-Send Portable - gerado de backend/uv.lock\n" + result.stdout

LAUNCHER_BAT = r"""@echo off
title Auto-Send Server
cd /d "%~dp0"

echo ========================================================
echo               AUTO-SEND - SISTEMA PORTATIL
echo ========================================================
echo.

if not exist "data\media_temp" mkdir "data\media_temp"
if not exist "data" mkdir "data"

if not defined AUTOSEND_DATA_DIR (
    if defined LOCALAPPDATA (
        set "AUTOSEND_DATA_DIR=%LOCALAPPDATA%\Auto-Send"
    ) else (
        set "AUTOSEND_DATA_DIR=%CD%\data"
    )
)
if not exist "%AUTOSEND_DATA_DIR%\media_temp" mkdir "%AUTOSEND_DATA_DIR%\media_temp"
if not exist "%AUTOSEND_DATA_DIR%\telegram_bot_api" mkdir "%AUTOSEND_DATA_DIR%\telegram_bot_api"

set "TELEGRAM_BOT_API_BIN=%CD%\bin\telegram-bot-api.exe"
set "TELEGRAM_BOT_API_DIR=%AUTOSEND_DATA_DIR%\telegram_bot_api"
set "STATIC_DIR=%CD%\app\static"
set "TEMP_MEDIA_DIR=%AUTOSEND_DATA_DIR%\media_temp"
set "DB_PATH=%AUTOSEND_DATA_DIR%\autosend.db"
set "DATABASE_URL=sqlite+aiosqlite:///%DB_PATH:\=/%"
set "CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000"
set "PATH=%CD%\bin;%CD%\python;%CD%\python\Scripts;%PATH%"
set "PYTHONPATH=%CD%\app\backend;%PYTHONPATH%"

set "PYTHON_BIN="
if exist "python\python.exe" set "PYTHON_BIN=python\python.exe"
if not defined PYTHON_BIN where python >nul 2>&1 && set "PYTHON_BIN=python"

if not defined PYTHON_BIN (
    echo [ERRO] Python nao foi encontrado em python\python.exe!
    pause
    exit /b 1
)

rem Autoverificacao do ambiente: grava data\diagnostico.txt e nunca impede o servidor de subir.
"%PYTHON_BIN%" -m src.infrastructure.portable_preflight
echo.
echo [*] Iniciando Auto-Send com deteccao inteligente de portas...
echo.

"%PYTHON_BIN%" -m src.presentation.main

echo.
echo [!] Servidor finalizado.
pause
"""

COMO_USAR_TXT = r"""========================================================================
                  AUTO-SEND PORTABLE - GUIA DE USO
========================================================================

Bem-vindo ao Auto-Send!
Este pacote foi preparado para rodar de forma 100% autonoma no seu Windows,
sem necessidade de configuracoes complexas.

------------------------------------------------------------------------
1. COMO INICIAR O SISTEMA
------------------------------------------------------------------------
Basta dar dois cliques no arquivo:
    Iniciar-AutoSend.bat

O que vai acontecer:
1. O servidor local do Telegram Bot API sera iniciado na porta 8081.
2. O servidor local do Auto-Send sera iniciado em segundo plano na porta 8000
   (se ela estiver ocupada, na proxima porta livre, ate a 8020).
3. Seu navegador de internet abrira automaticamente na tela do sistema,
   normalmente em http://127.0.0.1:8000
4. Uma janela preta (prompt de comando) ficara aberta informando que o
   sistema esta ativo.

------------------------------------------------------------------------
2. ONDE FICAM SALVOS SEUS DADOS E PERFIS
------------------------------------------------------------------------
Todos os canais cadastrados, perfis, configuracoes de bots e
mensagens agendadas ficam salvos com total seguranca fora da pasta do
pacote, em:
    %LOCALAPPDATA%\Auto-Send\

- O arquivo do banco de dados e: %LOCALAPPDATA%\Auto-Send\autosend.db
- Backups automaticos antes de atualizacoes: autosend.db.bak-<versao>
- Midias temporarias ficam em: %LOCALAPPDATA%\Auto-Send\media_temp\

VANTAGEM NAS ATUALIZACOES:
Quando sair uma versao nova do Auto-Send, voce pode extrair o novo .zip em
qualquer pasta: seus perfis, canais e agendamentos continuam la automaticamente!
Na tela do sistema, o botao "Abrir pasta de dados" abre essa pasta direto no
Explorador de Arquivos.

ATUALIZANDO DA VERSAO v0.4.0 (OU ANTERIOR):
No primeiro inicio, se ainda nao houver banco em %LOCALAPPDATA%\Auto-Send\,
o sistema procura a pasta "data" da versao antiga (na mesma pasta, em Downloads,
Area de Trabalho ou Documentos) e pergunta se deseja importar.
Se preferir copiar manualmente de outra pasta, basta copiar o arquivo
"data\autosend.db" da versao antiga para dentro de "%LOCALAPPDATA%\Auto-Send\".

------------------------------------------------------------------------
3. SUPORTE A VIDEOS GRANDES E MIDIAS PESADAS (ATE 2.000 MB)
------------------------------------------------------------------------
Este pacote ja vem 100% COMPLETO com o Telegram Bot API e o FFmpeg inclusos
na pasta bin/, pronto para processar e enviar videos de ate 2.000 MB (2 GB)!

- Telegram Bot API local: Permite envio direto de arquivos e videos de ate 2 GB,
  superando com folga o limite padrao de 50 MB da API remota.
- FFmpeg: Gera automaticamente miniaturas (thumbnails), calcula duracao e
  resolucao de qualquer video antes do disparo.

Ao iniciar o Auto-Send atraves do 'Iniciar-AutoSend.bat', o servidor local
do Telegram Bot API e acionado automaticamente na porta 8081 em segundo plano.
Voce nao precisa instalar nem configurar nada manualmente!

------------------------------------------------------------------------
4. COMO FECHAR O SISTEMA
------------------------------------------------------------------------
Quando terminar de usar:
1. Basta fechar a janela do Auto-Send clicando no botao [X] ou pressionar Ctrl+C.
2. Todos os processos do Auto-Send e do Telegram Bot API serao desligados
   imediatamente de forma limpa e segura, liberando todas as portas e memoria.

Duvidas e problemas: https://github.com/emersonmrd/auto-send/issues
========================================================================
"""

BIN_README_TXT = """PASTA DE EXECUTAVEIS E DLLS (INCLUSOS NO PACOTE)
================================================

Este pacote ja contem os executaveis e bibliotecas necessarios para operacao completa:
1. telegram-bot-api.exe (+ libcrypto-3-x64.dll, libssl-3-x64.dll, z.dll):
   - Servidor local do Telegram Bot API (v10.3 64-bit).
   - Habilita envio de arquivos e videos de ate 2 GB (2000 MB).
   - Inicializado automaticamente na porta 8081 pelo Iniciar-AutoSend.bat.

2. ffmpeg.exe & ffprobe.exe:
   - Processamento de midias, extracao automatica de miniaturas e metadados de video.

Caso precise atualizar ou reinstalar esses binarios, execute:
   python scripts/setup_windows_binaries.py
"""

PYTHON_README_TXT = """PASTA DO PYTHON EMBARCADO
=========================

Esta pasta abriga o runtime do Python 3.12 (64-bit) para Windows.
Se este pacote nao veio com o Python pre-instalado, execute o assistente:
   python scripts/setup_windows_python_embed.py

Ou instale o Python 3.12+ no Windows e marque 'Add Python to PATH'.
"""


def build_frontend_static() -> None:
    """Executa o build estático do Next.js."""
    print("\n📦 [1/6] Compilando frontend Next.js estático...")
    # No Windows o npm é npm.cmd, que o CreateProcess só encontra pelo caminho resolvido.
    npm = shutil.which("npm")
    if npm is None:
        print("❌ Erro: npm não encontrado no PATH.")
        sys.exit(1)
    cmd = [npm, "--prefix", str(FRONTEND_DIR), "run", "build"]
    result = subprocess.run(cmd, cwd=ROOT_DIR, env={**os.environ, "NEXT_EXPORT": "true"})
    if result.returncode != 0:
        print("❌ Erro ao compilar o frontend estático.")
        sys.exit(1)

    out_dir = FRONTEND_DIR / "out"
    if not (out_dir / "index.html").exists():
        print(f"❌ Erro: '{out_dir}/index.html' não encontrado após o build.")
        sys.exit(1)
    print("✅ Frontend compilado com sucesso em frontend/out.")


def setup_package_structure(target_dir: Path) -> None:
    """Cria a estrutura de pastas do pacote portátil."""
    print(f"\n📂 [2/6] Estruturando diretório de distribuição em: {target_dir}")

    # Criação das pastas fundamentais
    app_static = target_dir / "app" / "static"
    app_backend = target_dir / "app" / "backend"
    data_dir = target_dir / "data"
    media_temp_dir = data_dir / "media_temp"
    bin_dir = target_dir / "bin"
    python_dir = target_dir / "python"

    for d in [app_static, app_backend, media_temp_dir, bin_dir, python_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Copiar frontend estático
    print("   -> Copiando arquivos estáticos para app/static/...")
    frontend_out = FRONTEND_DIR / "out"
    shutil.copytree(frontend_out, app_static, dirs_exist_ok=True)

    # 2. Copiar backend source e pyproject.toml
    print("   -> Copiando código do backend para app/backend/...")
    shutil.copytree(BACKEND_DIR / "src", app_backend / "src", dirs_exist_ok=True)
    shutil.copy2(BACKEND_DIR / "pyproject.toml", app_backend / "pyproject.toml")

    # Gerar requirements.txt a partir do lockfile
    req_file = app_backend / "requirements.txt"
    with open(req_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(export_runtime_requirements())
    print("   -> requirements.txt gerado do uv.lock (dependências de produção).")

    # O pacote redistribui software de terceiros: licença do projeto e avisos vão na raiz.
    for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT_DIR / notice, target_dir / notice)

    # 3. data/ e data/media_temp com .gitkeep
    (data_dir / ".gitkeep").touch(exist_ok=True)
    (media_temp_dir / ".gitkeep").touch(exist_ok=True)

    # 4. bin/ com README explicativo
    with open(bin_dir / "README.txt", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(BIN_README_TXT)

    # 5. python/ com README explicativo
    with open(python_dir / "README.txt", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(PYTHON_README_TXT)

    print("✅ Estrutura de diretórios criada com sucesso.")


# Runtime do Visual C++ que o telegram-bot-api.exe importa. Um Windows sem o VC++ Redistributable não tem
# essas DLLs (0xC0000135 ao abrir); a Microsoft permite distribuí-las ao lado do executável (app-local).
VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
VSWHERE = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")


def find_vc_runtime_dir() -> Path | None:
    """Pasta Microsoft.VC14x.CRT (x64) mais recente da instalação do Visual Studio, via vswhere."""
    if not VSWHERE.exists():
        return None
    result = subprocess.run(
        [str(VSWHERE), "-latest", "-products", "*", "-find", r"VC\Redist\MSVC\*\x64\Microsoft.VC*.CRT\vcruntime140.dll"],
        capture_output=True,
        text=True,
    )
    found = [Path(line).parent for line in result.stdout.splitlines() if line.strip()]
    return max(found, default=None)


def bundle_vc_runtime(bin_dir: Path) -> None:
    """Copia o runtime do VC++ para bin/, para os binários abrirem sem o Redistributable instalado."""
    if sys.platform != "win32":
        print("   -> [i] Runtime do VC++ só é copiado num build no Windows (fonte: Visual Studio Redist).")
        return
    crt_dir = find_vc_runtime_dir()
    if crt_dir is None:
        print("❌ Erro: runtime do VC++ (Microsoft.VC14x.CRT) não encontrado; instale o Visual Studio Build Tools.")
        sys.exit(1)
    for dll in VC_RUNTIME_DLLS:
        shutil.copy2(crt_dir / dll, bin_dir / dll)
    print(f"   -> Runtime do VC++ copiado de {crt_dir}")


def write_launcher_and_docs(target_dir: Path) -> None:
    """Gera o executável .bat de inicialização e o manual COMO_USAR.txt com quebras de linha Windows CRLF."""
    print("\n📝 [4/6] Gerando Iniciar-AutoSend.bat e documentação...")

    launcher_path = target_dir / "Iniciar-AutoSend.bat"
    with open(launcher_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(LAUNCHER_BAT)
    print(f"   -> Launcher criado: {launcher_path}")

    como_usar_path = target_dir / "COMO_USAR.txt"
    with open(como_usar_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(COMO_USAR_TXT)
    print(f"   -> Guia criado: {como_usar_path}")

    print("✅ Launcher e documentação gerados com formato Windows (CRLF).")


def validate_bundle(target_dir: Path) -> None:
    """Valida se todos os artefatos essenciais foram criados no pacote."""
    print("\n🔍 [5/6] Validando integridade do pacote gerado...")

    essential_files = [
        target_dir / "Iniciar-AutoSend.bat",
        target_dir / "COMO_USAR.txt",
        target_dir / "LICENSE",
        target_dir / "THIRD_PARTY_NOTICES.md",
        target_dir / "app" / "static" / "index.html",
        target_dir / "app" / "backend" / "pyproject.toml",
        target_dir / "app" / "backend" / "requirements.txt",
        target_dir / "app" / "backend" / "src" / "presentation" / "main.py",
        target_dir / "data" / ".gitkeep",
        target_dir / "data" / "media_temp" / ".gitkeep",
        target_dir / "bin" / "README.txt",
        target_dir / "python" / "README.txt",
    ]

    missing = [str(f.relative_to(target_dir)) for f in essential_files if not f.exists()]
    if missing:
        print(f"❌ Erro de validação: arquivos ausentes no pacote:\n  {missing}")
        sys.exit(1)

    print("✅ Todos os 10 arquivos essenciais validados com sucesso!")

    # Verificação de binários auxiliares
    telegram_exe = target_dir / "bin" / "telegram-bot-api.exe"
    ffmpeg_exe = target_dir / "bin" / "ffmpeg.exe"
    if telegram_exe.exists() and ffmpeg_exe.exists():
        print("   -> Executáveis auxiliares: telegram-bot-api.exe e ffmpeg.exe presentes (Suporte a vídeos de 2.000 MB ativo!).")
    else:
        print("   -> [i] Binários auxiliares ausentes em bin/. Execute 'python scripts/setup_windows_binaries.py' para incluí-los.")


def create_zip_archive(source_dir: Path, zip_dest: Path) -> None:
    """Compacta a pasta portátil em um arquivo .zip."""
    import zipfile
    print(f"\n📦 [6/6] Compactando {source_dir.name} em {zip_dest}...")
    temp_zip = zip_dest.with_suffix(".tmp.zip")
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(source_dir.parent)
                zf.write(file_path, arcname)
    temp_zip.replace(zip_dest)
    size_mb = zip_dest.stat().st_size / (1024 * 1024)
    print(f"✅ Arquivo compactado com sucesso: {zip_dest} ({size_mb:.2f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de Pacote Portátil Auto-Send para Windows.")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Pula a etapa de compilação estática do Next.js (usa frontend/out existente)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PORTABLE_DIR,
        help="Diretório de saída para o pacote portátil (padrão: dist/AutoSend-Portable)",
    )
    parser.add_argument(
        "--download-binaries",
        action="store_true",
        default=False,
        help="Força o download e instalação do Telegram Bot API e FFmpeg na pasta bin/",
    )
    parser.add_argument(
        "--skip-binaries",
        action="store_true",
        default=False,
        help="Pula o download de binários auxiliares mesmo se estiverem ausentes",
    )
    parser.add_argument(
        "--skip-python",
        action="store_true",
        default=False,
        help="Não embute o Python 3.12 com as dependências (o pacote passa a depender do Python do sistema)",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        default=False,
        help="Gera arquivo .zip do pacote portátil ao final",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("   GERADOR DO PACOTE PORTÁTIL WINDOWS - AUTO-SEND")
    print("=" * 60)

    if not args.skip_build:
        build_frontend_static()
    else:
        print("\n⏩ [1/6] Pulando compilação do frontend (--skip-build ativo).")

    setup_package_structure(args.output_dir)

    # Configuração de binários auxiliares
    bin_target = args.output_dir / "bin"
    has_telegram = (bin_target / "telegram-bot-api.exe").exists()
    has_ffmpeg = (bin_target / "ffmpeg.exe").exists()
    should_download = args.download_binaries or (not args.skip_binaries and (not has_telegram or not has_ffmpeg))

    if should_download:
        print("\n📦 [3/6] Baixando e configurando binários Windows (Telegram Bot API & FFmpeg)...")
        setup_windows_binaries(bin_dir=bin_target)
        bundle_vc_runtime(bin_target)
    else:
        print("\n⏩ [3/6] Binários Windows já presentes em bin/ ou pulados via --skip-binaries.")

    # Sem o Python embutido o launcher cai no Python do sistema, que uma máquina limpa não tem.
    if not args.skip_python:
        setup_embed_python(
            target_dir=args.output_dir / "python",
            req_file=args.output_dir / "app" / "backend" / "requirements.txt",
        )
    else:
        print("\n⏩ Python embutido pulado via --skip-python.")

    write_launcher_and_docs(args.output_dir)
    validate_bundle(args.output_dir)

    if args.zip:
        zip_path = args.output_dir.parent / f"{args.output_dir.name}.zip"
        create_zip_archive(args.output_dir, zip_path)

    print("\n" + "=" * 60)
    print("🎉 PACOTE PORTÁTIL CRIADO COM SUCESSO!")
    print(f"📂 Localização: {args.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    use_utf8_console()
    main()
