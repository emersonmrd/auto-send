// Corpo de erro da API (AGENTS.md §12): `detail` é string em inglês no contrato HTTP,
// ou a lista de um 422 de validação do Pydantic. Este módulo é o catálogo único de tradução
// para mensagens em português exibidas ao usuário (Issue #32).

type ValidationIssue = { loc?: unknown; msg?: unknown };

export const WEBHOOK_ACTIVE_DETAIL =
  "Bot webhook is active: automatic discovery is unavailable";

export const BOT_IN_USE_DETAIL =
  "Bot is currently in use by another program";

const BARE_BOT_TOKEN_RE = /\b\d{6,}:[A-Za-z0-9_-]{10,}\b/g;
const URL_BOT_TOKEN_RE = /\/bot[^/\s]+/g;

export function redactBotTokens(text: string): string {
  return text
    .replace(URL_BOT_TOKEN_RE, "/bot[REDACTED]")
    .replace(BARE_BOT_TOKEN_RE, "[REDACTED_TOKEN]");
}

export const API_ERROR_CATALOG: Record<string, string> = {
  // Perfis e autenticação do bot
  "Profile not found": "Perfil não encontrado.",
  "Template not found": "Modelo de mensagem não encontrado.",
  "Broadcast cancelled by user": "Envio do disparo cancelado pelo usuário.",
  "Invalid Telegram Bot Token format":
    "Formato de token do bot inválido. Use o token gerado pelo @BotFather (ex.: 123456789:ABC...).",

  // Canais e descoberta
  "Channel not found": "Canal não encontrado.",
  "Channel already registered for this profile":
    "Este canal já está cadastrado para este perfil.",
  "Invalid Telegram Channel Chat ID format (must start with -100 followed by digits)":
    "Formato de ID do canal inválido. O ID deve começar com -100 seguido de números.",
  "Bot is not administrator in the channel":
    "O bot não é administrador deste canal. Adicione-o como administrador com permissão de publicar e tente de novo.",
  "Could not reach Telegram, try again":
    "Não foi possível falar com o Telegram agora. Tente de novo em instantes.",
  [WEBHOOK_ACTIVE_DETAIL]:
    "Este bot está ligado a outro sistema (webhook), por isso a busca automática não funciona. Vincule o canal pelo link de um post, pelo ID ou pelo @username.",
  [BOT_IN_USE_DETAIL]:
    "Este bot está sendo usado por outro programa agora. Feche o outro programa ou use outro bot.",
  "Invite links (t.me/+...) cannot be resolved by a bot: use the link of a post in the channel or the -100... chat ID":
    'Link de convite não serve. No canal, toque numa mensagem e use "Copiar link", ou informe o ID -100...',
  "Invalid chat identifier (use @username, t.me/username, a post link t.me/c/... or the -100... chat ID)":
    "Identificador de canal inválido. Use @username, t.me/username, o link de um post (t.me/c/...) ou o ID -100...",
  "Invalid discovered chat (expected a channel or group with a negative numeric id)":
    "Esse chat não é um canal nem supergrupo válido do Telegram.",

  // Broadcasts, fila e agendamento
  "Broadcast not found": "Agendamento não encontrado.",
  "Tracking ID not found": "Identificador de progresso não encontrado.",
  "There is a broadcast currently dispatching. Wait for it to finish and try again.":
    "Há um envio em andamento. Aguarde terminar e tente de novo.",
  "scheduled_at must include a timezone":
    "A data e hora do agendamento precisam incluir o fuso horário.",
  "scheduled_at cannot be in the past":
    "A data e hora do agendamento não podem estar no passado.",
  "Invalid scheduled_at ISO-8601 format":
    "Formato de data e hora do agendamento inválido.",
  "Cannot edit an in-flight, completed, or cancelled broadcast":
    "Não é possível editar um agendamento em envio, concluído ou cancelado.",
  "Cannot cancel an in-flight or completed broadcast":
    "Não é possível cancelar um agendamento em envio ou já concluído.",
  "Cannot reschedule an in-flight, completed, or cancelled broadcast":
    "Não é possível reagendar um envio em andamento, concluído ou cancelado.",
  "Cannot update content of an in-flight, completed, or cancelled broadcast":
    "Não é possível alterar o conteúdo de um envio em andamento, concluído ou cancelado.",
  "Cannot dispatch an in-flight, completed, failed, or cancelled broadcast":
    "Não é possível disparar um envio em andamento, concluído, com falha ou cancelado.",
  "Only pending or scheduled broadcasts can become misfired":
    "Apenas agendamentos pendentes podem ser marcados como expirados.",
  "Cannot modify target channels of a completed, failed, or cancelled broadcast":
    "Não é possível alterar os canais de um agendamento concluído, com falha ou cancelado.",
  "Cannot lock an in-flight, completed, failed, or cancelled broadcast":
    "Não é possível editar um agendamento em envio, concluído, com falha ou cancelado.",
  "Cannot modify media of an in-flight, completed, failed, or cancelled broadcast":
    "Não é possível alterar a mídia de um agendamento em envio, concluído, com falha ou cancelado.",
  "Cannot edit media of an in-flight, completed, or cancelled broadcast":
    "Não é possível alterar a mídia de um agendamento em envio, concluído ou cancelado.",
  "No media file provided": "Nenhum arquivo de mídia foi enviado.",
  "Broadcast does not have media": "Este agendamento não possui mídia.",
  "Media not found": "Arquivo de mídia do agendamento não encontrado.",

  // Destinos, mídia, botões e HTML
  "Invalid target_channel_ids format":
    "Formato da lista de canais de destino inválido.",
  "target_channel_ids must be a non-empty list":
    "Selecione pelo menos um canal de destino.",
  "Unsupported media format":
    "Formato de mídia não suportado. Envie uma imagem (PNG, JPG, WEBP, GIF) ou vídeo (MP4).",
  "Both button_text and button_url are required when defining an inline button":
    "Informe tanto o texto quanto a URL ao adicionar um botão de link.",
  "Insecure or invalid URL scheme. Only https:// allowed.":
    "Use um endereço https:// válido.",
  "Insecure or invalid URL scheme: Private network prohibited.":
    "Endereço de rede local ou privada não é permitido no link.",
  "Insecure or invalid URL scheme: Private IP prohibited.":
    "Endereço de IP privado não é permitido no link.",
  "Unsupported HTML tag in message":
    "Formatação HTML não suportada pelo Telegram na mensagem.",
  "Invalid HTML formatting in message":
    "Formatação HTML inválida na mensagem.",
  "Invalid link URL in message: only https:// with a public host is allowed":
    "Use um endereço https:// válido no link do texto.",

  // Sistema
  "Unable to open the local data directory on this system":
    "Não foi possível abrir a pasta de dados neste sistema.",

  // Enquetes (Polls #97)
  "A broadcast cannot have both media and a poll":
    "Uma mensagem não pode conter mídia e enquete ao mesmo tempo.",
  "Invalid poll options format":
    "Formato das opções da enquete inválido.",
  "poll must have at least 2 options":
    "A enquete deve ter pelo menos 2 opções.",
  "poll options must be a list":
    "As opções da enquete devem ser fornecidas em formato de lista.",
  "question cannot be empty":
    "A pergunta da enquete não pode estar vazia.",
  "question cannot exceed 300 characters":
    "A pergunta da enquete não pode exceder 300 caracteres.",
  "poll cannot have more than 10 options":
    "A enquete não pode ter mais de 10 opções.",
  "poll option cannot be empty":
    "As opções da enquete não podem estar vazias.",
  "poll option cannot exceed 100 characters":
    "A opção da enquete não pode exceder 100 caracteres.",
  "quiz polls cannot allow multiple answers":
    "Enquetes no modo Quiz não podem permitir múltiplas respostas.",
  "quiz polls require correct_option_id":
    "Enquetes no modo Quiz exigem a seleção de uma resposta correta.",
  "correct_option_id must be an integer":
    "O identificador da resposta correta deve ser um número inteiro.",
  "correct_option_id is out of range":
    "A resposta correta selecionada é inválida ou fora da lista de opções.",
  "explanation cannot exceed 200 characters":
    "A explicação do Quiz não pode exceder 200 caracteres.",
  "regular polls cannot have correct_option_id":
    "Enquetes regulares não aceitam resposta correta pré-definida.",
  "regular polls cannot have explanation":
    "Enquetes regulares não aceitam explicação de resposta.",
};

