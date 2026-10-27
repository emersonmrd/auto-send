import { test, expect } from "@playwright/test";

test.describe("Editor Visual - Estilos Ativos e Limpar Formatação (Issue #61)", () => {
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

  test("destaca os botões da toolbar correspondentes aos estilos ativos sob o cursor", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    const boldBtn = page.getByRole("button", { name: "Negrito" });
    const italicBtn = page.getByRole("button", { name: "Itálico" });
    const codeBlockBtn = page.getByRole("button", { name: "Bloco de código" });

    // Inicialmente nenhum estilo está ativo
    await expect(boldBtn).toHaveAttribute("aria-pressed", "false");
    await expect(italicBtn).toHaveAttribute("aria-pressed", "false");

    // Digita texto normal
    await editor.click();
    await page.keyboard.type("Texto comum ");

    // Aplica negrito selecionando o texto ou clicando no botão
    await page.keyboard.press("Control+b");
    await page.keyboard.type("em negrito");

    // O botão Negrito deve estar destacado com aria-pressed="true"
    await expect(boldBtn).toHaveAttribute("aria-pressed", "true");
    await expect(italicBtn).toHaveAttribute("aria-pressed", "false");

    // Sai do negrito pressionando Ctrl+B novamente
    await page.keyboard.press("Control+b");
    await page.keyboard.type(" e ");

    // O botão Negrito não deve mais estar ativo no texto normal
    await expect(boldBtn).toHaveAttribute("aria-pressed", "false");

    // Clica no botão Bloco de código
    await codeBlockBtn.click();
    await page.keyboard.type("const y = 20;");

    // O botão Bloco de código deve estar ativo
    await expect(codeBlockBtn).toHaveAttribute("aria-pressed", "true");
  });

  test("remove toda a formatação do texto selecionado ao clicar no botão 'Limpar formatação'", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    const clearFormatBtn = page.getByRole("button", { name: "Limpar formatação" });
    await expect(clearFormatBtn).toBeVisible();

    await editor.click();
    // Digita texto formatado
    await page.keyboard.press("Control+b");
    await page.keyboard.type("Texto ");
    await page.keyboard.press("Control+i");
    await page.keyboard.type("formatado");

    // Verifica que o editor tem tags b e i
    await expect(editor.locator("b")).toContainText("Texto");
    await expect(editor.locator("i")).toContainText("formatado");

    // Seleciona todo o conteúdo do editor
    await page.keyboard.press("Control+a");

    // Clica no botão Limpar formatação
    await clearFormatBtn.click();

    // As tags b e i devem ter sido removidas do editor
    await expect(editor.locator("b")).toHaveCount(0);
    await expect(editor.locator("i")).toHaveCount(0);

    // O texto puro deve permanecer intacto
    await expect(editor).toContainText("Texto formatado");

    // Os botões devem estar desmarcados
    const boldBtn = page.getByRole("button", { name: "Negrito" });
    await expect(boldBtn).toHaveAttribute("aria-pressed", "false");
  });
});
