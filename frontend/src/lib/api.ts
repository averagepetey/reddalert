import { getAuthHeaders } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_BASE = `${API_URL}/api`;

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const authHeaders = getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders, ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(body || `API error: ${res.status}`);
  }
  return res.json();
}

// --- Auth ---

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export function login(email: string, password: string) {
  return apiFetch<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(email: string, password: string) {
  return apiFetch<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// --- Keywords ---

export interface Keyword {
  id: string;
  phrases: string[];
  exclusions: string[];
  proximity_window: number;
  require_order: boolean;
  use_stemming: boolean;
  is_active: boolean;
  created_at: string;
}

export function getKeywords() {
  return apiFetch<Keyword[]>("/keywords");
}

export function createKeyword(data: {
  phrases: string[];
  exclusions?: string[];
  proximity_window?: number;
  require_order?: boolean;
  use_stemming?: boolean;
}) {
  return apiFetch<Keyword>("/keywords", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateKeyword(id: string, data: Partial<Keyword>) {
  return apiFetch<Keyword>(`/keywords/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteKeyword(id: string) {
  return apiFetch<void>(`/keywords/${id}`, { method: "DELETE" });
}

// --- Subreddits ---

export interface Subreddit {
  id: string;
  name: string;
  status: "active" | "inaccessible" | "private";
  include_media_posts: boolean;
  dedupe_crossposts: boolean;
  filter_bots: boolean;
  last_polled_at: string | null;
}

export function getSubreddits() {
  return apiFetch<Subreddit[]>("/subreddits");
}

export function addSubreddit(data: {
  name: string;
  include_media_posts?: boolean;
  dedupe_crossposts?: boolean;
  filter_bots?: boolean;
}) {
  return apiFetch<Subreddit>("/subreddits", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateSubreddit(id: string, data: Partial<Subreddit>) {
  return apiFetch<Subreddit>(`/subreddits/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deleteSubreddit(id: string) {
  return apiFetch<void>(`/subreddits/${id}`, { method: "DELETE" });
}

export interface SubredditSuggestion {
  name: string;
  subscribers: number;
  description: string;
}

export function searchSubreddits(query: string) {
  return apiFetch<SubredditSuggestion[]>(
    `/subreddits/search?q=${encodeURIComponent(query)}`
  );
}

// --- Webhooks ---

export interface Webhook {
  id: string;
  url: string;
  is_primary: boolean;
  is_active: boolean;
  last_tested_at: string | null;
}

export function getWebhooks() {
  return apiFetch<Webhook[]>("/webhooks");
}

export function addWebhook(data: { url: string; is_primary?: boolean }) {
  return apiFetch<Webhook>("/webhooks", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function testWebhook(id: string) {
  return apiFetch<{ success: boolean }>(`/webhooks/${id}/test`, { method: "POST" });
}

export function setPrimaryWebhook(id: string) {
  return apiFetch<Webhook>(`/webhooks/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_primary: true }),
  });
}

export function deleteWebhook(id: string) {
  return apiFetch<void>(`/webhooks/${id}`, { method: "DELETE" });
}

// --- Discord OAuth ---

export interface DiscordAuthUrl {
  auth_url: string;
  state: string;
}

export function getDiscordAuthUrl(): Promise<DiscordAuthUrl> {
  return apiFetch<DiscordAuthUrl>("/discord/auth-url");
}

export function sendDiscordGuild(guild_id: string, permissions: string, state: string): Promise<Webhook> {
  return apiFetch<Webhook>("/discord/callback", {
    method: "POST",
    body: JSON.stringify({ guild_id, permissions, state }),
  });
}

// --- Matches ---

export interface Match {
  id: string;
  keyword_id: string;
  content_id: string;
  content_type: "post" | "comment";
  subreddit: string;
  matched_phrase: string;
  also_matched: string[];
  snippet: string;
  reddit_url: string;
  reddit_author: string;
  detected_at: string;
  alert_status: "pending" | "sent" | "failed";
}

export interface MatchFilters {
  subreddit?: string;
  keyword_id?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  per_page?: number;
}

export interface PaginatedMatches {
  items: Match[];
  total: number;
  page: number;
  per_page: number;
}

export function getMatches(filters?: MatchFilters) {
  const params = new URLSearchParams();
  if (filters) {
    Object.entries(filters).forEach(([key, val]) => {
      if (val !== undefined && val !== "") params.set(key, String(val));
    });
  }
  const qs = params.toString();
  return apiFetch<PaginatedMatches>(`/matches${qs ? `?${qs}` : ""}`);
}

// --- Stats ---

export interface KeywordStat {
  keyword_id: string;
  phrases: string[];
  match_count: number;
}

export interface SubredditStat {
  subreddit: string;
  match_count: number;
}

export interface DashboardStats {
  total_matches: number;
  matches_last_24h: number;
  matches_last_7d: number;
  top_keywords: KeywordStat[];
  top_subreddits: SubredditStat[];
}

export function getStats() {
  return apiFetch<DashboardStats>("/stats");
}

// --- Client settings ---

export interface ClientSettings {
  id: string;
  email: string;
  polling_interval: number;
  created_at: string;
}

export function getSettings() {
  return apiFetch<ClientSettings>("/clients/me");
}

export function updateSettings(data: { polling_interval?: number; email?: string }) {
  return apiFetch<ClientSettings>("/clients/me", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}
