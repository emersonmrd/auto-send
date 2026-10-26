// Corpo de erro da API (AGENTS.md §12): `detail` é string, ou a lista de um 422 de validação do Pydantic.
type ValidationIssue = { msg?: unknown };

const CHANNEL_REGISTRATION_ERRORS: Record<string, string> = {
  "Bot is not administrator in the channel":
    "O bot não é administrador deste canal. Adicione-o como administrador com permissão de publicar e tente de novo.",
  "Could not reach Telegram, try again":
    "Não foi possível falar com o Telegram agora. Tente de novo em instantes.",
  "There is a broadcast currently dispatching. Wait for it to finish and try again.":
    "Há um envio em andamento. Aguarde terminar e tente de novo.",
};

const DELIVERY_FAILURE_MESSAGES: Record<string, string> = {
  BOT_NOT_IN_CHAT: "O bot não está no canal",
  NO_POST_PERMISSION: "O bot não é administrador ou não tem permissão de publicar",
  INVALID_TOKEN: "Token do bot inválido ou revogado",
  RATE_LIMITED: "Limite do Telegram; tente mais tarde",
  TELEGRAM_UNAVAILABLE: "Telegram indisponível no momento do envio",
};

export function formatDeliveryFailureReason(
  category?: string | null,
  detail?: string | null
): string {
  if (category && DELIVERY_FAILURE_MESSAGES[category]) {
    return DELIVERY_FAILURE_MESSAGES[category];
  }
  if (detail && detail.trim()) {
    return detail.trim();
  }
  return "Falha ao enviar para o canal";
}

export function extractApiError(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;

  if (typeof detail === "string" && detail.trim()) {
    const trimmed = detail.trim();
    return CHANNEL_REGISTRATION_ERRORS[trimmed] ?? trimmed;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: ValidationIssue) => (typeof issue?.msg === "string" ? issue.msg : ""))
      .filter(Boolean);
    if (messages.length) {
      return messages.join("; ");
    }
  }
  return fallback;
}

// Resposta HTTP de erro: houve resposta do servidor, então não é "erro de conexão".
export class ApiHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiHttpError";
  }
}
