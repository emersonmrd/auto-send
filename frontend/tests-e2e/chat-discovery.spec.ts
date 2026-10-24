import { test, expect, type Route } from "@playwright/test";

// Busca de canais do bot (issue #23): a tela lista os chats, vincula com um clique e resolve @username.
test.describe("Buscar canais do bot", () => {
  let channels: { id: string; profile_id: string; title: string; chat_id: string; invite_link: string; is_active: boolean }[];
  let createdBodies: unknown[];

  const json = (route: Route, status: number, body: unknown) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  test.beforeEach(async ({ page }) => {
    channels = [
      { id: "c-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001111111111", invite_link: "", is_active: true },
    ];
    createdBodies = [];

    await page.route("**/api/v1/profiles", (route) =>
      json(route, 200, [
        { id: "profile-1", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
      ]),
    );
    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
    await page.route("**/api/v1/profiles/profile-1/channels", async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        createdBodies.push(body);
        channels.push({ id: `c-${channels.length + 1}`, profile_id: "profile-1", invite_link: "", is_active: true, ...body });
        return json(route, 201, channels[channels.length - 1]);
      }
      return json(route, 200, channels);
    });
    await page.route("**/api/v1/profiles/profile-1/discover-chats", (route) =>
      json(route, 200, {
        chats: [
          { chat_id: "-1001111111111", title: "Canal de Novidades", type: "channel", username: "canalnovidades", registrable: true, already_registered: true },
          { chat_id: "-1002222222222", title: "Novidades", type: "channel", username: null, registrable: true, already_registered: false },
          { chat_id: "-444444444", title: "Grupo antigo", type: "group", username: null, registrable: false, already_registered: false },
        ],
      }),
    );

    await page.goto("/");
    await page.getByText("Acme", { exact: true }).first().click();
    await page.getByRole("button", { name: "Adicionar Canal" }).click();
  });

  test("lista os chats do bot e vincula o escolhido com um clique", async ({ page }) => {
    await page.getByRole("button", { name: "Buscar canais do bot" }).click();

    const panel = page.getByRole("region", { name: "Buscar canais do bot" });
    await expect(panel.getByText("Já vinculado")).toBeVisible();
    await expect(panel.getByText("Grupo comum não suportado")).toBeVisible();

    await panel.getByRole("listitem").filter({ hasText: "Novidades" }).getByRole("button", { name: "Adicionar canal" }).click();

    await expect(page.getByText('Canal "Novidades" vinculado.').first()).toBeVisible();
    expect(createdBodies).toEqual([{ title: "Novidades", chat_id: "-1002222222222" }]);
    await expect(panel.getByText("Já vinculado")).toHaveCount(2);
  });

  test("rotula o tipo e o ID do chat sem separador ambíguo (issue #13)", async ({ page }) => {
    await page.getByRole("button", { name: "Buscar canais do bot" }).click();

    const panel = page.getByRole("region", { name: "Buscar canais do bot" });
    await expect(panel.getByText("Canal: @canalnovidades (-1001111111111)", { exact: true })).toBeVisible();
    await expect(panel.getByText("Canal: -1002222222222", { exact: true })).toBeVisible();
    await expect(panel.getByText("Grupo: -444444444", { exact: true })).toBeVisible();
    await expect(panel.getByText(/·/)).toHaveCount(0);
  });

  test("resolve um canal público pelo link", async ({ page }) => {
    let identifier: unknown;
    await page.route("**/api/v1/profiles/profile-1/resolve-chat", (route) => {
      identifier = route.request().postDataJSON();
      return json(route, 200, { chat_id: "-1003333333333", title: "Canal Público", type: "channel", username: "publico", registrable: true });
    });

    await page.getByPlaceholder("@meucanal ou t.me/meucanal").fill("t.me/publico");
    await page.getByRole("button", { name: "Buscar canal público" }).click();

    await expect(page.getByText("Canal Público", { exact: true })).toBeVisible();
    expect(identifier).toEqual({ identifier: "t.me/publico" });
  });

  test("mostra o motivo quando o Telegram recusa a busca", async ({ page }) => {
    await page.route("**/api/v1/profiles/profile-1/discover-chats", (route) =>
      json(route, 400, { detail: "Telegram API error (409): Conflict: can't use getUpdates method while webhook is active" }),
    );

    await page.getByRole("button", { name: "Buscar canais do bot" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "webhook is active" })).toBeVisible();
  });

  test("avisa quando o bot não tem mensagens recentes", async ({ page }) => {
    await page.route("**/api/v1/profiles/profile-1/discover-chats", (route) => json(route, 200, { chats: [] }));

    await page.getByRole("button", { name: "Buscar canais do bot" }).click();

    await expect(page.getByText(/Nenhum canal encontrado/)).toBeVisible();
  });
});
