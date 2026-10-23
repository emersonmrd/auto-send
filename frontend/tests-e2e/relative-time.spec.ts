import { test, expect } from "@playwright/test";
import { formatRelativeTime } from "../src/lib/relativeTime";

const NOW = new Date("2026-10-22T12:00:00Z");
const at = (ms: number) => new Date(NOW.getTime() + ms);
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

// Função pura: roda no runner do Playwright sem abrir navegador.
test.describe("formatRelativeTime", () => {
  test("usa a maior unidade que cabe", () => {
    expect(formatRelativeTime(at(30 * MIN), NOW, "pt-BR")).toBe("em 30 minutos");
    expect(formatRelativeTime(at(2 * HOUR), NOW, "pt-BR")).toBe("em 2 horas");
    expect(formatRelativeTime(at(3 * DAY), NOW, "pt-BR")).toBe("em 3 dias");
  });

  test("usa as formas naturais do idioma", () => {
    expect(formatRelativeTime(at(DAY), NOW, "pt-BR")).toBe("amanhã");
    expect(formatRelativeTime(at(10 * 1000), NOW, "pt-BR")).toBe("agora");
    expect(formatRelativeTime(at(2 * HOUR), NOW, "en-US")).toBe("in 2 hours");
  });

  test("descreve horários que já passaram", () => {
    expect(formatRelativeTime(at(-5 * MIN), NOW, "pt-BR")).toBe("há 5 minutos");
  });

  test("arredonda para a unidade mais próxima", () => {
    expect(formatRelativeTime(at(119 * MIN), NOW, "pt-BR")).toBe("em 2 horas");
    expect(formatRelativeTime(at(89 * MIN), NOW, "pt-BR")).toBe("em 1 hora");
  });
});

test.describe("Fila de agendamentos", () => {
  test.use({ locale: "pt-BR", timezoneId: "America/Sao_Paulo" });

  test("mostra a data relativa ao lado da data absoluta", async ({ page }) => {
    const scheduledAt = new Date(Date.now() + 2 * HOUR + 5 * MIN).toISOString();
    await page.route("**/api/v1/profiles", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ id: "profile-1", name: "Acme", bot_username: "acme_news_bot", avatar_url: null, is_active: true }]),
      }),
    );
    await page.route("**/api/v1/profiles/*/channels", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/profiles/*/scheduled-broadcasts", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { id: "b-1", profile_id: "profile-1", target_channel_ids: [], text: "Promo", media: null, button: null, status: "SCHEDULED", scheduled_at: scheduledAt },
        ]),
      }),
    );

    await page.goto("/");
    await page.getByTitle("Abrir Fila de Agendamentos").click();
    await expect(page.getByTestId("schedule-relative-time")).toHaveText("em 2 horas");
  });
});
