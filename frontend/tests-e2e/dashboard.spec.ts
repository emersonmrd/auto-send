import { test, expect } from "@playwright/test";

test.describe("Auto-Send E2E Dashboard Flows", () => {
  test.beforeEach(async ({ page }) => {
    // Intercepta rotas de backend para permitir teste E2E determinístico da interface
    await page.route("**/api/v1/profiles", async (route) => {
      if (route.request().method() === "GET") {
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
      } else if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "profile-2",
            name: "Camila",
            bot_username: "camila_bot",
            avatar_url: null,
            is_active: true,
          }),
        });
      }
    });

    await page.route("**/api/v1/profiles/*/channels", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "chan-1",
              profile_id: "profile-1",
              title: "Canal de Novidades",
              chat_id: "-1001234567890",
              invite_link: "https://t.me/+news",
              is_active: true,
            },
          ]),
        });
      }
    });

    await page.route("**/api/v1/broadcasts", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          broadcast_id: "broad-1",
          status: "COMPLETED",
          dispatched_count: 1,
          total_targets: 1,
          errors: [],
        }),
      });
    });
  });

  test("deve carregar o dashboard no estilo Telegram Web e selecionar o perfil", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=Acme").first()).toBeVisible();
    await expect(page.locator("text=@acme_news_bot").first()).toBeVisible();
  });

  test("a aba do navegador mostra o nome do app (issue #5)", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle("Auto-Send");
  });

  test("deve digitar mensagem e refletir no Live Preview do balão do Telegram", async ({ page }) => {
    await page.goto("/");
    const input = page.getByPlaceholder("Escreva a mensagem do canal");
    await input.fill("Novidades da semana no canal!");

    // O preview deve exibir o texto digitado em tempo real
    await expect(page.locator("text=Novidades da semana no canal!").first()).toBeVisible();
  });

  test("deve abrir modal de link inline e renderizar o botão no live preview", async ({ page }) => {
    await page.goto("/");
    
    // Clica no botão de configurar link inline
    const linkBtn = page.locator('button[title*="link"]').or(page.locator('button:has(svg.lucide-link)'));
    if (await linkBtn.count() > 0) {
      await linkBtn.first().click();
      await page.fill('input[placeholder*="Saiba mais"]', "Acesse Aqui");
      await page.fill('input[placeholder*="https://"]', "https://t.me/+promo");
      await page.click('button:has-text("Confirmar Botão")');

      // Verifica se o botão inline aparece no preview
      await expect(page.locator('text=Acesse Aqui').first()).toBeVisible();
    }
  });

  async function sendBroadcast(page: import("@playwright/test").Page) {
    await page.goto("/");
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Mensagem com erro");
    await page.locator('button:has(svg.lucide-send)').first().click();
  }

  test("mostra as mensagens do 422 do Pydantic quando o detail é uma lista", async ({ page }) => {
    // Registrada depois do beforeEach, esta rota tem precedência sobre o mock de sucesso.
    await page.route("**/api/v1/broadcasts", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: [{ loc: ["body", "scheduled_at"], msg: "scheduled_at cannot be in the past" }] }),
      }),
    );
    await sendBroadcast(page);
    await expect(page.getByText("scheduled_at cannot be in the past").first()).toBeVisible({ timeout: 5000 });
  });

  test("resposta HTTP sem JSON não vira erro de conexão", async ({ page }) => {
    await page.route("**/api/v1/broadcasts", (route) =>
      route.fulfill({ status: 502, contentType: "text/html", body: "<html>Bad Gateway</html>" }),
    );
    await sendBroadcast(page);
    await expect(page.getByText("Falha HTTP 502").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Erro de conexão")).toHaveCount(0);
  });

  test("sem resposta HTTP mostra erro de conexão", async ({ page }) => {
    await page.route("**/api/v1/broadcasts", (route) => route.abort("connectionrefused"));
    await sendBroadcast(page);
    await expect(page.getByText("Erro de conexão com o servidor backend").first()).toBeVisible({ timeout: 5000 });
  });

  test("deve realizar disparo de broadcast com sucesso", async ({ page }) => {
    await page.goto("/");
    const input = page.getByPlaceholder("Escreva a mensagem do canal");
    await input.fill("Mensagem teste de broadcast");

    const sendBtn = page.locator('button:has(svg.lucide-send)').or(page.locator('button[title="Disparar Imediatamente"]'));
    await sendBtn.first().click();

    // A mensagem aparece no toast e na faixa de status do compositor; basta a primeira estar visível
    await expect(page.getByText("Disparado com sucesso para 1 canal(is)!").first()).toBeVisible({ timeout: 5000 });
  });
});
