import os from "node:os";
import path from "node:path";

// Portas e modo da suíte da aplicação real, lidos pela config e pelos testes.
export const APP_PORT = 8011;
export const FAKE_TELEGRAM_PORT = 8091;
// Com bot e canal de teste no ambiente, a suíte usa o Telegram de verdade em vez da API falsa.
export const USES_REAL_TELEGRAM = Boolean(process.env.E2E_BOT_TOKEN && process.env.E2E_CHANNEL_ID);
// Banco e mídia temporários do backend da suíte, recriados a cada execução.
export const RUN_DIR = path.join(os.tmpdir(), "auto-send-real-app");
