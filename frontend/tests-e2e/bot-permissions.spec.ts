import { test, expect, type Page, type Route } from "@playwright/test";
import type { BotPermissions, Channel } from "../src/types";

// Issue #107: o botão "i" de cada destino mostra o que o bot pode enviar ali, lido do Telegram.
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const channels: Channel[] = [
  { id: "c-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001111111111", invite_link: "", is_active: true, chat_type: "channel", is_forum: false },
  { id: "c-2", profile_id: "profile-1", title: "Grupo VIP", chat_id: "-1002222222222", invite_link: "", is_active: true, chat_type: "supergroup", is_forum: false },
];

const channelAdmin: BotPermissions = {
  chat_type: "channel",
  is_forum: false,
  bot_status: "administrator",
  can_send_messages: true,
  can_send_photos: true,
  can_send_videos: true,
  can_send_polls: true,
  checked_at: "2026-10-28T12:00:00Z",
};

const groupMember: BotPermissions = {
  chat_type: "supergroup",
  is_forum: false,
  bot_status: "member",
  can_send_messages: true,
  can_send_photos: false,
  can_send_videos: true,
  can_send_polls: true,
  checked_at: "2026-10-28T12:00:00Z",
};

async function openComposer(page: Page) {
  await page.route("**/api/v1/profiles", (route) =>
    json(route, 200, [
      { id: "profile-1", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
    ]),
  );
  await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
  await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, 200, channels));
  await page.goto("/");
  await page.getByText("Acme", { exact: true }).first().click();
  await expect(page.getByText("Grupo VIP").first()).toBeVisible();
}

const row = (dialog: ReturnType<Page["getByRole"]>, label: string) =>
  dialog.locator("div").filter({ has: dialog.page().getByText(label, { exact: true }) }).last();

test.describe("Permissões do bot por destino (#107)", () => {
  test("canal com o bot administrador mostra tudo liberado", async ({ page }) => {
    await page.route("**/api/v1/channels/c-1/bot-permissions", (route) => json(route, 200, channelAdmin));
    await openComposer(page);

    await page.getByRole("button", { name: "O que o bot pode fazer em Canal de Novidades", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Canal de Novidades" });
    await expect(dialog).toContainText("📢 Canal");
    await expect(dialog).toContainText("Administrador");
    await expect(dialog.getByRole("img", { name: "pode enviar" })).toHaveCount(4);
    await expect(dialog.getByRole("img", { name: "não pode enviar" })).toHaveCount(0);
  });

  test("grupo que proíbe fotos mostra o motivo e não muda a seleção do destino", async ({ page }) => {
    await page.route("**/api/v1/channels/c-2/bot-permissions", (route) => json(route, 200, groupMember));
    await openComposer(page);

    await page.getByRole("button", { name: "O que o bot pode fazer em Grupo VIP", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Grupo VIP" });
    await expect(dialog).toContainText("👥 Grupo");
    await expect(dialog).toContainText("Membro");
    await expect(row(dialog, "Foto")).toContainText("o grupo não deixa membros enviarem fotos");
    await expect(dialog.getByRole("img", { name: "não pode enviar" })).toHaveCount(1);

    await dialog.getByRole("button", { name: "Fechar painel de permissões", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    // A página abre com todos os destinos selecionados; abrir o painel não desmarca o grupo.
    await expect(page.getByRole("button").filter({ hasText: "Grupo VIP" }).first().locator("svg.lucide-check")).toHaveCount(1);
  });

  test("Atualizar lê de novo do Telegram", async ({ page }) => {
    // O grupo libera fotos depois que o painel abre; só o Atualizar traz a mudança.
    let photosAllowed = false;
    let calls = 0;
    await page.route("**/api/v1/channels/c-2/bot-permissions", (route) => {
      calls += 1;
      return json(route, 200, { ...groupMember, can_send_photos: photosAllowed });
    });
    await openComposer(page);
    await page.getByRole("button", { name: "O que o bot pode fazer em Grupo VIP", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Grupo VIP" });
    await expect(dialog.getByRole("img", { name: "não pode enviar" })).toHaveCount(1);
    const callsBeforeRefresh = calls;
    photosAllowed = true;

    await dialog.getByRole("button", { name: "Atualizar", exact: true }).click();

    await expect(dialog.getByRole("img", { name: "não pode enviar" })).toHaveCount(0);
    expect(calls).toBe(callsBeforeRefresh + 1);
  });

  test("Telegram fora do ar mostra o erro traduzido", async ({ page }) => {
    await page.route("**/api/v1/channels/c-1/bot-permissions", (route) =>
      json(route, 503, { detail: "Could not reach Telegram, try again" }),
    );
    await openComposer(page);
    await page.getByRole("button", { name: "O que o bot pode fazer em Canal de Novidades", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Canal de Novidades" });
    await expect(dialog.getByRole("alert")).not.toContainText("Could not reach Telegram");
    await expect(dialog.getByRole("alert")).toBeVisible();
  });

  test("Esc fecha o painel", async ({ page }) => {
    await page.route("**/api/v1/channels/c-1/bot-permissions", (route) => json(route, 200, channelAdmin));
    await openComposer(page);
    await page.getByRole("button", { name: "O que o bot pode fazer em Canal de Novidades", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "O que o bot pode fazer em Canal de Novidades" });
    await expect(dialog).toContainText("Administrador");

    await page.keyboard.press("Escape");

    await expect(dialog).toHaveCount(0);
  });
});
