import { test, expect } from "@playwright/test";
import { extractApiError } from "../src/lib/apiError";

// Função pura: roda no runner do Playwright sem abrir navegador (Issue #32).
test.describe("extractApiError", () => {
  test("traduz os details conhecidos do backend para português", () => {
    expect(extractApiError({ detail: "Profile not found" }, "fallback")).toBe("Perfil não encontrado.");
    expect(
      extractApiError(
        { detail: "Bot is currently in use by another program" },
        "fallback"
      )
    ).toBe("Este bot está sendo usado por outro programa agora. Feche o outro programa ou use outro bot.");
    expect(
      extractApiError(
        { detail: "Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)" },
        "fallback"
      )
    ).toBe("Formato de ID do canal inválido. O ID deve começar com -100 seguido de números.");
  });

  test("converte a lista de um 422 do Pydantic em 'Campo X inválido'", () => {
    const body = {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "token"], msg: "Value error, Invalid Telegram Bot Token format", type: "value_error" },
      ],
    };
    expect(extractApiError(body, "fallback")).toBe("Campo name inválido; Campo token inválido");
  });

  test("usa mensagem genérica em português com o original entre parênteses quando não há tradução", () => {
    expect(extractApiError({ detail: "Unexpected upstream failure" }, "fallback")).toBe(
      "Não foi possível concluir a operação (Unexpected upstream failure)"
    );
  });

  test("remove tokens de bot vazados na mensagem de erro (§9)", () => {
    expect(
      extractApiError(
        { detail: "Telegram error for 123456789:ABCdefGhIJKlmNoPQRstu_0001" },
        "fallback"
      )
    ).not.toContain("123456789:ABCdefGhIJKlmNoPQRstu_0001");
  });

  test("cai no fallback sem detail utilizável", () => {
    expect(extractApiError(null, "fallback")).toBe("fallback");
    expect(extractApiError({}, "fallback")).toBe("fallback");
    expect(extractApiError({ detail: "" }, "fallback")).toBe("fallback");
    expect(extractApiError({ detail: [{ loc: ["x"] }] }, "fallback")).toBe("fallback");
  });
});
