import { test, expect } from "@playwright/test";

test.describe("Editor Visual - Saída de Blocos de Código (Issue #60)", () => {
  test.beforeEach(async ({ page }) => {
    // Intercepta rotas de backend para permitir teste E2E determinístico da interface
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

  test("permite sair do bloco de código pressionando ArrowDown no final do bloco", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    await editor.click();
    // Clica no botão Bloco de código
    await page.getByRole("button", { name: "Bloco de código" }).click();

    // Digita o código dentro do bloco
    await page.keyboard.type("const x = 10;");

    // Verifica que o pre foi criado dentro do editor
    const preElement = editor.locator("pre");
    await expect(preElement).toContainText("const x = 10;");

    // Pressiona Seta para baixo para sair do bloco
    await page.keyboard.press("ArrowDown");

    // Digita o texto seguinte fora do código
    await page.keyboard.type("Texto apos o codigo");

    // O texto seguinte não deve estar dentro da tag pre
    await expect(preElement).not.toContainText("Texto apos o codigo");
    // O editor como um todo deve conter ambos
    await expect(editor).toContainText("const x = 10;");
    await expect(editor).toContainText("Texto apos o codigo");

    // Verifica se o preview exibe o código formatado e o texto abaixo
    const previewPre = page.locator("pre").first();
    await expect(previewPre).toBeVisible();
    await expect(previewPre).toContainText("const x = 10;");
  });

  test("permite sair do bloco de código com Enter duplo no final do bloco", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    await editor.click();
    await page.getByRole("button", { name: "Bloco de código" }).click();

    await page.keyboard.type('console.log("hello");');

    const preElement = editor.locator("pre");
    await expect(preElement).toContainText('console.log("hello");');

    // Primeiro Enter cria nova linha dentro do bloco
    await page.keyboard.press("Enter");
    // Segundo Enter (Enter duplo) deve sair do bloco
    await page.keyboard.press("Enter");

    // Digita o texto subsequente fora do código
    await page.keyboard.type("Paragrafo normal");

    await expect(preElement).not.toContainText("Paragrafo normal");
    await expect(editor).toContainText("Paragrafo normal");
  });

  test("permite sair do bloco de código via atalho Control+Enter", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    await editor.click();
    await page.getByRole("button", { name: "Bloco de código" }).click();

    await page.keyboard.type("echo 123");

    const preElement = editor.locator("pre");
    await expect(preElement).toContainText("echo 123");

    // Control+Enter para sair imediatamente
    await page.keyboard.press("Control+Enter");

    await page.keyboard.type("Linha externa");

    await expect(preElement).not.toContainText("Linha externa");
    await expect(editor).toContainText("Linha externa");
  });

  test("permite criar linha acima do bloco pressionando ArrowUp no início do bloco", async ({ page }) => {
    const editor = page.getByRole("textbox", { name: "Mensagem do canal" });
    await expect(editor).toBeVisible();

    await editor.click();
    await page.getByRole("button", { name: "Bloco de código" }).click();

    await page.keyboard.type("bloco no topo");

    // Move o cursor para o início do bloco
    for (let i = 0; i < "bloco no topo".length; i++) {
      await page.keyboard.press("ArrowLeft");
    }

    // Pressiona ArrowUp para escapar para cima
    await page.keyboard.press("ArrowUp");

    // Digita o título acima do código
    await page.keyboard.type("Titulo antes");

    const preElement = editor.locator("pre");
    await expect(preElement).not.toContainText("Titulo antes");
    await expect(editor).toContainText("Titulo antes");
    await expect(editor).toContainText("bloco no topo");
  });
});
