import { test, expect } from "@playwright/test";

test.describe("Modelos e Presets de Mensagens Reutilizáveis por Perfil (Issue #63)", () => {
  let templates: Array<{
    id: string;
    profile_id: string;
    name: string;
    text: string;
    button_text?: string | null;
    button_url?: string | null;
    created_at: string;
    updated_at: string;
  }> = [];

  test.beforeEach(async ({ page }) => {
    templates = [
      {
        id: "tmpl-initial",
        profile_id: "profile-1",
        name: "Aviso de Manutenção",
        text: "Atenção: nossos sistemas passarão por manutenção programada.",
        button_text: "Status do Sistema",
        button_url: "https://status.exemplo.com",
        created_at: "2026-10-27T10:00:00Z",
        updated_at: "2026-10-27T10:00:00Z",
      },
    ];

    await page.route("**/api/v1/profiles", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "profile-1",
            name: "Canal Tech",
            bot_username: "tech_news_bot",
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

    await page.route("**/api/v1/profiles/*/scheduled-broadcasts", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    // Mock das rotas de templates
    await page.route("**/api/v1/profiles/*/templates", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(templates),
        });
      } else if (route.request().method() === "POST") {
        const payload = JSON.parse(route.request().postData() || "{}");
        const newTmpl = {
          id: `tmpl-${Date.now()}`,
          profile_id: "profile-1",
          name: payload.name,
          text: payload.text,
          button_text: payload.button_text || null,
          button_url: payload.button_url || null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        templates.unshift(newTmpl);
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(newTmpl),
        });
      }
    });

    await page.route("**/api/v1/profiles/*/templates/*", async (route) => {
      if (route.request().method() === "DELETE") {
        const url = route.request().url();
        const id = url.split("/").pop();
        templates = templates.filter((t) => t.id !== id);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ message: "Template deleted successfully", id }),
        });
      }
    });

    await page.goto("/");
  });

  test("carrega um modelo salvo diretamente no compositor com 1 clique", async ({ page }) => {
    // Abre a gaveta de modelos
    const openTemplatesBtn = page.getByRole("button", { name: /Modelos/i }).first();
    await expect(openTemplatesBtn).toBeVisible();
    await openTemplatesBtn.click();

    // O drawer de modelos deve listar o modelo inicial
    const drawer = page.getByRole("dialog", { name: /Modelos de Mensagens/i });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("Aviso de Manutenção")).toBeVisible();

    // Clica no botão 'Usar Modelo' com 1 clique
    const useBtn = drawer.getByRole("button", { name: /Usar Modelo/i }).first();
    await useBtn.click();

    // O compositor deve estar preenchido com o texto do modelo
    const editor = page.getByRole("textbox", { name: /Mensagem do canal/i });
    await expect(editor).toContainText("Atenção: nossos sistemas passarão por manutenção programada.");

    // O Live Preview deve refletir o texto e o botão inline
    await expect(page.getByText("Status do Sistema")).toBeVisible();
  });

  test("salva a mensagem atual do compositor como novo modelo reutilizável", async ({ page }) => {
    // Digita uma nova mensagem no compositor
    const editor = page.getByRole("textbox", { name: /Mensagem do canal/i });
    await editor.fill("Comunicado urgente aos assinantes do canal.");

    // Clica no botão de salvar como modelo
    const saveModelBtn = page.getByRole("button", { name: /Salvar como Modelo/i });
    await expect(saveModelBtn).toBeVisible();
    await saveModelBtn.click();

    // Modal de confirmação/nome do modelo abre
    const saveModal = page.getByRole("dialog", { name: /Salvar como Modelo/i });
    await expect(saveModal).toBeVisible();

    // Preenche o nome do modelo
    await page.getByLabel(/Nome do Modelo/i).fill("Comunicado Urgente");

    // Confirma salvamento
    await saveModal.getByRole("button", { name: /Salvar Modelo/i }).click();

    // Abre a gaveta de modelos para conferir
    const openTemplatesBtn = page.getByRole("button", { name: /Modelos/i }).first();
    await openTemplatesBtn.click();

    const drawer = page.getByRole("dialog", { name: /Modelos de Mensagens/i });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("Comunicado Urgente", { exact: true })).toBeVisible();
  });

  test("permite excluir um modelo salvo via confirmação acessível", async ({ page }) => {
    // Abre a gaveta de modelos
    const openTemplatesBtn = page.getByRole("button", { name: /Modelos/i }).first();
    await openTemplatesBtn.click();

    const drawer = page.getByRole("dialog", { name: /Modelos de Mensagens/i });
    await expect(drawer).toBeVisible();

    // Clica no botão de excluir do modelo inicial
    const deleteBtn = drawer.getByTitle(/Excluir modelo/i).first();
    await deleteBtn.click();

    // Modal acessível do ConfirmDialog aparece
    const confirmDialog = page.getByRole("dialog", { name: /Excluir Modelo/i });
    await expect(confirmDialog).toBeVisible();

    // Confirma exclusão
    await confirmDialog.getByRole("button", { name: /Excluir/i }).click();

    // O modelo não deve mais estar na lista
    await expect(drawer.getByText("Aviso de Manutenção")).not.toBeVisible();
  });
});
