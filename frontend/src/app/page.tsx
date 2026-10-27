"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Profile,
  Channel,
  DiscoveredChat,
  ScheduledBroadcast,
  AffectedBroadcastItem,
  AffectedBroadcastsResponse,
  BroadcastHistoryItem,
  ChannelDeliveryResult,
  EditLockResponse,
  TelegramApiConfigResponse,
} from "@/types";
import { formatRelativeTime } from "@/lib/relativeTime";
import { ApiHttpError, extractApiError, formatDeliveryFailureReason } from "@/lib/apiError";
import ChatDiscoveryPanel from "@/components/ChatDiscoveryPanel";
import ConfirmDialog, { ConfirmDialogProps } from "@/components/ConfirmDialog";
import {
  TelegramRichEditor,
  TelegramRichEditorHandle,
  renderTelegramHtmlPreview,
} from "@/components/TelegramRichEditor";

type PendingConfirm = Omit<ConfirmDialogProps, "onCancel">;

interface BroadcastResponse {
  broadcast_id?: string;
  status?: string;
  scheduled_at?: string;
  dispatched_count?: number;
  total_targets?: number;
  errors?: string[];
  delivery_results?: ChannelDeliveryResult[];
  detail?: string | Array<{ msg?: string }>;
}

interface TelegramUploadProgress {
  percent: number;
  sent_bytes: number;
  total_bytes: number;
  status: string;
  stage?: string;
}

interface ToastNotice {
  id: string;
  message: string;
  type: "success" | "error" | "info";
}

// "" no export estático = mesma origem do backend que serve a tela (next.config.ts); no `npm run dev`, a porta 8000.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

import {
  Send,
  Paperclip,
  CheckCheck,
  Plus,
  Users,
  Tv,
  Check,
  AlertCircle,
  Video,
  Image as ImageIcon,
  Calendar,
  Clock,
  ExternalLink,
  ListOrdered,
  SquarePlus,
  X,
  Trash2,
  Edit,
  RefreshCw,
  Info,
  Server,
} from "lucide-react";

