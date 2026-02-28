const API_BASE = "/api/v1";

function getToken(): string | null {
  return localStorage.getItem("spredd_token");
}

export function setToken(token: string) {
  localStorage.setItem("spredd_token", token);
}

export function clearToken() {
  localStorage.removeItem("spredd_token");
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

// ── Auth ──

export interface LoginResponse {
  token: string;
  user: {
    id: string;
    telegram_id: number;
    username?: string;
    first_name?: string;
  };
}

export async function telegramLogin(
  data: Record<string, string>
): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/telegram-login", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── Markets / Feed ──

export interface FeedMarket {
  id: string;
  platform: string;
  title: string;
  image?: string;
  yes_price: number;
  no_price: number;
  volume?: number;
  category?: string;
  end_date?: string;
  creator?: {
    username: string;
    avatar?: string;
  };
}

export interface FeedResponse {
  markets: FeedMarket[];
  next_cursor: number | null;
}

export async function getFeed(
  cursor?: number,
  limit = 20
): Promise<FeedResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor != null) params.set("cursor", String(cursor));
  return request<FeedResponse>(`/markets/feed?${params}`);
}

export async function getMarketDetail(
  platform: string,
  marketId: string
): Promise<Record<string, unknown>> {
  return request(`/markets/${platform}/${encodeURIComponent(marketId)}`);
}

// ── Trading ──

export interface QuoteRequest {
  platform: string;
  market_id: string;
  outcome: "yes" | "no";
  side: "buy" | "sell";
  amount: string;
}

export interface QuoteResponse {
  platform: string;
  market_id: string;
  outcome: string;
  side: string;
  amount: string;
  price: number;
  expected_output: string;
  fees?: Record<string, string>;
  price_impact?: number;
}