export const TELEGRAM_ERROR_CATALOG: Array<{
  pattern: RegExp;
  translation: string;
}> = [
  {
    pattern: /chat not found/i,
    translation:
      "Canal ou grupo não encontrado. Verifique se o ID ou @username está correto e se o bot é membro.",
  },
  {
    pattern: /group chat was upgraded to a supergroup/i,
    translation:
      "O grupo foi promovido para supergrupo e o identificador mudou. Atualize o canal com o novo ID (-100...).",
  },
  {
    pattern: /(?:not enough rights|have no rights|chat_write_forbidden|need administrator rights)/i,
    translation:
      "O bot não tem permissão para enviar mensagens neste canal. Adicione o bot como administrador com permissão de publicar.",
  },
  {
    pattern: /bot was blocked by the user/i,
    translation: "O bot foi bloqueado pelo usuário.",
  },
  {
    pattern: /(?:bot was kicked|bot is not a member)/i,
    translation:
      "O bot não é membro ou foi removido deste canal. Adicione-o novamente como administrador.",
  },
  {
    pattern: /message is too long/i,
    translation:
      "A mensagem excede o limite de caracteres permitido pelo Telegram (máximo 4.096 caracteres).",
  },
  {
    pattern: /message caption is too long/i,
    translation:
      "A legenda da mídia excede o limite de 1.024 caracteres do Telegram.",
  },
  {
    pattern: /message text is empty/i,
    translation: "O texto da mensagem não pode estar vazio.",
  },
  {
    pattern: /BUTTON_URL_INVALID/i,
    translation: "A URL informada para o botão é inválida.",
  },
  {
    pattern: /can'?t parse entities/i,
    translation:
      "A formatação HTML ou Markdown contém erros ou tags não suportadas pelo Telegram.",
  },
  {
    pattern: /(?:wrong file identifier|failed to get HTTP URL content)/i,
    translation:
      "Não foi possível carregar ou processar o arquivo de mídia enviado.",
  },
  {
    pattern: /user is deactivated/i,
    translation:
      "O canal ou usuário de destino foi desativado pelo Telegram.",
  },
  {
    pattern: /unauthorized/i,
    translation:
      "Token do bot inválido, revogado ou expirado. Confira o token no @BotFather.",
  },
  {
    pattern: /too many requests/i,
    translation:
      "Limite de requisições do Telegram excedido. Aguarde alguns instantes antes de tentar novamente.",
  },
];

