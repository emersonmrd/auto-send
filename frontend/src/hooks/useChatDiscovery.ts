import { useState } from "react";
import { extractApiError } from "@/lib/apiError";
import type { DiscoverChatsResponse, DiscoveredChat, DiscoveredChatListItem } from "@/types";

// Detalhes conhecidos do backend (contrato em inglês, §12) com a explicação que a tela mostra.
const WEBHOOK_ACTIVE = "Bot webhook is active: automatic discovery is unavailable";
const KNOWN_ERRORS: Record<string, string> = {
  [WEBHOOK_ACTIVE]:
    "Este bot está ligado a outro sistema (webhook), por isso a busca automática não funciona. Vincule o canal pelo link de um post, pelo ID ou pelo @username.",
  "Invite links (t.me/+...) cannot be resolved by a bot: use the link of a post in the channel or the -100... chat ID":
    'Link de convite não serve. No canal, toque numa mensagem e use "Copiar link", ou informe o ID -100...',
};

// Busca os chats do bot do perfil (getUpdates) e resolve um canal por link, ID ou @username (getChat) pelo backend.
export function useChatDiscovery(apiBaseUrl: string, profileId: string) {
  const [chats, setChats] = useState<DiscoveredChatListItem[] | null>(null);
  const [resolved, setResolved] = useState<DiscoveredChat | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [webhookActive, setWebhookActive] = useState(false);

  async function post<T>(path: string, body?: unknown): Promise<T | null> {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/profiles/${profileId}/${path}`, {
        method: "POST",
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = extractApiError(data, `Falha HTTP ${res.status}`);
        setWebhookActive(detail === WEBHOOK_ACTIVE);
        setError(KNOWN_ERRORS[detail] ?? detail);
        return null;
      }
      return data as T;
    } catch {
      setError("Erro de conexão com o servidor backend");
      return null;
    } finally {
      setIsLoading(false);
    }
  }

  async function discover() {
    const data = await post<DiscoverChatsResponse>("discover-chats");
    if (data) setChats(data.chats);
  }

  async function resolve(identifier: string) {
    setResolved(null);
    const data = await post<DiscoveredChat>("resolve-chat", { identifier });
    if (data) setResolved(data);
  }

  return { chats, resolved, isLoading, error, webhookActive, discover, resolve };
}
