export type Page = "overview" | "subscriptions" | "notifications";
export type Status = "active" | "expired" | "pending" | "sent" | "failed";

export interface Overview {
  bot_connected: boolean;
  active_subscriptions: number;
  expired_subscriptions: number;
  poll_errors: number;
  pending_notifications: number;
  sent_notifications: number;
  failed_notifications: number;
}

export interface Subscription {
  id: string;
  user_id: string;
  guild_id: string | null;
  channel_id: string;
  user_name?: string | null;
  guild_name?: string | null;
  channel_name?: string | null;
  theater_id: string;
  theater_name?: string | null;
  show_date: string;
  keyword?: string | null;
  status: Status;
  created_at: string;
  expires_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  pending_count: number;
  failed_count: number;
}

export interface Notification {
  id: string;
  subscription_id: string;
  status: Status;
  attempts: number;
  last_error?: string | null;
  created_at: string;
  sent_at?: string | null;
  next_retry_at?: string | null;
  movie_titles: string[];
  user_id: string;
  user_name?: string | null;
  guild_id: string | null;
  guild_name?: string | null;
  channel_id: string;
  channel_name?: string | null;
  theater_name?: string | null;
  show_date: string;
  keyword?: string | null;
}

export interface SubscriptionDetail extends Subscription {
  movies: string[];
  notifications: Notification[];
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
