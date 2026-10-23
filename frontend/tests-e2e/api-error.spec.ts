import { test, expect } from "@playwright/test";
import { extractApiError } from "../src/lib/apiError";

// Função pura: roda no runner do Playwright sem abrir navegador.
test.describe("extractApiError", () => {
  test("usa o detail quando é string", () => {
    expect(extractApiError({ detail: "Profile not found" }, "fallback")).toBe("Profile not found");
  });

  test("junta as mensagens quando o detail é a lista de um 422 do Pydantic", () => {
    const body = {
      detail: [
        { loc: ["body", "name"], msg: "Field required", type: "missing" },
        { loc: ["body", "token"], msg: "Value error, Invalid Telegram Bot Token format", type: "value_error" },
      ],
    };
    expect(extractApiError(body, "fallback")).toBe("Field required; Value error, Invalid Telegram Bot Token format");
  });

  test("cai no fallback sem detail utilizável", () => {
    expect(extractApiError(null, "fallback")).toBe("fallback");
    expect(extractApiError({}, "fallback")).toBe("fallback");
    expect(extractApiError({ detail: "" }, "fallback")).toBe("fallback");
    expect(extractApiError({ detail: [{ loc: ["x"] }] }, "fallback")).toBe("fallback");
  });
});
