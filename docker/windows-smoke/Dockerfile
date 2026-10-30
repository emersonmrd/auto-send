# escape=`
# Smoke test do pacote portatil num Windows limpo: sem Python, Node nem VC++ alem do que vem no sistema.
# Contexto de build = raiz do repositorio (o .dockerignore da raiz deixa passar so os dois arquivos abaixo).
#   python scripts\bundle_portable_windows.py --download-binaries --zip
#   docker build -f docker\windows-smoke\Dockerfile -t auto-send-windows-smoke .
#   docker run --rm auto-send-windows-smoke
# So roda em host Windows com Docker em modo de container Windows (no CI: runner windows-2022).

# Imagem oficial da Microsoft, canal LTSC (suporte longo), fixada por digest; o Dependabot atualiza o digest.
# windows/server e nao servercore: o Server Core nao tem DLLs que todo Windows desktop tem (ex.: AVICAP32.dll,
# que o ffmpeg importa), e o teste reprovaria o pacote por algo que nao falta na maquina do usuario.
# Nenhuma das duas traz runtime extra (VC++, .NET, Python), entao o teste continua num Windows limpo.
# A versao do host precisa casar com a da imagem: ltsc2022 <-> Windows Server 2022 (runner windows-2022).
FROM mcr.microsoft.com/windows/server:ltsc2022@sha256:7a15615ebaa86fc085707866747b8806d457ab939a97c98c5af50e6c34b4a5d2

LABEL org.opencontainers.image.title="auto-send-windows-smoke" `
      org.opencontainers.image.description="Smoke test do pacote portatil do Auto-Send num Windows Server limpo" `
      org.opencontainers.image.source="https://github.com/emersonmrd/auto-send"

WORKDIR C:\smoke

COPY scripts/smoke_test_portable.ps1 dist/AutoSend-Portable.zip ./

# Usuario sem privilegio de administrador (AGENTS.md 8.3, CWE-250); o teste so precisa do proprio %TEMP%.
USER ContainerUser

# Container de execucao unica: sem HEALTHCHECK nem EXPOSE, o codigo de saida e o resultado do teste.
ENTRYPOINT ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\smoke\\smoke_test_portable.ps1", "-ZipPath", "C:\\smoke\\AutoSend-Portable.zip"]
