import type { BotMemberStatus, BotPermissions } from "@/types";

export const BOT_STATUS_LABEL: Record<BotMemberStatus, string> = {
  creator: "Criador",
  administrator: "Administrador",
  member: "Membro",
  restricted: "Restrito",
  left: "Fora do chat",
  kicked: "Removido do chat",
};

export interface PermissionRow {
  label: string;
  allowed: boolean;
  reason: string | null;
}

const CONTENTS: Array<{ key: keyof BotPermissions; label: string; noun: string }> = [
  { key: "can_send_messages", label: "Texto", noun: "mensagens" },
  { key: "can_send_photos", label: "Foto", noun: "fotos" },
  { key: "can_send_videos", label: "Vídeo", noun: "vídeos" },
  { key: "can_send_polls", label: "Enquete", noun: "enquetes" },
];

// Motivo em português de cada conteúdo que o bot não pode enviar, pela situação dele no destino (#107).
function denialReason(p: BotPermissions, noun: string): string {
  if (p.bot_status === "left" || p.bot_status === "kicked") return "o bot não está neste chat";
  if (p.chat_type !== "supergroup") return "em canal, o bot precisa ser administrador com permissão de publicar";
  if (p.bot_status === "restricted") return `o bot está restrito e não pode enviar ${noun} neste grupo`;
  return `o grupo não deixa membros enviarem ${noun}`;
}

export function permissionRows(p: BotPermissions): PermissionRow[] {
  return CONTENTS.map(({ key, label, noun }) => {
    const allowed = p[key] === true;
    return { label, allowed, reason: allowed ? null : denialReason(p, noun) };
  });
}
