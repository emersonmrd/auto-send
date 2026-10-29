import { test, expect, type Page, type Route } from "@playwright/test";
import type { Channel } from "../src/types";

// Issue #101: suporte a tópicos de fóruns de supergrupos (message_thread_id)
const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const forumChannels: Channel[] = [
  {
    id: "c-topic-1",
    profile_id: "profile-1",
    title: "Grupo VIP",
    chat_id: "-1001999999999",
    invite_link: "",
    is_active: true,
    chat_type: "supergroup",
    is_forum: true,
    message_thread_id: 10,
    topic_name: "Geral",
    destination_id: "-1001999999999:10",
  },
  {
    id: "c-topic-2",
    profile_id: "profile-1",
    title: "Grupo VIP",
    chat_id: "-1001999999999",
    invite_link: "",
    is_active: true,
    chat_type: "supergroup",
    is_forum: true,
    message_thread_id: 20,
    topic_name: "Anúncios",
    destination_id: "-1001999999999:20",
  },
];

async function openComposerWithTopics(page: Page) {
  await page.route("**/api/v1/profiles", (route) =>
    json(route, 200, [
      { id: "profile-1", name: "Bot VIP", bot_username: "vip_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
    ]),
  );
  await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
  await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, 200, forumChannels));
  await page.goto("/");
  await page.getByText("Bot VIP", { exact: true }).first().click();
}

test.describe("Suporte a tópicos de fóruns de supergrupos (#101)", () => {
  test("Exibe rótulo do tópico nos chips de destino para múltiplos tópicos no mesmo supergrupo", async ({ page }) => {
    await openComposerWithTopics(page);

    // Confere que ambos os tópicos aparecem com o selo do tópico
    await expect(page.getByText("Grupo VIP (#Geral)").first()).toBeVisible();
    await expect(page.getByText("Grupo VIP (#Anúncios)").first()).toBeVisible();
  });

  test("Permite alternar a seleção de tópicos de forma independente", async ({ page }) => {
    await openComposerWithTopics(page);

    const chipGeral = page.getByRole("button").filter({ hasText: "Grupo VIP (#Geral)" }).first();
    const chipAnuncios = page.getByRole("button").filter({ hasText: "Grupo VIP (#Anúncios)" }).first();

    // Inicialmente ambos estão selecionados (com ícone check)
    await expect(chipGeral.locator("svg.lucide-check")).toHaveCount(1);
    await expect(chipAnuncios.locator("svg.lucide-check")).toHaveCount(1);

    // Desmarca o tópico Geral clicando nele
    await chipGeral.click();
    await expect(chipGeral.locator("svg.lucide-check")).toHaveCount(0);
    // Anúncios continua selecionado
    await expect(chipAnuncios.locator("svg.lucide-check")).toHaveCount(1);
  });

  test("Preenche automaticamente ID do tópico ao colar link t.me/c/<id>/<topic> no modal de adicionar canal", async ({ page }) => {
    await openComposerWithTopics(page);

    await page.getByRole("button", { name: "Adicionar Canal", exact: true }).click();
    await expect(page.getByRole("heading", { name: /Adicionar Canal/ })).toBeVisible();

    const chatIdInput = page.locator("#field-new-channel-chat-id");
    const topicIdInput = page.locator("#field-new-channel-topic-id");

    await chatIdInput.fill("https://t.me/c/1234567890/45");

    await expect(chatIdInput).toHaveValue("-1001234567890");
    await expect(topicIdInput).toHaveValue("45");
  });
});
