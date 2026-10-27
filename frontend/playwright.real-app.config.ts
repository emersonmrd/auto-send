import path from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { APP_PORT, FAKE_TELEGRAM_PORT, RUN_DIR as runDir, USES_REAL_TELEGRAM } from "./tests-real-app/env";

// Teste da aplicação real: o backend FastAPI sobe como no pacote portátil, servindo o frontend exportado
// (frontend/out) e a API na mesma porta, com banco e mídia temporários. Nada de rota simulada no navegador.
// Telegram: com E2E_BOT_TOKEN e E2E_CHANNEL_ID no ambiente, o backend fala com o Telegram de verdade;
// sem eles, com a API falsa de tests-real-app/fake-telegram.mjs, que registra o que recebeu.
// Rode com `npm run test:real-app` (tests-real-app/run.mjs faz o export e limpa a pasta temporária antes).

const backendDir = path.resolve(__dirname, "../backend");
const staticDir = path.resolve(__dirname, "out");

const fakeTelegram = {
  command: "node tests-real-app/fake-telegram.mjs",
  url: `http://127.0.0.1:${FAKE_TELEGRAM_PORT}/__calls`,
  env: { FAKE_TELEGRAM_PORT: String(FAKE_TELEGRAM_PORT) },
  reuseExistingServer: false,
};

const backend = {
  // tests-real-app/run.mjs recria a pasta temporária (banco e mídia) antes; nunca o auto_send.db.
  command: `uv run uvicorn src.presentation.main:app --host 127.0.0.1 --port ${APP_PORT}`,
  cwd: backendDir,
  url: `http://127.0.0.1:${APP_PORT}/api/v1/health`,
  timeout: 120_000,
  reuseExistingServer: false,
  env: {
    STATIC_DIR: staticDir,
    DATABASE_URL: `sqlite+aiosqlite:///${runDir}/real-app.db`,
    TEMP_MEDIA_DIR: `${runDir}/media`,
    // Telegram real: sem credenciais do my.telegram.org, como no PC de quem usa o pacote (API pública).
    // API falsa: o gateway só usa um TELEGRAM_API_BASE_URL próprio quando há credenciais (servidor local),
    // então a falsa entra no lugar do servidor local com credenciais de mentira.
    ...(USES_REAL_TELEGRAM
      ? {
          TELEGRAM_API_ID: process.env.TELEGRAM_API_ID || "",
          TELEGRAM_API_HASH: process.env.TELEGRAM_API_HASH || "",
        }
      : {
          TELEGRAM_API_ID: "1",
          TELEGRAM_API_HASH: "fake-api-hash",
          TELEGRAM_API_BASE_URL: `http://127.0.0.1:${FAKE_TELEGRAM_PORT}`,
        }),
  },
};

export default defineConfig({
  testDir: "./tests-real-app",
  // Um backend e um banco para a suíte inteira: os testes rodam em sequência.
  workers: 1,
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${APP_PORT}`,
    // O trace grava o que é digitado: com o Telegram real ele guardaria o token do bot.
    trace: USES_REAL_TELEGRAM ? "off" : "retain-on-failure",
  },
  webServer: USES_REAL_TELEGRAM ? [backend] : [fakeTelegram, backend],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
