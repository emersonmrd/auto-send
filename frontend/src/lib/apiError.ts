// Corpo de erro da API (AGENTS.md §12): `detail` é string, ou a lista de um 422 de validação do Pydantic.
type ValidationIssue = { msg?: unknown };

export function extractApiError(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
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
