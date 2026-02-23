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
