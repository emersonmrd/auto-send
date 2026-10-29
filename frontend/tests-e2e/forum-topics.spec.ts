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

  test("Campo ID do Tópico aceita apenas dígitos positivos e sanitiza caracteres inválidos e negativos", async ({ page }) => {
    await openComposerWithTopics(page);

    await page.getByRole("button", { name: "Adicionar Canal", exact: true }).click();
    const topicIdInput = page.locator("#field-new-channel-topic-id");

    // Tentativa de digitar valor negativo com letras
    await topicIdInput.fill("-12abc34");
    // Apenas dígitos positivos permanecem
    await expect(topicIdInput).toHaveValue("1234");
  });

  test("Exibe aviso de envio em andamento e desabilita confirmação no modal de exclusão", async ({ page }) => {
    await openComposerWithTopics(page);

    await page.route("**/api/v1/channels/c-topic-1/affected-broadcasts", (route) =>
      json(route, 200, {
        will_be_cancelled: [],
        will_lose_target: [],
        in_flight_count: 1,
      }),
    );

    const chipGeral = page.getByRole("button").filter({ hasText: "Grupo VIP (#Geral)" }).first();
    await chipGeral.getByRole("button", { name: "Excluir Canal" }).click();

    await expect(page.getByTestId("channel-delete-in-flight-warning")).toBeVisible();
    await expect(page.getByTestId("channel-delete-in-flight-warning")).toContainText("Há 1 envio em andamento para este canal");

    const confirmBtn = page.getByRole("button", { name: "Confirmar Exclusão" });
    await expect(confirmBtn).toBeDisabled();
  });

  test("Quando há mais de 4 canais, modal de destinos gerencia canais com submodais em primeiro plano", async ({ page }) => {
    const fiveChannels: Channel[] = [
      { id: "c1", profile_id: "profile-1", title: "Canal 1", chat_id: "-1001", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1001" },
      { id: "c2", profile_id: "profile-1", title: "Canal 2", chat_id: "-1002", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1002" },
      { id: "c3", profile_id: "profile-1", title: "Canal 3", chat_id: "-1003", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1003" },
      { id: "c4", profile_id: "profile-1", title: "Canal 4", chat_id: "-1004", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1004" },
      { id: "c5", profile_id: "profile-1", title: "Canal 5", chat_id: "-1005", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1005" },
    ];

    await page.route("**/api/v1/profiles", (route) =>
      json(route, 200, [
        { id: "profile-1", name: "Bot VIP", bot_username: "vip_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
      ]),
    );
    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
    await page.route("**/api/v1/profiles/profile-1/channels", (route) => json(route, 200, fiveChannels));
    await page.route("**/api/v1/channels/c1/affected-broadcasts", (route) =>
      json(route, 200, { will_be_cancelled: [], will_lose_target: [], in_flight_count: 0 }),
    );

    await page.goto("/");
    await page.getByText("Bot VIP", { exact: true }).first().click();

    // Botão de seletor compacto visível
    const destinationsBtn = page.getByRole("button", { name: /Canais Destino/ });
    await expect(destinationsBtn).toBeVisible();
    await destinationsBtn.click();

    const destinationsModal = page.getByTestId("destinations-modal");
    await expect(destinationsModal).toBeVisible();

    // 1. Abrir edição de canal a partir do modal de destinos
    const editBtn = destinationsModal.getByRole("button", { name: "Editar Canal" }).first();
    await editBtn.click();
    const editHeading = page.getByRole("heading", { name: /Editar Canal/ });
    await expect(editHeading).toBeVisible();
    // Cancela a edição e confere que o modal de destinos continua ativo
    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(destinationsModal).toBeVisible();

    // 2. Abrir exclusão de canal a partir do modal de destinos
    const deleteBtn = destinationsModal.getByRole("button", { name: "Excluir Canal" }).first();
    await deleteBtn.click();
    const deleteHeading = page.getByRole("heading", { name: /Excluir Canal/ });
    await expect(deleteHeading).toBeVisible();
    // Cancela a exclusão e confere que o modal de destinos continua ativo
    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(destinationsModal).toBeVisible();

    // 3. Abrir "+ Adicionar Novo Canal" a partir do modal de destinos
    const addBtn = destinationsModal.getByRole("button", { name: "Adicionar Novo Canal" });
    await addBtn.click();
    const addHeading = page.getByRole("heading", { name: /Adicionar Canal/ });
    await expect(addHeading).toBeVisible();
    // Cancela o cadastro e confere que o modal de destinos continua ativo
    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(destinationsModal).toBeVisible();
  });

  test("Quando adiciona novo canal a partir do modal de destinos, o modal permanece ativo com o novo canal listado", async ({ page }) => {
    const initialChannels: Channel[] = [
      { id: "c1", profile_id: "profile-1", title: "Canal 1", chat_id: "-1001", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1001" },
      { id: "c2", profile_id: "profile-1", title: "Canal 2", chat_id: "-1002", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1002" },
      { id: "c3", profile_id: "profile-1", title: "Canal 3", chat_id: "-1003", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1003" },
      { id: "c4", profile_id: "profile-1", title: "Canal 4", chat_id: "-1004", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1004" },
      { id: "c5", profile_id: "profile-1", title: "Canal 5", chat_id: "-1005", invite_link: "", is_active: true, chat_type: "channel", is_forum: false, message_thread_id: null, topic_name: null, destination_id: "-1005" },
    ];
    let currentChannels = [...initialChannels];

    await page.route("**/api/v1/profiles", (route) =>
      json(route, 200, [
        { id: "profile-1", name: "Bot VIP", bot_username: "vip_bot", avatar_url: null, is_active: true, created_at: "2026-10-19T10:00:00Z" },
      ]),
    );
    await page.route("**/api/v1/profiles/profile-1/scheduled-broadcasts", (route) => json(route, 200, []));
    await page.route("**/api/v1/profiles/profile-1/channels", (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        const newChan = {
          id: "c6",
          profile_id: "profile-1",
          title: body.title,
          chat_id: body.chat_id,
          invite_link: "",
          is_active: true,
          chat_type: "channel",
          is_forum: false,
          message_thread_id: null,
          topic_name: null,
          destination_id: body.chat_id,
        };
        currentChannels = [...currentChannels, newChan];
        return json(route, 201, newChan);
      }
      return json(route, 200, currentChannels);
    });

    await page.goto("/");
    await page.getByText("Bot VIP", { exact: true }).first().click();

    const destinationsBtn = page.getByRole("button", { name: /Canais Destino/ });
    await destinationsBtn.click();
    const destinationsModal = page.getByTestId("destinations-modal");
    await expect(destinationsModal).toBeVisible();

    // Clica em Adicionar Novo Canal a partir do rodapé do modal
    await destinationsModal.getByRole("button", { name: "Adicionar Novo Canal" }).click();

    // Preenche o formulário do submodal
    await page.locator("#field-new-channel-title").fill("Canal Extra 6");
    await page.locator("#field-new-channel-chat-id").fill("-1001006");
    await page.getByRole("button", { name: "Vincular Canal" }).click();

    // Modal de adicionar fecha e o modal de destinos permanece aberto contendo o novo canal
    await expect(destinationsModal).toBeVisible();
    await expect(destinationsModal.getByText("Canal Extra 6")).toBeVisible();
  });
});
