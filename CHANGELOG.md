# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento [SemVer](https://semver.org/lang/pt-BR/).
Correção = patch, adição = minor, mudança incompatível = major. A skill `release` lê a seção `[Unreleased]` para decidir o próximo número.

## [Unreleased]

### Added
- Cadastro de canal pelo link de um post ou pelo ID: o campo da busca de canais aceita, além de `@username`/`t.me/username`, o link copiado de um post (`https://t.me/c/<id>/<post>`, convertido para `-100<id>`), o link de post de canal público (`t.me/<username>/<post>`) e o ID `-100…`. Serve para canal privado em que ninguém postou nas últimas 24 h e para bot ligado a outro sistema por webhook (#12).

### Changed
- `POST /api/v1/profiles/{profile_id}/resolve-chat` aceita as novas formas de identificador. Link de convite (`t.me/+…`) responde `422` explicando que é preciso o link de um post ou o ID; os demais identificadores inválidos respondem `422 "Invalid chat identifier (...)"` (#12).
- `POST /api/v1/profiles/{profile_id}/discover-chats` com webhook ativo no bot responde `400 "Bot webhook is active: automatic discovery is unavailable"`, sem abrir o circuit breaker; a tela explica em português e leva para a entrada manual. O app nunca apaga o webhook (#12).
- O painel de busca de canais orienta a publicar uma mensagem no canal antes de buscar e, com a lista vazia, aponta o link de um post ou o ID (#12).
- CI: a mutação do domínio, no PR, muta só os arquivos de domínio alterados (domínio inteiro quando um teste de domínio ou o `pyproject.toml` muda, no PR de release e na `main`), guarda o cache do mutmut entre execuções e publica os sobreviventes no resumo do job. O `verify.sh` aplica a mesma seleção e passa a considerar mudanças não commitadas (#26).

### Removed
- Dependências `aiogram` e `aiofiles` do backend, declaradas sem nenhum uso: saem da imagem Docker e do pacote portátil junto com 9 dependências transitivas (`aiohttp` e afins). Um teste reprova dependência de runtime que o `src/` não usa (#4).

### Fixed
- Busca de canais do bot: cada chat mostra o tipo e o ID com rótulo explícito (`Canal: -1001234567890`, ou `Canal: @acme (-1001234567890)` com username), em vez do separador `·` que confundia o tipo com o ID (#13).
- A aba do navegador mostra "Auto-Send" em vez de "Create Next App", o título padrão do template do Next.js (#5).
- Compositor: anexar um arquivo de nome muito longo não empurra mais o campo de mensagem e os botões Enviar/Agendar para fora da tela; o nome aparece truncado, com o nome completo no `title` (#17).
- Acessibilidade: os campos dos formulários (perfil, canal, botão inline, link de texto, agendamento e edição) têm o rótulo visível associado (`<label htmlFor>`), e o campo de mensagem tem `aria-label`; leitores de tela anunciam o rótulo, não o placeholder (#6).

### Security
- `docker-compose.yml`: a API (que não tem autenticação) e a tela passam a ser publicadas só em `127.0.0.1` (`127.0.0.1:8000`, `127.0.0.1:3000`), e o servidor local do Telegram deixa de ser publicado no host: só o backend o usa, pela rede do Compose. Antes, as três portas abriam em todas as interfaces, e numa rede compartilhada ou num VPS qualquer um podia usar a API. Para acessar de outra máquina, ponha um proxy reverso com autenticação na frente (#35).
- A API recusa com `400 {"detail": "Invalid host header"}` qualquer requisição cujo `Host` não seja `127.0.0.1`, `localhost`, `[::1]` ou um nome listado em `ALLOWED_HOSTS`. Isso impede que uma página maliciosa aberta no navegador use a API local por DNS rebinding (enviar, agendar, apagar). Quem acessa por um proxy reverso precisa pôr o domínio dele em `ALLOWED_HOSTS` (#36).
- Pacote portátil: o servidor local do Telegram (`telegram-bot-api.exe`) sobe com `--http-ip-address=127.0.0.1` e passa a aceitar conexões só da própria máquina. Antes ele escutava em todas as interfaces, e qualquer computador da rede podia usá-lo, embora só o backend precise dele. O smoke do Windows confere que a porta abre em `127.0.0.1` e fica fechada no IP da rede (#37).
- O log de início do servidor local do Telegram mostra `--api-id=***` e `--api-hash=***` em vez das credenciais do my.telegram.org. Antes, com o logging em `INFO`, o `api_hash` ia em texto puro para o log (#40).
- O rastreador de progresso de upload (`GET /api/v1/broadcasts/progress/{tracking_id}`) passa a ter limite: uma entrada sem uso por 30 minutos sai na próxima escrita, e acima de 1.000 entradas saem as usadas há mais tempo. Antes, cada `tracking_id` enviado pelo cliente ficava na memória para sempre. O prazo conta do último acesso, então um upload longo não perde o progresso no meio (#38).
- CI: no push para a `main`, o job `Dependency, Code & Secret Scan` varre o histórico inteiro com o gitleaks 8.24.3 (mesma versão e checksum do `verify.sh`) e falha se achar segredo. Antes, o `gitleaks-action` verificava 0 commits no push, e o histórico nunca passava pelo scanner; nos PRs, a action continua varrendo só os commits do PR (#41).
- `POST /api/v1/broadcasts` confere o tipo real da mídia e da capa pela assinatura do arquivo (JPEG, PNG, WebP, MP4/MOV), e não só pela extensão. Conteúdo que não bate com a extensão responde `422 "Unsupported media format"`, antes de qualquer coisa ser gravada em `temp_media/`. Cada arquivo tem limite de tamanho, configurável em `MAX_MEDIA_UPLOAD_MB` (padrão: 2.000 MB com o servidor local do Telegram, 50 MB na API pública); acima dele, `413 "Media file too large (limit: N MB)"` e o arquivo parcial é apagado. Uma capa enviada sem vídeo deixa de ser gravada e esquecida em `temp_media/` (#39).

## [0.4.0] - 2026-10-23

### Added
- Código aberto sob a licença MIT, com `README.md`, `SECURITY.md` e `THIRD_PARTY_NOTICES.md`. O pacote portátil passa a levar a `LICENSE` e os avisos de terceiros (FFmpeg GPL-3.0, telegram-bot-api, OpenSSL, Python e bibliotecas).

## [0.3.0] - 2026-10-23

### Added
- Busca de canais do bot no cadastro de canal: o botão "Buscar canais do bot" lista os canais e grupos em que o bot do perfil está, e cada canal ou supergrupo é vinculado com um clique, sem copiar o `-100…` à mão. Um campo opcional resolve um canal público por `@username` ou `t.me/username`. Novas rotas `POST /api/v1/profiles/{profile_id}/discover-chats` e `POST /api/v1/profiles/{profile_id}/resolve-chat`. A busca só lê os updates do Telegram: não confirma nenhum (sem `offset`) nem altera a configuração do bot (sem `allowed_updates`).
- Teste da aplicação real (`npm run test:real-app`, também no CI): o backend sobe como no pacote portátil, servindo o frontend exportado, e o Playwright percorre os fluxos de quem usa o app contra ele. O Telegram é uma API falsa que registra o que recebeu (`getMe`, `sendMessage`, `sendPhoto`, `sendVideo`), ou o Telegram real com um bot e um canal de teste (`E2E_BOT_TOKEN`, `E2E_CHANNEL_ID`).

### Changed
- As imagens do `backend/Dockerfile`, do `frontend/Dockerfile` e do `docker-compose.yml` passam a ser fixadas por tag e digest (`python:3.12-slim`, `ghcr.io/astral-sh/uv:0.6.5`, `node:22-alpine`, `aiogram/telegram-bot-api:10.3`), e o teste de política de imagens reprova imagem sem digest.

### Fixed
- Pacote portátil: com a porta 8000 ocupada, o backend subia na 8001, mas a tela continuava chamando a API na 8000 e nada funcionava. O export do frontend agora chama a API na mesma origem que serve a tela, e o smoke test Windows ocupa a 8000 antes de subir o launcher. O `npm run dev` continua usando `http://localhost:8000`.
- No pacote portátil, cadastrar um bot falhava com `Network error validating bot token: All connection attempts failed` (400). O launcher subia o `telegram-bot-api` local sem `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`, ele encerrava logo, e o backend continuava apontando para `127.0.0.1:8081`, porque o fallback para a API pública só reconhecia o host `telegram-bot-api` do Docker Compose. Sem as credenciais, o servidor local não é iniciado; com elas, um servidor local fora do ar cai na API pública em qualquer endereço. O smoke test do Windows passa a cadastrar um bot com token falso e exige a recusa do Telegram (422), não um erro de conexão.

## [0.2.0] - 2026-10-23

### Added
- O `Iniciar-AutoSend.bat` faz uma autoverificação a cada início: confere se o `telegram-bot-api.exe`, o `ffmpeg.exe` e o `ffprobe.exe` abrem nesta máquina e se o caminho da pasta tem acento, grava o resultado em `data\diagnostico.txt` e mostra uma linha `[OK]` ou `[AVISO]` na janela, sem impedir o servidor de subir. Quem usa o pacote não precisa rodar nada.
- Smoke test do pacote portátil num container Windows limpo (`windows/server`, sem Python, Node nem runtime do VC++), rodado no PR da release (branch `release/`), num PR com o label `windows-build` e na própria tag, antes de publicar: extrai o `.zip`, confere os binários, sobe o `Iniciar-AutoSend.bat` e verifica a API e o frontend. Na tag, o `release.yml` só publica o `.zip` que passou nesse teste. Os PRs comuns não rodam jobs Windows. A imagem é definida em `docker/windows-smoke/Dockerfile` (imagem oficial da Microsoft, fixada por digest, usuário sem privilégio) e também roda em qualquer Windows com Docker. Um teste passa a reprovar Dockerfile com `:latest`, imagem sem tag, imagem fora das oficiais ou estágio final como root.

### Fixed
- O `telegram-bot-api.exe` do pacote portátil não abria num Windows sem o Visual C++ Redistributable (`0xC0000135`, faltavam `VCRUNTIME140.dll`, `MSVCP140.dll` e `VCRUNTIME140_1.dll`). O build no Windows agora copia essas DLLs da pasta `Redist` do Visual Studio para `bin/`, ao lado do executável, e falha se não as encontrar.
- O pacote portátil não trazia o Python: a pasta `python/` só tinha um README, e o launcher dependia de um Python 3.12 instalado no sistema com as dependências do backend. O build agora embute o Python 3.12 com as dependências travadas do `uv.lock` (`--skip-python` desliga). O `._pth` do Python embutido passa a incluir `..\app\backend`, porque com ele o `PYTHONPATH` do launcher é ignorado.
- O build do pacote portátil no Windows não achava o `npm` (`FileNotFoundError`), porque lá ele é um `npm.cmd`; e o script `build:export` usava `NEXT_EXPORT=true next build`, sintaxe que o `cmd.exe` não entende. Por isso a `v0.1.1` também saiu sem o `.zip`. O build agora chama o npm pelo caminho resolvido e passa `NEXT_EXPORT` pelo ambiente, e o CI gera o pacote num runner Windows a cada PR (artefato `AutoSend-Portable`).

## [0.1.1] - 2026-10-22

### Fixed
- O build do pacote portátil morria no Windows com `UnicodeEncodeError` no primeiro emoji das mensagens de progresso, porque o console abre em cp1252; por isso a `v0.1.0` saiu sem o `.zip`. Os scripts de build agora trocam o console para UTF-8 antes de imprimir.

## [0.1.0] - 2026-10-22

Primeira versão pública.

### Added
- Cadastro de perfis (bots do Telegram) e canais.
- Broadcast de texto, foto e vídeo para os canais de um perfil, com botão de link inline e hyperlink no texto.
- Suporte a vídeos de até 2GB via servidor local `telegram-bot-api`, com fallback para a API pública (limite de 50MB).
- Barra de progresso real de upload, incluindo o estágio de processamento pelo Telegram.
- Miniaturas proporcionais e metadados nativos (dimensões e duração) para vídeos.
- Agendamento de broadcasts com fila, cancelamento, edição, normalização de fuso horário e reconciliação após reinício (APScheduler + SQLite).
- Circuit breaker e respeito a `Retry-After` (HTTP 429) no gateway do Telegram.
- Pacote portátil para Windows com launcher de 1 clique, download automático do `telegram-bot-api` e do ffmpeg, portas dinâmicas e encerramento dos processos filhos via Job Object.
- Docker Compose com healthchecks, imagens fixadas e containers não-root.
- Fila de agendamentos mostra a data relativa ("em 2 horas", "amanhã") ao lado da data, no idioma do navegador, atualizada a cada minuto.

### Changed
- `POST /api/v1/broadcasts` com `scheduled_at` no passado responde `422 "scheduled_at cannot be in the past"` (antes `400 "Scheduled date must be in the future"`), igual ao `PATCH`; os dois aceitam até 60 s de atraso de relógio.
- Cancelar um agendamento e carregar um agendamento sobre um rascunho pedem confirmação num modal acessível (foco preso, `Esc` fecha), não mais no `confirm()` do navegador; o lint proíbe `alert`/`confirm`/`prompt`.
- `POST /api/v1/broadcasts`: quando nenhum canal recebe, `status` passa de `PARTIALLY_COMPLETED` para `FAILED`, o mesmo valor que já era gravado. Entrega parcial continua `PARTIALLY_COMPLETED` e agora também é gravada assim.
- Vídeos verticais são enviados com as dimensões nativas (o recorte 4:5 foi revertido).
- Frontend consome a URL da API por variável de ambiente e exibe erros em toasts, sem `alert()`.

### Fixed
- Migração automática de bancos SQLite com esquema antigo.
- SQLite em modo WAL com `busy_timeout` contra `database is locked`.
- CORS sem wildcard com credenciais; TTL no rastreador de progresso de upload; rejeição de agendamentos no passado.
- Erros da API aparecem com a mensagem do backend, inclusive as listas de validação (422); uma resposta HTTP de erro não é mais exibida como "Erro de conexão".
- Testes usam banco e diretório de mídia temporários; antes, rodar os testes de integração apagava as tabelas do `auto_send.db` real.
- O OpenAPI anunciava a versão `1.0.0`; agora usa a mesma versão de `backend/pyproject.toml` e `frontend/package.json`, com um teste que compara as três fontes.
- `PATCH /api/v1/broadcasts/{id}` rejeitava qualquer horário até o instante atual, enquanto o `POST` aceitava 60 s de atraso; a regra agora é única e mora no domínio.
- O pacote portátil instalava as versões mais novas de cada dependência (`>=`); agora instala exatamente as do `backend/uv.lock`, inclusive as dependências só de Windows.
- Status de entrega parcial: a rota gravava `FAILED` e o agendador gravava `COMPLETED`; os dois agora gravam `PARTIALLY_COMPLETED`, decidido pelo agregado (`finish_dispatch`).

### Security
- `certifi` atualizado para 2026.10.19 (PYSEC-2026-4320).
- O pacote portátil confere o SHA-256 do telegram-bot-api, do ffmpeg, do Python embutido e do `get-pip.py` (agora fixado num commit) antes de extrair; um arquivo divergente é apagado e o build falha.
