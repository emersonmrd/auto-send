# Auto-Send

Self-hosted dashboard to manage Telegram bots and schedule broadcasts to the channels they administer.

Each **profile** holds one Telegram bot. You link the channels and groups where that bot is an
administrator, then compose a message (text, photo or video, with an optional inline link button)
and send it now or schedule it. Auto-Send runs on your own machine; bot tokens never leave the backend.

## Features

- Multiple profiles, each with its own bot token, validated against the Telegram API on registration.
- Channel discovery: list the chats the bot is in and link them with one click, or resolve a public
  `@username` / `t.me/...` link.
- Broadcasts with text, photo or video and an inline URL button, with a live preview shaped like a Telegram message.
  Text longer than a caption is sent as a separate message before the media.
- Reusable message templates (presets): save and load messages with one click directly in the composer.
- Scheduling in UTC, shown in the browser's time zone; scheduled broadcasts can be edited, rescheduled or cancelled.
- Large videos (up to 2 GB) through a local [Telegram Bot API server](https://github.com/tdlib/telegram-bot-api);
  easily configure your credentials directly from the settings dialog.
- Multi-channel broadcast optimization: single physical upload with instant delivery to subsequent channels via Telegram `file_id` reuse.
- Dynamic transmission feedback: real-time live elapsed timer, accurate upload progress, and immediate broadcast cancellation without phantom deliveries.
- Rate-limit handling (`Retry-After`) and an automated circuit breaker protecting against Telegram API throttles.
- Windows portable package: unzip and double-click, with seamless data preservation across version upgrades.

## Quick start

### Windows portable package

1. Download `AutoSend-Portable.zip` from [Releases](https://github.com/emersonmrd/auto-send/releases) and check its SHA-256.
2. Unzip it and double-click `Iniciar-AutoSend.bat`. The browser opens at `http://localhost:8000`.
3. Application data and configuration are safely stored in `%LOCALAPPDATA%\Auto-Send\` (persisting across updates and extractions). You can open this folder directly via the "Abrir pasta de dados" (Open data folder) button in the dashboard.

The package is not code-signed, so Windows SmartScreen may warn on first run ("More info" → "Run anyway").

### Docker Compose

```bash
cp .env.example .env   # optional: TELEGRAM_API_ID / TELEGRAM_API_HASH from https://my.telegram.org
docker compose up --build
```

Frontend at `http://localhost:3000`, API at `http://localhost:8000` (OpenAPI docs at `/docs`).

Both ports are published on `127.0.0.1` only. The API has no authentication: to reach it from another machine (a VPS, your LAN), put a reverse proxy with authentication in front of it instead of publishing the ports on `0.0.0.0`. The API only answers requests whose `Host` is a loopback name; add the proxy's domain to `ALLOWED_HOSTS` in `.env`.

### From source

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node.js 22.

```bash
cd backend && uv sync && uv run uvicorn src.presentation.main:app --reload --port 8000
cd frontend && npm ci && npm run dev
```

## Configuration

| Variable | Purpose |
|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Credentials from [my.telegram.org](https://my.telegram.org) for the local Bot API server (2 GB uploads). Use your own. |
| `TELEGRAM_API_BASE_URL` | Bot API base URL; defaults to the public API. |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API. |
| `NEXT_PUBLIC_API_URL` | API URL used by the frontend. |

## Development

- Architecture, engineering rules and verification commands: [`AGENTS.md`](AGENTS.md) (in Portuguese).
- Run every check locally: `bash scripts/dev/verify.sh`.
- Changes are listed in [`CHANGELOG.md`](CHANGELOG.md).

## Responsible use

Auto-Send is a tool for publishing to channels **you own or administer, with bots you created**.
You are responsible for the content you send and for following the
[Telegram Terms of Service](https://telegram.org/tos), the
[Bot Developer Terms](https://telegram.org/tos/bot-developers) and the laws that apply to you.
Do not use it for spam, unsolicited messages or content that Telegram's terms forbid.

## Security

See [`SECURITY.md`](SECURITY.md) to report a vulnerability.

## License

[MIT](LICENSE). The Windows package redistributes third-party software under its own licenses;
see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

The software is provided "as is", without warranty of any kind. Use it at your own risk.
