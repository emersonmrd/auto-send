// Roda a suíte da aplicação real: export do frontend (NEXT_EXPORT=true), pasta temporária limpa e Playwright.
// Em Node, e não como "VAR=valor comando" no package.json, para funcionar também no cmd.exe do Windows.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const runDir = path.join(os.tmpdir(), "auto-send-real-app");
const npx = process.platform === "win32" ? "npx.cmd" : "npx";

function run(args, env = {}) {
  const result = spawnSync(npx, args, { stdio: "inherit", env: { ...process.env, ...env }, shell: process.platform === "win32" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run(["next", "build"], { NEXT_EXPORT: "true" });
// Banco e mídia do backend recriados a cada execução; nunca o auto_send.db.
fs.rmSync(runDir, { recursive: true, force: true });
fs.mkdirSync(path.join(runDir, "media"), { recursive: true });
run(["playwright", "test", "-c", "playwright.real-app.config.ts", ...process.argv.slice(2)]);
