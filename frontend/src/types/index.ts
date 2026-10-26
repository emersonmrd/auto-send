export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

export interface OpenDataDirResponse {
  path: string;
  opened: boolean;
}

export interface Profile {
  id: string;
  name: string;
  bot_username: string;
  avatar_url?: string | null;
  is_active: boolean;
  created_at?: string;
}

export interface ProfileListItem extends Profile {
  created_at: string;
}

export interface DeleteResourceResponse {
  message: string;
  id: string;
}

export interface Channel {
  id: string;
  profile_id: string;
  title: string;
  chat_id: string;
  invite_link?: string;
  is_active: boolean;
}

export interface ChannelCreateResponse {
  id: string;
  profile_id: string;
  title: string;
  chat_id: string;
  invite_link: string;
}

export interface ChannelUpdateResponse {
  id: string;
  profile_id: string;
  name: string;
  title: string;
  telegram_channel_id: string;
  chat_id: string;
}

export interface BroadcastHistoryItem {
  id: string;
  profile_id: string;
  text: string;
  status: string;
  channels_count: number;
  scheduled_at?: string | null;
  created_at: string;
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
}

export type CreateBroadcastResponse = ScheduledBroadcastCreateResponse | BroadcastResponse;

export interface BroadcastMedia {
  file_path: string;
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
  status: "PENDING" | "SCHEDULED" | "MISFIRED" | "DISPATCHING" | "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED" | "CANCELLED";
  scheduled_at: string | null;
  created_at?: string | null;
}

export interface CancelBroadcastResponse {
  id: string;
  status: string;
  message: string;
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
}

// POST /api/v1/profiles/{profile_id}/discover-chats
export interface DiscoveredChatListItem extends DiscoveredChat {
  already_registered: boolean;
}

export interface DiscoverChatsResponse {
  chats: DiscoveredChatListItem[];
}
