import { test, expect, Page } from "@playwright/test";

const scheduled = {
  id: "broad-9",
  profile_id: "profile-1",
  target_channel_ids: ["-1001234567890"],
  text: "Promo agendada",
  media: null,
  button: null,
  status: "SCHEDULED",
  scheduled_at: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
  created_at: "2026-10-19T10:00:00Z",
};

async function mockBackend(page: Page, cancelCalls: string[]) {
  await page.route("**/api/v1/profiles", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "profile-1", name: "Acme", bot_username: "acme_news_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
      ]),
    }),
  );
  await page.route("**/api/v1/profiles/*/channels", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "chan-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001234567890", invite_link: "", is_active: true },
      ]),
    }),
  );
  await page.route("**/api/v1/profiles/*/scheduled-broadcasts", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([scheduled]) }),
  );
  await page.route("**/api/v1/broadcasts/*/cancel", (route) => {
    cancelCalls.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...scheduled, status: "CANCELLED" }) });
  });
}

async function openQueue(page: Page) {
  await page.goto("/");
  await page.getByTitle("Abrir Fila de Agendamentos").click();
  await expect(page.getByText("Promo agendada").first()).toBeVisible();
}

test.describe("Confirmação não bloqueante (AGENTS.md §8.5)", () => {
  test("cancelar agendamento pede confirmação num modal acessível", async ({ page }) => {
    const cancelCalls: string[] = [];
    await mockBackend(page, cancelCalls);
    page.on("dialog", (dialog) => {
      throw new Error(`diálogo nativo do navegador: ${dialog.type()}`);
    });
    await openQueue(page);

    await page.getByTitle("Cancelar agendamento e descartar mídias").click();
    const dialog = page.getByRole("dialog", { name: "Cancelar agendamento" });
    await expect(dialog).toBeVisible();

    // Esc dispensa sem cancelar
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(cancelCalls).toHaveLength(0);

    await page.getByTitle("Cancelar agendamento e descartar mídias").click();
    await dialog.getByRole("button", { name: "Cancelar agendamento" }).click();
    await expect(dialog).toBeHidden();
    await expect.poll(() => cancelCalls.length).toBe(1);
  });

  test("carregar agendamento sobre um rascunho pede confirmação", async ({ page }) => {
    await mockBackend(page, []);
    page.on("dialog", (dialog) => {
      throw new Error(`diálogo nativo do navegador: ${dialog.type()}`);
    });
    await page.goto("/");
    const composer = page.getByPlaceholder("Escreva a mensagem do canal");
    await composer.fill("Rascunho em andamento");
    await page.getByTitle("Abrir Fila de Agendamentos").click();

    await page.getByRole("button", { name: "Carregar no Editor" }).click();
    const dialog = page.getByRole("dialog", { name: "Substituir rascunho" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Manter rascunho" }).click();
    await expect(composer).toHaveValue("Rascunho em andamento");

    await page.getByRole("button", { name: "Carregar no Editor" }).click();
    await dialog.getByRole("button", { name: "Substituir" }).click();
    await expect(composer).toHaveValue("Promo agendada");
  });
});
