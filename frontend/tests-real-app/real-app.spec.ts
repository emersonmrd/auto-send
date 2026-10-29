import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "@playwright/test";
import { FAKE_TELEGRAM_PORT, REAL_BOT_TOKEN, REAL_CHANNEL_ID, REAL_SUPERGROUP_ID, RUN_DIR, USES_REAL_TELEGRAM } from "./env";

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
// Supergrupo de teste (#99, #100): o real, se houver, ou o da API falsa.
const SUPERGROUP_ID = REAL_SUPERGROUP_ID || "-1005555555555";
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

// Só os envios: antes de cada um o backend lê as permissões do bot (getMe, getChatMember, getChat, #107).
async function sentCalls(page: Page): Promise<TelegramCall[]> {
  return (await telegramCalls(page)).filter((c) => c.method.startsWith("send"));
}

async function clearTelegramCalls(page: Page) {
  if (!USES_REAL_TELEGRAM) await page.request.delete(`http://127.0.0.1:${FAKE_TELEGRAM_PORT}/__calls`);
}

// Deixa marcados só os destinos pedidos. Com a API falsa a suíte vincula mais canais (busca, link, webhook)
// do que com o Telegram real, então desmarcar um destino só não basta.
async function selectOnlyDestinations(page: Page, titles: string[]) {
  const chips = page.getByRole("button").filter({ has: page.getByRole("button", { name: /^O que o bot pode fazer em / }) });
  for (const chip of await chips.all()) {
    const title = await chip.getByRole("button", { name: /^O que o bot pode fazer em / }).getAttribute("aria-label");
    const wanted = titles.some((t) => title === `O que o bot pode fazer em ${t}`);
    const selected = (await chip.locator("svg.lucide-check").count()) > 0;
    if (wanted !== selected) await chip.click();
  }
}