export async function getQuote(req: QuoteRequest): Promise<QuoteResponse> {
  return request<QuoteResponse>("/trade/quote", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export interface TradeRequest {
  platform: string;
  market_id: string;
  outcome: "yes" | "no";
  side: "buy" | "sell";
  amount: string;
  slippage_bps?: number;
}

export interface TradeResponse {
  success: boolean;
  order_id?: string;
  tx_hash?: string;
  message?: string;
  error?: string;
}

export async function executeTrade(
  req: TradeRequest
): Promise<TradeResponse> {
  return request<TradeResponse>("/trade/execute", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ── Positions ──

export interface Position {
  id: string;
  platform: string;
  market_id: string;
  market_title: string;
  outcome: string;
  token_amount: number;
  entry_price: number;
  current_price: number;
  status: "open" | "closed" | "won" | "lost";
  pnl: number;
  created_at: string;
}

export async function getPositions(
  status?: string
): Promise<{ positions: Position[] }> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  return request(`/positions?${params}`);
}

// ── User ──

export interface UserInfo {
  id: string;
  telegram_id: number;
  username?: string;
  first_name?: string;
  active_platform: string;
  referral_code?: string;
  created_at: string;
  avatar?: string;
}

export async function getUserInfo(): Promise<UserInfo> {
  return request<UserInfo>("/user/me");
}

export interface WalletBalance {
  chain_family: string;
  public_key: string;
  balances: Array<{ token: string; balance: string; usd_value?: string }>;
}

export async function getBalances(): Promise<{ balances: WalletBalance[] }> {
  return request("/user/balances");
}

// ── Categories ──

export interface Category {
  id: string;
  name: string;
  icon?: string;
}

export async function getCategories(): Promise<{ categories: Category[] }> {
  return request("/markets/categories");
}

// ── Trending ──

export async function getTrending(limit = 10): Promise<{ markets: FeedMarket[] }> {
  return request(`/markets/trending?limit=${limit}`);
}

// ── Category Markets ──

export async function getMarketsByCategory(
  category: string,
  page = 1,
  limit = 10
): Promise<{ markets: FeedMarket[]; total: number; has_more: boolean }> {
  const params = new URLSearchParams({
    category,
    page: String(page),
    limit: String(limit),
  });
  return request(`/markets?${params}`);
}

// ── Search ──

export async function searchMarkets(
  query: string,
  page = 1,
  limit = 10
): Promise<{ markets: FeedMarket[]; total: number; has_more: boolean }> {
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    limit: String(limit),
  });
  return request(`/markets/search?${params}`);
}

// ── PnL Summary ──

export interface PnlSummary {
  total_pnl: number;
  win_rate: number;
  active_positions: number;
  win_streak: number;
  total_trades: number;
  total_invested: number;
}

export async function getPnlSummary(): Promise<PnlSummary> {
  return request<PnlSummary>("/user/pnl/summary");
}

// ── Pagination ──

export interface Pagination {
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
}

// ── Leaderboard (mock-ready) ──

export interface LeaderboardEntry {
  rank: number;
  user_id: string;
  username: string;
  avatar?: string;
  pnl: number;
  win_rate: number;
  total_trades: number;
}

export async function getLeaderboard(
  period: "24h" | "7d" | "30d" | "all" = "7d",
  sort: "profit" | "win_rate" = "profit",
  limit = 50
): Promise<{ entries: LeaderboardEntry[] }> {
  const params = new URLSearchParams({ period, sort, limit: String(limit) });
  try {
    return await request(`/leaderboard?${params}`);
  } catch {
    // Mock data until endpoint exists
    return {
      entries: [
        { rank: 1, user_id: "1", username: "CryptoKing", pnl: 12450.50, win_rate: 0.78, total_trades: 142 },
        { rank: 2, user_id: "2", username: "MarketWhiz", pnl: 8920.30, win_rate: 0.72, total_trades: 98 },
        { rank: 3, user_id: "3", username: "PredictionPro", pnl: 6780.00, win_rate: 0.69, total_trades: 205 },
        { rank: 4, user_id: "4", username: "AlphaTrader", pnl: 5430.25, win_rate: 0.65, total_trades: 87 },
        { rank: 5, user_id: "5", username: "BetMaster", pnl: 4210.80, win_rate: 0.71, total_trades: 156 },
        { rank: 6, user_id: "6", username: "OracleX", pnl: 3890.15, win_rate: 0.62, total_trades: 134 },
        { rank: 7, user_id: "7", username: "Forecaster", pnl: 3120.40, win_rate: 0.68, total_trades: 76 },
        { rank: 8, user_id: "8", username: "EdgeSeeker", pnl: 2450.90, win_rate: 0.59, total_trades: 112 },
        { rank: 9, user_id: "9", username: "SharpBet", pnl: 1980.60, win_rate: 0.64, total_trades: 95 },
        { rank: 10, user_id: "10", username: "DeltaHunter", pnl: 1540.20, win_rate: 0.57, total_trades: 188 },
      ],
    };
  }
}

// ── Comments (mock-ready) ──

export interface Comment {
  id: string;
  user_id: string;
  username: string;
  avatar?: string;
  text: string;
  created_at: string;
  likes: number;
}

export async function getComments(
  marketId: string
): Promise<{ comments: Comment[] }> {
  try {
    return await request(`/comments/${marketId}`);
  } catch {
    return { comments: [] };
  }
}

export async function postComment(
  marketId: string,
  text: string
): Promise<Comment> {
  return request(`/comments/${marketId}`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

// ── Bookmarks (mock-ready) ──

export async function getBookmarks(): Promise<{ markets: FeedMarket[] }> {
  try {
    return await request("/bookmarks");
  } catch {
    return { markets: [] };
  }
}

export async function toggleBookmark(
  platform: string,
  marketId: string
): Promise<{ bookmarked: boolean }> {
  return request("/bookmarks", {
    method: "POST",
    body: JSON.stringify({ platform, market_id: marketId }),
  });
}

// ── Follow (mock-ready) ──

export async function followUser(
  userId: string
): Promise<{ following: boolean }> {
  return request("/follow", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function getFollowing(): Promise<{ users: Array<{ user_id: string; username: string; avatar?: string }> }> {
  try {
    return await request("/following");
  } catch {
    return { users: [] };
  }
}

// ── Submit Event (mock-ready) ──

export interface SubmitEventRequest {
  question: string;
  description: string;
  category: string;
  end_date: string;
  resolution_source?: string;
}

export async function submitEvent(
  data: SubmitEventRequest
): Promise<{ success: boolean; event_id?: string }> {
  return request("/markets/submit", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ── User Settings (mock-ready) ──

export interface UserSettings {
  notifications_enabled: boolean;
  notifications_trades: boolean;
  notifications_price_alerts: boolean;
  notifications_social: boolean;
  language: string;
  currency: string;
  timezone: string;
  two_factor_enabled: boolean;
}

export async function getUserSettings(): Promise<UserSettings> {
  try {
    return await request<UserSettings>("/user/settings");
  } catch {
    return {
      notifications_enabled: true,
      notifications_trades: true,
      notifications_price_alerts: true,
      notifications_social: false,
      language: "en",
      currency: "USD",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      two_factor_enabled: false,
    };
  }
}

export async function updateUserSettings(
  settings: Partial<UserSettings>
): Promise<UserSettings> {
  return request<UserSettings>("/user/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}
