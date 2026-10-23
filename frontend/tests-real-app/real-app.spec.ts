import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "@playwright/test";
import { FAKE_TELEGRAM_PORT, RUN_DIR, USES_REAL_TELEGRAM } from "./env";

// Fluxos de quem usa o app, contra o backend real servindo o frontend exportado (playwright.real-app.config.ts).
// Com a API falsa do Telegram, cada fluxo também confere o que chegou ao Telegram.

type TelegramCall = {
  method: string;
  tokenSuffix: string;
  query: Record<string, string>;
  fields: Record<string, unknown>;
  files: Record<string, { filename: string; size: number }>;
};

const FAKE_TOKEN = "123456789:AAFakeTokenForTheRealAppSuite_0001";
const REJECTED_TOKEN = "100000000:AAFakeTokenTheTelegramRejects_0001";
const botToken = process.env.E2E_BOT_TOKEN || FAKE_TOKEN;
const channelId = process.env.E2E_CHANNEL_ID || "-1001234567890";
const profileName = `Perfil ${Date.now()}`;
// PNG 1x1 válido.
const PHOTO = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function telegramCalls(page: Page): Promise<TelegramCall[]> {
  const res = await page.request.get(`http://127.0.0.1:${FAKE_TELEGRAM_PORT}/__calls`);
  return res.json();
}

async function clearTelegramCalls(page: Page) {
  if (!USES_REAL_TELEGRAM) await page.request.delete(`http://127.0.0.1:${FAKE_TELEGRAM_PORT}/__calls`);
}

async function openProfile(page: Page) {
  await page.goto("/");
  await page.getByText(profileName, { exact: true }).first().click();
  await expect(page.getByText("Canal de Teste").first()).toBeVisible();
}