async function fillPoll(page: Page, question: string) {
  await page.getByLabel("Criar Enquete").click();
  const dialog = page.getByRole("dialog", { name: "Criar Enquete do Telegram" });
  await dialog.getByPlaceholder("Ex: Qual tema vocês querem no próximo conteúdo?").fill(question);
  await dialog.getByPlaceholder("Opção 1").fill("Sim");
  await dialog.getByPlaceholder("Opção 2").fill("Não");
  return dialog;
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
      const [call] = await sentCalls(page);
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
      const [call] = await sentCalls(page);
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
      const [call] = await sentCalls(page);
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
    // O Telegram real leva mais de 30 s (o timeout padrão do teste) para receber o vídeo de 7,9 MB.
    test.setTimeout(90_000);
    const videoBuffer = USES_REAL_TELEGRAM && hasRealVideo ? fs.readFileSync(realVideoPath) : FAKE_MP4;

    await openProfile(page);
    await page
      .locator('input[type="file"]')
      .setInputFiles({ name: "video.mp4", mimeType: "video/mp4", buffer: videoBuffer });
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Legenda do vídeo");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 60_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await sentCalls(page);
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
    // A busca só lê (getUpdates, getChat); a vinculação de cada canal confere se o bot é admin (getMe + getChatMember, #2)
    // e depois lê o tipo do chat (getChat pelo ID, #99).
    expect(calls.map((c) => c.method)).toEqual([
      "getUpdates",
      "getMe",
      "getChatMember",
      "getChat",
      "getChat",
      "getMe",
      "getChatMember",
      "getChat",
      "getChat",
      "getMe",
      "getChatMember",
      "getChat",
    ]);
    // A busca só lê: sem offset nenhum update é confirmado, sem allowed_updates a configuração do bot fica igual.
    expect(calls[0].query).toEqual({ timeout: "0" });
    expect(calls[3].query).toEqual({ chat_id: "-1002222222222" });
    expect(calls[4].query).toEqual({ chat_id: "@canalpublico" });
    expect(calls[8].query).toEqual({ chat_id: "-1004444444444" });

    // Os canais vinculados pela busca aparecem na barra de canais do perfil, com o tipo lido do Telegram (#99).
    await page.goto("/");
    await page.getByText(profileName, { exact: true }).first().click();
    await expect(page.getByText("Canal Descoberto").first()).toBeVisible();
    await expect(page.getByText("Canal Público").first()).toBeVisible();
    const chip = page.getByRole("button").filter({ hasText: "Canal Descoberto" }).first();
    await expect(chip.getByRole("img", { name: "Canal", exact: true })).toBeVisible();
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

  // Por último: com mais um destino vinculado, os envios acima iriam para dois chats.
  test("vincula um supergrupo com o bot só como membro e mostra o tipo lido do Telegram (#99, #100)", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM && !REAL_SUPERGROUP_ID, "sem E2E_SUPERGROUP_AUTOSEND no ambiente");
    const supergroupId = SUPERGROUP_ID;
    await openProfile(page);
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
    await page.getByPlaceholder("Ex: Canal de Novidades").fill("Supergrupo de Teste");
    await page.getByPlaceholder("-1001234567890").fill(supergroupId);
    await page.getByRole("button", { name: "Vincular Canal" }).click();

    const chip = page.getByRole("button").filter({ hasText: "Supergrupo de Teste" }).first();
    // Supergrupo com tópicos aparece como fórum; o de teste real pode ter ou não.
    await expect(chip.getByRole("img", { name: /^(Grupo|Fórum)$/ })).toBeVisible();
    if (!USES_REAL_TELEGRAM) {
      await expect(chip.getByRole("img", { name: "Grupo", exact: true })).toBeVisible();
      const calls = await telegramCalls(page);
      // Bot só membro (#100): o getChat do ensure_bot_can_post confere que é grupo; o segundo lê o tipo (#99).
      expect(calls.map((c) => c.method)).toEqual(["getMe", "getChatMember", "getChat", "getChat"]);
      expect(calls[2].query).toEqual({ chat_id: supergroupId });
    }
  });

  test("o painel do supergrupo mostra a situação do bot e o que o grupo deixa enviar (#107)", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM && !REAL_SUPERGROUP_ID, "sem E2E_SUPERGROUP_AUTOSEND no ambiente");
    await openProfile(page);
    await page.getByRole("button", { name: "O que o bot pode fazer em Supergrupo de Teste", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Supergrupo de Teste" });
    await expect(dialog).toContainText(/Criador|Administrador|Membro|Restrito/);
    await expect(dialog).toContainText(/Lido do Telegram em/);
    if (!USES_REAL_TELEGRAM) {
      await expect(dialog).toContainText("👥 Grupo");
      await expect(dialog).toContainText("Membro");
      await expect(dialog.getByRole("img", { name: "não pode enviar" })).toHaveCount(1);
      await expect(dialog).toContainText("o grupo não deixa membros enviarem fotos");
      const calls = await telegramCalls(page);
      expect(calls.map((c) => c.method)).toEqual(["getMe", "getChatMember", "getChat"]);
      expect(calls[2].query).toEqual({ chat_id: "-1005555555555" });
    }
  });

  // Grupo × canal: daqui em diante o supergrupo está vinculado, e a página abre com todos os destinos marcados.
  test("envia texto só para o supergrupo (#100)", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM && !REAL_SUPERGROUP_ID, "sem E2E_SUPERGROUP_AUTOSEND no ambiente");
    await openProfile(page);
    await selectOnlyDestinations(page, ["Supergrupo de Teste"]);
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Teste de texto no supergrupo");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await sentCalls(page);
      expect(call.method).toBe("sendMessage");
      expect(call.fields).toMatchObject({ chat_id: SUPERGROUP_ID, text: "Teste de texto no supergrupo" });
    }
  });

  test("enquete com votos visíveis vai para o supergrupo (#99)", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM && !REAL_SUPERGROUP_ID, "sem E2E_SUPERGROUP_AUTOSEND no ambiente");
    await openProfile(page);
    await selectOnlyDestinations(page, ["Supergrupo de Teste"]);
    const dialog = await fillPoll(page, "Enquete pública no supergrupo?");
    await dialog.getByRole("checkbox", { name: /Voto Anônimo/ }).uncheck();
    await dialog.getByRole("button", { name: "Salvar", exact: true }).click();
    await expect(page.getByText("(Votos visíveis)")).toBeVisible();

    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    if (!USES_REAL_TELEGRAM) {
      const [call] = await sentCalls(page);
      expect(call.method).toBe("sendPoll");
      expect(call.fields).toMatchObject({ chat_id: SUPERGROUP_ID, question: "Enquete pública no supergrupo?", is_anonymous: false });
    }
  });

  test("com canal e supergrupo nos destinos, a enquete sai anônima para os dois (#99)", async ({ page }) => {
    test.skip(USES_REAL_TELEGRAM && !REAL_SUPERGROUP_ID, "sem E2E_SUPERGROUP_AUTOSEND no ambiente");
    await openProfile(page);
    await selectOnlyDestinations(page, ["Canal de Teste", "Supergrupo de Teste"]);
    const dialog = await fillPoll(page, "Enquete anônima no canal e no grupo?");
    const anonymous = dialog.getByRole("checkbox", { name: /Voto Anônimo/ });
    // O Telegram recusa enquete pública em canal: com um canal entre os destinos, o voto anônimo fica travado.
    await expect(anonymous).toBeChecked();
    await expect(anonymous).toBeDisabled();
    await dialog.getByRole("button", { name: "Salvar", exact: true }).click();

    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText("Disparado com sucesso para 2 canal(is)!").first()).toBeVisible({ timeout: 30_000 });
    if (!USES_REAL_TELEGRAM) {
      const polls = (await sentCalls(page)).filter((c) => c.method === "sendPoll");
      expect(polls.map((c) => c.fields.chat_id).sort()).toEqual([channelId, SUPERGROUP_ID].sort());
      expect(polls.map((c) => c.fields.is_anonymous)).toEqual([true, true]);
    }
  });

  test("foto para grupo que proíbe fotos: o grupo falha com o motivo e o canal recebe (#107)", async ({ page }) => {
    // O supergrupo da API falsa proíbe fotos aos membros; o supergrupo real de teste pode liberar.
    test.skip(USES_REAL_TELEGRAM, "depende das permissões do supergrupo da API falsa");
    await openProfile(page);
    await selectOnlyDestinations(page, ["Canal de Teste", "Supergrupo de Teste"]);
    await page
      .locator('input[type="file"]')
      .setInputFiles({ name: "foto.png", mimeType: "image/png", buffer: PHOTO });
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Foto para o canal e o grupo");
    await page.getByLabel("Enviar Agora").click();

    await expect(page.getByText(/Envio parcial \(1 enviado\(s\)\)/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/O bot não pode enviar fotos neste grupo/).first()).toBeVisible();
    const sends = await sentCalls(page);
    // Nenhuma tentativa ao grupo sem permissão: só o canal recebeu o sendPhoto.
    expect(sends.map((c) => [c.method, c.fields.chat_id])).toEqual([["sendPhoto", channelId]]);
  });
});
