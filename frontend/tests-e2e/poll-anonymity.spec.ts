import { test, expect, type Page, type Route } from "@playwright/test";
import type { Channel } from "../src/types";

// Issue #99 parte B: o Telegram recusa enquete pública (não anônima) em canal.
// Só com todos os destinos sendo grupos o voto anônimo pode ser desmarcado.
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const channels: Channel[] = [
  { id: "c-1", profile_id: "profile-1", title: "Canal de Novidades", chat_id: "-1001111111111", invite_link: "", is_active: true, chat_type: "channel", is_forum: false },
  { id: "c-2", profile_id: "profile-1", title: "Grupo VIP", chat_id: "-1002222222222", invite_link: "", is_active: true, chat_type: "supergroup", is_forum: false },
  { id: "c-3", profile_id: "profile-1", title: "Canal Antigo", chat_id: "-1003333333333", invite_link: "", is_active: true, chat_type: null, is_forum: false },
];

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

const chip = (page: Page, title: string) => page.getByRole("button").filter({ hasText: title }).first();

async function keepOnly(page: Page, keep: string) {
  // A página abre com todos os canais selecionados.
  for (const c of channels) {
    if (c.title !== keep) await chip(page, c.title).click();
  }
}

test.describe("Voto anônimo conforme os destinos (#99)", () => {
  test("com canal entre os destinos, o voto anônimo fica travado e explicado", async ({ page }) => {
    await openComposer(page);
    await page.getByRole("button", { name: "Criar Enquete", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "Criar Enquete do Telegram" });
    const anonymous = dialog.getByRole("checkbox", { name: /Voto Anônimo/ });
    await expect(anonymous).toBeChecked();
    await expect(anonymous).toBeDisabled();
    await expect(dialog.getByRole("note")).toContainText("Algum destino é canal");
  });

  test("só com grupos, dá para criar enquete com votos visíveis", async ({ page }) => {
    await openComposer(page);
    await keepOnly(page, "Grupo VIP");
    await page.getByRole("button", { name: "Criar Enquete", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "Criar Enquete do Telegram" });
    await expect(dialog.getByRole("note")).toHaveCount(0);
    await dialog.getByPlaceholder("Ex: Qual tema vocês querem no próximo conteúdo?").fill("Qual tema?");
    await dialog.getByPlaceholder("Opção 1").fill("A");
    await dialog.getByPlaceholder("Opção 2").fill("B");
    await dialog.getByRole("checkbox", { name: /Voto Anônimo/ }).uncheck();
    await dialog.getByRole("button", { name: "Salvar", exact: true }).click();

    await expect(page.getByText("(Votos visíveis)")).toBeVisible();
  });

  test("voltar a incluir um canal sem tipo torna a enquete anônima de novo", async ({ page }) => {
    await openComposer(page);
    await keepOnly(page, "Grupo VIP");
    await page.getByRole("button", { name: "Criar Enquete", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Criar Enquete do Telegram" });
    await dialog.getByPlaceholder("Ex: Qual tema vocês querem no próximo conteúdo?").fill("Qual tema?");
    await dialog.getByPlaceholder("Opção 1").fill("A");
    await dialog.getByPlaceholder("Opção 2").fill("B");
    await dialog.getByRole("checkbox", { name: /Voto Anônimo/ }).uncheck();
    await dialog.getByRole("button", { name: "Salvar", exact: true }).click();
    await expect(page.getByText("(Votos visíveis)")).toBeVisible();

    await chip(page, "Canal Antigo").click();

    await expect(page.getByText("(Anônima)")).toBeVisible();
  });
});
