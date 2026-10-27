import { test, expect } from "@playwright/test";
import {
  extractApiError,
  formatDeliveryFailureReason,
  translateTelegramError,
  TELEGRAM_ERROR_CATALOG,
} from "../src/lib/apiError";

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

  test("traduz erros comuns da API do Telegram encapsulados em 'Telegram API error' (Issue #57)", () => {
    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: chat not found" },
        "fallback"
      )
    ).toBe("Canal ou grupo não encontrado. Verifique se o ID ou @username está correto e se o bot é membro.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: group chat was upgraded to a supergroup, migrate to chat_id -1001234567890" },
        "fallback"
      )
    ).toBe("O grupo foi promovido para supergrupo e o identificador mudou. Atualize o canal com o novo ID (-100...).");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: have no rights to send a message" },
        "fallback"
      )
    ).toBe("O bot não tem permissão para enviar mensagens neste canal. Adicione o bot como administrador com permissão de publicar.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: not enough rights to send text messages to the chat" },
        "fallback"
      )
    ).toBe("O bot não tem permissão para enviar mensagens neste canal. Adicione o bot como administrador com permissão de publicar.");

    expect(
      extractApiError(
        { detail: "Telegram API error (403): Forbidden: bot was blocked by the user" },
        "fallback"
      )
    ).toBe("O bot foi bloqueado pelo usuário.");

    expect(
      extractApiError(
        { detail: "Telegram API error (403): Forbidden: bot was kicked from the channel chat" },
        "fallback"
      )
    ).toBe("O bot não é membro ou foi removido deste canal. Adicione-o novamente como administrador.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: message is too long" },
        "fallback"
      )
    ).toBe("A mensagem excede o limite de caracteres permitido pelo Telegram (máximo 4.096 caracteres).");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: message caption is too long" },
        "fallback"
      )
    ).toBe("A legenda da mídia excede o limite de 1.024 caracteres do Telegram.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: message text is empty" },
        "fallback"
      )
    ).toBe("O texto da mensagem não pode estar vazio.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: BUTTON_URL_INVALID" },
        "fallback"
      )
    ).toBe("A URL informada para o botão é inválida.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: can't parse entities: Character '(' is reserved" },
        "fallback"
      )
    ).toBe("A formatação HTML ou Markdown contém erros ou tags não suportadas pelo Telegram.");

    expect(
      extractApiError(
        { detail: "Telegram API error (400): Bad Request: wrong file identifier/HTTP URL specified" },
        "fallback"
      )
    ).toBe("Não foi possível carregar ou processar o arquivo de mídia enviado.");

    expect(
      extractApiError(
        { detail: "Telegram API error (403): Forbidden: user is deactivated" },
        "fallback"
      )
    ).toBe("O canal ou usuário de destino foi desativado pelo Telegram.");

    expect(
      extractApiError(
        { detail: "Telegram API error (401): Unauthorized" },
        "fallback"
      )
    ).toBe("Token do bot inválido, revogado ou expirado. Confira o token no @BotFather.");

    expect(
      extractApiError(
        { detail: "Telegram API error (429): Too Many Requests: retry after 25" },
        "fallback"
      )
    ).toBe("Limite de requisições do Telegram excedido. Aguarde alguns instantes antes de tentar novamente.");
  });

  test("traduz erros do Telegram passados diretamente como detail ou no fallback do formatDeliveryFailureReason (Issue #57)", () => {
    expect(
      extractApiError({ detail: "Bad Request: chat not found" }, "fallback")
    ).toBe("Canal ou grupo não encontrado. Verifique se o ID ou @username está correto e se o bot é membro.");

    expect(
      formatDeliveryFailureReason("OTHER", "Bad Request: have no rights to send a message")
    ).toBe("O bot não tem permissão para enviar mensagens neste canal. Adicione o bot como administrador com permissão de publicar.");

    expect(
      formatDeliveryFailureReason(null, "Bad Request: chat not found")
    ).toBe("Canal ou grupo não encontrado. Verifique se o ID ou @username está correto e se o bot é membro.");
  });

  test("garante 100% de cobertura nos padrões do catálogo TELEGRAM_ERROR_CATALOG (Issue #57)", () => {
    expect(TELEGRAM_ERROR_CATALOG.length).toBeGreaterThanOrEqual(14);
    for (const item of TELEGRAM_ERROR_CATALOG) {
      expect(item.pattern).toBeInstanceOf(RegExp);
      expect(typeof item.translation).toBe("string");
      expect(item.translation.length).toBeGreaterThan(10);
    }
    expect(translateTelegramError("An unknown custom error")).toBeNull();
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
