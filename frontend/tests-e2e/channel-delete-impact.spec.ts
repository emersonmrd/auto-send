import { test, expect, Page } from "@playwright/test";

const testProfile = {
  id: "profile-1",
  name: "Acme",
  bot_username: "acme_news_bot",
  avatar_url: null,
  is_active: true,
  created_at: "2026-10-19T10:00:00Z",
};

const testChannel = {
  id: "chan-1",
  profile_id: "profile-1",
  title: "Canal de Novidades",
  chat_id: "-1001234567890",
  invite_link: "https://t.me/+news",
  is_active: true,
};

const affectedBroadcastsData = {
  will_be_cancelled: [
    {
      id: "broad-cancel-1",
      text_preview: "Mensagem exclusiva deste canal",
      scheduled_at: new Date(Date.now() + 3600000).toISOString(),
      status: "SCHEDULED",
      target_channel_ids: ["-1001234567890"],
    },
  ],
  will_lose_target: [
    {
      id: "broad-target-1",
      text_preview: "Mensagem compartilhada com múltiplos destinos",
      scheduled_at: new Date(Date.now() + 7200000).toISOString(),
      status: "SCHEDULED",
      target_channel_ids: ["-1001234567890", "-1009876543210"],
    },
  ],
  in_flight_count: 0,
};

async function setupMocks(page: Page, deletedChannelIds: string[]) {
  // Mock perfis
  await page.route("**/api/v1/profiles", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([testProfile]),
      });
    }
  });

  // Mock canais do perfil
  await page.route("**/api/v1/profiles/*/channels", async (route) => {
    if (route.request().method() === "GET") {
      const channels = deletedChannelIds.includes(testChannel.id) ? [] : [testChannel];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(channels),
      });
    }
  });

  // Mock agendamentos e transmissões
  await page.route("**/api/v1/profiles/*/scheduled-broadcasts", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/profiles/*/broadcasts", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/profiles/*/message-templates", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  // Mock affected-broadcasts para o canal
  await page.route(`**/api/v1/channels/${testChannel.id}/affected-broadcasts`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(affectedBroadcastsData),
    });
  });

  // Mock DELETE do canal
  await page.route(`**/api/v1/channels/${testChannel.id}`, async (route) => {
    if (route.request().method() === "DELETE") {
      deletedChannelIds.push(testChannel.id);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true, message: "Canal removido" }),
      });
    }
  });
}

test.describe("Exclusão de Canal com Impacto em Agendamentos (Issue #65)", () => {
  test("exibe modal com agendamentos afetados e cancela sem excluir ao clicar em Cancelar", async ({ page }) => {
    const deletedChannelIds: string[] = [];
    await setupMocks(page, deletedChannelIds);

    await page.goto("/");
    await expect(page.locator("text=Acme").first()).toBeVisible();
    await expect(page.locator("text=Canal de Novidades").first()).toBeVisible();

    // Clica no botão de excluir canal
    const deleteBtn = page.getByTitle("Excluir Canal").first();
    await deleteBtn.click();

    // Valida abertura do modal
    const modalHeading = page.getByRole("heading", { name: "Excluir Canal" });
    await expect(modalHeading).toBeVisible();

    // Valida alerta de agendamentos afetados
    const affectedBox = page.locator('[data-testid="channel-delete-affected-broadcasts"]');
    await expect(affectedBox).toBeVisible();
    await expect(affectedBox).toContainText("1 agendamento será cancelado (tinha só este canal):");
    await expect(affectedBox).toContainText("Mensagem exclusiva deste canal");
    await expect(affectedBox).toContainText("1 agendamento perde este destino (continua nos demais canais):");
    await expect(affectedBox).toContainText("Mensagem compartilhada com múltiplos destinos");

    // Clica em Cancelar
    await page.getByRole("button", { name: "Cancelar" }).click();
    await expect(modalHeading).toBeHidden();
    expect(deletedChannelIds).toHaveLength(0);
    await expect(page.locator("text=Canal de Novidades").first()).toBeVisible();
  });

  test("confirma exclusão do canal, dispara DELETE e atualiza lista com feedback", async ({ page }) => {
    const deletedChannelIds: string[] = [];
    await setupMocks(page, deletedChannelIds);

    await page.goto("/");
    await expect(page.locator("text=Acme").first()).toBeVisible();
    await expect(page.locator("text=Canal de Novidades").first()).toBeVisible();

    // Clica no botão de excluir canal
    await page.getByTitle("Excluir Canal").first().click();

    // Confirma exclusão
    const confirmBtn = page.getByRole("button", { name: "Confirmar Exclusão" });
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();

    // Verifica que o endpoint DELETE foi chamado
    await expect.poll(() => deletedChannelIds.length).toBe(1);
    expect(deletedChannelIds[0]).toBe(testChannel.id);

    // Valida feedback de sucesso
    await expect(page.locator("text=removido com sucesso").first()).toBeVisible();
  });
});
