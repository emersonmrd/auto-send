"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { useChatDiscovery } from "@/hooks/useChatDiscovery";
import type { DiscoveredChat } from "@/types";

interface ChatDiscoveryPanelProps {
  apiBaseUrl: string;
  profileId: string;
  // chat_id dos canais já vinculados ao perfil (a página recarrega a lista depois de vincular).
  registeredChatIds: string[];
  // Vincula o chat como canal do perfil; devolve true quando deu certo.
  onAdd: (chat: DiscoveredChat) => Promise<boolean>;
}

const TYPE_LABEL: Record<DiscoveredChat["type"], string> = {
  channel: "Canal",
  supergroup: "Supergrupo",
  group: "Grupo",
};

function ChatRow({
  chat,
  alreadyRegistered,
  onAdd,
}: {
  chat: DiscoveredChat;
  alreadyRegistered: boolean;
  onAdd: (chat: DiscoveredChat) => Promise<boolean>;
}) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-lg bg-[#242f3d] px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm text-gray-100">{chat.title || chat.chat_id}</p>
        <p className="truncate text-[11px] text-gray-400">
          {TYPE_LABEL[chat.type]}: {chat.username ? `@${chat.username} (${chat.chat_id})` : chat.chat_id}
        </p>
      </div>
      {alreadyRegistered ? (
        <span className="shrink-0 text-[11px] text-gray-400">Já vinculado</span>
      ) : chat.registrable ? (
        <button
          type="button"
          onClick={() => onAdd(chat)}
          className="shrink-0 rounded-lg bg-[#5288c1] px-2.5 py-1 text-xs font-medium text-white hover:bg-[#4374a5]"
        >
          Adicionar canal
        </button>
      ) : (
        <span className="shrink-0 text-[11px] text-gray-400" title="Converta o grupo em supergrupo no Telegram">
          Grupo comum não suportado
        </span>
      )}
    </li>
  );
}

export default function ChatDiscoveryPanel({ apiBaseUrl, profileId, registeredChatIds, onAdd }: ChatDiscoveryPanelProps) {
  const { chats, resolved, isLoading, error, webhookActive, discover, resolve } = useChatDiscovery(apiBaseUrl, profileId);
  const [identifier, setIdentifier] = useState("");
  const identifierId = useId();
  const identifierRef = useRef<HTMLInputElement>(null);

  // Com webhook ativo a busca automática nunca funciona: o foco vai direto para a entrada manual.
  useEffect(() => {
    if (webhookActive) identifierRef.current?.focus();
  }, [webhookActive]);

  const isRegistered = (chatId: string) => registeredChatIds.includes(chatId);
  const handleResolve = () => {
    if (identifier.trim()) resolve(identifier);
  };

  return (
    <section className="mb-5 space-y-3 border-b border-[#242f3d] pb-5" aria-label="Buscar canais do bot">
      <ol className="list-decimal space-y-0.5 pl-4 text-xs leading-relaxed text-gray-400">
        <li>Adicione o bot do perfil como administrador do canal.</li>
        <li>Publique uma mensagem no canal e clique em buscar: o bot só enxerga canais com mensagem recente.</li>
      </ol>

      <button
        type="button"
        onClick={discover}
        disabled={isLoading}
        className="flex items-center gap-1.5 rounded-lg bg-[#242f3d] px-3 py-1.5 text-xs font-medium text-[#5288c1] hover:bg-[#2b5278] hover:text-white disabled:opacity-50"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        Buscar canais do bot
      </button>

      {chats !== null &&
        (chats.length === 0 ? (
          <p className="text-xs text-gray-400">
            Nenhum canal encontrado. O Telegram guarda as mensagens por 24 horas: publique uma nova no canal e busque de
            novo, ou cole abaixo o link de um post do canal (toque numa mensagem e use &quot;Copiar link&quot;) ou o ID -100...
          </p>
        ) : (
          <ul className="max-h-48 space-y-1.5 overflow-y-auto">
            {chats.map((chat) => (
              <ChatRow key={chat.chat_id} chat={chat} alreadyRegistered={isRegistered(chat.chat_id)} onAdd={onAdd} />
            ))}
          </ul>
        ))}

      {/* div, não form: o painel fica dentro do formulário do modal de canal. */}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label htmlFor={identifierId} className="mb-1 block text-xs text-gray-400">
            Link de um post, ID ou @username do canal
          </label>
          <input
            id={identifierId}
            ref={identifierRef}
            type="text"
            placeholder="t.me/c/123.../15, -100... ou @meucanal"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleResolve();
              }
            }}
            className="w-full rounded-lg border border-transparent bg-[#242f3d] px-3 py-2 text-sm text-white outline-none focus:border-[#5288c1]"
          />
        </div>
        <button
          type="button"
          onClick={handleResolve}
          disabled={isLoading || !identifier.trim()}
          aria-label="Buscar canal pelo link ou ID"
          title="Buscar canal pelo link ou ID"
          className="rounded-lg bg-[#242f3d] p-2 text-[#5288c1] hover:bg-[#2b5278] hover:text-white disabled:opacity-50"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>

      {resolved && (
        <ul>
          <ChatRow chat={resolved} alreadyRegistered={isRegistered(resolved.chat_id)} onAdd={onAdd} />
        </ul>
      )}

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}
