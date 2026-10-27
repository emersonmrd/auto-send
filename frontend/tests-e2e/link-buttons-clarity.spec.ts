import { test, expect, type Route } from "@playwright/test";

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

test.describe("Clareza dos botões de link e remoção de link externo redundante (issue #59)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/profiles", (route) =>
      json(route, [
        {
          id: "profile-1",
          name: "Acme",
          bot_username: "acme_bot",
          avatar_url: null,
          is_active: true,
          created_at: "2026-10-19T10:00:00Z",
        },
      ]),
    );
    await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, []));
    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, []));
    await page.goto("/");
    await page.getByText("Acme", { exact: true }).first().click();
  });

  test("não deve exibir botão redundante de link de texto fora do editor", async ({ page }) => {
    // 1. O botão de link externo ao lado do anexo de mídia foi removido para evitar duplicidade e confusão
    await expect(page.getByRole("button", { name: "Inserir Link em Palavra do Texto" })).toHaveCount(0);

    // 2. O botão de link no texto continua disponível na toolbar interna do editor de texto rico
    const richEditorToolbarLink = page.getByRole("button", { name: "Inserir ou editar link no texto" });
    await expect(richEditorToolbarLink).toBeVisible();

    // 3. Ao clicar no link da toolbar, abre o modal de link no texto
    await richEditorToolbarLink.click();
    const textLinkModal = page.getByRole("dialog", { name: "Inserir Link em Palavra do Texto" });
    await expect(textLinkModal).toBeVisible();
    await textLinkModal.getByRole("button", { name: "Cancelar" }).click();
    await expect(textLinkModal).toHaveCount(0);

    // 4. O botão físico abaixo da mensagem (Inline Keyboard) permanece acessível e diferenciado
    const inlineButtonAction = page.getByRole("button", { name: "Adicionar Botão Abaixo da Mensagem" });
    await expect(inlineButtonAction).toBeVisible();
    await inlineButtonAction.click();
    const inlineButtonModal = page.getByRole("dialog", { name: "Adicionar Botão Abaixo da Mensagem" });
    await expect(inlineButtonModal).toBeVisible();
    await inlineButtonModal.getByRole("button", { name: "Cancelar" }).click();
    await expect(inlineButtonModal).toHaveCount(0);
  });
});
