import { test, expect } from "@playwright/test";

test.describe("Identidade Visual e Branding - Robô Carteiro (Issue #62)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/profiles", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "profile-1",
            name: "Acme",
            bot_username: "acme_news_bot",
            avatar_url: null,
            is_active: true,
            created_at: "2026-10-19T10:00:00Z",
          },
        ]),
      });
    });

    await page.route("**/api/v1/profiles/*/channels", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.route("**/api/v1/profiles/*/broadcasts", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto("/");
  });

  test("exibe o ícone proprietário do Robô Carteiro no cabeçalho da aplicação", async ({ page }) => {
    // O cabeçalho da barra lateral deve conter o ícone do Robô Carteiro
    const robotIcon = page.getByTestId("robot-mail-icon");
    await expect(robotIcon).toBeVisible();

    // Verifica que é um elemento SVG com acessibilidade e semântica de imagem
    await expect(robotIcon).toHaveAttribute("role", "img");
    await expect(robotIcon).toHaveAttribute("aria-label", "Robô Carteiro Auto-Send");

    // Verifica que o SVG contém elementos do envelope e do robô
    const envelopePart = robotIcon.locator("[data-part='envelope']");
    await expect(envelopePart).toBeAttached();

    const antennaPart = robotIcon.locator("[data-part='antenna']");
    await expect(antennaPart).toBeAttached();
  });

  test("configura o favicon vetorial (icon.svg) nos metadados da aplicação", async ({ page }) => {
    // Verifica se a tag <link rel="icon"> existe e aponta para o novo ícone vetorial
    const iconLink = page.locator('link[rel*="icon"]');
    const hrefs = await iconLink.evaluateAll((links) => links.map((l) => l.getAttribute("href")));
    const hasSvgIcon = hrefs.some((h) => h && h.includes("icon.svg"));
    expect(hasSvgIcon).toBe(true);
  });
});
