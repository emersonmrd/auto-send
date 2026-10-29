"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Loader2, RefreshCw, X } from "lucide-react";
import { extractApiError } from "@/lib/apiError";
import { BOT_STATUS_LABEL, permissionRows } from "@/lib/botPermissions";
import { chatKind } from "@/lib/chatKind";
import type { BotPermissions, Channel } from "@/types";

interface BotPermissionsDialogProps {
  apiBaseUrl: string;
  channel: Pick<Channel, "id" | "title">;
  onClose: () => void;
}

// Painel "i" do destino (#107): lê do Telegram, ao abrir e em "Atualizar", o que o bot pode enviar ali.
export default function BotPermissionsDialog({ apiBaseUrl, channel, onClose }: BotPermissionsDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [permissions, setPermissions] = useState<BotPermissions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPermissions = useCallback(async (): Promise<{ data: BotPermissions | null; error: string | null }> => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/channels/${channel.id}/bot-permissions`);
      const data = await res.json().catch(() => null);
      if (!res.ok) return { data: null, error: extractApiError(data, `Falha HTTP ${res.status}`) };
      return { data: data as BotPermissions, error: null };
    } catch {
      return { data: null, error: "Erro de conexão com o servidor backend" };
    }
  }, [apiBaseUrl, channel.id]);

  const apply = (result: { data: BotPermissions | null; error: string | null }) => {
    if (result.data) setPermissions(result.data);
    setError(result.error);
    setIsLoading(false);
  };

  useEffect(() => {
    let active = true;
    fetchPermissions().then((result) => {
      if (active) apply(result);
    });
    return () => {
      active = false;
    };
  }, [fetchPermissions]);

  const refresh = async () => {
    setIsLoading(true);
    apply(await fetchPermissions());
  };

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      // Prende o Tab no painel, como o ConfirmDialog.
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [onClose]);

  const kind = permissions ? chatKind(permissions.chat_type, permissions.is_forum) : null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        className="bg-[#17212b] border border-gray-700 rounded-xl max-w-md w-full p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <h3 id={titleId} className="text-base font-semibold text-gray-100">
            O que o bot pode fazer em {channel.title}
          </h3>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Fechar painel de permissões"
            title="Fechar painel de permissões"
            className="p-1 rounded text-gray-400 hover:text-white hover:bg-gray-700"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-300 bg-red-900/30 border border-red-500/30 rounded-lg p-3 mb-4">
            {error}
          </p>
        )}

        {permissions && (
          <dl className="text-sm text-gray-200 space-y-2 mb-4">
            <div className="flex justify-between gap-4">
              <dt className="text-gray-400">Tipo</dt>
              <dd>{kind ? `${kind.emoji} ${kind.label}` : "Tipo ainda desconhecido"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-gray-400">Situação do bot</dt>
              <dd>{BOT_STATUS_LABEL[permissions.bot_status]}</dd>
            </div>
            {permissionRows(permissions).map((row) => (
              <div key={row.label} className="flex justify-between gap-4">
                <dt className="text-gray-400">{row.label}</dt>
                <dd className="text-right">
                  <span role="img" aria-label={row.allowed ? "pode enviar" : "não pode enviar"}>
                    {row.allowed ? "✅" : "❌"}
                  </span>
                  {row.reason && <span className="block text-xs text-gray-400">{row.reason}</span>}
                </dd>
              </div>
            ))}
          </dl>
        )}

        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-gray-500">
            {permissions &&
              `Lido do Telegram em ${new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "medium" }).format(
                new Date(permissions.checked_at)
              )}`}
          </span>
          <button
            type="button"
            onClick={refresh}
            disabled={isLoading}
            className="text-xs bg-[#242f3d] hover:bg-[#2b5278] disabled:opacity-60 text-[#71aaeb] hover:text-white px-3 py-1.5 rounded-lg transition flex items-center gap-1.5"
          >
            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            {isLoading ? "Lendo do Telegram..." : "Atualizar"}
          </button>
        </div>
      </div>
    </div>
  );
}
