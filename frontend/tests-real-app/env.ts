import os from "node:os";
import path from "node:path";

// Portas e modo da suíte da aplicação real, lidos pela config e pelos testes.
export const APP_PORT = 8011;
export const FAKE_TELEGRAM_PORT = 8091;
// Credenciais reais de teste: aceita E2E_BOT_TOKEN e E2E_CHANNEL_ID padrão ou aliases existentes.
export const REAL_BOT_TOKEN =
  process.env.E2E_BOT_TOKEN ||
  process.env.E2E_BOT_TOKEN_ALFA ||
  process.env.E2E_BOT_TOKEN_2 ||
  "";

export const REAL_CHANNEL_ID =
  process.env.E2E_CHANNEL_ID ||
  process.env.E2E_CHANNEL_AUTOSEND ||
  process.env.E2E_CHANNEL_TEST ||
  process.env.E2E_CHANNEL_TEST3 ||
  "";

// Supergrupo de teste (#99), com o bot de teste como administrador; sem ele, a suíte usa o supergrupo da API falsa.
export const REAL_SUPERGROUP_ID = process.env.E2E_SUPERGROUP_AUTOSEND || "";

// Com bot e canal de teste no ambiente, a suíte usa o Telegram de verdade em vez da API falsa.
export const USES_REAL_TELEGRAM = Boolean(REAL_BOT_TOKEN && REAL_CHANNEL_ID);
// Banco e mídia temporários do backend da suíte, recriados a cada execução.
export const RUN_DIR = path.join(os.tmpdir(), "auto-send-real-app");
