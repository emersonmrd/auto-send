# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento [SemVer](https://semver.org/lang/pt-BR/).
Correção = patch, adição = minor, mudança incompatível = major. A skill `release` lê a seção `[Unreleased]` para decidir o próximo número.

## [Unreleased]

### Added
- Suporte completo a enquetes nativas do Telegram (`sendPoll`) no compositor e agendamentos: modos enquete comum e quiz/questionário, opções dinâmicas (2 a 10), voto anônimo, múltiplas escolhas, resposta correta, explicação pós-voto e prévia interativa no balão (#97).
- Rota `POST /api/v1/broadcasts/abort-upload/{tracking_id}`: cancelar um envio na tela interrompe o disparo no backend, apaga a mídia temporária e marca o broadcast como `CANCELLED`, guardando os canais que já receberam (#86).
- Teste automatizado garantindo que os modelos de mensagem sobrevivem a atualizações futuras do banco de dados, e menção explícita aos modelos de mensagem no `COMO_USAR.txt` do pacote portátil (#92).
- Validação automatizada no CI (`Decide what to run`) e script `validate_pr_checklist.py` garantindo que toda Pull Request contenha a seção `## Checklist`, skills utilizadas e confirmação de merge humano (#95).
- Tipo do chat nos canais: o vínculo lê do Telegram se o destino é canal, supergrupo ou fórum e mostra o selo (📢 Canal, 👥 Grupo, 💬 Fórum) nos canais destino e na busca. Grupo comum ganha uma explicação passo a passo de como convertê-lo em supergrupo, e a busca não lista mais o grupo comum que já virou supergrupo. Canais vinculados antes desta versão recebem o tipo na próxima edição. Contrato: `chat_type` e `is_forum` nas respostas de canal e `is_forum` nos chats descobertos (campos novos, compatíveis); migração 8 do banco (#99).
- Enquete com votos visíveis só pode ir para grupos: com algum canal (ou canal ainda sem tipo) entre os destinos, o compositor trava o voto anônimo e explica por quê, e a API responde `422` em `POST /api/v1/broadcasts` e no `PATCH` que troca destinos (#99).
- Bot só como membro pode ser vinculado a grupos e supergrupos: administrador continua obrigatório só em canal. O vínculo de grupo não depende das permissões de envio; as mensagens de erro de envio deixam de supor que todo destino é canal (#100).
- Botão "i" em cada canal destino: abre um painel com o tipo do chat, a situação do bot (criador, administrador, membro, restrito ou fora do chat) e se ele pode enviar texto, foto, vídeo e enquete, com o motivo de cada ❌. Os dados são lidos do Telegram ao abrir e em "Atualizar". Contrato: rota nova `GET /api/v1/channels/{channel_id}/bot-permissions` (`200`, `404`, `503`) (#107).
- Antes de cada envio (imediato, "enviar agora" ou agendado), o backend confere se o bot pode mandar aquele conteúdo ao destino: texto, foto, vídeo ou enquete. Sem permissão, o destino aparece como falha com o motivo em português (ex.: "O bot não pode enviar fotos neste grupo"), nenhum envio é tentado a ele, e os outros destinos recebem normalmente. Se o Telegram não responder à consulta, o envio segue como antes (#107).

### Fixed
- Botões "Editar Canal" e "Excluir Canal" nos chips de destino agora abrem a edição e o diálogo de exclusão ao pressionar Enter ou Espaço, sem alternar a seleção do destino (#114).
- Enquete criada pela API sem o campo `poll_is_anonymous` saía pública: o FastAPI trata booleano de formulário ausente como `false`. Agora a ausência vale como voto anônimo, o padrão documentado (#99).
- Cancelar o envio várias vezes não publica mais a mensagem repetida no canal: antes, o backend continuava o disparo depois que o navegador fechava a conexão (#86).
- A barra de progresso não estaciona mais em 97% enquanto o Telegram processa o vídeo: a segunda fase mostra animação contínua, cronômetro e tamanho do arquivo, e crava 100% na confirmação (#86).
- O card de progresso do envio tem a mesma largura da caixa de texto do compositor e não mostra mais o prefixo "Fase 1/2", que sobrou de quando havia duas fases (#87).
- O gateway do Telegram fica estritamente isolado em porta fechada local durante os testes de contrato OpenAPI, impedindo fallback para a API pública na nuvem e eliminando timeouts intermitentes no Schemathesis (#91).


## [0.6.1] - 2026-10-27

### Performance
- Reutilização instantânea de `file_id` do Telegram em disparos de mídias (vídeos e fotos) para múltiplos canais, realizando o upload físico do binário uma única vez e despachando para os canais subsequentes por referência, reduzindo drasticamente o tempo de envio e consumo de rede (#83).

### Fixed
- Correção da oscilação e saltos para 100% na barra de progresso durante o envio de vídeos para múltiplos canais, mantendo cálculo contínuo e sincronizado com o arquivo real (#83).
- Suporte a aliases de credenciais no runner E2E real (`E2E_BOT_TOKEN_ALFA`, `E2E_CHANNEL_TEST`, etc.) para testes com bots e canais reais (#83).


## [0.6.0] - 2026-10-27

### Added
- Modal interativo e persistência de credenciais da Telegram API (`TELEGRAM_API_ID` e `TELEGRAM_API_HASH`) em `%LOCALAPPDATA%\Auto-Send\.env` (mantido entre versões e pastas no Windows), permitindo configurar ou alterar credenciais a qualquer momento e ativando o servidor local para uploads de até 2 GB (#56).
- Presets e modelos de mensagens reutilizáveis por perfil: criação, carregamento com um clique no compositor, exclusão com modal de confirmação acessível e listagem ordenada (#63).
- Identidade visual proprietária: ícone SVG vetorial e favicon com tema do Robô Carteiro (#62).
- Melhorias na barra do editor: destaque dos botões correspondentes aos estilos ativos sob o cursor e botão para limpar formatação (#61).
- Testes automatizados permanentes para os 3 cenários do pacote Windows portátil: persistência de dados em `%LOCALAPPDATA%\Auto-Send` entre extrações de releases, endpoint `POST /api/v1/system/open-data-dir` e fluxo Playwright de impacto na exclusão de canal com agendamentos (#65).
- Testes automatizados permanentes para o pipeline de envio de vídeos com streaming, leitura de metadados reais de 7 MB e 356 MB (duração e resolução vertical 4K) e ciclo de vida com descarte garantido de arquivos temporários em envio e cancelamento (#64).

### Changed
- Remoção do botão externo redundante de inserção de link no compositor, centralizando a formatação de hiperlinks exclusivamente na barra do editor e diferenciando a seção de botão físico abaixo da mensagem (Inline Keyboard) (#59).
- Remoção do modal redundante de edição na fila de agendamentos, unificando todo o fluxo de edição no compositor principal (#58).

### Fixed
- Mensagens amigáveis em português para erros retornados pela API do Telegram no catálogo da interface desktop (#57).
- Navegação em blocos de código do editor: suporte a teclas direcionais (ArrowUp / ArrowDown) e Enter / Ctrl+Enter para criar linhas e sair do bloco (#60).
- Prevenção de cadastro de canais duplicados por perfil no backend (`409 Conflict`) e debounce com feedback de loading em botões de ação do frontend (#54).
- Resolução de violação de strict mode no seletor do botão 'Salvar' da suíte Playwright no modal de link inline do dashboard (#77).


## [0.5.0] - 2026-10-26

### Added
- Cadastro de canal pelo link de um post ou pelo ID: o campo da busca de canais aceita, além de `@username`/`t.me/username`, o link copiado de um post (`https://t.me/c/<id>/<post>`, convertido para `-100<id>`), o link de post de canal público (`t.me/<username>/<post>`) e o ID `-100…`. Serve para canal privado em que ninguém postou nas últimas 24 h e para bot ligado a outro sistema por webhook (#12).
- Persistência do banco de dados entre atualizações e migrações numeradas com backup (#24):
  - No pacote portátil para Windows, os dados (`autosend.db`, `media_temp/` e `telegram_bot_api/`) ficam em `%LOCALAPPDATA%\Auto-Send\`, preservando perfis, canais e agendamentos quando o usuário extrai uma versão nova em outra pasta.
  - Na primeira inicialização sem banco em `%LOCALAPPDATA%\Auto-Send\`, o app procura `data\autosend.db` da `v0.4.0` na própria pasta da release, na pasta pai e em Downloads, Área de Trabalho e Documentos, oferecendo importar sem apagar o arquivo original.
  - Migrações numeradas em `PRAGMA user_version` (em transação e idempotentes) com backup automático `autosend.db.bak-<versão anterior>` antes de cada migração, mantendo os 3 backups mais recentes; se uma migração falhar, o banco permanece na versão anterior e o app avisa sem abrir.
  - Botão "Abrir pasta de dados" na barra lateral (`POST /api/v1/system/open-data-dir`).
- Janela de tolerância de agendamento (`SCHEDULE_MISFIRE_GRACE_MINUTES`, padrão: 30 minutos) e status `MISFIRED` (#1):
  - Agendamentos vencidos dentro da janela disparam normalmente; acima da janela (no startup ou após suspensão do PC), vão para `MISFIRED` em vez de serem enviados fora de hora.
  - O arquivo temporário de mídia é mantido enquanto o agendamento estiver `MISFIRED`, sendo apagado ao enviar ou descartar.
  - Na interface, um banner não bloqueante avisa sobre agendamentos expirados e a fila exibe os itens `MISFIRED` no topo com o selo "Expirado" e as ações **Enviar agora** (`POST /api/v1/broadcasts/{broadcast_id}/dispatch-now`), **Reagendar** (`PATCH /api/v1/broadcasts/{broadcast_id}`) e **Descartar** (`DELETE /api/v1/broadcasts/{broadcast_id}/cancel`).
- Verificação de permissão de administrador no cadastro e na edição de canal (#2):
  - `POST /api/v1/profiles/{profile_id}/channels` e `PUT /api/v1/channels/{channel_id}` (quando o `chat_id` muda) consultam `getMe` + `getChatMember` no Telegram para confirmar que o bot do perfil é administrador com permissão de publicar (`can_post_messages`).
  - Se o bot não estiver no canal ou não puder publicar, responde `400 {"detail": "Bot is not administrator in the channel"}`; se o Telegram estiver inacessível (rede, timeout, 429, 5xx ou circuito aberto), responde `503 {"detail": "Could not reach Telegram, try again"}` sem gravar o canal.
- Prevenção de agendamentos órfãos ao excluir ou editar canais e perfis (#28):
  - Novas rotas `GET /api/v1/channels/{channel_id}/affected-broadcasts` e `GET /api/v1/profiles/{profile_id}/affected-broadcasts` listam para os modais os agendamentos que serão cancelados e os que apenas perderão o destino (ou terão o destino atualizado).
  - `DELETE /api/v1/channels/{channel_id}` remove o canal de `target_channel_ids` nos agendamentos pendentes e cancela (removendo o job e apagando a mídia) os que ficarem sem canal; `PUT /api/v1/channels/{channel_id}` atualiza o `chat_id` nos agendamentos pendentes; `DELETE /api/v1/profiles/{profile_id}` cancela os agendamentos pendentes e limpa os recursos antes de remover o perfil.
  - Se houver envio `DISPATCHING` para o canal ou perfil, a exclusão ou troca de ID é recusada com `422`.
- Resultado e motivo de falha por canal nos envios e no histórico (#31):
  - `POST /api/v1/broadcasts` (envio imediato), `POST /api/v1/broadcasts/{broadcast_id}/dispatch-now` e `GET /api/v1/profiles/{profile_id}/broadcasts` passam a incluir `delivery_results` (`chat_id`, `delivered`, `failure_category`, `detail`).
  - O gateway classifica as recusas do Telegram nas categorias do domínio (`BOT_NOT_IN_CHAT`, `NO_POST_PERMISSION`, `INVALID_TOKEN`, `RATE_LIMITED`, `TELEGRAM_UNAVAILABLE`, `OTHER`) sem nunca expor o token do bot, e a tela mostra o resultado e o motivo em português por canal.
  - Migração #4 adiciona a coluna `delivery_results` na tabela `broadcasts`.
- Edição de agendamentos diretamente no compositor com trava de edição temporária (#15):
  - Na fila de agendamentos, a ação "Carregar no Editor" adquire uma trava temporária de 90 segundos (`POST /api/v1/broadcasts/{id}/edit-lock`, renovada a cada 30 s), carrega texto, canais de destino, data e botões inline no compositor principal e exibe aviso de modo de edição com botão para sair (`DELETE /api/v1/broadcasts/{id}/edit-lock`).
  - Ao clicar em "Agendar", salva no mesmo registro via `PATCH /api/v1/broadcasts/{id}` (com atualização de canais e liberação do lock) sem duplicar o agendamento na fila.
  - O agendador e reconciliador suspendem o disparo enquanto a trava estiver ativa; se o horário agendado for ultrapassado durante a edição, o lock expirado cancela o agendamento de forma limpa.
  - Migração #5 adiciona a coluna `edit_locked_until` na tabela `broadcasts`.
- Mídia do agendamento no modo de edição do compositor (#18):
  - Ao carregar um agendamento com mídia para edição, o preview exibe a foto ou o vídeo atual diretamente pela nova rota `GET /api/v1/broadcasts/{broadcast_id}/media` (streaming inline com validação contra path traversal e sem expor o caminho interno no servidor).
  - O compositor exibe uma barra dedicada com o tipo e tamanho da mídia agendada e botão para remover (`DELETE /api/v1/broadcasts/{broadcast_id}/media`, apagando o arquivo físico do disco).
  - O botão de anexo permite substituir a mídia existente ou adicionar mídia a um agendamento de texto (`PUT /api/v1/broadcasts/{broadcast_id}/media`, com remoção limpa do arquivo anterior se substituído).
  - O DTO `BroadcastMediaResponse` deixa de expor o campo `file_path`.
  - No domínio, `BroadcastMessage.replace_media()` e `BroadcastMessage.remove_media()` garantem a integridade do estado e tipos suportados em agendamentos pendentes.

### Changed
- `POST /api/v1/profiles/{profile_id}/resolve-chat` aceita as novas formas de identificador. Link de convite (`t.me/+…`) responde `422` explicando que é preciso o link de um post ou o ID; os demais identificadores inválidos respondem `422 "Invalid chat identifier (...)"` (#12).
- `POST /api/v1/profiles/{profile_id}/discover-chats` com webhook ativo no bot responde `400 "Bot webhook is active: automatic discovery is unavailable"`, sem abrir o circuit breaker; a tela explica em português e leva para a entrada manual. O app nunca apaga o webhook (#12).
- O painel de busca de canais orienta a publicar uma mensagem no canal antes de buscar e, com a lista vazia, aponta o link de um post ou o ID (#12).
- CI: a mutação do domínio, no PR, muta só os arquivos de domínio alterados (domínio inteiro quando um teste de domínio ou o `pyproject.toml` muda, no PR de release e na `main`), guarda o cache do mutmut entre execuções e publica os sobreviventes no resumo do job. O `verify.sh` aplica a mesma seleção e passa a considerar mudanças não commitadas (#26).
- Todas as 17 rotas da API declaram `response_model` (Pydantic) e os códigos de erro possíveis no OpenAPI, espelhados em `frontend/src/types/index.ts` e validados por `response_schema_conformance` no Schemathesis, sem alterar os campos já devolvidos (#3).
- Inicialização do pacote portátil e `/api/v1/health` (#29):
  - `GET /api/v1/health` passa a devolver `{"status": "healthy", "app": "auto-send", "version": "<versão>"}`.
  - O launcher abre o navegador em `http://127.0.0.1:<porta>` (em vez de `localhost`), confere portas livres em IPv4 (`127.0.0.1`) e IPv6 (`::1`) e grava o PID ativo em `%LOCALAPPDATA%\Auto-Send\autosend.pid` (removido ao fechar).
  - Se o Auto-Send da mesma versão já estiver aberto na porta 8000, abre o navegador nele sem subir outra instância; se houver instância de outra versão ou travada, pergunta se deve encerrar apenas o PID da própria trava; se for outro programa, usa a próxima porta livre.

### Removed
- Dependências `aiogram` e `aiofiles` do backend, declaradas sem nenhum uso: saem da imagem Docker e do pacote portátil junto com 9 dependências transitivas (`aiohttp` e afins). Um teste reprova dependência de runtime que o `src/` não usa (#4).

### Fixed
- Busca de canais do bot: cada chat mostra o tipo e o ID com rótulo explícito (`Canal: -1001234567890`, ou `Canal: @acme (-1001234567890)` com username), em vez do separador `·` que confundia o tipo com o ID (#13).
- A aba do navegador mostra "Auto-Send" em vez de "Create Next App", o título padrão do template do Next.js (#5).
- Compositor: anexar um arquivo de nome muito longo não empurra mais o campo de mensagem e os botões Enviar/Agendar para fora da tela; o nome aparece truncado, com o nome completo no `title` (#17).
- Acessibilidade: os campos dos formulários (perfil, canal, botão inline, link de texto, agendamento e edição) têm o rótulo visível associado (`<label htmlFor>`), e o campo de mensagem tem `aria-label`; leitores de tela anunciam o rótulo, não o placeholder (#6).
- Mensagens de erro em português e separação entre webhook ativo e bot em uso por outro programa (#32):
  - No `getUpdates` da busca de canais, o `409` por leitura concorrente (`"terminated by other getUpdates request"`) passa a levantar `BotInUseError("Bot is currently in use by another program")` em vez de `WebhookActiveError`, exibindo na tela que o bot está em uso em outro programa.
  - Catálogo centralizado em `frontend/src/lib/apiError.ts` traduz todos os `detail` da API e listas `422` do Pydantic (`"Campo <campo> inválido"`) para português, remove eventuais tokens de bot e usa mensagem genérica em português com o original entre parênteses quando não houver tradução cadastrada.
- Editor de mensagem com formatação visual (sem HTML cru) e sanitização de HTML do Telegram (#16):
  - Novo componente `TelegramRichEditor` usado no compositor e no modal "Editar", exibindo o texto formatado (negrito, itálico, sublinhado, riscado, código, bloco de código, citação, spoiler e link `https://`) sem expor tags `<a href="...">`, com edição/remoção ao clicar em um link existente.
  - O preview e os cards da fila renderizam todas as formatações do Telegram (incluindo spoiler borrado até clicar, citação com barra lateral e código monoespaçado).
  - No domínio (`validate_and_escape_telegram_html`), caracteres `<`, `>` e `&` comuns são escapados antes do envio ao Telegram, e tags não suportadas ou links que não sejam `https://` com host público são recusados com `422`.

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
