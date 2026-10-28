import { test, expect, type Page, type Route } from "@playwright/test";

// Issue #87: o card de progresso do envio fica alinhado à caixa de texto e não mostra mais "Fase 1/2".
// PNG 1x1 transparente.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function startMediaSend(page: Page) {
  await page.route("**/api/v1/profiles", (route) =>
    json(route, [
      { id: "profile-1", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
    ]),
  );
  await page.route("**/api/v1/profiles/profile-1/channels", (route) =>
    json(route, [
      { id: "c-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001234567890", invite_link: "", is_active: true },
    ]),
  );
  await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, []));
  // O envio nunca responde, para o card de progresso continuar na tela.
  await page.route("**/api/v1/broadcasts", () => new Promise<void>(() => {}));
  await page.route("**/api/v1/broadcasts/upload-progress/**", (route) =>
    json(route, { status: "uploading", sent_bytes: 0, total_bytes: PNG_1X1.length }),
  );

  await page.goto("/");
  await page.getByPlaceholder("Escreva a mensagem do canal").fill("Novidades da semana");
  await page.locator('input[type="file"]').setInputFiles({ name: "novidades.png", mimeType: "image/png", buffer: PNG_1X1 });
  await page.getByRole("button", { name: "Enviar Agora", exact: true }).click();
}

const progressCard = (page: Page) =>
  page.getByTitle("Cancelar upload em andamento").locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]");

test.describe("Card de progresso do envio (issue #87)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  test("não mostra o prefixo Fase 1/2", async ({ page }) => {
    await startMediaSend(page);
    const card = progressCard(page);
    await expect(card).toBeVisible();
    await expect(card).not.toContainText("Fase");
  });

  test("tem a mesma largura e posição da caixa de texto", async ({ page }) => {
    await startMediaSend(page);
    const card = progressCard(page);
    await expect(card).toBeVisible();

    const textBox = page
      .getByPlaceholder("Escreva a mensagem do canal")
      .locator("xpath=ancestor::div[contains(@class,'rounded-2xl')][1]");
    const cardBox = await card.boundingBox();
    const inputBox = await textBox.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(inputBox).not.toBeNull();
    expect(Math.abs(cardBox!.x - inputBox!.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(cardBox!.width - inputBox!.width)).toBeLessThanOrEqual(1);
  });
});
