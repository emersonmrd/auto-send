import type { DiscoveredChat } from "@/types";

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
