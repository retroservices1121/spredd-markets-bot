/**
 * API client for Spredd Mini App.
 * Communicates with the FastAPI backend.
 */

const API_BASE = "/api/v1";

interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  initData?: string;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiRequest<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, initData } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Add Telegram initData for authentication
  if (initData) {
    headers["X-Telegram-Init-Data"] = initData;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new ApiError(response.status, error.detail || "Request failed");
  }

  return response.json();
}

// ===================
// User API
// ===================

export interface UserInfo {
  id: string;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  active_platform: string;
  referral_code: string | null;
  created_at: string;
}

export async function getCurrentUser(initData: string): Promise<UserInfo> {
  return apiRequest<{ user: UserInfo }>("/user/me", { initData }).then(
    (r) => r as unknown as UserInfo
  );
}

export async function setActivePlatform(
  initData: string,
  platform: string
): Promise<void> {
  await apiRequest("/user/platform", {
    method: "POST",
    body: { platform },
    initData,
  });
}

// ===================
// Wallet API
// ===================

export interface WalletBalance {
  chain_family: string;
  public_key: string;
  balances: Array<{
    token: string;
    amount: string;
    chain: string;
  }>;
}

export async function getWalletBalances(
  initData: string
): Promise<{ wallets: WalletBalance[] }> {
  return apiRequest("/wallet/balances", { initData });
}

export async function getWalletAddress(
  initData: string,
  chainFamily: string
): Promise<{ chain_family: string; public_key: string }> {
  return apiRequest(`/wallet/address/${chainFamily}`, { initData });
}

// ===================
// Markets API
// ===================

export interface MarketInfo {
  platform: string;
  id: string;
  title: string;
  yes_price: number | null;
  no_price: number | null;
  volume: string | null;
  is_active: boolean;
}

export async function searchMarkets(
  initData: string,
  query: string,
  platform?: string,
  limit?: number
): Promise<{ markets: MarketInfo[] }> {
  const params = new URLSearchParams({ q: query });
  if (platform) params.set("platform", platform);
  if (limit) params.set("limit", limit.toString());

  return apiRequest(`/markets/search?${params}`, { initData });
}

export async function getTrendingMarkets(
  initData: string,
  platform?: string,
  limit?: number
): Promise<{ markets: MarketInfo[] }> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);
  if (limit) params.set("limit", limit.toString());

  return apiRequest(`/markets/trending?${params}`, { initData });
}

export async function getMarketDetails(
  initData: string,
  platform: string,
  marketId: string
): Promise<{ market: unknown }> {
  return apiRequest(`/markets/${platform}/${marketId}`, { initData });
}

export interface Category {
  id: string;
  label: string;
  emoji: string;
}

export async function getCategories(): Promise<{ categories: Category[] }> {
  return apiRequest("/markets/categories", {});
}

export async function getMarketsByCategory(
  initData: string,
  category: string,
  limit?: number
): Promise<{ markets: MarketInfo[] }> {
  const params = new URLSearchParams();
  if (limit) params.set("limit", limit.toString());
  const queryStr = params.toString() ? `?${params}` : "";
  return apiRequest(`/markets/category/${category}${queryStr}`, { initData });
}

// ===================
// Trading API
// ===================

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
  input_amount: string;
  expected_output: string;
  price: number;
  price_impact: number | null;
  fees: Record<string, string>;
}

export async function getQuote(
  initData: string,
  request: QuoteRequest
): Promise<QuoteResponse> {
  return apiRequest("/trading/quote", {
    method: "POST",
    body: request,
    initData,
  });
}

export interface OrderRequest {
  platform: string;
  market_id: string;
  outcome: "yes" | "no";
  side: "buy" | "sell";
  amount: string;
  slippage_bps?: number;
}

export interface OrderResponse {
  order_id: string;
  status: string;
  tx_hash: string | null;
  message: string;
}

export async function executeOrder(
  initData: string,
  request: OrderRequest
): Promise<OrderResponse> {
  return apiRequest("/trading/execute", {
    method: "POST",
    body: request,
    initData,
  });
}

// ===================
// Positions API
// ===================

export interface PositionInfo {
  id: string;
  platform: string;
  market_id: string;
  market_title: string;
  outcome: string;
  token_amount: string;
  entry_price: number;
  current_price: number | null;
  status: string;
  pnl: number | null;
  created_at: string;
}

export async function getPositions(
  initData: string,
  platform?: string,
  status?: string
): Promise<{ positions: PositionInfo[] }> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);
  if (status) params.set("status", status);

  return apiRequest(`/positions?${params}`, { initData });
}

// ===================
// PnL API
// ===================

export interface PnLSummary {
  platform: string;
  total_pnl: number;
  total_trades: number;
  roi_percent: number;
  winning_trades: number;
  losing_trades: number;
}

export async function getPnLSummary(
  initData: string,
  platform?: string
): Promise<{ summaries: PnLSummary[] }> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);

  return apiRequest(`/pnl/summary?${params}`, { initData });
}

// ===================
// Referral API
// ===================

export interface ReferralStats {
  referral_code: string | null;
  total_referrals: number;
  fee_balances: Array<{
    chain_family: string;
    claimable_usdc: string;
    total_earned_usdc: string;
    total_withdrawn_usdc: string;
  }>;
}

export async function getReferralStats(initData: string): Promise<ReferralStats> {
  return apiRequest("/referral/stats", { initData });
}

// ===================
// Bridge API
// ===================

export interface BridgeChain {
  id: string;
  name: string;
  balance: string;
  has_balance: boolean;
}

export interface BridgeChainsResponse {
  chains: BridgeChain[];
  wallet_address: string | null;
  dest_chain: string;
}

export async function getBridgeChains(initData: string): Promise<BridgeChainsResponse> {
  return apiRequest("/bridge/chains", { initData });
}

export interface BridgeQuoteRequest {
  source_chain: string;
  amount: string;
}

export interface BridgeQuoteResponse {
  source_chain: string;
  dest_chain: string;
  amount: string;
  fast_bridge: {
    output_amount: string;
    fee_amount: string;
    fee_percent: number;
    estimated_time: string;
    available: boolean;
    error?: string;
  } | null;
  standard_bridge: {
    output_amount: string;
    fee_amount: string;
    fee_percent: number;
    estimated_time: string;
    available: boolean;
  } | null;
}

export async function getBridgeQuote(
  initData: string,
  request: BridgeQuoteRequest
): Promise<BridgeQuoteResponse> {
  return apiRequest("/bridge/quote", {
    method: "POST",
    body: request,
    initData,
  });
}

export interface BridgeExecuteRequest {
  source_chain: string;
  amount: string;
  mode: "fast" | "standard";
}

export interface BridgeExecuteResponse {
  success: boolean;
  source_chain: string;
  dest_chain: string;
  amount: string;
  tx_hash: string | null;
  message: string;
}

export async function executeBridge(
  initData: string,
  request: BridgeExecuteRequest
): Promise<BridgeExecuteResponse> {
  return apiRequest("/bridge/execute", {
    method: "POST",
    body: request,
    initData,
  });
}
