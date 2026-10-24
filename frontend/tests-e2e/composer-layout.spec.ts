import { test, expect, type Page, type Route } from "@playwright/test";

// Issue #17: um nome de arquivo longo não pode empurrar o compositor (texto, Enviar, Agendar) para fora da tela.
const LONG_NAME = `${"foto_da_campanha_de_novidades_".repeat(8)}final.png`;
// PNG 1x1 transparente.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function openComposerWithLongMedia(page: Page) {
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

  await page.goto("/");
  await page.getByPlaceholder("Escreva a mensagem do canal").fill("Novidades da semana");
  await page.locator('input[type="file"]').setInputFiles({ name: LONG_NAME, mimeType: "image/png", buffer: PNG_1X1 });
}

async function expectComposerInsideViewport(page: Page) {
  const attached = page.getByText(LONG_NAME, { exact: true });
  await expect(attached).toBeVisible();

  await expect(page.getByPlaceholder("Escreva a mensagem do canal")).toBeInViewport({ ratio: 1 });
  await expect(page.locator("button:has(svg.lucide-send)").first()).toBeInViewport({ ratio: 1 });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // O nome completo fica acessível no title, mesmo truncado na tela.
  await expect(attached).toHaveAttribute("title", LONG_NAME);
}

test.describe("Compositor com nome de arquivo longo (issue #17)", () => {
  test("continua dentro da tela no desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openComposerWithLongMedia(page);
    await expectComposerInsideViewport(page);
  });

  // A largura de celular fica fora: sem mídia nenhuma o compositor já não cabe em 390 px (problema à parte da #17).
  test("continua dentro da tela numa janela estreita", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await openComposerWithLongMedia(page);
    await expectComposerInsideViewport(page);
  });
});
