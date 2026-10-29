import type { Channel, DiscoveredChat } from "@/types";

export interface ChatKind {
  emoji: string;
  label: string;
}

// Rótulo do tipo do chat (#99). Fórum é supergrupo com tópicos; grupo comum ainda não pode ser vinculado.
export function chatKind(chatType: DiscoveredChat["type"] | null, isForum: boolean): ChatKind | null {
  if (chatType === "channel") return { emoji: "📢", label: "Canal" };
  if (chatType === "supergroup") return isForum ? { emoji: "💬", label: "Fórum" } : { emoji: "👥", label: "Grupo" };
  if (chatType === "group") return { emoji: "👥", label: "Grupo comum" };
  return null;
}

// Enquete pública (votos visíveis) só vai se todo destino for grupo conhecido: o Telegram a recusa em canal,
// e canal ainda sem tipo conta como canal (#99). Mesma regra do backend (BroadcastPoll.ensure_fits_destinations).
export function allowsPublicPoll(targetChatIds: string[], channels: Pick<Channel, "chat_id" | "chat_type">[]): boolean {
  return (
    targetChatIds.length > 0 &&
    targetChatIds.every((id) => channels.find((c) => c.chat_id === id)?.chat_type === "supergroup")
  );
}