export default function Home() {
  const [toast, setToast] = useState<ToastNotice | null>(null);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    setToast({ id: Date.now().toString(), message, type });
    setTimeout(() => {
      setToast((current) => (current?.message === message ? null : current));
    }, 4000);
  };

  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<Profile | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelIds, setSelectedChannelIds] = useState<string[]>([]);

  // Composição da Mensagem
  const [text, setText] = useState("");
  const [buttonText, setButtonText] = useState("");
  const [buttonUrl, setButtonUrl] = useState("");
  const [showButtonModal, setShowButtonModal] = useState(false);
  const [tempButtonText, setTempButtonText] = useState("");
  const [tempButtonUrl, setTempButtonUrl] = useState("");
  const [mediaFile, setMediaFile] = useState<File | null>(null);
  const [mediaPreviewUrl, setMediaPreviewUrl] = useState<string | null>(null);
  // Mídia do agendamento sendo editado no compositor (#18)
  const [existingEditingMedia, setExistingEditingMedia] = useState<{
    mediaType: "PHOTO" | "VIDEO";
    fileSize?: number | null;
    url: string;
  } | null>(null);
  const [existingMediaRemoved, setExistingMediaRemoved] = useState(false);

  // Configurações Telegram API (2 GB) (#56)
  const [telegramApiConfig, setTelegramApiConfig] = useState<TelegramApiConfigResponse | null>(null);
  const [showTelegramApiModal, setShowTelegramApiModal] = useState(false);
  const [apiIdInput, setApiIdInput] = useState("");
  const [apiHashInput, setApiHashInput] = useState("");
  const [isSavingTelegramApi, setIsSavingTelegramApi] = useState(false);

  // Inserção de Link no Texto da Mensagem (Inline Hyperlink)
  const composerEditorRef = useRef<TelegramRichEditorHandle | null>(null);

  // Modo edição de um agendamento carregado no compositor (#15)
  const [composerEditing, setComposerEditing] = useState<{ id: string; scheduledAt: string | null } | null>(null);
  useEffect(() => {
    if (!composerEditing) return;
    const renew = setInterval(() => {
      void fetch(`${API_BASE_URL}/api/v1/broadcasts/${composerEditing.id}/edit-lock`, { method: "POST" }).catch(
        () => undefined,
      );
    }, 30_000);
    return () => clearInterval(renew);
  }, [composerEditing]);
  const [telegramProgress, setTelegramProgress] = useState<TelegramUploadProgress | null>(null);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Agendamento
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [scheduledAtInput, setScheduledAtInput] = useState("");
  const [scheduleConfirmedPreview, setScheduleConfirmedPreview] = useState<string | null>(null);
  const scheduleDateTimeInputRef = useRef<HTMLInputElement>(null);

  // Fila de Agendamentos (Queue Drawer & Edição)
  const [showQueueDrawer, setShowQueueDrawer] = useState(false);
  // Relógio da fila: acertado ao abrir a gaveta e atualizado a cada minuto enquanto ela está aberta.
  // Começa nulo porque o export estático do Next não aceita `new Date()` no prerender.
  const [queueNow, setQueueNow] = useState<Date | null>(null);
  useEffect(() => {
    if (!showQueueDrawer) return;
    const timer = setInterval(() => setQueueNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, [showQueueDrawer]);
  const [scheduledQueue, setScheduledQueue] = useState<ScheduledBroadcast[]>([]);
  const [broadcastHistory, setBroadcastHistory] = useState<BroadcastHistoryItem[]>([]);
  const [isLoadingQueue, setIsLoadingQueue] = useState(false);
  const [editingBroadcast, setEditingBroadcast] = useState<ScheduledBroadcast | null>(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editText, setEditText] = useState("");
  const [editButtonText, setEditButtonText] = useState("");
  const [editButtonUrl, setEditButtonUrl] = useState("");
  const [editScheduledAtInput, setEditScheduledAtInput] = useState("");
  const [editScheduleConfirmedPreview, setEditScheduleConfirmedPreview] = useState<string | null>(null);
  const editDateTimeInputRef = useRef<HTMLInputElement>(null);
  const [isUpdatingScheduled, setIsUpdatingScheduled] = useState(false);
  const [actionInProgressId, setActionInProgressId] = useState<string | null>(null);

  // Status de envio e Upload Progress
  const [isSending, setIsSending] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadPhase, setUploadPhase] = useState<"uploading" | "transmitting" | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const activeXhrRef = useRef<XMLHttpRequest | null>(null);

  // Modal de Adicionar Perfil
  const [showAddProfileModal, setShowAddProfileModal] = useState(false);
  const [newProfileName, setNewProfileName] = useState("");
  const [newBotToken, setNewBotToken] = useState("");
  const [isCreatingProfile, setIsCreatingProfile] = useState(false);

  // Modal de Editar Perfil
  const [showEditProfileModal, setShowEditProfileModal] = useState(false);
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null);
  const [editProfileName, setEditProfileName] = useState("");
  const [editProfileBotToken, setEditProfileBotToken] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);

  // Modal de Excluir Perfil
  const [showDeleteProfileModal, setShowDeleteProfileModal] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState<Profile | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const dismissConfirm = useCallback(() => setPendingConfirm(null), []);
  const [isDeletingProfile, setIsDeletingProfile] = useState(false);
  const [affectedBroadcasts, setAffectedBroadcasts] = useState<AffectedBroadcastsResponse | null>(null);

  const renderAffectedItemsList = (items: AffectedBroadcastItem[]) => {
    const visible = items.slice(0, 5);
    const remaining = items.length - visible.length;
    return (
      <ul className="mt-1.5 space-y-1 text-[11px] text-gray-300">
        {visible.map((item) => {
          const dt = item.scheduled_at
            ? new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(
                new Date(item.scheduled_at)
              )
            : "Sem data";
          return (
            <li key={item.id} className="truncate">
              • <span className="font-mono text-[#71aaeb]">{dt}</span> —{" "}
              {item.text_preview || "Mensagem sem texto"}
            </li>
          );
        })}
        {remaining > 0 && <li className="text-gray-400 italic">e mais {remaining}</li>}
      </ul>
    );
  };

  // Metadados de Vídeo (HTML5 Video Element)
  const [videoMetadata, setVideoMetadata] = useState<{
    duration: number;
    width: number;
    height: number;
  } | null>(null);
  const [videoThumbnailBlob, setVideoThumbnailBlob] = useState<Blob | null>(null);

  // Modal de Adicionar Canal
  const [showAddChannelModal, setShowAddChannelModal] = useState(false);
  const [newChannelTitle, setNewChannelTitle] = useState("");
  const [newChannelChatId, setNewChannelChatId] = useState("");
  const [isCreatingChannel, setIsCreatingChannel] = useState(false);
  const pendingChannelChatIdsRef = useRef<Set<string>>(new Set());

  // Modal de Editar Canal
  const [showEditChannelModal, setShowEditChannelModal] = useState(false);
  const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
  const [editChannelTitle, setEditChannelTitle] = useState("");
  const [editChannelChatId, setEditChannelChatId] = useState("");
  const [isSavingChannel, setIsSavingChannel] = useState(false);

  // Modal de Excluir Canal
  const [showDeleteChannelModal, setShowDeleteChannelModal] = useState(false);
  const [deletingChannel, setDeletingChannel] = useState<Channel | null>(null);
  const [isDeletingChannel, setIsDeletingChannel] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const sendAbortControllerRef = useRef<AbortController | null>(null);
  const isSubmittingRef = useRef<boolean>(false);
  const lastSubmitSignatureRef = useRef<{ signature: string; timestamp: number } | null>(null);
  const TELEGRAM_MAX_STANDARD_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB
  const DEBOUNCE_WINDOW_MS = 3000; // 3 segundos anti-duplo-disparo idêntico

  const formatFileSize = (bytes: number) => {
    if (bytes >= 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    return `${(bytes / 1024).toFixed(1)} KB`;
  };

  const toLocalDateTimeParts = (d: Date) => {
    const pad = (n: number) => String(n).padStart(2, "0");
    const datePart = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const timePart = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const combined = `${datePart}T${timePart}`;
    const formatted = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} às ${timePart}`;
    return { datePart, timePart, combined, formatted };
  };

  const applyScheduleDateTime = (d: Date, isEdit = false) => {
    const { combined, formatted } = toLocalDateTimeParts(d);
    if (isEdit) {
      setEditScheduledAtInput(combined);
      setEditScheduleConfirmedPreview(formatted);
      editDateTimeInputRef.current?.blur();
    } else {
      setScheduledAtInput(combined);
      setScheduleConfirmedPreview(formatted);
      scheduleDateTimeInputRef.current?.blur();
    }
  };

  const handleQuickPreset = (preset: "5m" | "15m" | "1h" | "tomorrow12", isEdit = false) => {
    const now = new Date();
    let target: Date;
    if (preset === "5m") {
      target = new Date(now.getTime() + 5 * 60 * 1000);
    } else if (preset === "15m") {
      target = new Date(now.getTime() + 15 * 60 * 1000);
    } else if (preset === "1h") {
      target = new Date(now.getTime() + 60 * 60 * 1000);
    } else {
      target = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 12, 0, 0);
    }
    applyScheduleDateTime(target, isEdit);
  };

  const handleConfirmDateTimeSelection = (isEdit = false) => {
    const raw = isEdit ? editScheduledAtInput : scheduledAtInput;
    if (!raw) {
      applyScheduleDateTime(new Date(Date.now() + 10 * 60 * 1000), isEdit);
      return;
    }
    const parsed = new Date(raw);
    if (!isNaN(parsed.getTime())) {
      applyScheduleDateTime(parsed, isEdit);
    }
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };

  const handleAbortSend = () => {
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
      progressIntervalRef.current = null;
    }
    setTelegramProgress(null);
    if (activeXhrRef.current) {
      try {
        activeXhrRef.current.abort();
      } catch {}
      activeXhrRef.current = null;
    }
    if (sendAbortControllerRef.current) {
      sendAbortControllerRef.current.abort();
      sendAbortControllerRef.current = null;
    }
    setIsSending(false);
    setUploadProgress(null);
    setUploadPhase(null);
  };

  // Carregar Perfis
  const fetchProfiles = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/profiles`);
      if (res.ok) {
        const data = await res.json();
        setProfiles(data);
        if (data.length > 0) {
          setSelectedProfile((prev) => prev || data[0]);
        }
      }
    } catch {
      // Backend offline ou ainda não iniciado
    }
  };

  useEffect(() => {
    let ignore = false;
    async function load() {
      try {
        const [res, configRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/profiles`).catch(() => null),
          fetch(`${API_BASE_URL}/api/v1/system/telegram-api-config`).catch(() => null),
        ]);
        if (res && res.ok && !ignore) {
          const data = await res.json();
          setProfiles(data);
          if (data.length > 0) {
            setSelectedProfile((prev) => prev || data[0]);
          }
        }
        if (configRes && configRes.ok && !ignore) {
          const configData: TelegramApiConfigResponse = await configRes.json();
          setTelegramApiConfig(configData);
          if (configData.api_id) {
            setApiIdInput(configData.api_id);
          }
        }
      } catch {
        // Backend ainda não iniciado
      }
    }
    load();
    return () => {
      ignore = true;
    };
  }, []);

  const handleSaveTelegramApiConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSavingTelegramApi) return;
    setIsSavingTelegramApi(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/system/telegram-api-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_id: apiIdInput.trim(),
          api_hash: apiHashInput.trim(),
        }),
      });
      if (res.ok) {
        const data: TelegramApiConfigResponse = await res.json();
        setTelegramApiConfig(data);
        setShowTelegramApiModal(false);
        showToast(
          data.configured
            ? "Credenciais salvas! Servidor local ativado (uploads até 2 GB)."
            : "Configurações atualizadas.",
          "success",
        );
      } else {
        const err = await res.json().catch(() => null);
        showToast(extractApiError(err, "Erro ao salvar credenciais"), "error");
      }
    } catch {
      showToast("Falha de conexão com a API", "error");
    } finally {
      setIsSavingTelegramApi(false);
    }
  };

  const formatChannelDeliveryList = useCallback(
    (results?: ChannelDeliveryResult[] | null): string => {
      if (!results || results.length === 0) return "";
      return results
        .map((r) => {
          const channelName = channels.find((c) => c.chat_id === r.chat_id)?.title || r.chat_id;
          if (r.delivered) {
            return `${channelName} ✓`;
          }
          return `${channelName} ✗ ${formatDeliveryFailureReason(r.failure_category, r.detail)}`;
        })
        .join(" · ");
    },
    [channels]
  );

  // Carregar Fila de Agendamentos do Perfil Selecionado
  const fetchScheduledQueue = useCallback(async (profileId?: string) => {
    const targetProfileId = profileId || selectedProfile?.id;
    if (!targetProfileId) return;
    setIsLoadingQueue(true);
    try {
      const [res, histRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/profiles/${targetProfileId}/scheduled-broadcasts`).catch(() => null),
        fetch(`${API_BASE_URL}/api/v1/profiles/${targetProfileId}/broadcasts`).catch(() => null),
      ]);
      if (res && res.ok) {
        const data = await res.json();
        setScheduledQueue(data);
      } else {
        setScheduledQueue([]);
      }
      if (histRes && histRes.ok) {
        const histData: BroadcastHistoryItem[] = await histRes.json();
        setBroadcastHistory(
          Array.isArray(histData)
            ? histData.filter((b) =>
                ["COMPLETED", "PARTIALLY_COMPLETED", "FAILED"].includes(b.status)
              )
            : []
        );
      } else {
        setBroadcastHistory([]);
      }
    } catch {
      // Backend offline ou erro inesperado
      setScheduledQueue([]);
      setBroadcastHistory([]);
    } finally {
      setIsLoadingQueue(false);
    }
  }, [selectedProfile?.id]);

  // Carregar Canais e Fila do Perfil Selecionado
  useEffect(() => {
    let ignore = false;
    async function loadChannelsAndQueue() {
      if (!selectedProfile) {
        if (!ignore) {
          setChannels([]);
          setScheduledQueue([]);
        }
        return;
      }

      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/profiles/${selectedProfile.id}/channels`);
        if (res.ok && !ignore) {
          const data: Channel[] = await res.json();
          setChannels(data);
          // Por padrão seleciona todos os canais
          setSelectedChannelIds(data.map((c) => c.chat_id));
        } else if (!ignore) {
          setChannels([]);
        }
      } catch {
        if (!ignore) setChannels([]);
      }

      if (!ignore) {
        await fetchScheduledQueue(selectedProfile.id);
      }
    }
    loadChannelsAndQueue();
    return () => {
      ignore = true;
    };
  }, [selectedProfile, fetchScheduledQueue]);

  // Cleanup de Blob URL de prévia de mídia para evitar memory leaks
  useEffect(() => {
    return () => {
      if (mediaPreviewUrl) {
        URL.revokeObjectURL(mediaPreviewUrl);
      }
    };
  }, [mediaPreviewUrl]);

  // Manipulação de Mídia
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.size > TELEGRAM_MAX_STANDARD_SIZE_BYTES && !telegramApiConfig?.configured) {
        setShowTelegramApiModal(true);
      }
      if (mediaPreviewUrl) URL.revokeObjectURL(mediaPreviewUrl);
      setMediaFile(file);
      setMediaPreviewUrl(URL.createObjectURL(file));
      setExistingMediaRemoved(false);

      const isVideo =
        file.type.toLowerCase().startsWith("video/") ||
        /\.(mp4|mov|avi|mkv|webm)$/i.test(file.name);

      if (isVideo) {
        const video = document.createElement("video");
        video.preload = "metadata";
        video.muted = true;
        video.playsInline = true;
        const tempBlobUrl = URL.createObjectURL(file);

        let metadataCaptured = false;
        const handleLoaded = () => {
          if (metadataCaptured) return;
          metadataCaptured = true;
          const duration = Math.round(video.duration) || 0;
          const width = video.videoWidth || 0;
          const height = video.videoHeight || 0;
          setVideoMetadata({ duration, width, height });
          video.currentTime = Math.min(1.0, video.duration / 2 || 0);
        };

        video.onloadedmetadata = handleLoaded;
        video.onloadeddata = handleLoaded;

        video.onseeked = () => {
          try {
            if (video.videoWidth > 0 && video.videoHeight > 0) {
              const duration = Math.round(video.duration) || 0;
              const width = video.videoWidth;
              const height = video.videoHeight;
              setVideoMetadata({ duration, width, height });

              const aspect = (video.videoWidth || 16) / (video.videoHeight || 9);
              let thumbW = 320;
              let thumbH = Math.round(320 / aspect);
              if (thumbH > 320) {
                thumbH = 320;
                thumbW = Math.round(320 * aspect);
              }
              const canvas = document.createElement("canvas");
              canvas.width = Math.max(1, thumbW);
              canvas.height = Math.max(1, thumbH);
              const ctx = canvas.getContext("2d");
              if (ctx) {
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                canvas.toBlob(
                  (blob) => {
                    if (blob) {
                      setVideoThumbnailBlob(blob);
                    }
                    URL.revokeObjectURL(tempBlobUrl);
                  },
                  "image/jpeg",
                  0.85
                );
                return;
              }
            }
          } catch (err) {
            console.error("Erro ao gerar thumbnail no canvas:", err);
          }
          URL.revokeObjectURL(tempBlobUrl);
        };

        video.onerror = () => {
          setVideoMetadata(null);
          setVideoThumbnailBlob(null);
          URL.revokeObjectURL(tempBlobUrl);
        };
        video.src = tempBlobUrl;
      } else {
        setVideoMetadata(null);
        setVideoThumbnailBlob(null);
      }
    }
  };

  const removeMedia = () => {
    setMediaFile(null);
    setVideoMetadata(null);
    setVideoThumbnailBlob(null);
    if (mediaPreviewUrl) URL.revokeObjectURL(mediaPreviewUrl);
    setMediaPreviewUrl(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (existingEditingMedia) {
      setExistingMediaRemoved(true);
    }
  };

  const clearComposerIfUnmodified = (
    sentText: string,
    sentFile: File | null,
    sentBtnText: string,
    sentBtnUrl: string
  ) => {
    setText((prev) => (prev === sentText ? "" : prev));
    setButtonText((prev) => (prev === sentBtnText ? "" : prev));
    setButtonUrl((prev) => (prev === sentBtnUrl ? "" : prev));
    setMediaFile((prevFile) => {
      if (prevFile === sentFile) {
        if (mediaPreviewUrl) URL.revokeObjectURL(mediaPreviewUrl);
        setMediaPreviewUrl(null);
        setVideoMetadata(null);
        setVideoThumbnailBlob(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
        return null;
      }
      return prevFile;
    });
  };

  const isImageMedia = (file: File | null) => {
    if (!file) return false;
    if (file.type && file.type.toLowerCase().startsWith("image/")) return true;
    const ext = file.name.split(".").pop()?.toLowerCase();
    const imageExtensions = [
      "jpg",
      "jpeg",
      "png",
      "webp",
      "gif",
      "bmp",
      "svg",
      "ico",
      "jfif",
      "pjpeg",
      "pjp",
      "avif",
      "tiff",
      "tif",
    ];
    return imageExtensions.includes(ext || "");
  };

  // Handlers do Recurso 1: Botão Físico Abaixo da Mensagem (Inline Keyboard)
  const handleOpenButtonModal = () => {
    setTempButtonText(buttonText);
    setTempButtonUrl(buttonUrl);
    setShowButtonModal(true);
  };

  const handleSaveButtonModal = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    let cleanUrl = tempButtonUrl.trim();
    if (cleanUrl && !/^https?:\/\//i.test(cleanUrl)) {
      cleanUrl = `https://${cleanUrl}`;
    }
    setButtonText(tempButtonText.trim());
    setButtonUrl(cleanUrl);
    setShowButtonModal(false);
  };

  const handleRemoveButtonModal = () => {
    setButtonText("");
    setButtonUrl("");
    setTempButtonText("");
    setTempButtonUrl("");
    setShowButtonModal(false);
  };

  const handleCancelButtonModal = () => {
    setShowButtonModal(false);
  };

  // Renderizador impecável de Links HTML e texto para o Balão do Telegram (Live Preview)
  const renderFormattedMessage = (rawText: string) => renderTelegramHtmlPreview(rawText);

  // Envio ou Agendamento do Broadcast
  const handleSendBroadcast = async (scheduleDateIso?: string) => {
    // 1. Lock síncrono imediato contra duplo clique antes do re-render do React
    if (isSubmittingRef.current) {
      return;
    }

    if (composerEditing) {
      showToast("Você está editando um agendamento. Use Agendar para salvar ou saia do modo edição.", "info");
      return;
    }

    if (!selectedProfile) {
      setFeedback({ type: "error", message: "Selecione um perfil!" });
      return;
    }
    if (selectedChannelIds.length === 0) {
      setFeedback({ type: "error", message: "Selecione pelo menos um canal de destino!" });
      return;
    }
    if (!text.trim() && !mediaFile) {
      setFeedback({ type: "error", message: "Escreva uma mensagem ou anexe uma mídia!" });
      return;
    }

    // 2. Debounce temporal contra reenvio acidental do mesmo payload em janela curta (3s)
    const payloadSignature = JSON.stringify({
      profileId: selectedProfile.id,
      channels: [...selectedChannelIds].sort(),
      text: text.trim(),
      mediaName: mediaFile?.name || null,
      mediaSize: mediaFile?.size || 0,
      buttonText: buttonText.trim(),
      buttonUrl: buttonUrl.trim(),
      scheduleDateIso: scheduleDateIso || null,
    });
    const now = Date.now();
    if (
      lastSubmitSignatureRef.current &&
      lastSubmitSignatureRef.current.signature === payloadSignature &&
      now - lastSubmitSignatureRef.current.timestamp < DEBOUNCE_WINDOW_MS
    ) {
      return;
    }

    isSubmittingRef.current = true;
    lastSubmitSignatureRef.current = { signature: payloadSignature, timestamp: now };

    // Captura snapshot dos dados que estão sendo enviados no momento do clique
    const currentProfileId = selectedProfile.id;
    const currentText = text;
    const currentMediaFile = mediaFile;
    const currentButtonText = buttonText;
    const currentButtonUrl = buttonUrl;
    const currentChannelIds = [...selectedChannelIds];

    setIsSending(true);
    setFeedback(null);
    if (currentMediaFile) {
      setUploadProgress(0);
      setUploadPhase("uploading");
    } else {
      setUploadProgress(null);
      setUploadPhase(null);
    }

    const abortController = new AbortController();
    sendAbortControllerRef.current = abortController;

    const trackingId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : "track_" + Date.now();

    const formData = new FormData();
    formData.append("tracking_id", trackingId);
    formData.append("profile_id", currentProfileId);
    formData.append("target_channel_ids", JSON.stringify(currentChannelIds));
    formData.append("text", currentText);
    if (currentButtonText && currentButtonUrl) {
      formData.append("button_text", currentButtonText);
      formData.append("button_url", currentButtonUrl);
    }
    if (currentMediaFile) {
      formData.append("media_file", currentMediaFile);
      if (videoMetadata) {
        formData.append("video_duration", String(Math.round(videoMetadata.duration)));
        formData.append("video_width", String(Math.round(videoMetadata.width)));
        formData.append("video_height", String(Math.round(videoMetadata.height)));
      }
      if (videoThumbnailBlob) {
        formData.append("thumbnail_file", videoThumbnailBlob, "thumb.jpg");
      }
    }
    if (scheduleDateIso) {
      formData.append("scheduled_at", scheduleDateIso);
    }

    try {
      const result: BroadcastResponse = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        activeXhrRef.current = xhr;

        const onAbort = () => {
          xhr.abort();
          reject(new DOMException("Upload cancelado pelo usuário", "AbortError"));
        };
        abortController.signal.addEventListener("abort", onAbort);

        let pollingStarted = false;
        const startTelegramPolling = () => {
          if (pollingStarted) return;
          pollingStarted = true;
          setUploadProgress(100);
          setUploadPhase("transmitting");

          const pollProgress = async () => {
            try {
              const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/progress/${trackingId}`);
              if (res.ok) {
                const data: TelegramUploadProgress = await res.json();
                if (data && typeof data.percent === "number") {
                  setTelegramProgress(data);
                  if (data.status === "completed" || data.status === "failed") {
                    if (progressIntervalRef.current) {
                      clearInterval(progressIntervalRef.current);
                      progressIntervalRef.current = null;
                    }
                  }
                }
              }
            } catch {
              // Silencioso em caso de oscilação transitória
            }
          };

          pollProgress();
          progressIntervalRef.current = setInterval(pollProgress, 400);
        };

        if (xhr.upload) {
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable && event.total > 0) {
              const percent = Math.min(99, Math.round((event.loaded / event.total) * 100));
              setUploadProgress(percent);
              setUploadPhase("uploading");
            }
          };
          xhr.upload.onload = () => {
            startTelegramPolling();
          };
        }

        xhr.onload = () => {
          abortController.signal.removeEventListener("abort", onAbort);
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = null;
          }
          let data: unknown = null;
          try {
            data = JSON.parse(xhr.responseText);
          } catch {
            data = null;
          }
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve((data as BroadcastResponse | null) ?? { status: "SUCCESS" });
          } else {
            reject(new ApiHttpError(extractApiError(data, `Falha HTTP ${xhr.status}`), xhr.status));
          }
        };

        xhr.onerror = () => {
          abortController.signal.removeEventListener("abort", onAbort);
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = null;
          }
          reject(new Error("Erro de conexão com o servidor backend"));
        };

        xhr.onabort = () => {
          abortController.signal.removeEventListener("abort", onAbort);
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = null;
          }
          reject(new DOMException("Upload cancelado pelo usuário", "AbortError"));
        };

        xhr.open("POST", `${API_BASE_URL}/api/v1/broadcasts`);
        xhr.send(formData);
      });

      if (result?.status === "SCHEDULED" && result.scheduled_at) {
        setFeedback({
          type: "success",
          message: `Mensagem agendada com sucesso para ${new Date(result.scheduled_at).toLocaleString()}!`,
        });
        fetchScheduledQueue(currentProfileId);
        clearComposerIfUnmodified(currentText, currentMediaFile, currentButtonText, currentButtonUrl);
        setShowScheduleModal(false);
        setScheduledAtInput("");
        setScheduleConfirmedPreview(null);
      } else {
        const dispatchedCount = result?.dispatched_count ?? 0;
        const errorsList = Array.isArray(result?.errors) ? result.errors : [];
        const deliverySummary = formatChannelDeliveryList(result?.delivery_results);
        const hasFailedChannel = Array.isArray(result?.delivery_results)
          ? result.delivery_results.some((r) => !r.delivered)
          : false;
        const hasErrors = errorsList.length > 0 || hasFailedChannel;

        if (dispatchedCount === 0 || hasErrors) {
          lastSubmitSignatureRef.current = null;
          const errorDetails =
            deliverySummary ||
            (errorsList.length > 0
              ? errorsList.join(", ")
              : "Nenhum canal recebeu a mensagem (0 disparos concluídos).");
          const sizeHint =
            currentMediaFile && currentMediaFile.size > TELEGRAM_MAX_STANDARD_SIZE_BYTES
              ? ` (Arquivo com ${formatFileSize(currentMediaFile.size)}: verifique estabilidade da rede).`
              : "";

          setFeedback({
            type: "error",
            message:
              dispatchedCount > 0
                ? `Envio parcial (${dispatchedCount} enviado(s)): ${errorDetails}${sizeHint}`
                : `Falha no envio: ${errorDetails}${sizeHint}`,
          });
          fetchScheduledQueue(currentProfileId);
        } else {
          setFeedback({
            type: "success",
            message: `Disparado com sucesso para ${dispatchedCount} canal(is)!`,
          });
          fetchScheduledQueue(currentProfileId);
          clearComposerIfUnmodified(currentText, currentMediaFile, currentButtonText, currentButtonUrl);
          setShowScheduleModal(false);
          setScheduledAtInput("");
          setScheduleConfirmedPreview(null);
        }
      }
    } catch (err: unknown) {
      lastSubmitSignatureRef.current = null;
      if (err instanceof Error && (err.name === "AbortError" || err.message.includes("cancelado"))) {
        setFeedback({
          type: "error",
          message: "Envio cancelado pelo usuário. Sua mensagem e mídia foram mantidas no editor.",
        });
      } else if (err instanceof ApiHttpError) {
        setFeedback({ type: "error", message: `Falha no envio: ${err.message}` });
      } else {
        const sizeHint =
          currentMediaFile && currentMediaFile.size > TELEGRAM_MAX_STANDARD_SIZE_BYTES
            ? ` Verifique também se o arquivo (${formatFileSize(currentMediaFile.size)}) não excedeu o tempo limite de upload.`
            : "";
        setFeedback({
          type: "error",
          message: `Erro de conexão com o servidor backend.${sizeHint}`,
        });
      }
    } finally {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
      setTelegramProgress(null);
      sendAbortControllerRef.current = null;
      activeXhrRef.current = null;
      setIsSending(false);
      setUploadProgress(null);
      setUploadPhase(null);
      setTimeout(() => {
        isSubmittingRef.current = false;
      }, 300);
    }
  };

  const handleConfirmSchedule = (e: React.FormEvent) => {
    e.preventDefault();
    if (!scheduledAtInput) {
      setFeedback({ type: "error", message: "Selecione uma data e hora para o agendamento." });
      return;
    }
    const selectedDate = new Date(scheduledAtInput);
    if (isNaN(selectedDate.getTime())) {
      setFeedback({ type: "error", message: "Data e hora inválidas." });
      return;
    }
    if (selectedDate.getTime() <= Date.now() - 60000) {
      setFeedback({ type: "error", message: "A data de agendamento deve ser no futuro." });
      return;
    }
    if (composerEditing) {
      void saveComposerEdit(selectedDate.toISOString());
      return;
    }
    handleSendBroadcast(selectedDate.toISOString());
  };

  // Cancelar Mensagem Agendada
  const handleCancelScheduled = (broadcastId: string) => {
    setPendingConfirm({
      title: "Cancelar agendamento",
      message: "Tem certeza que deseja cancelar este agendamento? Os arquivos temporários serão descartados.",
      confirmLabel: "Cancelar agendamento",
      cancelLabel: "Voltar",
      destructive: true,
      onConfirm: () => {
        setPendingConfirm(null);
        void cancelScheduled(broadcastId);
      },
    });
  };

  const cancelScheduled = async (broadcastId: string) => {
    setActionInProgressId(broadcastId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${broadcastId}/cancel`, {
        method: "DELETE",
      });
      if (res.ok) {
        setFeedback({
          type: "success",
          message: "Agendamento cancelado com sucesso e recursos liberados!",
        });
        if (selectedProfile) {
          fetchScheduledQueue(selectedProfile.id);
        }
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({
          type: "error",
          message: extractApiError(err, "Falha ao cancelar agendamento"),
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Erro de conexão ao tentar cancelar agendamento",
      });
    } finally {
      setActionInProgressId(null);
    }
  };

  // Disparar Agora um Agendamento Expirado (MISFIRED)
  const handleDispatchMisfiredNow = async (broadcastId: string) => {
    setActionInProgressId(broadcastId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${broadcastId}/dispatch-now`, {
        method: "POST",
      });
      if (res.ok) {
        const result: BroadcastResponse = await res.json();
        const dispatchedCount = result?.dispatched_count ?? 0;
        const errorsList = Array.isArray(result?.errors) ? result.errors : [];
        const deliverySummary = formatChannelDeliveryList(result?.delivery_results);
        const hasFailedChannel = Array.isArray(result?.delivery_results)
          ? result.delivery_results.some((r) => !r.delivered)
          : false;
        if (dispatchedCount === 0 || errorsList.length > 0 || hasFailedChannel) {
          const details =
            deliverySummary || errorsList.join(", ") || "Nenhum canal recebeu a mensagem.";
          setFeedback({
            type: "error",
            message:
              dispatchedCount > 0
                ? `Envio parcial (${dispatchedCount} enviado(s)): ${details}`
                : `Falha no envio: ${details}`,
          });
        } else {
          setFeedback({
            type: "success",
            message: `Disparado com sucesso para ${dispatchedCount} canal(is)!`,
          });
        }
        if (selectedProfile) {
          fetchScheduledQueue(selectedProfile.id);
        }
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({
          type: "error",
          message: extractApiError(err, "Falha ao disparar agendamento"),
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Erro de conexão ao tentar disparar agendamento",
      });
    } finally {
      setActionInProgressId(null);
    }
  };

  // Abrir Modal de Edição de Agendamento
  const handleOpenEditScheduled = (item: ScheduledBroadcast) => {
    setEditingBroadcast(item);
    setEditText(item.text || "");
    setEditButtonText(item.button?.text || "");
    setEditButtonUrl(item.button?.url || "");
    // Formatar ISO para o input datetime-local e campos de data/hora no fuso local
    if (item.scheduled_at) {
      const d = new Date(item.scheduled_at);
      if (!isNaN(d.getTime()) && d.getTime() > Date.now()) {
        applyScheduleDateTime(d, true);
      } else {
        applyScheduleDateTime(new Date(Date.now() + 15 * 60 * 1000), true);
      }
    } else {
      setEditScheduledAtInput("");
      setEditScheduleConfirmedPreview(null);
    }
    setShowEditModal(true);
  };

  // Carregar Agendamento de Volta para o Compositor
  const handleLoadIntoComposer = (item: ScheduledBroadcast) => {
    if (text.trim() || mediaFile) {
      setPendingConfirm({
        title: "Substituir rascunho",
        message:
          "Você possui uma mensagem ou mídia preenchida no editor. Deseja substituir o texto pelo agendamento selecionado? (O arquivo de mídia anexado atual será mantido)",
        confirmLabel: "Substituir",
        cancelLabel: "Manter rascunho",
        onConfirm: () => {
          setPendingConfirm(null);
          void applyScheduledToComposer(item);
        },
      });
      return;
    }
    void applyScheduledToComposer(item);
  };

  const applyScheduledToComposer = async (item: ScheduledBroadcast) => {
    // "Carregar no Editor" edita o próprio agendamento, com trava no backend (#15).
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${item.id}/edit-lock`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        showToast(extractApiError(err, "Não foi possível abrir o agendamento para edição"), "error");
        return;
      }
    } catch {
      showToast("Erro de conexão ao abrir o agendamento para edição", "error");
      return;
    }
    setText(item.text || "");
    setButtonText(item.button?.text || "");
    setButtonUrl(item.button?.url || "");
    if (item.target_channel_ids && item.target_channel_ids.length > 0) {
      setSelectedChannelIds(item.target_channel_ids);
    }
    if (item.scheduled_at) {
      const d = new Date(item.scheduled_at);
      if (!isNaN(d.getTime())) applyScheduleDateTime(d, false);
    }
    // Mídia do agendamento (#18)
    if (item.media) {
      setExistingEditingMedia({
        mediaType: item.media.media_type,
        fileSize: item.media.file_size,
        url: `${API_BASE_URL}/api/v1/broadcasts/${item.id}/media`,
      });
      setExistingMediaRemoved(false);
      setMediaFile(null);
      if (mediaPreviewUrl) {
        URL.revokeObjectURL(mediaPreviewUrl);
        setMediaPreviewUrl(null);
      }
    } else {
      setExistingEditingMedia(null);
      setExistingMediaRemoved(false);
      setMediaFile(null);
      if (mediaPreviewUrl) {
        URL.revokeObjectURL(mediaPreviewUrl);
        setMediaPreviewUrl(null);
      }
    }
    setComposerEditing({ id: item.id, scheduledAt: item.scheduled_at });
    setShowQueueDrawer(false);
    setFeedback({
      type: "success",
      message: "Agendamento aberto no editor para edição.",
    });
  };

  const resetComposerAfterEdit = () => {
    setComposerEditing(null);
    setText("");
    setButtonText("");
    setButtonUrl("");
    setScheduledAtInput("");
    setScheduleConfirmedPreview(null);
    setExistingEditingMedia(null);
    setExistingMediaRemoved(false);
    setMediaFile(null);
    setVideoThumbnailBlob(null);
    setVideoMetadata(null);
    if (mediaPreviewUrl) {
      URL.revokeObjectURL(mediaPreviewUrl);
      setMediaPreviewUrl(null);
    }
  };

  // Sair do modo edição sem salvar: libera a trava; se o horário já passou, o backend cancela (#15).
  const handleExitComposerEdit = async () => {
    if (!composerEditing) return;
    const editingId = composerEditing.id;
    resetComposerAfterEdit();
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${editingId}/edit-lock`, { method: "DELETE" });
      const data: EditLockResponse | null = await res.json().catch(() => null);
      if (res.ok && data?.cancelled) {
        showToast("O horário passou durante a edição: o agendamento foi cancelado.", "info");
      }
    } catch {
      // Sem rede: a trava expira sozinha em ~90 s.
    }
    if (selectedProfile) fetchScheduledQueue(selectedProfile.id);
  };

  // Salvar o modo edição: PUT/DELETE na mídia (#18) e PATCH no mesmo agendamento (#15).
  const saveComposerEdit = async (scheduleDateIso: string) => {
    if (!composerEditing) return;
    if (selectedChannelIds.length === 0) {
      setFeedback({ type: "error", message: "Selecione pelo menos um canal de destino!" });
      return;
    }
    if ((buttonText && !buttonUrl) || (!buttonText && buttonUrl)) {
      showToast("Informe tanto o texto quanto a URL do botão, ou deixe ambos vazios.", "error");
      return;
    }
    try {
      if (mediaFile) {
        const formData = new FormData();
        formData.append("media_file", mediaFile);
        if (videoThumbnailBlob) {
          formData.append("thumbnail_file", videoThumbnailBlob, "thumb.jpg");
        }
        if (videoMetadata) {
          if (videoMetadata.duration) formData.append("video_duration", String(Math.round(videoMetadata.duration)));
          if (videoMetadata.width) formData.append("video_width", String(videoMetadata.width));
          if (videoMetadata.height) formData.append("video_height", String(videoMetadata.height));
        }
        const mediaRes = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${composerEditing.id}/media`, {
          method: "PUT",
          body: formData,
        });
        if (!mediaRes.ok) {
          const err = await mediaRes.json().catch(() => null);
          setFeedback({ type: "error", message: extractApiError(err, "Erro ao atualizar mídia do agendamento") });
          return;
        }
      } else if (existingMediaRemoved) {
        const mediaRes = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${composerEditing.id}/media`, {
          method: "DELETE",
        });
        if (!mediaRes.ok) {
          const err = await mediaRes.json().catch(() => null);
          setFeedback({ type: "error", message: extractApiError(err, "Erro ao remover mídia do agendamento") });
          return;
        }
      }

      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${composerEditing.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          scheduled_at: scheduleDateIso,
          target_channel_ids: selectedChannelIds,
          button_text: buttonText && buttonUrl ? buttonText : "",
          button_url: buttonText && buttonUrl ? buttonUrl : "",
        }),
      });
      if (res.ok) {
        setShowScheduleModal(false);
        resetComposerAfterEdit();
        setFeedback({ type: "success", message: "Agendamento atualizado com sucesso!" });
        if (selectedProfile) fetchScheduledQueue(selectedProfile.id);
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({ type: "error", message: extractApiError(err, "Erro ao atualizar agendamento") });
      }
    } catch {
      setFeedback({ type: "error", message: "Falha de conexão com o servidor" });
    }
  };

  // Salvar Edição do Agendamento
  const handleSaveEditScheduled = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingBroadcast) return;

    if (!editScheduledAtInput) {
      showToast("Selecione uma data e hora para o agendamento.", "error");
      return;
    }
    const selectedDate = new Date(editScheduledAtInput);
    if (isNaN(selectedDate.getTime())) {
      showToast("Data e hora inválidas.", "error");
      return;
    }
    if (selectedDate.getTime() <= Date.now() - 60000) {
      showToast("A data de reagendamento deve ser no futuro.", "error");
      return;
    }

    if ((editButtonText && !editButtonUrl) || (!editButtonText && editButtonUrl)) {
      showToast("Informe tanto o texto quanto a URL do botão, ou deixe ambos vazios.", "error");
      return;
    }

    setIsUpdatingScheduled(true);
    try {
      const payload: Record<string, string> = {
        text: editText,
        scheduled_at: selectedDate.toISOString(),
      };
      if (editButtonText && editButtonUrl) {
        payload.button_text = editButtonText;
        payload.button_url = editButtonUrl;
      } else {
        payload.button_text = "";
        payload.button_url = "";
      }

      const res = await fetch(`${API_BASE_URL}/api/v1/broadcasts/${editingBroadcast.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        setShowEditModal(false);
        setEditingBroadcast(null);
        setFeedback({
          type: "success",
          message: "Agendamento atualizado com sucesso!",
        });
        if (selectedProfile) {
          fetchScheduledQueue(selectedProfile.id);
        }
      } else {
        const err = await res.json().catch(() => null);
        showToast(extractApiError(err, "Erro ao atualizar agendamento"), "error");
      }
    } catch {
      showToast("Falha de conexão com o servidor", "error");
    } finally {
      setIsUpdatingScheduled(false);
    }
  };

  // Criar Perfil
  const handleCreateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreatingProfile) return;
    setIsCreatingProfile(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newProfileName, bot_token: newBotToken }),
      });
      if (res.ok) {
        setShowAddProfileModal(false);
        setNewProfileName("");
        setNewBotToken("");
        fetchProfiles();
      } else {
        const err = await res.json();
        showToast(extractApiError(err, "Erro ao adicionar perfil"), "error");
      }
    } catch {
      showToast("Falha de conexão com a API", "error");
    } finally {
      setIsCreatingProfile(false);
    }
  };

  // Abrir Modal de Edição de Perfil
  const handleOpenEditProfile = (profile: Profile) => {
    setEditingProfile(profile);
    setEditProfileName(profile.name);
    setEditProfileBotToken("");
    setShowEditProfileModal(true);
  };

  // Salvar Edição do Perfil
  const handleSaveEditProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProfile) return;

    if (!editProfileName.trim()) {
      setFeedback({ type: "error", message: "O nome do perfil não pode estar vazio." });
      return;
    }
    if (!editProfileBotToken.trim()) {
      setFeedback({ type: "error", message: "Informe o token do Bot (@BotFather) para validação." });
      return;
    }

    setIsSavingProfile(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/profiles/${editingProfile.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: editProfileName.trim(),
          bot_token: editProfileBotToken.trim(),
          avatar_url: editingProfile.avatar_url || "",
        }),
      });

      if (res.ok) {
        const updated: Profile = await res.json();
        setFeedback({
          type: "success",
          message: `Perfil "${updated.name}" atualizada com sucesso!`,
        });
        setShowEditProfileModal(false);
        setEditingProfile(null);
        setEditProfileName("");
        setEditProfileBotToken("");
        await fetchProfiles();
        if (selectedProfile?.id === editingProfile.id) {
          setSelectedProfile(updated);
        }
      } else {
        const err = await res.json().catch(() => null);
        const errorMsg = extractApiError(err, "Erro ao atualizar perfil");
        setFeedback({
          type: "error",
          message: `Falha na validação do bot: ${errorMsg}`,
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Falha de conexão com a API ao tentar atualizar perfil.",
      });
    } finally {
      setIsSavingProfile(false);
    }
  };

  // Abrir Modal de Exclusão de Perfil
  const handleOpenDeleteProfile = (profile: Profile) => {
    setDeletingProfile(profile);
    setAffectedBroadcasts(null);
    setShowDeleteProfileModal(true);
    fetch(`${API_BASE_URL}/api/v1/profiles/${profile.id}/affected-broadcasts`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: AffectedBroadcastsResponse | null) => {
        if (data) setAffectedBroadcasts(data);
      })
      .catch(() => null);
  };

  // Confirmar Exclusão do Perfil
  const handleConfirmDeleteProfile = async () => {
    if (!deletingProfile) return;

    setIsDeletingProfile(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/profiles/${deletingProfile.id}`, {
        method: "DELETE",
      });

      if (res.ok) {
        setFeedback({
          type: "success",
          message: `Perfil "${deletingProfile.name}" excluída com sucesso!`,
        });
        const deletedId = deletingProfile.id;
        setShowDeleteProfileModal(false);
        setDeletingProfile(null);

        // Atualizar lista e desselecionar/reajustar perfil selecionado
        try {
          const listRes = await fetch(`${API_BASE_URL}/api/v1/profiles`);
          if (listRes.ok) {
            const data: Profile[] = await listRes.json();
            setProfiles(data);
            if (selectedProfile?.id === deletedId) {
              setSelectedProfile(data.length > 0 ? data[0] : null);
            }
          } else {
            setProfiles((prev) => prev.filter((m) => m.id !== deletedId));
            if (selectedProfile?.id === deletedId) {
              setSelectedProfile(null);
            }
          }
        } catch {
          setProfiles((prev) => prev.filter((m) => m.id !== deletedId));
          if (selectedProfile?.id === deletedId) {
            setSelectedProfile(null);
          }
        }
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({
          type: "error",
          message: extractApiError(err, "Erro ao excluir perfil"),
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Falha de conexão com a API ao tentar excluir perfil.",
      });
    } finally {
      setIsDeletingProfile(false);
    }
  };

  // Criar Canal
  // Vincula um canal à perfil selecionado e recarrega a lista; usado pelo formulário e pela busca de canais do bot.
  const addChannel = async (title: string, chatId: string): Promise<boolean> => {
    if (!selectedProfile) return false;
    const cleanId = chatId.trim();
    if (!cleanId) return false;
    if (pendingChannelChatIdsRef.current.has(cleanId)) return false;
    pendingChannelChatIdsRef.current.add(cleanId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/profiles/${selectedProfile.id}/channels`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), chat_id: cleanId }),
      });
      if (!res.ok) {
        if (res.status === 409) {
          showToast("Este canal já está cadastrado para este perfil.", "error");
          return false;
        }
        const err = await res.json();
        showToast(extractApiError(err, "Erro ao adicionar canal"), "error");
        return false;
      }
      const chRes = await fetch(`${API_BASE_URL}/api/v1/profiles/${selectedProfile.id}/channels`);
      const data = await chRes.json();
      setChannels(data);
      setSelectedChannelIds(data.map((c: Channel) => c.chat_id));
      return true;
    } catch {
      showToast("Falha de conexão com a API", "error");
      return false;
    } finally {
      pendingChannelChatIdsRef.current.delete(cleanId);
    }
  };

  const handleCreateChannel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreatingChannel) return;
    setIsCreatingChannel(true);
    try {
      if (await addChannel(newChannelTitle, newChannelChatId)) {
        setShowAddChannelModal(false);
        setNewChannelTitle("");
        setNewChannelChatId("");
      }
    } finally {
      setIsCreatingChannel(false);
    }
  };

  const handleAddDiscoveredChat = async (chat: DiscoveredChat): Promise<boolean> => {
    const added = await addChannel(chat.title || chat.chat_id, chat.chat_id);
    if (added) showToast(`Canal "${chat.title || chat.chat_id}" vinculado.`, "success");
    return added;
  };

  // Abrir Modal de Edição de Canal
  const handleOpenEditChannel = (channel: Channel) => {
    setEditingChannel(channel);
    setEditChannelTitle(channel.title);
    setEditChannelChatId(channel.chat_id);
    setAffectedBroadcasts(null);
    setShowEditChannelModal(true);
    fetch(`${API_BASE_URL}/api/v1/channels/${channel.id}/affected-broadcasts`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: AffectedBroadcastsResponse | null) => {
        if (data) setAffectedBroadcasts(data);
      })
      .catch(() => null);
  };

  // Salvar Edição do Canal
  const handleSaveEditChannel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingChannel || !selectedProfile) return;

    if (!editChannelTitle.trim()) {
      setFeedback({ type: "error", message: "O título do canal não pode estar vazio." });
      return;
    }
    if (!editChannelChatId.trim()) {
      setFeedback({ type: "error", message: "O Chat ID do canal não pode estar vazio." });
      return;
    }

    setIsSavingChannel(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/channels/${editingChannel.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: editChannelTitle.trim(),
          telegram_channel_id: editChannelChatId.trim(),
        }),
      });

      if (res.ok) {
        setFeedback({
          type: "success",
          message: `Canal "${editChannelTitle.trim()}" atualizado com sucesso!`,
        });
        const oldChatId = editingChannel.chat_id;
        const newChatId = editChannelChatId.trim();
        setShowEditChannelModal(false);
        setEditingChannel(null);
        setEditChannelTitle("");
        setEditChannelChatId("");

        // Recarregar canais do perfil
        const chRes = await fetch(`${API_BASE_URL}/api/v1/profiles/${selectedProfile.id}/channels`);
        if (chRes.ok) {
          const data: Channel[] = await chRes.json();
          setChannels(data);
        }
        setSelectedChannelIds((prev) =>
          prev.map((id) => (id === oldChatId ? newChatId : id))
        );
        if (oldChatId !== newChatId) {
          await fetchScheduledQueue(selectedProfile.id);
        }
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({
          type: "error",
          message: extractApiError(err, "Erro ao atualizar canal"),
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Falha de conexão com a API ao tentar atualizar canal.",
      });
    } finally {
      setIsSavingChannel(false);
    }
  };

  // Abrir Modal de Exclusão de Canal
  const handleOpenDeleteChannel = (channel: Channel) => {
    setDeletingChannel(channel);
    setAffectedBroadcasts(null);
    setShowDeleteChannelModal(true);
    fetch(`${API_BASE_URL}/api/v1/channels/${channel.id}/affected-broadcasts`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: AffectedBroadcastsResponse | null) => {
        if (data) setAffectedBroadcasts(data);
      })
      .catch(() => null);
  };

  // Confirmar Exclusão de Canal
  const handleConfirmDeleteChannel = async () => {
    if (!deletingChannel || !selectedProfile) return;

    setIsDeletingChannel(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/channels/${deletingChannel.id}`, {
        method: "DELETE",
      });

      if (res.ok) {
        setFeedback({
          type: "success",
          message: `Canal "${deletingChannel.title}" removido com sucesso!`,
        });
        const deletedChatId = deletingChannel.chat_id;
        const deletedId = deletingChannel.id;
        setShowDeleteChannelModal(false);
        setDeletingChannel(null);

        // Recarregar canais do perfil
        const chRes = await fetch(`${API_BASE_URL}/api/v1/profiles/${selectedProfile.id}/channels`);
        if (chRes.ok) {
          const data: Channel[] = await chRes.json();
          setChannels(data);
        } else {
          setChannels((prev) => prev.filter((c) => c.id !== deletedId));
        }
        setSelectedChannelIds((prev) => prev.filter((id) => id !== deletedChatId));
        await fetchScheduledQueue(selectedProfile.id);
      } else {
        const err = await res.json().catch(() => null);
        setFeedback({
          type: "error",
          message: extractApiError(err, "Erro ao excluir canal"),
        });
      }
    } catch {
      setFeedback({
        type: "error",
        message: "Falha de conexão com a API ao tentar excluir canal.",
      });
    } finally {
      setIsDeletingChannel(false);
    }
  };

  const handleOpenDataDir = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/system/open-data-dir`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Pasta de dados: ${data.path}`, "info");
      } else {
        const err = await res.json().catch(() => null);
        showToast(extractApiError(err, "Erro ao abrir pasta de dados"), "error");
      }
    } catch {
      showToast("Erro de conexão com o servidor", "error");
    }
  };

  return (
    <div className="flex h-screen bg-[#0e1621] text-white overflow-hidden font-sans">
      {/* TOAST FLUTUANTE NÃO BLOQUEANTE */}
      {toast && (
        <aside
          role="status"
          aria-live="polite"
          className={`fixed bottom-6 right-6 z-[120] max-w-sm w-full shadow-2xl rounded-xl p-4 border flex items-start justify-between gap-3 animate-in fade-in slide-in-from-bottom-2 duration-200 ${
            toast.type === "success"
              ? "bg-[#132a1c] text-green-200 border-green-600/80 shadow-green-950/40"
              : toast.type === "error"
              ? "bg-[#2c1518] text-red-200 border-red-600/80 shadow-red-950/40"
              : "bg-[#182533] text-blue-200 border-blue-600/80 shadow-blue-950/40"
          }`}
        >
          <div className="flex items-start gap-2.5 text-xs leading-relaxed">
            {toast.type === "success" ? (
              <Check className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            ) : toast.type === "error" ? (
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            ) : (
              <Info className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
            )}
            <div>
              <strong className="block font-semibold mb-0.5 text-white">
                {toast.type === "success" ? "Sucesso" : toast.type === "error" ? "Atenção" : "Informação"}
              </strong>
              <span>{toast.message}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setToast(null)}
            className="text-gray-400 hover:text-white transition p-1 text-sm font-bold leading-none cursor-pointer"
            title="Fechar"
            aria-label="Fechar notificação"
          >
            ✕
          </button>
        </aside>
      )}

      {/* BANNER / TOAST FLUTUANTE FIXO NO TOPO DA TELA */}
      {feedback && (
        <div
          role="alert"
          className={`fixed top-4 right-4 z-[100] max-w-md w-full shadow-2xl rounded-xl p-4 border flex items-start justify-between gap-3 animate-in fade-in slide-in-from-top-2 duration-200 ${
            feedback.type === "success"
              ? "bg-[#132a1c] text-green-200 border-green-600/80"
              : "bg-[#2c1518] text-red-200 border-red-600/80"
          }`}
        >
          <div className="flex items-start gap-2.5 text-xs leading-relaxed">
            {feedback.type === "success" ? (
              <Check className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            ) : (
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            )}
            <div>
              <strong className="block font-semibold mb-0.5 text-white">
                {feedback.type === "success" ? "Operação Concluída" : "Atenção — Ocorreu um Erro"}
              </strong>
              <span>{feedback.message}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className={`px-2.5 py-1 rounded-lg text-xs font-semibold shrink-0 transition ${
              feedback.type === "success"
                ? "bg-green-800/70 hover:bg-green-700 text-white"
                : "bg-red-800/70 hover:bg-red-700 text-white"
            }`}
          >
            OK / Fechar
          </button>
        </div>
      )}

      {/* SIDEBAR ESQUERDA: LISTA DE PERFIS / BOTS */}
      <div className="w-80 border-r border-[#17212b] bg-[#17212b] flex flex-col">
        {/* Header da Sidebar */}
        <div className="p-4 border-b border-[#242f3d] flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Users className="w-6 h-6 text-[#5288c1]" />
            <h1 className="font-semibold text-lg tracking-wide">Auto-Send Profiles</h1>
          </div>
          <button
            onClick={() => setShowAddProfileModal(true)}
            className="p-1.5 rounded-full hover:bg-[#242f3d] text-[#5288c1] transition"
            title="Adicionar Novo Perfil"
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>

        {/* Lista de Perfis */}
        <div className="flex-1 overflow-y-auto divide-y divide-[#0e1621]/30">
          {profiles.length === 0 ? (
            <div className="p-6 text-center text-gray-400 text-sm">
              Nenhum perfil cadastrado.
              <br />
              Clique no <strong>+</strong> acima para adicionar.
            </div>
          ) : (
            profiles.map((m) => {
              const isSelected = selectedProfile?.id === m.id;
              return (
                <div
                  key={m.id}
                  onClick={() => setSelectedProfile(m)}
                  className={`flex items-center p-3.5 cursor-pointer transition group ${
                    isSelected ? "bg-[#2b5278]" : "hover:bg-[#202b36]"
                  }`}
                >
                  <div className="w-12 h-12 rounded-full bg-[#5288c1] flex items-center justify-center font-bold text-lg text-white mr-3 shrink-0">
                    {m.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-baseline">
                      <h3 className="font-medium text-sm text-gray-100 truncate">{m.name}</h3>
                      <span className="text-[11px] text-green-400 bg-green-950/60 px-1.5 py-0.5 rounded">
                        Ativa
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 truncate">@{m.bot_username || "bot"}</p>
                  </div>
                  {/* Botões de Ação no Card: Editar e Excluir */}
                  <div
                    className={`flex items-center space-x-1 ml-2 transition-opacity ${
                      isSelected ? "opacity-90 group-hover:opacity-100" : "opacity-0 group-hover:opacity-100"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenEditProfile(m);
                      }}
                      className="p-1.5 rounded hover:bg-[#17212b] text-gray-400 hover:text-[#71aaeb] transition"
                      title="Editar"
                    >
                      <Edit className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenDeleteProfile(m);
                      }}
                      className="p-1.5 rounded hover:bg-[#17212b] text-gray-400 hover:text-red-400 transition"
                      title="Excluir"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="p-3 border-t border-[#242f3d] flex flex-col gap-2">
          <button
            type="button"
            onClick={() => setShowTelegramApiModal(true)}
            className="w-full text-xs text-gray-300 hover:text-white bg-[#202b36] hover:bg-[#2b5278] px-3 py-2 rounded-lg transition flex items-center justify-between gap-2 cursor-pointer"
            title="Configurações Telegram API (Uploads até 2 GB)"
          >
            <div className="flex items-center gap-2 min-w-0">
              <Server className="w-3.5 h-3.5 text-[#5288c1] shrink-0" />
              <span className="truncate">Telegram API</span>
            </div>
            <span
              className={`text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0 ${
                telegramApiConfig?.configured
                  ? "bg-green-950/80 text-green-300 border border-green-600/40"
                  : "bg-gray-800 text-gray-400 border border-gray-700"
              }`}
            >
              {telegramApiConfig?.configured ? "2 GB Ativo" : "50 MB"}
            </span>
          </button>
          <button
            type="button"
            onClick={handleOpenDataDir}
            className="w-full text-xs text-gray-300 hover:text-white bg-[#202b36] hover:bg-[#2b5278] px-3 py-2 rounded-lg transition flex items-center justify-center gap-2 cursor-pointer"
          >
            <ExternalLink className="w-3.5 h-3.5 text-[#5288c1]" />
            <span>Abrir pasta de dados</span>
          </button>
        </div>
      </div>

      {/* CHAT CANVAS / ÁREA CENTRAL ESTILO TELEGRAM WEB */}
      <div className="flex-1 min-w-0 flex flex-col bg-[#0e1621] relative">
        {selectedProfile ? (
          <>
            {/* Header do Chat: Seleção de Canais */}
            <div className="h-16 border-b border-[#17212b] bg-[#17212b] px-6 flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="w-9 h-9 rounded-full bg-[#5288c1] flex items-center justify-center font-bold text-white text-sm">
                  {selectedProfile.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <h2 className="font-semibold text-sm text-gray-100">{selectedProfile.name}</h2>
                  <p className="text-xs text-[#5288c1]">@{selectedProfile.bot_username}</p>
                </div>
              </div>

              {/* Badges / Checkboxes de Canais e Botão da Fila */}
              <div className="flex items-center space-x-2">
                <span className="text-xs text-gray-400 mr-1 flex items-center gap-1">
                  <Tv className="w-3.5 h-3.5" /> Canais Destino:
                </span>
                {channels.map((c) => {
                  const isChecked = selectedChannelIds.includes(c.chat_id);
                  return (
                    <div
                      key={c.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        if (isChecked) {
                          setSelectedChannelIds(selectedChannelIds.filter((id) => id !== c.chat_id));
                        } else {
                          setSelectedChannelIds([...selectedChannelIds, c.chat_id]);
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          if (isChecked) {
                            setSelectedChannelIds(selectedChannelIds.filter((id) => id !== c.chat_id));
                          } else {
                            setSelectedChannelIds([...selectedChannelIds, c.chat_id]);
                          }
                        }
                      }}
                      className={`text-xs px-2.5 py-1 rounded-full border transition flex items-center gap-1.5 cursor-pointer group select-none ${
                        isChecked
                          ? "bg-[#5288c1] border-[#5288c1] text-white"
                          : "border-gray-600 text-gray-400 hover:border-gray-400 bg-[#1e2a38]/40"
                      }`}
                    >
                      {isChecked && <Check className="w-3 h-3 shrink-0" />}
                      <span className="truncate max-w-[140px]">{c.title}</span>
                      <div className="flex items-center gap-0.5 ml-1 opacity-70 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenEditChannel(c);
                          }}
                          className={`p-0.5 rounded transition ${
                            isChecked
                              ? "hover:bg-white/20 text-white"
                              : "hover:bg-gray-700 text-gray-400 hover:text-[#71aaeb]"
                          }`}
                          title="Editar Canal"
                        >
                          <Edit className="w-3 h-3" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenDeleteChannel(c);
                          }}
                          className={`p-0.5 rounded transition ${
                            isChecked
                              ? "hover:bg-red-500/30 text-white hover:text-red-200"
                              : "hover:bg-red-900/40 text-gray-400 hover:text-red-400"
                          }`}
                          title="Excluir Canal"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  );
                })}

                <button
                  onClick={() => setShowAddChannelModal(true)}
                  className="text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#5288c1] hover:text-white px-2 py-1 rounded-full transition flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Adicionar Canal
                </button>

                {/* Botão da Fila de Agendamentos */}
                <div className="h-4 w-px bg-gray-700 mx-1" />
                <button
                  onClick={() => {
                    fetchScheduledQueue();
                    setQueueNow(new Date());
                    setShowQueueDrawer(true);
                  }}
                  className="relative text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#5288c1] hover:text-white px-3 py-1.5 rounded-full transition flex items-center gap-1.5 font-medium border border-[#3b6694]/40"
                  title="Abrir Fila de Agendamentos"
                >
                  <ListOrdered className="w-3.5 h-3.5" />
                  <span>Fila de Agendamentos</span>
                  {scheduledQueue.length > 0 && (
                    <span className="ml-1 bg-[#5288c1] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full">
                      {scheduledQueue.length}
                    </span>
                  )}
                </button>
              </div>
            </div>

            {/* BANNER NÃO BLOQUEANTE DE AGENDAMENTOS EXPIRADOS (MISFIRED) */}
            {scheduledQueue.some((b) => b.status === "MISFIRED") && (() => {
              const misfiredCount = scheduledQueue.filter((b) => b.status === "MISFIRED").length;
              return (
                <div
                  role="status"
                  data-testid="misfired-banner"
                  className="bg-amber-950/80 border-b border-amber-600/60 px-6 py-2.5 flex items-center justify-between gap-3 text-xs text-amber-200"
                >
                  <div className="flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    <span>
                      {misfiredCount === 1
                        ? "1 agendamento expirou enquanto o app estava fechado"
                        : `${misfiredCount} agendamentos expiraram enquanto o app estava fechado`}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      fetchScheduledQueue();
                      setQueueNow(new Date());
                      setShowQueueDrawer(true);
                    }}
                    className="px-2.5 py-1 rounded-lg bg-amber-600/80 hover:bg-amber-500 text-white font-semibold transition shrink-0"
                  >
                    Ver na fila
                  </button>
                </div>
              );
            })()}

            {/* FEED CENTRAL: PREVIEW AO VIVO DA MENSAGEM */}
            <div className="flex-1 overflow-y-auto p-6 flex flex-col justify-end items-center bg-[#0e1621] space-y-4">
              <div className="w-full max-w-xl flex flex-col items-end">
                <span className="text-[11px] text-gray-500 mb-1 font-medium tracking-wide">
                  PREVIEW AO VIVO (COMO O CANAL VAI RECEBER)
                </span>

                {/* Balão do Telegram com Scroll Suave Irrestrito para Mensagens Longas */}
                <div className="bg-[#2b5278] text-white rounded-2xl rounded-tr-sm p-3.5 shadow-lg max-w-md w-full border border-[#3b6694]/40 max-h-[70vh] overflow-y-auto scroll-smooth pr-2">
                  {/* Prévia de Imagem ou Vídeo */}
                  {mediaPreviewUrl ? (
                    <div className="relative mb-2 rounded-xl overflow-hidden bg-black/40 flex items-center justify-center">
                      {isImageMedia(mediaFile) ? (
                        <img
                          src={mediaPreviewUrl}
                          alt="Prévia da imagem"
                          className="max-h-64 w-full object-cover rounded-xl"
                        />
                      ) : (
                        <video
                          src={mediaPreviewUrl}
                          controls
                          className="max-h-64 w-full object-cover rounded-xl"
                        />
                      )}
                    </div>
                  ) : existingEditingMedia && !existingMediaRemoved ? (
                    <div className="relative mb-2 rounded-xl overflow-hidden bg-black/40 flex items-center justify-center">
                      {existingEditingMedia.mediaType === "PHOTO" ? (
                        <img
                          src={existingEditingMedia.url}
                          alt="Prévia da imagem do agendamento"
                          className="max-h-64 w-full object-cover rounded-xl"
                        />
                      ) : (
                        <video
                          src={existingEditingMedia.url}
                          controls
                          className="max-h-64 w-full object-cover rounded-xl"
                        />
                      )}
                    </div>
                  ) : null}

                  {/* Texto da Mensagem com Renderização de Links e Preservação de Espaçamento */}
                  <div className="text-sm whitespace-pre-wrap leading-relaxed break-words">
                    {renderFormattedMessage(text)}
                  </div>

                  {/* RECURSO 1: Botão de Link Físico Abaixo da Mensagem (Inline Keyboard Button) */}
                  {buttonText && buttonUrl && (
                    <div className="mt-3">
                      <a
                        href={buttonUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-full bg-[#203a56] hover:bg-[#1b3149] text-[#71aaeb] font-semibold text-xs py-2 px-3 rounded-lg flex items-center justify-center gap-1.5 transition border border-[#3b6694]/50"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        {buttonText}
                      </a>
                    </div>
                  )}

                  {/* Metadados e Check duplo do Telegram */}
                  <div className="flex justify-end items-center gap-1 mt-1 text-[10px] text-gray-300">
                    <span>12:00</span>
                    <CheckCheck className="w-3.5 h-3.5 text-[#64b5f6]" />
                  </div>
                </div>

                {/* Feedback de Envio */}
                {feedback && (
                  <div
                    className={`mt-4 px-4 py-2 rounded-lg text-xs flex items-center gap-2 ${
                      feedback.type === "success"
                        ? "bg-green-900/60 text-green-300 border border-green-700"
                        : "bg-red-900/60 text-red-300 border border-red-700"
                    }`}
                  >
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    {feedback.message}
                  </div>
                )}
              </div>
            </div>

            {/* RODAPÉ: COMPOSITOR ESTILO CHAT INPUT */}
            <div className="border-t border-[#17212b] bg-[#17212b] p-4">
              {isSending && !!mediaFile && uploadProgress !== null && (() => {
                const total =
                  telegramProgress && telegramProgress.total_bytes > 0
                    ? telegramProgress.total_bytes
                    : (mediaFile?.size ?? 0);
                const sent = telegramProgress?.sent_bytes ?? 0;
                const pct = telegramProgress?.percent ?? 0;
                const isTelegramProcessing =
                  telegramProgress?.stage === "processing_by_telegram" ||
                  (sent >= total && total > 0);

                return (
                  <div className="max-w-4xl mx-auto mb-3 bg-[#1e2c3a] border border-[#5288c1]/70 rounded-xl p-3.5 shadow-xl space-y-2.5">
                    <div className="flex items-center justify-between text-xs text-blue-200">
                      <div className="flex items-center gap-2.5">
                        <div className="w-4 h-4 border-2 border-[#5288c1] border-t-transparent rounded-full animate-spin shrink-0" />
                        <span className="font-medium text-white text-sm">
                          {uploadPhase === "transmitting" ? (
                            isTelegramProcessing
                              ? `Upload concluído (${formatFileSize(total)})! Telegram processando e publicando no canal... Quase lá!`
                              : `Transmitindo para o Telegram: ${pct}% (${formatFileSize(sent)} / ${formatFileSize(total)}) • Enviando...`
                          ) : (
                            `Fase 1/2: Enviando arquivo para o servidor... [${uploadProgress !== null ? uploadProgress : 0}%]`
                          )}
                        </span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="font-mono font-bold text-base text-[#71aaeb]">
                          {uploadPhase === "transmitting"
                            ? `${telegramProgress?.percent ?? 0}%`
                            : `${uploadProgress !== null ? uploadProgress : 0}%`}
                        </span>
                        <button
                          type="button"
                          onClick={handleAbortSend}
                          className="px-2.5 py-1 bg-red-900/80 hover:bg-red-800 text-red-100 rounded-lg font-medium transition shrink-0 text-xs shadow"
                          title="Cancelar upload em andamento"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                    {/* Barra de Progresso Real */}
                    <div className="w-full bg-[#0e1621] rounded-full h-3 overflow-hidden border border-[#3b6694]/50 p-0.5">
                      <div
                        className={`bg-gradient-to-r from-[#2b5278] via-[#5288c1] to-[#71aaeb] h-full rounded-full transition-all duration-200 ease-out shadow ${
                          uploadPhase === "transmitting" && isTelegramProcessing ? "animate-pulse" : ""
                        }`}
                        style={{
                          width: `${Math.max(
                            uploadPhase === "transmitting"
                              ? (telegramProgress?.percent ?? 0)
                              : (uploadProgress ?? 0),
                            5
                          )}%`,
                        }}
                      />
                    </div>
                  </div>
                );
              })()}
              {composerEditing && (
                <div
                  role="status"
                  className="max-w-4xl mx-auto mb-3 bg-amber-900/40 border border-amber-600/60 rounded-xl px-3.5 py-2 flex items-center justify-between gap-3 text-xs text-amber-100"
                >
                  <span className="flex items-center gap-2">
                    <Edit className="w-4 h-4 shrink-0 text-amber-300" />
                    Editando agendamento
                    {composerEditing.scheduledAt
                      ? ` de ${new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(new Date(composerEditing.scheduledAt))}`
                      : ""}
                    . Use Agendar para salvar.
                  </span>
                  <button
                    type="button"
                    onClick={() => void handleExitComposerEdit()}
                    className="px-2.5 py-1 bg-[#242f3d] hover:bg-[#2b5278] text-white rounded-lg font-medium transition shrink-0"
                  >
                    Sair do modo edição
                  </button>
                </div>
              )}
              <div className="max-w-4xl mx-auto flex items-end gap-3">
                {/* Input Invisível de Arquivo */}
                <input
                  type="file"
                  accept="video/*,image/*"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  className="hidden"
                />

                {/* Botão de Anexo */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className={`p-2.5 rounded-full hover:bg-[#242f3d] transition ${
                    mediaFile || (existingEditingMedia && !existingMediaRemoved)
                      ? "text-green-400 bg-[#242f3d]"
                      : "text-gray-400"
                  }`}
                  title={
                    mediaFile
                      ? `Anexado: ${mediaFile.name}`
                      : existingEditingMedia && !existingMediaRemoved
                      ? "Mídia agendada anexada (clique para trocar)"
                      : "Anexar Vídeo / Imagem"
                  }
                >
                  <Paperclip className="w-5 h-5" />
                </button>

                {/* RECURSO 1: Adicionar Botão Abaixo da Mensagem (Inline Keyboard) */}
                <button
                  type="button"
                  onClick={handleOpenButtonModal}
                  className={`p-2.5 rounded-full hover:bg-[#242f3d] transition ${
                    buttonText ? "text-[#5288c1] bg-[#242f3d] ring-1 ring-[#5288c1]/50" : "text-gray-400 hover:text-[#5288c1]"
                  }`}
                  title={
                    buttonText
                      ? `Botão Abaixo configurado: "${buttonText}"`
                      : "Adicionar Botão Abaixo da Mensagem"
                  }
                  aria-label="Adicionar Botão Abaixo da Mensagem"
                >
                  <SquarePlus className="w-5 h-5" />
                </button>

                {/* Área de Texto Expansível */}
                <div className="flex-1 min-w-0 bg-[#242f3d] rounded-2xl px-4 py-2 flex flex-col">
                  {!mediaFile && existingEditingMedia && !existingMediaRemoved && (
                    <div className="flex flex-col pb-1.5 mb-1.5 border-b border-gray-700 gap-1">
                      <div className="flex items-center justify-between text-xs text-green-400">
                        <span className="truncate min-w-0 flex items-center gap-1.5">
                          {existingEditingMedia.mediaType === "PHOTO" ? (
                            <ImageIcon className="w-3.5 h-3.5 shrink-0" />
                          ) : (
                            <Video className="w-3.5 h-3.5 shrink-0" />
                          )}
                          <span className="truncate" title="Mídia do agendamento">
                            Mídia do agendamento ({existingEditingMedia.mediaType === "PHOTO" ? "Foto" : "Vídeo"})
                          </span>
                          {existingEditingMedia.fileSize ? (
                            <span className="text-[11px] text-gray-400 shrink-0">
                              ({formatFileSize(existingEditingMedia.fileSize)})
                            </span>
                          ) : null}
                        </span>
                        <button
                          type="button"
                          disabled={isSending}
                          onClick={removeMedia}
                          className="text-red-400 hover:text-red-300 text-xs ml-2 disabled:opacity-50"
                        >
                          Remover
                        </button>
                      </div>
                    </div>
                  )}
                  {mediaFile && (
                    <div className="flex flex-col pb-1.5 mb-1.5 border-b border-gray-700 gap-1">
                      <div className="flex items-center justify-between text-xs text-green-400">
                        <span className="truncate min-w-0 flex items-center gap-1.5">
                          {isImageMedia(mediaFile) ? (
                            <ImageIcon className="w-3.5 h-3.5 shrink-0" />
                          ) : (
                            <Video className="w-3.5 h-3.5 shrink-0" />
                          )}
                          <span className="truncate" title={mediaFile.name}>{mediaFile.name}</span>
                          <span className="text-[11px] text-gray-400 shrink-0">
                            ({formatFileSize(mediaFile.size)})
                          </span>
                          {videoMetadata && (
                            <span className="text-[10px] bg-[#17212b] text-[#71aaeb] px-1.5 py-0.5 rounded border border-[#3b6694]/40 shrink-0 font-mono">
                              {videoMetadata.width}x{videoMetadata.height} • {Math.floor(videoMetadata.duration / 60)}:{String(Math.round(videoMetadata.duration % 60)).padStart(2, "0")}
                            </span>
                          )}
                        </span>
                        <button
                          type="button"
                          disabled={isSending}
                          onClick={removeMedia}
                          className="text-red-400 hover:text-red-300 text-xs ml-2 disabled:opacity-50"
                        >
                          Remover
                        </button>
                      </div>
                      {mediaFile.size > TELEGRAM_MAX_STANDARD_SIZE_BYTES && (
                        <div className="text-[12px] text-sky-200 bg-sky-950/70 border border-sky-600/60 rounded-lg p-2.5 flex items-start gap-2 shadow-sm">
                          <Info className="w-4 h-4 shrink-0 text-sky-400 mt-0.5" />
                          <div className="flex-1">
                            <p className="font-medium text-sky-100">
                              Enviando arquivo grande (+50 MB). Por favor, aguarde enquanto a transferência é concluída.
                            </p>
                            <p className="text-[11px] text-sky-300/80 mt-0.5">
                              Tamanho: {formatFileSize(mediaFile.size)}. O envio conta com suporte a streaming progressivo nos canais.
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  <TelegramRichEditor
                    ariaLabel="Mensagem do canal"
                    value={text}
                    onChange={setText}
                    placeholder="Escreva a mensagem do canal..."
                    minRows={2}
                    editorRefHandle={composerEditorRef}
                  />
                </div>

                {/* Botão de Agendamento */}
                <button
                  type="button"
                  disabled={isSending}
                  onClick={() => {
                    if (!scheduledAtInput) {
                      applyScheduleDateTime(new Date(Date.now() + 15 * 60 * 1000), false);
                    }
                    setShowScheduleModal(true);
                  }}
                  className="p-3 bg-[#242f3d] hover:bg-[#2b5278] active:scale-95 text-[#5288c1] hover:text-white rounded-full transition disabled:opacity-50 flex items-center justify-center shadow"
                  title="Agendar Mensagem"
                  aria-label="Agendar Mensagem"
                >
                  <Calendar className="w-5 h-5" />
                </button>

                {/* Botão de Cancelar Envio em Andamento (se estiver enviando) */}
                {isSending && (
                  <button
                    type="button"
                    onClick={handleAbortSend}
                    className="p-3 bg-red-900/70 hover:bg-red-800 active:scale-95 text-red-200 rounded-full transition flex items-center justify-center shadow"
                    title="Cancelar Upload / Envio em Andamento (mantém mensagem no editor)"
                    aria-label="Cancelar Upload"
                  >
                    <X className="w-5 h-5" />
                  </button>
                )}

                {/* Botão de Enviar Agora */}
                <button
                  type="button"
                  disabled={isSending}
                  onClick={() => handleSendBroadcast()}
                  className="p-3 bg-[#5288c1] hover:bg-[#4374a5] active:scale-95 text-white rounded-full transition disabled:opacity-50 flex items-center justify-center shadow"
                  title="Enviar Agora"
                  aria-label="Enviar Agora"
                >
                  {isSending ? (
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Send className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-500">
            <Users className="w-16 h-16 mb-4 text-gray-600" />
            <p className="text-base">Selecione ou adicione um perfil na barra lateral para começar.</p>
          </div>
        )}
      </div>

      {/* RECURSO 1: MODAL CONFIGURAR BOTÃO ABAIXO DA MENSAGEM */}
      {showButtonModal && (
        <div
          role="dialog"
          aria-label="Adicionar Botão Abaixo da Mensagem"
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
        >
          <form
            onSubmit={handleSaveButtonModal}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-sm w-full p-5 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-1 flex items-center gap-2">
              <SquarePlus className="w-4 h-4 text-[#5288c1]" /> Adicionar Botão Abaixo da Mensagem
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Cria um botão de link oficial do Telegram destacado logo abaixo do balão da mensagem.
            </p>
            <div className="space-y-3">
              <div>
                <label htmlFor="field-temp-button-text" className="text-xs text-gray-400 block mb-1">Texto do Botão</label>
                <input
                  id="field-temp-button-text"
                  type="text"
                  placeholder="Ex: Saiba mais"
                  value={tempButtonText}
                  onChange={(e) => setTempButtonText(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                  autoFocus
                />
              </div>
              <div>
                <label htmlFor="field-temp-button-url" className="text-xs text-gray-400 block mb-1">URL do Botão (https://)</label>
                <input
                  id="field-temp-button-url"
                  type="text"
                  placeholder="https://t.me/seucanal"
                  value={tempButtonUrl}
                  onChange={(e) => setTempButtonUrl(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
            </div>
            <div className="mt-5 flex items-center justify-between gap-2 pt-2 border-t border-gray-800">
              {buttonText || buttonUrl ? (
                <button
                  type="button"
                  onClick={handleRemoveButtonModal}
                  className="text-xs text-red-400 hover:text-red-300 font-medium transition"
                  title="Remover o botão inline configurado"
                >
                  Remover Botão
                </button>
              ) : (
                <div />
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleCancelButtonModal}
                  className="px-3 py-1.5 text-xs text-gray-400 hover:text-white transition rounded-lg"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium transition shadow"
                >
                  Salvar
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: AGENDAR MENSAGEM */}
      {showScheduleModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleConfirmSchedule}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-5 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-2 flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#5288c1]" /> Agendar Mensagem
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Defina a data e a hora em que o broadcast deve ser disparado automaticamente para os canais selecionados.
            </p>

            {/* Feedback visível também dentro do modal */}
            {feedback && (
              <div
                className={`mb-4 px-3 py-2.5 rounded-lg text-xs flex items-start justify-between gap-2 border ${
                  feedback.type === "success"
                    ? "bg-green-950/70 text-green-200 border-green-600/70"
                    : "bg-red-950/70 text-red-200 border-red-600/70"
                }`}
              >
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{feedback.message}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setFeedback(null)}
                  className="text-[11px] font-semibold underline shrink-0"
                >
                  OK
                </button>
              </div>
            )}

            {/* Indicador de progresso dentro do modal durante envio */}
            {isSending && (
              <div className="mb-4 bg-[#1e2c3a] border border-[#5288c1]/60 rounded-lg px-3 py-2.5 flex items-center justify-between gap-2 text-xs text-blue-200">
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-[#5288c1] border-t-transparent rounded-full animate-spin shrink-0" />
                  <span>
                    {mediaFile
                      ? `Enviando mídia (${formatFileSize(mediaFile.size)})... Aguarde...`
                      : "Agendando mensagem... Aguarde..."}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleAbortSend}
                  className="px-2 py-0.5 bg-red-900/70 hover:bg-red-800 text-red-100 rounded text-[11px] font-medium"
                >
                  Cancelar
                </button>
              </div>
            )}

            <div className="space-y-3">
              {/* Atalhos rápidos */}
              <div>
                <span className="text-[11px] text-gray-400 block mb-1.5">Atalhos Rápidos:</span>
                <div className="grid grid-cols-4 gap-1.5">
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("5m", false)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +5 min
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("15m", false)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +15 min
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("1h", false)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +1 hora
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("tomorrow12", false)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    Amanhã 12:00
                  </button>
                </div>
              </div>

              {/* Seletor unificado de Data e Hora */}
              <div>
                <label htmlFor="field-scheduled-at-input" className="text-xs text-gray-400 block mb-1">
                  Data e Hora de Disparo (Horário Local)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="field-scheduled-at-input"
                    ref={scheduleDateTimeInputRef}
                    type="datetime-local"
                    required
                    value={scheduledAtInput}
                    onChange={(e) => {
                      const val = e.target.value;
                      setScheduledAtInput(val);
                      const parsed = new Date(val);
                      if (!isNaN(parsed.getTime())) {
                        setScheduleConfirmedPreview(toLocalDateTimeParts(parsed).formatted);
                      }
                    }}
                    className="flex-1 bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1] [color-scheme:dark]"
                  />
                  <button
                    type="button"
                    onClick={() => handleConfirmDateTimeSelection(false)}
                    className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg transition shrink-0 shadow flex items-center gap-1"
                    title="Confirmar data e hora e fechar seletor"
                  >
                    <Check className="w-3.5 h-3.5" />
                    OK / Definir Data e Hora
                  </button>
                </div>
              </div>

              {/* Box verde de confirmação do horário selecionado */}
              {scheduleConfirmedPreview && (
                <div className="bg-emerald-950/60 border border-emerald-600/60 text-emerald-200 rounded-lg px-3 py-2 text-xs font-medium flex items-center gap-2">
                  <span>✅ Horário selecionado: {scheduleConfirmedPreview}</span>
                </div>
              )}
            </div>

            <div className="mt-5 pt-3 border-t border-[#242f3d] flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowScheduleModal(false);
                  setScheduledAtInput("");
                  setScheduleConfirmedPreview(null);
                }}
                className="px-3 py-2 text-xs text-gray-400 hover:text-white"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isSending}
                className="px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-semibold transition disabled:opacity-50 shadow-md flex items-center gap-1.5"
              >
                <Check className="w-4 h-4" />
                OK — Confirmar Agendamento
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: EDITAR PERFIL */}
      {showEditProfileModal && editingProfile && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <form
            onSubmit={handleSaveEditProfile}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-6 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-2 flex items-center gap-2">
              <Edit className="w-4 h-4 text-[#5288c1]" /> Editar
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Atualize o nome do perfil e/ou o token do bot. O token será revalidado com a API do Telegram.
            </p>
            <div className="space-y-4">
              <div>
                <label htmlFor="field-edit-profile-name" className="text-xs text-gray-400 block mb-1">Nome do Perfil</label>
                <input
                  id="field-edit-profile-name"
                  type="text"
                  required
                  placeholder="Ex: Acme"
                  value={editProfileName}
                  onChange={(e) => setEditProfileName(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
              <div>
                <label htmlFor="field-edit-profile-bot-token" className="text-xs text-gray-400 block mb-1">
                  Token do Bot (@BotFather)
                </label>
                <input
                  id="field-edit-profile-bot-token"
                  type="password"
                  required
                  placeholder="123456789:ABCdefGhIJKlmNoPQRstu..."
                  value={editProfileBotToken}
                  onChange={(e) => setEditProfileBotToken(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
                <span className="text-[11px] text-gray-500 mt-1 block">
                  Informe o token para salvar. Se o token for alterado, o @username será revalidado no Telegram.
                </span>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowEditProfileModal(false);
                  setEditingProfile(null);
                  setEditProfileName("");
                  setEditProfileBotToken("");
                }}
                disabled={isSavingProfile}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isSavingProfile}
                className="px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium transition disabled:opacity-50 flex items-center gap-1.5"
              >
                {isSavingProfile ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Salvando...
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    Salvar Alterações
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {pendingConfirm && <ConfirmDialog {...pendingConfirm} onCancel={dismissConfirm} />}

      {/* MODAL: EXCLUIR PERFIL */}
      {showDeleteProfileModal && deletingProfile && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-[#17212b] border border-red-500/40 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-red-400 mb-2 flex items-center gap-2">
              <Trash2 className="w-4 h-4 text-red-400" /> Excluir
            </h3>
            <p className="text-sm text-gray-200 mb-2 leading-relaxed">
              Tem certeza que deseja excluir o perfil <strong>{deletingProfile.name}</strong> (@{deletingProfile.bot_username || "bot"}) e todos os seus canais/histórico?
            </p>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Esta ação removerá todos os canais vinculados e agendamentos deste bot permanentemente.
            </p>
            {affectedBroadcasts && affectedBroadcasts.will_be_cancelled.length > 0 && (
              <div
                data-testid="profile-delete-affected-broadcasts"
                className="mb-5 bg-red-950/50 border border-red-500/40 rounded-lg p-3 text-xs text-red-200"
              >
                <strong className="block font-semibold">
                  {affectedBroadcasts.will_be_cancelled.length === 1
                    ? "1 agendamento pendente será cancelado:"
                    : `${affectedBroadcasts.will_be_cancelled.length} agendamentos pendentes serão cancelados:`}
                </strong>
                {renderAffectedItemsList(affectedBroadcasts.will_be_cancelled)}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteProfileModal(false);
                  setDeletingProfile(null);
                }}
                disabled={isDeletingProfile}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmDeleteProfile}
                disabled={isDeletingProfile}
                className="px-4 py-2 text-xs bg-red-600 hover:bg-red-500 text-white rounded-lg font-medium transition disabled:opacity-50 flex items-center gap-1.5 shadow"
              >
                {isDeletingProfile ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Excluindo...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Confirmar Exclusão
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: ADICIONAR PERFIL */}
      {showAddProfileModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleCreateProfile}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-6 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-4 flex items-center gap-2">
              <Plus className="w-4 h-4 text-[#5288c1]" /> Adicionar Novo Perfil
            </h3>
            <div className="space-y-4">
              <div>
                <label htmlFor="field-new-profile-name" className="text-xs text-gray-400 block mb-1">Nome do Perfil</label>
                <input
                  id="field-new-profile-name"
                  type="text"
                  required
                  placeholder="Ex: Acme"
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
              <div>
                <label htmlFor="field-new-bot-token" className="text-xs text-gray-400 block mb-1">
                  Token do Bot (@BotFather)
                </label>
                <input
                  id="field-new-bot-token"
                  type="password"
                  required
                  placeholder="123456789:ABCdefGhIJKlmNoPQRstu..."
                  value={newBotToken}
                  onChange={(e) => setNewBotToken(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
                <span className="text-[11px] text-gray-500 mt-1 block">
                  O bot será verificado em tempo real com a API do Telegram.
                </span>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAddProfileModal(false)}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isCreatingProfile}
                className="flex items-center gap-1.5 px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isCreatingProfile && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                {isCreatingProfile ? "Cadastrando..." : "Cadastrar Perfil"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: ADICIONAR CANAL */}
      {showAddChannelModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleCreateChannel}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-6 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-4 flex items-center gap-2">
              <Tv className="w-4 h-4 text-[#5288c1]" /> Adicionar Canal para {selectedProfile?.name}
            </h3>
            {selectedProfile && (
              <ChatDiscoveryPanel
                apiBaseUrl={API_BASE_URL}
                profileId={selectedProfile.id}
                registeredChatIds={channels.map((c) => c.chat_id)}
                onAdd={handleAddDiscoveredChat}
              />
            )}
            <div className="space-y-4">
              <div>
                <label htmlFor="field-new-channel-title" className="text-xs text-gray-400 block mb-1">Título do Canal</label>
                <input
                  id="field-new-channel-title"
                  type="text"
                  required
                  placeholder="Ex: Canal de Novidades"
                  value={newChannelTitle}
                  onChange={(e) => setNewChannelTitle(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
              <div>
                <label htmlFor="field-new-channel-chat-id" className="text-xs text-gray-400 block mb-1">
                  Chat ID do Telegram (começa com -100...)
                </label>
                <input
                  id="field-new-channel-chat-id"
                  type="text"
                  required
                  placeholder="-1001234567890"
                  value={newChannelChatId}
                  onChange={(e) => setNewChannelChatId(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
                <span className="text-[11px] text-gray-500 mt-1 block">
                  Certifique-se de que o bot do perfil já foi adicionado como Admin no canal.
                </span>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAddChannelModal(false)}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isCreatingChannel}
                className="flex items-center gap-1.5 px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isCreatingChannel && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                {isCreatingChannel ? "Vinculando..." : "Vincular Canal"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: EDITAR CANAL */}
      {showEditChannelModal && editingChannel && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <form
            onSubmit={handleSaveEditChannel}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-6 shadow-2xl"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-2 flex items-center gap-2">
              <Edit className="w-4 h-4 text-[#5288c1]" /> Editar Canal
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Atualize o título ou o Chat ID do canal do Telegram.
            </p>
            <div className="space-y-4">
              <div>
                <label htmlFor="field-edit-channel-title" className="text-xs text-gray-400 block mb-1">Título do Canal</label>
                <input
                  id="field-edit-channel-title"
                  type="text"
                  required
                  placeholder="Ex: Canal de Novidades"
                  value={editChannelTitle}
                  onChange={(e) => setEditChannelTitle(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
              <div>
                <label htmlFor="field-edit-channel-chat-id" className="text-xs text-gray-400 block mb-1">
                  Chat ID do Telegram (começa com -100...)
                </label>
                <input
                  id="field-edit-channel-chat-id"
                  type="text"
                  required
                  placeholder="-1001234567890"
                  value={editChannelChatId}
                  onChange={(e) => setEditChannelChatId(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
                <span className="text-[11px] text-gray-500 mt-1 block">
                  O bot do perfil deve permanecer como Administrador neste canal.
                </span>
              </div>
              {editChannelChatId.trim() !== editingChannel.chat_id &&
                affectedBroadcasts &&
                affectedBroadcasts.will_be_cancelled.length + affectedBroadcasts.will_lose_target.length > 0 && (() => {
                  const allAffected = [
                    ...affectedBroadcasts.will_be_cancelled,
                    ...affectedBroadcasts.will_lose_target,
                  ];
                  return (
                    <div
                      data-testid="channel-edit-affected-broadcasts"
                      className="bg-amber-950/50 border border-amber-500/40 rounded-lg p-3 text-xs text-amber-200"
                    >
                      <strong className="block font-semibold">
                        {allAffected.length === 1
                          ? "1 agendamento pendente passará a usar o novo ID:"
                          : `${allAffected.length} agendamentos pendentes passarão a usar o novo ID:`}
                      </strong>
                      {renderAffectedItemsList(allAffected)}
                    </div>
                  );
                })()}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowEditChannelModal(false);
                  setEditingChannel(null);
                  setEditChannelTitle("");
                  setEditChannelChatId("");
                }}
                disabled={isSavingChannel}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isSavingChannel}
                className="px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium transition disabled:opacity-50 flex items-center gap-1.5"
              >
                {isSavingChannel ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Salvando...
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    Salvar Alterações
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: EXCLUIR CANAL */}
      {showDeleteChannelModal && deletingChannel && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 animate-in fade-in duration-200">
          <div className="bg-[#17212b] border border-red-500/40 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-red-400 mb-2 flex items-center gap-2">
              <Trash2 className="w-4 h-4 text-red-400" /> Excluir Canal
            </h3>
            <p className="text-sm text-gray-200 mb-2 leading-relaxed">
              Deseja realmente remover o canal <strong>{deletingChannel.title}</strong> deste bot?
            </p>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              O bot não enviará mais transmissões para este Chat ID ({deletingChannel.chat_id}).
            </p>
            {affectedBroadcasts &&
              (affectedBroadcasts.will_be_cancelled.length > 0 ||
                affectedBroadcasts.will_lose_target.length > 0) && (
                <div
                  data-testid="channel-delete-affected-broadcasts"
                  className="mb-5 space-y-3 bg-[#202b36] border border-red-500/30 rounded-lg p-3 text-xs"
                >
                  {affectedBroadcasts.will_be_cancelled.length > 0 && (
                    <div className="text-red-200">
                      <strong className="block font-semibold">
                        {affectedBroadcasts.will_be_cancelled.length === 1
                          ? "1 agendamento será cancelado (tinha só este canal):"
                          : `${affectedBroadcasts.will_be_cancelled.length} agendamentos serão cancelados (tinham só este canal):`}
                      </strong>
                      {renderAffectedItemsList(affectedBroadcasts.will_be_cancelled)}
                    </div>
                  )}
                  {affectedBroadcasts.will_lose_target.length > 0 && (
                    <div className="text-amber-200">
                      <strong className="block font-semibold">
                        {affectedBroadcasts.will_lose_target.length === 1
                          ? "1 agendamento perde este destino (continua nos demais canais):"
                          : `${affectedBroadcasts.will_lose_target.length} agendamentos perdem este destino (continuam nos demais canais):`}
                      </strong>
                      {renderAffectedItemsList(affectedBroadcasts.will_lose_target)}
                    </div>
                  )}
                </div>
              )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteChannelModal(false);
                  setDeletingChannel(null);
                }}
                disabled={isDeletingChannel}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-white disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmDeleteChannel}
                disabled={isDeletingChannel}
                className="px-4 py-2 text-xs bg-red-600 hover:bg-red-500 text-white rounded-lg font-medium transition disabled:opacity-50 flex items-center gap-1.5 shadow"
              >
                {isDeletingChannel ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Excluindo...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Confirmar Exclusão
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DRAWER / MODAL: FILA DE AGENDAMENTOS */}
      {showQueueDrawer && (
        <div className="fixed inset-0 bg-black/60 flex justify-end z-50 animate-in fade-in duration-200">
          <div className="bg-[#17212b] border-l border-[#242f3d] w-full max-w-lg h-full flex flex-col shadow-2xl">
            {/* Header do Drawer */}
            <div className="p-4 border-b border-[#242f3d] flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Clock className="w-5 h-5 text-[#5288c1]" />
                <div>
                  <h3 className="font-semibold text-base text-gray-100">Fila de Agendamentos</h3>
                  <p className="text-xs text-gray-400">
                    {selectedProfile ? `Perfil: ${selectedProfile.name}` : "Selecione um perfil"}
                  </p>
                </div>
              </div>
              <div className="flex items-center space-x-1">
                <button
                  onClick={() => fetchScheduledQueue()}
                  disabled={isLoadingQueue}
                  className="p-1.5 rounded-full hover:bg-[#242f3d] text-gray-400 hover:text-white transition disabled:opacity-50"
                  title="Atualizar Fila"
                >
                  <RefreshCw className={`w-4 h-4 ${isLoadingQueue ? "animate-spin text-[#5288c1]" : ""}`} />
                </button>
                <button
                  onClick={() => setShowQueueDrawer(false)}
                  className="p-1.5 rounded-full hover:bg-[#242f3d] text-gray-400 hover:text-white transition"
                  title="Fechar"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Lista da Fila */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {isLoadingQueue ? (
                <div className="flex flex-col items-center justify-center h-48 text-gray-400 text-sm">
                  <div className="w-6 h-6 border-2 border-[#5288c1] border-t-transparent rounded-full animate-spin mb-2" />
                  Carregando agendamentos...
                </div>
              ) : scheduledQueue.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-48 text-gray-400 text-sm text-center">
                  <Calendar className="w-10 h-10 mb-2 text-gray-600" />
                  Nenhum broadcast agendado para este perfil.
                </div>
              ) : (
                scheduledQueue.map((item) => {
                  const isProcessing = actionInProgressId === item.id;
                  const isMisfired = item.status === "MISFIRED";
                  const scheduledAt = item.scheduled_at
                    ? new Date(item.scheduled_at)
                    : queueNow ?? new Date(0);
                  const formattedDate = new Intl.DateTimeFormat(undefined, { dateStyle: "short", timeStyle: "short" }).format(scheduledAt);
                  const relativeDate = queueNow ? formatRelativeTime(scheduledAt, queueNow) : null;
                  const isPhoto = item.media?.media_type === "PHOTO";
                  const isVideo = item.media?.media_type === "VIDEO";

                  return (
                    <div
                      key={item.id}
                      className={`bg-[#242f3d] rounded-xl p-4 border transition flex flex-col space-y-3 ${
                        isMisfired
                          ? "border-amber-500/60 hover:border-amber-400"
                          : "border-[#3b6694]/20 hover:border-[#3b6694]/50"
                      }`}
                    >
                      {/* Topo do card: Data e Status */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 text-xs text-[#71aaeb] font-medium">
                          <Clock className="w-3.5 h-3.5 shrink-0" />
                          <time dateTime={item.scheduled_at || undefined}>{formattedDate}</time>
                          {relativeDate && (
                            <span
                              className="px-1.5 py-0.5 rounded bg-[#2b5278]/60 text-[10px] text-white"
                              data-testid="schedule-relative-time"
                            >
                              {relativeDate}
                            </span>
                          )}
                        </div>
                        {isMisfired ? (
                          <span
                            data-testid="misfired-badge"
                            className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-amber-600/80 text-white"
                          >
                            Expirado
                          </span>
                        ) : (
                          <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-[#2b5278] text-white">
                            {item.status}
                          </span>
                        )}
                      </div>

                      {/* Conteúdo da mensagem com links formatados */}
                      <div className="text-xs text-gray-200 line-clamp-3 whitespace-pre-wrap leading-relaxed">
                        {item.text ? renderFormattedMessage(item.text) : <span className="italic text-gray-400">Mensagem sem texto</span>}
                      </div>

                      {/* Mídia e Botão se houver */}
                      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-gray-700/40 text-[11px] text-gray-400">
                        {item.media && (
                          <span className="inline-flex items-center gap-1 bg-[#17212b] px-2 py-1 rounded text-green-400">
                            {isPhoto ? <ImageIcon className="w-3 h-3" /> : <Video className="w-3 h-3" />}
                            {isPhoto ? "Foto anexada" : isVideo ? "Vídeo anexado" : "Mídia anexada"}
                          </span>
                        )}
                        {item.button && (
                          <span className="inline-flex items-center gap-1 bg-[#17212b] px-2 py-1 rounded text-[#71aaeb]">
                            <ExternalLink className="w-3 h-3" />
                            {item.button.text}
                          </span>
                        )}
                        <span className="text-gray-500 ml-auto">
                          {item.target_channel_ids?.length || 0} canal(is)
                        </span>
                      </div>

                      {/* Ações do Card */}
                      <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-700/50">
                        {isMisfired ? (
                          <>
                            <button
                              type="button"
                              onClick={() => handleDispatchMisfiredNow(item.id)}
                              disabled={isProcessing}
                              className="text-xs px-2.5 py-1 text-white bg-emerald-700 hover:bg-emerald-600 rounded transition flex items-center gap-1 disabled:opacity-50"
                              title="Enviar este agendamento expirado agora"
                            >
                              <Send className="w-3 h-3" />
                              Enviar agora
                            </button>
                            <button
                              type="button"
                              onClick={() => handleOpenEditScheduled(item)}
                              disabled={isProcessing}
                              className="text-xs px-2.5 py-1 text-[#71aaeb] hover:text-white bg-[#203a56] hover:bg-[#2b5278] rounded transition flex items-center gap-1 disabled:opacity-50"
                              title="Escolher novo horário para reagendar"
                            >
                              <Calendar className="w-3 h-3" />
                              Reagendar
                            </button>
                            <button
                              type="button"
                              onClick={() => handleCancelScheduled(item.id)}
                              disabled={isProcessing}
                              className="text-xs px-2.5 py-1 text-red-400 hover:text-white bg-red-950/40 hover:bg-red-900/60 rounded transition flex items-center gap-1 disabled:opacity-50"
                              title="Descartar agendamento expirado e remover mídia"
                            >
                              <Trash2 className="w-3 h-3" />
                              Descartar
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => handleLoadIntoComposer(item)}
                              className="text-xs px-2.5 py-1 text-gray-300 hover:text-white bg-[#17212b] hover:bg-[#202b36] rounded transition"
                              title="Carregar mensagem de volta para o compositor principal"
                            >
                              Carregar no Editor
                            </button>
                            <button
                              type="button"
                              onClick={() => handleOpenEditScheduled(item)}
                              disabled={isProcessing}
                              className="text-xs px-2.5 py-1 text-[#71aaeb] hover:text-white bg-[#203a56] hover:bg-[#2b5278] rounded transition flex items-center gap-1"
                              title="Editar mensagem e horário de agendamento"
                            >
                              <Edit className="w-3 h-3" />
                              Editar
                            </button>
                            <button
                              type="button"
                              onClick={() => handleCancelScheduled(item.id)}
                              disabled={isProcessing}
                              className="text-xs px-2.5 py-1 text-red-400 hover:text-white bg-red-950/40 hover:bg-red-900/60 rounded transition flex items-center gap-1 disabled:opacity-50"
                              title="Cancelar agendamento e descartar mídias"
                            >
                              <Trash2 className="w-3 h-3" />
                              Cancelar
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })
              )}

              {/* Histórico Recente de Envios com resultado por canal (#31) */}
              {broadcastHistory.length > 0 && (
                <div
                  data-testid="broadcast-history-section"
                  className="pt-4 mt-4 border-t border-[#242f3d] space-y-2.5"
                >
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Histórico Recente
                  </h4>
                  {broadcastHistory.slice(0, 10).map((hist) => {
                    const summary = formatChannelDeliveryList(hist.delivery_results);
                    const createdDt = new Intl.DateTimeFormat(undefined, {
                      dateStyle: "short",
                      timeStyle: "short",
                    }).format(new Date(hist.created_at));
                    return (
                      <div
                        key={hist.id}
                        data-testid="broadcast-history-item"
                        className="bg-[#1e2a38] rounded-xl p-3 border border-[#3b6694]/20 space-y-1.5 text-xs"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-gray-400">{createdDt}</span>
                          <span
                            className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full ${
                              hist.status === "COMPLETED"
                                ? "bg-emerald-800/70 text-emerald-200"
                                : hist.status === "PARTIALLY_COMPLETED"
                                ? "bg-amber-800/70 text-amber-200"
                                : "bg-red-900/70 text-red-200"
                            }`}
                          >
                            {hist.status}
                          </span>
                        </div>
                        <div className="text-gray-200 line-clamp-2 whitespace-pre-wrap">
                          {hist.text ? renderFormattedMessage(hist.text) : <span className="italic text-gray-400">Mensagem sem texto</span>}
                        </div>
                        {summary ? (
                          <div
                            data-testid="delivery-results-summary"
                            className="text-[11px] text-gray-300 pt-1 border-t border-gray-700/40"
                          >
                            {summary}
                          </div>
                        ) : (
                          <div className="text-[11px] text-gray-500 pt-1 border-t border-gray-700/40">
                            {hist.channels_count} canal(is)
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* MODAL: EDITAR AGENDAMENTO */}
      {showEditModal && editingBroadcast && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleSaveEditScheduled}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-lg w-full p-6 shadow-2xl max-h-[90vh] overflow-y-auto"
          >
            <h3 className="text-base font-semibold text-gray-100 mb-2 flex items-center gap-2">
              <Edit className="w-4 h-4 text-[#5288c1]" /> Editar Broadcast Agendado
            </h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              Altere o texto, o botão inline ou reprograme o horário de disparo no APScheduler.
            </p>

            <div className="space-y-4">
              <div>
                <label htmlFor="field-edit-text" className="text-xs text-gray-400 block mb-1">Texto da Mensagem</label>
                <div className="w-full bg-[#242f3d] rounded-lg px-3 py-2 border border-transparent focus-within:border-[#5288c1]">
                  <TelegramRichEditor
                    id="field-edit-text"
                    ariaLabel="Texto da Mensagem"
                    value={editText}
                    onChange={setEditText}
                    placeholder="Escreva a mensagem..."
                    minRows={3}
                  />
                </div>
              </div>

              {/* Atalhos rápidos na Edição */}
              <div>
                <span className="text-[11px] text-gray-400 block mb-1.5">Atalhos Rápidos de Reagendamento:</span>
                <div className="grid grid-cols-4 gap-1.5">
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("5m", true)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +5 min
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("15m", true)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +15 min
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("1h", true)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    +1 hora
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickPreset("tomorrow12", true)}
                    className="px-2 py-1.5 text-xs bg-[#242f3d] hover:bg-[#2b5278] text-[#71aaeb] hover:text-white rounded-lg border border-[#3b6694]/30 transition font-medium"
                  >
                    Amanhã 12:00
                  </button>
                </div>
              </div>

              {/* Seletor unificado de Data e Hora na Edição */}
              <div>
                <label htmlFor="field-edit-scheduled-at-input" className="text-xs text-gray-400 block mb-1">
                  Data e Hora de Disparo (Horário Local)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="field-edit-scheduled-at-input"
                    ref={editDateTimeInputRef}
                    type="datetime-local"
                    required
                    value={editScheduledAtInput}
                    onChange={(e) => {
                      const val = e.target.value;
                      setEditScheduledAtInput(val);
                      const parsed = new Date(val);
                      if (!isNaN(parsed.getTime())) {
                        setEditScheduleConfirmedPreview(toLocalDateTimeParts(parsed).formatted);
                      }
                    }}
                    className="flex-1 bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1] [color-scheme:dark]"
                  />
                  <button
                    type="button"
                    onClick={() => handleConfirmDateTimeSelection(true)}
                    className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg transition shrink-0 shadow flex items-center gap-1"
                    title="Confirmar data e hora e fechar seletor"
                  >
                    <Check className="w-3.5 h-3.5" />
                    OK / Definir Data e Hora
                  </button>
                </div>
              </div>

              {editScheduleConfirmedPreview && (
                <div className="bg-emerald-950/60 border border-emerald-600/60 text-emerald-200 rounded-lg px-3 py-2 text-xs font-medium flex items-center gap-2">
                  <span>✅ Horário selecionado: {editScheduleConfirmedPreview}</span>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="field-edit-button-text" className="text-xs text-gray-400 block mb-1">Texto do Botão Inline</label>
                  <input
                    id="field-edit-button-text"
                    type="text"
                    placeholder="Ex: Ver Link"
                    value={editButtonText}
                    onChange={(e) => setEditButtonText(e.target.value)}
                    className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                  />
                </div>
                <div>
                  <label htmlFor="field-edit-button-url" className="text-xs text-gray-400 block mb-1">URL (https://)</label>
                  <input
                    id="field-edit-button-url"
                    type="url"
                    placeholder="https://exemplo.com"
                    value={editButtonUrl}
                    onChange={(e) => setEditButtonUrl(e.target.value)}
                    className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                  />
                </div>
              </div>
            </div>

            <div className="mt-6 pt-3 border-t border-[#242f3d] flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowEditModal(false);
                  setEditingBroadcast(null);
                  setEditScheduleConfirmedPreview(null);
                }}
                className="px-3 py-2 text-xs text-gray-400 hover:text-white"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isUpdatingScheduled}
                className="px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-semibold transition disabled:opacity-50 shadow-md flex items-center gap-1.5"
              >
                <Check className="w-4 h-4" />
                {isUpdatingScheduled ? "Salvando..." : "OK — Confirmar Agendamento"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: CONFIGURAÇÃO TELEGRAM API (UPLOAD ATÉ 2 GB) (#56) */}
      {showTelegramApiModal && (
        <div
          role="dialog"
          aria-label="Configurações da Telegram API"
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
        >
          <form
            onSubmit={handleSaveTelegramApiConfig}
            className="bg-[#17212b] border border-[#242f3d] rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150"
          >
            <div className="flex items-start justify-between gap-3 border-b border-gray-700/60 pb-3">
              <div className="flex items-center gap-2">
                <Server className="w-5 h-5 text-[#5288c1]" />
                <h3 className="text-base font-semibold text-gray-100">
                  Configurações da Telegram API
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowTelegramApiModal(false)}
                className="text-gray-400 hover:text-white transition p-1"
                title="Fechar"
              >
                ✕
              </button>
            </div>

            <div className="bg-[#242f3d]/60 border border-gray-700/50 rounded-lg p-3 text-xs text-gray-300 space-y-2 leading-relaxed">
              <p>
                Para enviar vídeos e fotos acima de <strong>50 MB (até 2 GB)</strong>, o Telegram
                exige as credenciais da sua aplicação gratuita obtidas em{" "}
                <a
                  href="https://my.telegram.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#64b5f6] underline hover:text-[#90caf9] font-medium inline-flex items-center gap-1"
                >
                  my.telegram.org <ExternalLink className="w-3 h-3" />
                </a>
                .
              </p>
              <p className="text-[11px] text-gray-400">
                Faça login com seu telefone no Telegram, acesse <em>API development tools</em> e crie sua
                aplicação para obter o <strong>API ID</strong> e o <strong>API Hash</strong>.
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label htmlFor="field-telegram-api-id" className="text-xs text-gray-300 block mb-1">
                  API ID
                </label>
                <input
                  id="field-telegram-api-id"
                  type="text"
                  required
                  placeholder="Ex: 12345678"
                  value={apiIdInput}
                  onChange={(e) => setApiIdInput(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>

              <div>
                <label htmlFor="field-telegram-api-hash" className="text-xs text-gray-300 block mb-1">
                  API Hash
                </label>
                <input
                  id="field-telegram-api-hash"
                  type="password"
                  required
                  placeholder={telegramApiConfig?.has_api_hash ? "••••••••••••••••••••••••••••••••" : "Ex: 0123456789abcdef..."}
                  value={apiHashInput}
                  onChange={(e) => setApiHashInput(e.target.value)}
                  className="w-full bg-[#242f3d] rounded-lg px-3 py-2 text-sm text-white outline-none border border-transparent focus:border-[#5288c1]"
                />
              </div>
            </div>

            <div className="text-[11px] text-gray-400 bg-[#0e1621] p-2.5 rounded-lg border border-gray-800 space-y-1">
              <div className="flex items-center justify-between text-gray-300">
                <span>Status do upload:</span>
                <span className={telegramApiConfig?.configured ? "text-green-400 font-medium" : "text-amber-400 font-medium"}>
                  {telegramApiConfig?.configured ? "Servidor Local Ativo (até 2.000 MB)" : "API Pública (até 50 MB)"}
                </span>
              </div>
              <p className="text-[10px] text-gray-500 truncate" title={telegramApiConfig?.env_file_path || ""}>
                Salvo em: {telegramApiConfig?.env_file_path || "%LOCALAPPDATA%\\Auto-Send\\.env"} (preservado entre versões).
              </p>
            </div>

            <div className="pt-2 border-t border-gray-800 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowTelegramApiModal(false)}
                className="px-3 py-2 text-xs text-gray-400 hover:text-white transition"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isSavingTelegramApi}
                className="flex items-center gap-1.5 px-4 py-2 text-xs bg-[#5288c1] hover:bg-[#4374a5] text-white rounded-lg font-medium transition disabled:opacity-50"
              >
                {isSavingTelegramApi && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                {isSavingTelegramApi ? "Salvando..." : "Salvar Credenciais"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
