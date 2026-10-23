export interface Profile {
  id: string;
  name: string;
  bot_username: string;
  avatar_url?: string;
  is_active: boolean;
  created_at?: string;
}

export interface Channel {
  id: string;
  profile_id: string;
  title: string;
  chat_id: string;
  invite_link?: string;
  is_active: boolean;
}

export interface BroadcastResponse {
  broadcast_id: string;
  status: string;
  dispatched_count: number;
  total_targets: number;
  errors: string[];
}

export interface ScheduledBroadcast {
  id: string;
  profile_id: string;
  target_channel_ids: string[];
  text: string;
  media?: {
    file_path: string;
    media_type: "PHOTO" | "VIDEO";
    file_size?: number;
  } | null;
  button?: {
    text: string;
    url: string;
  } | null;
  status: "PENDING" | "SCHEDULED" | "DISPATCHING" | "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED" | "CANCELLED";
  scheduled_at: string;
  created_at?: string;
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
