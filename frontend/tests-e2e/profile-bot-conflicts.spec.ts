import { test, expect, type Route } from "@playwright/test";

// Issue #102: detecção e aviso não-bloqueante sobre bot em uso por outro sistema (webhook/polling)
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

test.describe("Detecção de conflitos de bot no cadastro de perfil (#102)", () => {
  test("exibe aviso não bloqueante ao configurar bot com webhook externo ativo", async ({ page }) => {
    await page.route("**/api/v1/profiles", (route) => {
      if (route.request().method() === "POST") {
        return json(route, 201, {
          id: "profile-wh",
          name: "Perfil Webhook",
          bot_username: "webhook_bot",
          avatar_url: null,
          is_active: true,
          has_active_webhook: true,
          webhook_url: "https://external.service/webhook",
          warning:
            "Aviso: Este bot possui um Webhook ativo apontando para outro sistema (https://external.service/webhook). O envio de mensagens pelo Auto-Send funcionará normalmente, mas a busca automática de canais exigirá o vínculo manual por link/ID (ou a remoção do webhook no @BotFather).",
        });
      }
      return json(route, 200, [
        { id: "p-init", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true },
      ]);
    });

    await page.route("**/api/v1/profiles/validate-bot", (route) =>
      json(route, 200, {
        is_valid: true,
        bot_username: "webhook_bot",
        has_active_webhook: true,
        webhook_url: "https://external.service/webhook",
        has_active_polling: false,
        is_duplicate_token: false,
        warning:
          "Aviso: Este bot possui um Webhook ativo apontando para outro sistema (https://external.service/webhook). O envio de mensagens pelo Auto-Send funcionará normalmente, mas a busca automática de canais exigirá o vínculo manual por link/ID (ou a remoção do webhook no @BotFather).",
      })
    );

    await page.route("**/api/v1/profiles/p-init/channels", (route) => json(route, 200, []));
    await page.route("**/api/v1/profiles/p-init/scheduled-broadcasts", (route) => json(route, 200, []));
    await page.route("**/api/v1/system/telegram-api-config", (route) =>
      json(route, 200, { configured: false, api_id: "", has_api_hash: false, max_upload_mb: 50, env_file_path: "" })
    );

    await page.goto("/");
    await expect(page.getByText("Acme").first()).toBeVisible();

    // Abre modal de adicionar perfil
    await page.getByRole("button", { name: "Adicionar Novo Perfil", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Adicionar Novo Perfil" })).toBeVisible();

    await page.locator("#field-new-profile-name").fill("Perfil Webhook");
    await page.locator("#field-new-bot-token").fill("1234567890:WEBHOOK_TOKEN_1234567890");
    await page.locator("#field-new-bot-token").blur();

    // Deve exibir o aviso não-bloqueante no modal
    const alert = page.getByRole("alert").filter({ hasText: "Webhook ativo" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("@BotFather");

    // O botão de cadastrar não deve estar bloqueado
    const submitBtn = page.getByRole("button", { name: "Cadastrar Perfil", exact: true });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // Modal deve fechar e feedback deve ser apresentado
    await expect(page.getByRole("heading", { name: "Adicionar Novo Perfil" })).toHaveCount(0);
  });

  test("exibe aviso de polling ativo e token já cadastrado em outro perfil", async ({ page }) => {
    await page.route("**/api/v1/profiles", (route) => {
      if (route.request().method() === "POST") {
        return json(route, 201, {
          id: "profile-poll",
          name: "Perfil Polling",
          bot_username: "polling_bot",
          avatar_url: null,
          is_active: true,
          has_active_polling: true,
          is_duplicate_token: true,
          warning:
            "Aviso: Outra instância ou serviço está recebendo atualizações (polling ativo) com este bot. Além disso, este token já está em uso pelo perfil Acme.",
        });
      }
      return json(route, 200, [
        { id: "p-init", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true },
      ]);
    });

    await page.route("**/api/v1/profiles/validate-bot", (route) =>
      json(route, 200, {
        is_valid: true,
        bot_username: "polling_bot",
        has_active_webhook: false,
        webhook_url: null,
        has_active_polling: true,
        is_duplicate_token: true,
        warning:
          "Aviso: Outra instância ou serviço está recebendo atualizações (polling ativo) com este bot. Além disso, este token já está em uso pelo perfil Acme.",
      })
    );

    await page.route("**/api/v1/profiles/p-init/channels", (route) => json(route, 200, []));
    await page.route("**/api/v1/profiles/p-init/scheduled-broadcasts", (route) => json(route, 200, []));
    await page.route("**/api/v1/system/telegram-api-config", (route) =>
      json(route, 200, { configured: false, api_id: "", has_api_hash: false, max_upload_mb: 50, env_file_path: "" })
    );

    await page.goto("/");
    await expect(page.getByText("Acme").first()).toBeVisible();

    await page.getByRole("button", { name: "Adicionar Novo Perfil", exact: true }).click();
    await page.locator("#field-new-profile-name").fill("Perfil Polling");
    await page.locator("#field-new-bot-token").fill("1234567890:POLLING_TOKEN_1234567890");
    await page.locator("#field-new-bot-token").blur();

    const alert = page.getByRole("alert").filter({ hasText: "polling ativo" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("já está em uso pelo perfil Acme");

    const submitBtn = page.getByRole("button", { name: "Cadastrar Perfil", exact: true });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    await expect(page.getByRole("heading", { name: "Adicionar Novo Perfil" })).toHaveCount(0);
  });
});
