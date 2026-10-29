export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

export interface OpenDataDirResponse {
  path: string;
  opened: boolean;
}

export interface TelegramApiConfigResponse {
  configured: boolean;
  api_id: string;
  has_api_hash: boolean;
  max_upload_mb: number;
  env_file_path: string;
}

export interface UpdateTelegramApiConfigRequest {
  api_id: string;
  api_hash: string;
}

export interface Profile {
  id: string;
  name: string;
  bot_username: string;
  avatar_url?: string | null;
  is_active: boolean;
  created_at?: string;
  warning?: string | null;
  has_active_webhook?: boolean;
  webhook_url?: string | null;
  has_active_polling?: boolean;
  is_duplicate_token?: boolean;
}

export interface ValidateBotResponse {
  is_valid: boolean;
  bot_username: string;
  has_active_webhook: boolean;
  webhook_url?: string | null;
  has_active_polling: boolean;
  is_duplicate_token: boolean;
  warning?: string | null;
}

export interface ProfileListItem extends Profile {
  created_at: string;
}

export interface DeleteResourceResponse {
  message: string;
  id: string;
}

// Tipo informado pelo Telegram (#99); null em canal vinculado antes disso, até a próxima edição.
export type ChannelChatType = "channel" | "supergroup";

export interface Channel {
  id: string;
  profile_id: string;
  title: string;
  chat_id: string;
  invite_link?: string;
  is_active: boolean;
  chat_type: ChannelChatType | null;
  is_forum: boolean;
  message_thread_id?: number | null;
  topic_name?: string | null;
  destination_id?: string | null;
}

// Situação do bot no destino, como o getChatMember a informa (#107).
export type BotMemberStatus = "creator" | "administrator" | "member" | "restricted" | "left" | "kicked";

// GET /api/v1/channels/{channel_id}/bot-permissions (#107).
export interface BotPermissions {
  chat_type: ChannelChatType | null;
  is_forum: boolean;
  bot_status: BotMemberStatus;
  can_send_messages: boolean;
  can_send_photos: boolean;
  can_send_videos: boolean;
  can_send_polls: boolean;
  checked_at: string;
}

export interface ChannelCreateResponse {
  id: string;
  profile_id: string;
  title: string;
  chat_id: string;
  invite_link: string;
  chat_type: ChannelChatType | null;
  is_forum: boolean;
  message_thread_id?: number | null;
  topic_name?: string | null;
  destination_id?: string | null;
}

export interface ChannelUpdateResponse {
  id: string;
  profile_id: string;
  name: string;
  title: string;
  telegram_channel_id: string;
  chat_id: string;
  chat_type: ChannelChatType | null;
  is_forum: boolean;
  message_thread_id?: number | null;
  topic_name?: string | null;
  destination_id?: string | null;
}

export type DeliveryFailureCategory =
  | "BOT_NOT_IN_CHAT"
  | "NO_POST_PERMISSION"
  | "INVALID_TOKEN"
  | "RATE_LIMITED"
  | "TELEGRAM_UNAVAILABLE"
  | "OTHER";

export interface ChannelDeliveryResult {
  chat_id: string;
  delivered: boolean;
  failure_category?: DeliveryFailureCategory | null;
  detail?: string | null;
}

export interface BroadcastPoll {
  question: string;
  options: string[];
  is_anonymous: boolean;
  allows_multiple_answers: boolean;
  poll_type: "regular" | "quiz";
  correct_option_id?: number | null;
  explanation?: string | null;
  is_closed?: boolean;
}

export interface BroadcastHistoryItem {
  id: string;
  profile_id: string;
  text: string;
  status: string;
  channels_count: number;
  scheduled_at?: string | null;
  created_at: string;
  delivery_results?: ChannelDeliveryResult[];
  poll?: BroadcastPoll | null;
}

export interface BroadcastProgressResponse {
  tracking_id: string;
  stage: string;
  percent: number;
  sent_bytes: number;
  total_bytes: number;
  status: string;
  created_at?: number | null;
  updated_at?: number | null;
}

export interface ScheduledBroadcastCreateResponse {
  broadcast_id: string;
  status: string;
  scheduled_at: string;
  channels_count: number;
  dispatched_count: number;
}

export interface BroadcastResponse {
  broadcast_id: string;
  status: string;
  dispatched_count: number;
  total_targets: number;
  errors: string[];
  delivery_results?: ChannelDeliveryResult[];
}

export type CreateBroadcastResponse = ScheduledBroadcastCreateResponse | BroadcastResponse;

export interface BroadcastMedia {
  media_type: "PHOTO" | "VIDEO";
  file_size?: number | null;
}

export interface BroadcastButton {
  text: string;
  url: string;
}

export interface ScheduledBroadcast {
  id: string;
  profile_id: string;
  target_channel_ids: string[];
  text: string;
  media?: BroadcastMedia | null;
  button?: BroadcastButton | null;
  poll?: BroadcastPoll | null;
  status: "PENDING" | "SCHEDULED" | "MISFIRED" | "DISPATCHING" | "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED" | "CANCELLED";
  scheduled_at: string | null;
  created_at?: string | null;
}

// Trava de edição do agendamento (#15): POST renova, DELETE sai do modo edição.
export interface EditLockResponse {
  id: string;
  status: string;
  edit_locked_until?: string | null;
  cancelled: boolean;
}

export interface CancelBroadcastResponse {
  id: string;
  status: string;
  message: string;
}

export interface AbortBroadcastResponse {
  tracking_id: string;
  status: string;
}

export interface AffectedBroadcastItem {
  id: string;
  text_preview: string;
  scheduled_at?: string | null;
  status: string;
  target_channel_ids: string[];
}

export interface AffectedBroadcastsResponse {
  will_be_cancelled: AffectedBroadcastItem[];
  will_lose_target: AffectedBroadcastItem[];
  in_flight_count: number;
}

// POST /api/v1/profiles/{profile_id}/resolve-chat
export interface DiscoveredChat {
  chat_id: string;
  title: string;
  type: "channel" | "supergroup" | "group";
  username: string | null;
  // Canal ou supergrupo (-100...); grupo comum não pode ser vinculado.
  registrable: boolean;
  // Supergrupo com tópicos ativados (#99).
  is_forum: boolean;
  message_thread_id?: number | null;
  topic_name?: string | null;
}

// POST /api/v1/profiles/{profile_id}/discover-chats
export interface DiscoveredChatListItem extends DiscoveredChat {
  already_registered: boolean;
}

export interface DiscoverChatsResponse {
  chats: DiscoveredChatListItem[];
}

export interface MessageTemplate {
  id: string;
  profile_id: string;
  name: string;
  text: string;
  button_text?: string | null;
  button_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateMessageTemplateRequest {
  name: string;
  text: string;
  button_text?: string | null;
  button_url?: string | null;
}