test.describe.serial("aplicação real", () => {
  test.beforeEach(async ({ page }) => clearTelegramCalls(page));

  test("cadastra o perfil validando o token no Telegram", async ({ page }) => {
    await page.goto("/");
    await page.getByTitle("Adicionar Novo Perfil").click();
    await page.getByPlaceholder("Ex: Acme").fill(profileName);
    await page.getByPlaceholder("123456789:ABCdefGhIJKlmNoPQRstu...").fill(botToken);
    await page.getByRole("button", { name: "Cadastrar Perfil" }).click();

    await expect(page.getByText(profileName, { exact: true }).first()).toBeVisible();
    if (!USES_REAL_TELEGRAM) {
      await expect(page.getByText("@teste_0001_bot").first()).toBeVisible();
      const calls = await telegramCalls(page);
      expect(calls.map((c) => c.method)).toEqual(["getMe"]);
    }
  });

  test("mostra o motivo quando o Telegram recusa o token", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM, "a recusa é simulada pela API falsa");
    await page.goto("/");
    await page.getByTitle("Adicionar Novo Perfil").click();
    await page.getByPlaceholder("Ex: Acme").fill("Perfil recusado");
    await page.getByPlaceholder("123456789:ABCdefGhIJKlmNoPQRstu...").fill(REJECTED_TOKEN);
    await page.getByRole("button", { name: "Cadastrar Perfil" }).click();

    await expect(page.getByText(/Unauthorized/).first()).toBeVisible();
    await expect(page.getByText("Perfil recusado", { exact: true })).toHaveCount(0);
  });

  test("vincula o canal ao perfil", async ({ page }) => {
    await page.goto("/");
    await page.getByText(profileName, { exact: true }).first().click();
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
    await page.getByPlaceholder("Ex: Canal de Novidades").fill("Canal de Teste");
    await page.getByPlaceholder("-1001234567890").fill(channelId);
    await page.getByRole("button", { name: "Vincular Canal" }).click();

    await expect(page.getByText("Canal de Teste").first()).toBeVisible();
  });

  test("envia texto para o canal", async ({ page }) => {
    await openProfile(page);
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Teste de texto da aplicação real");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await telegramCalls(page);
      expect(call.method).toBe("sendMessage");
      expect(call.fields).toMatchObject({ chat_id: channelId, text: "Teste de texto da aplicação real" });
    }
  });

  test("envia foto com legenda pelo sendPhoto", async ({ page }) => {
    await openProfile(page);
    await page.locator('input[type="file"]').setInputFiles({ name: "foto.png", mimeType: "image/png", buffer: PHOTO });
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Legenda da foto");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await telegramCalls(page);
      expect(call.method).toBe("sendPhoto");
      expect(call.fields).toMatchObject({ chat_id: channelId, caption: "Legenda da foto" });
      expect(Object.keys(call.files)).toEqual(["photo"]);
    }
  });

  test("envia vídeo pelo sendVideo com streaming", async ({ page }) => {
    // Com o Telegram real, um .mp4 inválido seria recusado; o vídeo real fica para o exploratório.
    test.skip(USES_REAL_TELEGRAM, "precisa de um vídeo válido para o Telegram real");
    await openProfile(page);
    await page
      .locator('input[type="file"]')
      .setInputFiles({ name: "video.mp4", mimeType: "video/mp4", buffer: Buffer.from("fake mp4 bytes") });
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Legenda do vídeo");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    const [call] = await telegramCalls(page);
    expect(call.method).toBe("sendVideo");
    expect(call.fields).toMatchObject({ chat_id: channelId, caption: "Legenda do vídeo", supports_streaming: "true" });
    expect(Object.keys(call.files)).toEqual(["video"]);
  });

  test("agenda e cancela sem nada chegar ao Telegram", async ({ page }) => {
    await openProfile(page);
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Mensagem agendada para cancelar");
    await page.getByLabel("Agendar Mensagem").click();
    await page.getByRole("button", { name: "+1 hora" }).click();
    await page.getByRole("button", { name: "OK — Confirmar Agendamento" }).click();
    await expect(page.getByText(/Mensagem agendada com sucesso/).first()).toBeVisible();
    await page.getByRole("button", { name: "OK / Fechar" }).click();

    await page.getByTitle("Abrir Fila de Agendamentos").click();
    await expect(page.getByText("Mensagem agendada para cancelar").first()).toBeVisible();
    await page.getByTitle("Cancelar agendamento e descartar mídias").click();
    await page.getByRole("button", { name: "Cancelar agendamento" }).click();
    await expect(page.getByText("Nenhum broadcast agendado para este perfil.")).toBeVisible();

    if (!USES_REAL_TELEGRAM) expect(await telegramCalls(page)).toEqual([]);
  });

  // Depois dos envios: os canais vinculados aqui entrariam nos destinos dos testes de envio acima.
  test("busca os canais do bot e vincula sem digitar o -100", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM, "os canais do bot real dependem das mensagens das últimas 24 h");
    await openProfile(page);
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
    const panel = page.getByRole("region", { name: "Buscar canais do bot" });

    await panel.getByRole("button", { name: "Buscar canais do bot" }).click();
    await panel.getByRole("listitem").filter({ hasText: "Canal Descoberto" }).getByRole("button", { name: "Adicionar canal" }).click();
    await expect(page.getByText('Canal "Canal Descoberto" vinculado.').first()).toBeVisible();

    await panel.getByPlaceholder("@meucanal ou t.me/meucanal").fill("https://t.me/canalpublico");
    await panel.getByRole("button", { name: "Buscar canal público" }).click();
    await panel.getByRole("listitem").filter({ hasText: "Canal Público" }).getByRole("button", { name: "Adicionar canal" }).click();
    await expect(page.getByText('Canal "Canal Público" vinculado.').first()).toBeVisible();
    await expect(panel.getByText("Já vinculado")).toHaveCount(2);

    const calls = await telegramCalls(page);
    expect(calls.map((c) => c.method)).toEqual(["getUpdates", "getChat"]);
    // A busca só lê: sem offset nenhum update é confirmado, sem allowed_updates a configuração do bot fica igual.
    expect(calls[0].query).toEqual({ timeout: "0" });
    expect(calls[1].query).toEqual({ chat_id: "@canalpublico" });

    // Os dois canais vinculados pela busca aparecem na barra de canais do perfil.
    await page.goto("/");
    await page.getByText(profileName, { exact: true }).first().click();
    await expect(page.getByText("Canal Descoberto").first()).toBeVisible();
    await expect(page.getByText("Canal Público").first()).toBeVisible();
  });

  test("não deixa mídia temporária depois de enviar e cancelar", () => {
    // AGENTS.md §10: o arquivo em temp_media é apagado depois do envio, com sucesso ou erro, e no cancelamento.
    expect(fs.readdirSync(path.join(RUN_DIR, "media"))).toEqual([]);
  });
});
