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

    await page.route("**/api/v1/profiles/*/broadcasts", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
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
    
    // Clica no botão de configurar botão abaixo da mensagem
    const linkBtn = page.getByRole("button", { name: "Adicionar Botão Abaixo da Mensagem" });
    if (await linkBtn.count() > 0) {
      await linkBtn.first().click();
      await page.fill('input[placeholder*="Saiba mais"]', "Acesse Aqui");
      await page.fill('input[placeholder*="https://"]', "https://t.me/+promo");
      await page.getByRole("button", { name: "Salvar" }).click();

      // Verifica se o botão inline aparece no preview
      await expect(page.locator('text=Acesse Aqui').first()).toBeVisible();
    }
  });

  async function sendBroadcast(page: import("@playwright/test").Page) {
    await page.goto("/");
    await page.getByPlaceholder("Escreva a mensagem do canal").fill("Mensagem com erro");
    await page.locator('button:has(svg.lucide-send)').first().click();
  }

  test("mostra as mensagens do 422 do Pydantic traduzidas como 'Campo X inválido' (issue #32)", async ({ page }) => {
    // Registrada depois do beforeEach, esta rota tem precedência sobre o mock de sucesso.
    await page.route("**/api/v1/broadcasts", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: [{ loc: ["body", "scheduled_at"], msg: "scheduled_at cannot be in the past" }] }),
      }),
    );
    await sendBroadcast(page);
    await expect(page.getByText("Campo scheduled_at inválido").first()).toBeVisible({ timeout: 5000 });
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

  test("edita link de texto em agendamento sem mostrar HTML cru e exige https:// (issue #16)", async ({ page }) => {
    const futureIso = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
    let patchedBody: Record<string, unknown> | null = null;

    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "b-link-1",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: '<b>Oferta</b> <a href="https://example.com/pagina">teste</a>',
            status: "SCHEDULED",
            scheduled_at: futureIso,
            created_at: new Date().toISOString(),
            media: null,
            button: null,
          },
        ]),
      }),
    );

    await page.route("**/api/v1/broadcasts/b-link-1", async (route) => {
      if (route.request().method() === "PATCH") {
        patchedBody = route.request().postDataJSON();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            broadcast_id: "b-link-1",
            status: "SCHEDULED",
            scheduled_at: futureIso,
            text: patchedBody?.text,
            button: null,
          }),
        });
      }
      return route.continue();
    });

    await page.goto("/");
    await page.getByTitle("Abrir Fila de Agendamentos").click();
    await page.getByTitle("Editar mensagem e horário de agendamento").click();

    const editField = page.getByRole("textbox", { name: "Texto da Mensagem" });
    await expect(editField).toBeVisible();
    // Aparece formatado, sem mostrar tags HTML cruas
    await expect(editField).toContainText("Oferta teste");
    await expect(editField).not.toContainText("<a href");

    // Clicar no link dentro do editor abre o modal de link preenchido
    await editField.locator("a", { hasText: "teste" }).click();
    const linkDialog = page.getByRole("dialog", { name: "Inserir Link em Palavra do Texto" });
    await expect(linkDialog).toBeVisible();
    await expect(linkDialog.getByLabel("Palavra / Texto exibido")).toHaveValue("teste");
    await expect(linkDialog.getByLabel("URL de destino")).toHaveValue("https://example.com/pagina");

    // Recusa http:// mostrando "Use um endereço https://"
    await linkDialog.getByLabel("URL de destino").fill("http://example.com/inseguro");
    await linkDialog.getByRole("button", { name: "Salvar Link" }).click();
    await expect(linkDialog.getByRole("alert")).toContainText("Use um endereço https://");

    // Completa https:// quando informado sem protocolo e salva
    await linkDialog.getByLabel("Palavra / Texto exibido").fill("novo link");
    await linkDialog.getByLabel("URL de destino").fill("example.com/nova");
    await linkDialog.getByRole("button", { name: "Salvar Link" }).click();
    await expect(linkDialog).toHaveCount(0);

    await page.getByRole("button", { name: "OK — Confirmar Agendamento" }).click();
    expect(patchedBody).toMatchObject({
      text: '<b>Oferta</b> <a href="https://example.com/nova">novo link</a>',
    });
  });

  test("carregar no editor ativa trava, edita o agendamento via PATCH sem duplicar e permite sair (issue #15)", async ({ page }) => {
    const futureIso = new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString();
    let lockAcquired = false;
    let lockReleased = false;
    let patchCalledWith: Record<string, unknown> | null = null;

    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "b-edit-15",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: "Texto original do agendamento",
            status: "SCHEDULED",
            scheduled_at: futureIso,
            created_at: new Date().toISOString(),
            media: null,
            button: null,
          },
        ]),
      }),
    );

    await page.route("**/api/v1/broadcasts/b-edit-15/edit-lock", (route) => {
      if (route.request().method() === "POST") {
        lockAcquired = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "b-edit-15",
            status: "SCHEDULED",
            edit_locked_until: new Date(Date.now() + 90000).toISOString(),
            cancelled: false,
          }),
        });
      }
      if (route.request().method() === "DELETE") {
        lockReleased = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "b-edit-15",
            status: "SCHEDULED",
            edit_locked_until: null,
            cancelled: false,
          }),
        });
      }
      return route.continue();
    });

    await page.route("**/api/v1/broadcasts/b-edit-15", (route) => {
      if (route.request().method() === "PATCH") {
        patchCalledWith = route.request().postDataJSON();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "b-edit-15",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: patchCalledWith?.text,
            status: "SCHEDULED",
            scheduled_at: futureIso,
          }),
        });
      }
      return route.continue();
    });

    await page.goto("/");
    await page.getByTitle("Abrir Fila de Agendamentos").click();

    // 1. Clicar em "Carregar no Editor"
    await page.getByRole("button", { name: "Carregar no Editor" }).click();
    expect(lockAcquired).toBe(true);

    // 2. Banner de edição visível
    const banner = page.getByRole("status").filter({ hasText: "Editando agendamento" });
    await expect(banner).toBeVisible();

    // 3. Modifica o texto no editor
    const composerInput = page.getByPlaceholder("Escreva a mensagem do canal");
    await composerInput.fill("Texto editado no compositor");

    // 4. Salva a edição via modal de agendamento -> PATCH no mesmo broadcast
    await page.getByRole("button", { name: "Agendar Mensagem" }).click();
    await page.getByRole("button", { name: "OK — Confirmar Agendamento" }).click();

    await expect(page.getByText("Agendamento atualizado com sucesso!").first()).toBeVisible();
    expect(patchCalledWith).toMatchObject({
      text: "Texto editado no compositor",
      target_channel_ids: ["-1001234567890"],
    });

    // Fecha o toast para liberar a área de cliques
    const closeToast = page.getByRole("button", { name: "OK / Fechar" });
    if (await closeToast.count() > 0) {
      await closeToast.click();
    }

    // 5. Carregar de novo e sair do modo edição via botão no banner
    await page.getByTitle("Abrir Fila de Agendamentos").click();
    await page.getByRole("button", { name: "Carregar no Editor" }).click();
    await expect(banner).toBeVisible();
    await banner.getByRole("button", { name: "Sair do modo edição" }).click();
    expect(lockReleased).toBe(true);
    await expect(banner).toHaveCount(0);
  });

  test("loads scheduled broadcast with media into composer, shows preview, and handles remove media (#18)", async ({ page }) => {
    let deleteMediaCalled = false;
    let patchCalled = false;
    const futureIso = new Date(Date.now() + 3600000).toISOString();

    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "b-edit-18",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: "Texto do agendamento com foto",
            status: "SCHEDULED",
            scheduled_at: futureIso,
            created_at: new Date().toISOString(),
            media: {
              media_type: "PHOTO",
              file_size: 2048,
            },
            button: null,
          },
        ]),
      }),
    );

    await page.route("**/api/v1/broadcasts/b-edit-18/edit-lock", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "b-edit-18",
          status: "SCHEDULED",
          edit_locked_until: new Date(Date.now() + 90000).toISOString(),
          cancelled: false,
        }),
      }),
    );

    await page.route("**/api/v1/broadcasts/b-edit-18/media", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "image/jpeg",
          body: Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46]),
        });
      }
      if (route.request().method() === "DELETE") {
        deleteMediaCalled = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "b-edit-18",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: "Texto do agendamento com foto",
            status: "SCHEDULED",
            scheduled_at: futureIso,
            media: null,
          }),
        });
      }
      return route.continue();
    });

    await page.route("**/api/v1/broadcasts/b-edit-18", (route) => {
      if (route.request().method() === "PATCH") {
        patchCalled = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "b-edit-18",
            profile_id: "profile-1",
            target_channel_ids: ["-1001234567890"],
            text: "Texto do agendamento com foto",
            status: "SCHEDULED",
            scheduled_at: futureIso,
            media: null,
          }),
        });
      }
      return route.continue();
    });

    await page.goto("/");
    await page.getByTitle("Abrir Fila de Agendamentos").click();

    // 1. Clicar em "Carregar no Editor"
    await page.getByRole("button", { name: "Carregar no Editor" }).click();

    // 2. Imagem visível no preview e barra de mídia presente
    const previewImg = page.locator('img[alt="Prévia da imagem do agendamento"]');
    await expect(previewImg).toBeVisible();

    const mediaBar = page.getByText("Mídia do agendamento (Foto)");
    await expect(mediaBar).toBeVisible();

    // 3. Remover a mídia existente
    await page.getByRole("button", { name: "Remover" }).click();
    await expect(previewImg).toHaveCount(0);
    await expect(mediaBar).toHaveCount(0);

    // 4. Salvar agendamento: dispara DELETE /media e PATCH
    await page.getByRole("button", { name: "Agendar Mensagem" }).click();
    await page.getByRole("button", { name: "OK — Confirmar Agendamento" }).click();

    await expect(page.getByText("Agendamento atualizado com sucesso!").first()).toBeVisible();
    expect(deleteMediaCalled).toBe(true);
    expect(patchCalled).toBe(true);
  });
});
