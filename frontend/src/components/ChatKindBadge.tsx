import { chatKind } from "@/lib/chatKind";
import type { Channel } from "@/types";

// Emoji do tipo do canal destino (#99); canal sem tipo conhecido não mostra nada.
export default function ChatKindBadge({ chatType, isForum }: { chatType: Channel["chat_type"]; isForum: boolean }) {
  const kind = chatKind(chatType, isForum);
  if (!kind) return null;
  return (
    <span role="img" aria-label={kind.label} title={kind.label} className="shrink-0 text-[11px] leading-none">
      {kind.emoji}
    </span>
  );
}
