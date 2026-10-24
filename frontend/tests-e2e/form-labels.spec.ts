import { test, expect, type Page, type Route } from "@playwright/test";

// Issue #6: o nome acessível de cada campo é o rótulo visível, não o placeholder.
const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function unlabeledFields(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input:not([type=hidden]):not([type=file]), textarea")]
      .filter((el) => el.offsetParent !== null && el.labels?.length === 0 && !el.getAttribute("aria-label"))
      .map((el) => el.getAttribute("placeholder") || el.outerHTML.slice(0, 80)),
  );
}

test.describe("Rótulos dos formulários (issue #6)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/profiles", (route) =>
      json(route, [
        { id: "profile-1", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
      ]),
    );
    await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, []));
    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, []));
    await page.goto("/");
  });

  test("cadastro de perfil: campos localizados pelo rótulo", async ({ page }) => {
    await page.getByTitle("Adicionar Novo Perfil").click();

    await page.getByLabel("Nome do Perfil").fill("Acme");
    await page.getByLabel("Token do Bot (@BotFather)").fill("123456789:fake");
    await expect(page.getByRole("textbox", { name: "Ex: Acme" })).toHaveCount(0);
    expect(await unlabeledFields(page)).toEqual([]);
  });

  test("cadastro de canal: campos localizados pelo rótulo", async ({ page }) => {
    await page.getByText("Acme", { exact: true }).first().click();
    await page.getByRole("button", { name: "Adicionar Canal" }).click();

    await page.getByLabel("Título do Canal").fill("Canal de Novidades");
    await page.getByLabel("Chat ID do Telegram (começa com -100...)").fill("-1001234567890");
    expect(await unlabeledFields(page)).toEqual([]);
  });
});
