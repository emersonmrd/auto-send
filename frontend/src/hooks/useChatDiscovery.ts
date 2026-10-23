import { useState } from "react";
import { extractApiError } from "@/lib/apiError";
import type { DiscoverChatsResponse, DiscoveredChat, DiscoveredChatListItem } from "@/types";

// Busca os chats do bot do perfil (getUpdates) e resolve um @username público (getChat) pelo backend.
export function useChatDiscovery(apiBaseUrl: string, profileId: string) {
  const [chats, setChats] = useState<DiscoveredChatListItem[] | null>(null);
  const [resolved, setResolved] = useState<DiscoveredChat | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        setError(extractApiError(data, `Falha HTTP ${res.status}`));
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

  return { chats, resolved, isLoading, error, discover, resolve };
}
