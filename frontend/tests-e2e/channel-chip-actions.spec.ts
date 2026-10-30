import { test, expect, type Page, type Route } from "@playwright/test";
import type { Channel } from "../src/types";

// Issue #114: botões Editar e Excluir do chip de destino devem funcionar pelo teclado (Enter e Espaço)
// sem alternar a seleção do destino.
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const channels: Channel[] = [
  { id: "c-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001111111111", invite_link: "", is_active: true, chat_type: "channel", is_forum: false },
];

async function openComposer(page: Page) {
  await page.route("**/api/v1/profiles", (route) =>
    json(route, 200, [
      { id: "profile-1", name: "Acme", bot_username: "acme_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
    ]),
  );
  await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
  await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, 200, channels));
  await page.route("**/api/v1/channels/c-1/affected-scheduled-broadcasts", (route) =>
    json(route, 200, { channel_id: "c-1", will_be_cancelled: [], will_lose_target: [] }),
  );
  await page.goto("/");
  await page.getByText("Acme", { exact: true }).first().click();
  await page.getByRole("button", { name: /Canais Destino/ }).click();
  const destinationsModal = page.getByTestId("destinations-modal");
  await expect(destinationsModal).toBeVisible();
  await expect(destinationsModal.locator("text=Canal de Novidades").first()).toBeVisible();
}

test.describe("Ações do canal de destino pelo teclado (#114)", () => {
  test("Enter no botão Editar Canal abre modal de edição sem desmarcar o canal", async ({ page }) => {
    await openComposer(page);

    const editBtn = page.getByTestId("destinations-modal").getByRole("button", { name: "Editar Canal", exact: true }).first();
    await editBtn.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByRole("heading", { name: "Editar Canal", exact: true })).toBeVisible();

    // Fecha o modal e confirma que o canal continua selecionado
    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Editar Canal", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("destinations-modal").locator("div").filter({ hasText: "Canal de Novidades" }).first().locator("svg.lucide-check")).toHaveCount(1);
  });

  test("Espaço no botão Editar Canal abre modal de edição sem desmarcar o canal", async ({ page }) => {
    await openComposer(page);

    const editBtn = page.getByTestId("destinations-modal").getByRole("button", { name: "Editar Canal", exact: true }).first();
    await editBtn.focus();
    await page.keyboard.press("Space");

    await expect(page.getByRole("heading", { name: "Editar Canal", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Editar Canal", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("destinations-modal").locator("div").filter({ hasText: "Canal de Novidades" }).first().locator("svg.lucide-check")).toHaveCount(1);
  });

  test("Enter no botão Excluir Canal abre modal de confirmação sem desmarcar o canal", async ({ page }) => {
    await openComposer(page);

    const deleteBtn = page.getByTestId("destinations-modal").getByRole("button", { name: "Excluir Canal", exact: true }).first();
    await deleteBtn.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByRole("heading", { name: "Excluir Canal", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Excluir Canal", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("destinations-modal").locator("div").filter({ hasText: "Canal de Novidades" }).first().locator("svg.lucide-check")).toHaveCount(1);
  });

  test("Espaço no botão Excluir Canal abre modal de confirmação sem desmarcar o canal", async ({ page }) => {
    await openComposer(page);

    const deleteBtn = page.getByTestId("destinations-modal").getByRole("button", { name: "Excluir Canal", exact: true }).first();
    await deleteBtn.focus();
    await page.keyboard.press("Space");

    await expect(page.getByRole("heading", { name: "Excluir Canal", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Excluir Canal", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("destinations-modal").locator("div").filter({ hasText: "Canal de Novidades" }).first().locator("svg.lucide-check")).toHaveCount(1);
  });
});