export function translateTelegramError(desc: string): string | null {
  const clean = redactBotTokens(desc.trim());
  for (const { pattern, translation } of TELEGRAM_ERROR_CATALOG) {
    if (pattern.test(clean)) {
      return translation;
    }
  }
  return null;
}

const API_ERROR_PATTERNS: Array<{
  pattern: RegExp;
  format: (match: RegExpExecArray) => string;
}> = [
  {
    pattern: /^Profile with ID '.*' not found\.$/,
    format: () => "Perfil não encontrado.",
  },
  {
    pattern: /^Telegram Bot Token validation failed:\s*(.+)$/i,
    format: (m) =>
      `Não foi possível validar o token do bot no Telegram (${m[1]}). Confira o token no @BotFather.`,
  },
  {
    pattern: /^Media file too large \(limit:\s*(\d+)\s*MB\)$/i,
    format: (m) => `Arquivo de mídia muito grande (limite: ${m[1]} MB).`,
  },
  {
    pattern: /^(.+) is not a channel or group$/i,
    format: (m) => `O endereço informado (${m[1]}) não é um canal nem supergrupo.`,
  },
  {
    pattern: /^Telegram unreachable \((.+)\)$/i,
    format: (m) =>
      `Não foi possível falar com o Telegram agora (${m[1]}). Tente de novo em instantes.`,
  },
  {
    pattern: /^Telegram API error(?:\s*\(\d+\))?:\s*(.+)$/i,
    format: (m) => {
      const tg = translateTelegramError(m[1]);
      if (tg) {
        return tg;
      }
      return `O Telegram recusou a operação (${m[1]}).`;
    },
  },
];

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
  if (detail && detail.trim()) {
    const tg = translateTelegramError(detail.trim());
    if (tg) {
      return tg;
    }
  }
  if (category && DELIVERY_FAILURE_MESSAGES[category]) {
    return DELIVERY_FAILURE_MESSAGES[category];
  }
  if (detail && detail.trim()) {
    return redactBotTokens(detail.trim());
  }
  return "Falha ao enviar para o canal";
}

export function translateApiDetail(rawDetail: string): string {
  const safeDetail = redactBotTokens(rawDetail.trim());
  const exact = API_ERROR_CATALOG[safeDetail];
  if (exact) {
    return exact;
  }
  for (const { pattern, format } of API_ERROR_PATTERNS) {
    const match = pattern.exec(safeDetail);
    if (match) {
      return format(match);
    }
  }
  const tgDirect = translateTelegramError(safeDetail);
  if (tgDirect) {
    return tgDirect;
  }
  return `Não foi possível concluir a operação (${safeDetail})`;
}

export function extractApiError(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return translateApiDetail(detail);
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: ValidationIssue) => {
        if (typeof issue?.msg !== "string" || !issue.msg.trim()) {
          return "";
        }
        const loc = Array.isArray(issue.loc) ? issue.loc : [];
        const field = loc.length > 0 ? String(loc[loc.length - 1]).trim() : "";
        if (field) {
          return `Campo ${field} inválido`;
        }
        return translateApiDetail(issue.msg);
      })
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
