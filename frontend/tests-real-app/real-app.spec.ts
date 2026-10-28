import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "@playwright/test";
import { FAKE_TELEGRAM_PORT, REAL_BOT_TOKEN, REAL_CHANNEL_ID, RUN_DIR, USES_REAL_TELEGRAM } from "./env";

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
const WEBHOOK_TOKEN = "200000000:AAFakeTokenWithAnActiveWebhook_0002";
const botToken = REAL_BOT_TOKEN || FAKE_TOKEN;
const channelId = REAL_CHANNEL_ID || "-1001234567890";
const profileName = `Perfil ${Date.now()}`;
// PNG 1x1 válido.
// O backend confere a assinatura (caixa ftyp de um MP4) antes de aceitar o vídeo (#39).
const FAKE_MP4 = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from("ftypmp42fake mp4 bytes")]);
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

  test("cria e envia uma enquete para o canal pelo sendPoll", async ({ page }) => {
    await openProfile(page);
    await page.getByLabel("Criar Enquete").click();

    const dialog = page.getByRole("dialog", { name: "Criar Enquete do Telegram" });
    await dialog.getByPlaceholder("Ex: Qual tema vocês querem no próximo conteúdo?").fill("Qual seu framework favorito?");
    await dialog.getByPlaceholder("Opção 1").fill("React");
    await dialog.getByPlaceholder("Opção 2").fill("Vue");
    await dialog.getByRole("button", { name: "Salvar", exact: true }).click();

    await expect(page.getByText("Qual seu framework favorito?").first()).toBeVisible();

    await page.getByLabel("Enviar Agora").click();
    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });

    if (!USES_REAL_TELEGRAM) {
      const [call] = await telegramCalls(page);
      expect(call.method).toBe("sendPoll");
      expect(call.fields.chat_id).toBe(channelId);
      expect(call.fields.question).toBe("Qual seu framework favorito?");
      expect(call.fields.options).toEqual(["React", "Vue"]);
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
    const realVideoPath = path.resolve(process.cwd(), "..", "tests_media", "WhatsApp Video 2026-10-19 at 23.00.07.mp4");
    const hasRealVideo = fs.existsSync(realVideoPath);
    if (USES_REAL_TELEGRAM && !hasRealVideo) {
      test.skip(true, "precisa de um vídeo válido para o Telegram real");
    }
    const videoBuffer = USES_REAL_TELEGRAM && hasRealVideo ? fs.readFileSync(realVideoPath) : FAKE_MP4;

    await openProfile(page);
    await page
      .locator('input[type="file"]')
      .setInputFiles({ name: "video.mp4", mimeType: "video/mp4", buffer: videoBuffer });
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Legenda do vídeo");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 60_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await telegramCalls(page);
      expect(call.method).toBe("sendVideo");
      expect(call.fields).toMatchObject({ chat_id: channelId, caption: "Legenda do vídeo", supports_streaming: "true" });
      expect(Object.keys(call.files)).toEqual(["video"]);
    }
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

    const identifier = panel.getByLabel("Link de um post, ID ou @username do canal");
    const resolveButton = panel.getByRole("button", { name: "Buscar canal pelo link ou ID" });
    await identifier.fill("https://t.me/canalpublico");
    await resolveButton.click();
    await panel.getByRole("listitem").filter({ hasText: "Canal Público" }).getByRole("button", { name: "Adicionar canal" }).click();
    await expect(page.getByText('Canal "Canal Público" vinculado.').first()).toBeVisible();

    // Canal privado pelo "Copiar link" de um post (#12): t.me/c/<id>/<post> vira -100<id>.
    await identifier.fill("https://t.me/c/4444444444/7");
    await resolveButton.click();
    await panel.getByRole("listitem").filter({ hasText: "Canal Privado" }).getByRole("button", { name: "Adicionar canal" }).click();
    await expect(page.getByText('Canal "Canal Privado" vinculado.').first()).toBeVisible();

    // Link de convite não é resolvido e nem chega ao Telegram.
    await identifier.fill("https://t.me/+convite");
    await resolveButton.click();
    await expect(panel.getByRole("alert")).toContainText("Link de convite não serve");

    const calls = await telegramCalls(page);
    // A busca só lê (getUpdates, getChat); a vinculação de cada canal confere se o bot é admin (getMe + getChatMember, #2).
    expect(calls.map((c) => c.method)).toEqual([
      "getUpdates",
      "getMe",
      "getChatMember",
      "getChat",
      "getMe",
      "getChatMember",
      "getChat",
      "getMe",
      "getChatMember",
    ]);
    // A busca só lê: sem offset nenhum update é confirmado, sem allowed_updates a configuração do bot fica igual.
    expect(calls[0].query).toEqual({ timeout: "0" });
    expect(calls[3].query).toEqual({ chat_id: "@canalpublico" });
    expect(calls[6].query).toEqual({ chat_id: "-1004444444444" });

    // Os dois canais vinculados pela busca aparecem na barra de canais do perfil.
    await page.goto("/");
    await page.getByText(profileName, { exact: true }).first().click();
    await expect(page.getByText("Canal Descoberto").first()).toBeVisible();
    await expect(page.getByText("Canal Público").first()).toBeVisible();
  });

  // Também roda com o Telegram real: o bot de teste está no canal de teste, e o getChat por ID não depende de mensagens.
  test("resolve o canal de teste pelo ID e pelo link de um post", async ({ page }) => {
    await openProfile(page);
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
    const panel = page.getByRole("region", { name: "Buscar canais do bot" });
    const identifier = panel.getByLabel("Link de um post, ID ou @username do canal");
    const resolveButton = panel.getByRole("button", { name: "Buscar canal pelo link ou ID" });

    for (const raw of [channelId, `https://t.me/c/${channelId.replace(/^-100/, "")}/1`]) {
      await identifier.fill(raw);
      await resolveButton.click();
      await expect(panel.getByRole("listitem").filter({ hasText: channelId }).getByText("Já vinculado")).toBeVisible();
    }
    if (!USES_REAL_TELEGRAM) {
      const calls = await telegramCalls(page);
      expect(calls.map((c) => [c.method, c.query.chat_id])).toEqual([
        ["getChat", channelId],
        ["getChat", channelId],
      ]);
    }
  });

  test("bot com webhook ativo: explica e vincula pelo ID", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM, "o webhook ativo é simulado pela API falsa");
    await page.goto("/");
    await page.getByTitle("Adicionar Novo Perfil").click();
    await page.getByPlaceholder("Ex: Acme").fill("Perfil com webhook");
    await page.getByPlaceholder("123456789:ABCdefGhIJKlmNoPQRstu...").fill(WEBHOOK_TOKEN);
    await page.getByRole("button", { name: "Cadastrar Perfil" }).click();
    await page.getByText("Perfil com webhook", { exact: true }).first().click();
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
    const panel = page.getByRole("region", { name: "Buscar canais do bot" });

    await panel.getByRole("button", { name: "Buscar canais do bot" }).click();
    await expect(panel.getByRole("alert")).toContainText("Este bot está ligado a outro sistema (webhook)");

    const identifier = panel.getByLabel("Link de um post, ID ou @username do canal");
    await expect(identifier).toBeFocused();
    await identifier.fill("-1004444444444");
    await panel.getByRole("button", { name: "Buscar canal pelo link ou ID" }).click();
    await panel.getByRole("listitem").filter({ hasText: "Canal Privado" }).getByRole("button", { name: "Adicionar canal" }).click();
    await expect(page.getByText('Canal "Canal Privado" vinculado.').first()).toBeVisible();

    // O app nunca apaga o webhook do bot: nenhuma chamada a deleteWebhook/setWebhook.
    const methods = (await telegramCalls(page)).map((c) => c.method);
    expect(methods).not.toContain("deleteWebhook");
    expect(methods).not.toContain("setWebhook");
  });

  test("não deixa mídia temporária depois de enviar e cancelar", () => {
    // AGENTS.md §10: o arquivo em temp_media é apagado depois do envio, com sucesso ou erro, e no cancelamento.
    expect(fs.readdirSync(path.join(RUN_DIR, "media"))).toEqual([]);
  });
});
