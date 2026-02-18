/** Market and trade types */

/** Supported prediction market platforms */
export type Platform = "polymarket" | "kalshi" | "opinion" | "limitless" | "myriad";

/** Platform display metadata */
export interface PlatformMeta {
  id: Platform;
  label: string;
  chain: string;
  currency: string;
}

/** All supported platforms with display info */
export const PLATFORMS: PlatformMeta[] = [
  { id: "polymarket", label: "Polymarket", chain: "Polygon", currency: "USDC.e" },
  { id: "kalshi", label: "Kalshi", chain: "N/A", currency: "USD" },
  { id: "opinion", label: "Opinion", chain: "Solana", currency: "USDC" },
  { id: "limitless", label: "Limitless", chain: "Base", currency: "USDC" },
  { id: "myriad", label: "Myriad", chain: "BSC", currency: "USDT" },
];

/** A single outcome (Yes/No) within a market */
export interface MarketOutcome {
  name: string;
  price: number; // 0-1 probability
  tokenId: string; // CLOB token ID for trading
}

/** A single binary market (condition) */
export interface MarketInfo {
  conditionId: string;
  question: string;
  outcomes: MarketOutcome[];
  /** CLOB token IDs: [yes, no] */
  clobTokenIds: [string, string];
  /** Whether this is a neg-risk market */
  isNegRisk: boolean;
  /** Parent event slug */
  eventSlug: string;
}

/** Top-level event grouping one or more markets */
export interface PolymarketEvent {
  id: string;
  slug: string;
  title: string;
  description: string;
  image: string;
  markets: MarketInfo[];
  volume: number;
  liquidity: number;
  startDate: string;
  endDate: string;
  active: boolean;
  closed: boolean;
  /** Category/tag */
  category: string;
}

/** Side of a trade */
export type TradeSide = "buy" | "sell";

/** Outcome selection */
export type OutcomeSelection = "yes" | "no";

/** Orderbook level */
export interface OrderbookLevel {
  price: number;
  size: number;
}

/** Orderbook for a token */
export interface Orderbook {
  bids: OrderbookLevel[];
  asks: OrderbookLevel[];
  midPrice: number;
  spread: number;
}

/** Trade quote calculated from orderbook */
export interface TradeQuote {
  tokenId: string;
  outcome: OutcomeSelection;
  side: TradeSide;
  amount: number; // USD input
  expectedOutput: number; // shares output
  avgPrice: number;
  worstPrice: number;
  estimatedPayout: number; // max payout if resolved in favor
  platform?: Platform;
  priceImpact?: number; // percentage
  fees?: Record<string, string>;
}

/** Quote response from Bot API */
export interface BotQuoteResponse {
  platform: string;
  market_id: string;
  outcome: string;
  side: string;
  input_amount: string;
  expected_output: string;
  price: number;
  price_impact?: number;
  fees: Record<string, string>;
}

/** Order response from Bot API */
export interface BotOrderResponse {
  order_id: string;
  status: string;
  tx_hash?: string;
  message: string;
}

/** Result of a submitted trade (UI-facing) */
export interface TradeResult {
  success: boolean;
  orderId?: string;
  txHash?: string;
  message?: string;
  errorMessage?: string;
}

/** A user's position on a market */
export interface Position {
  id: string;
  platform: Platform;
  market_id: string;
  market_title: string;
  outcome: string;
  token_amount: number;
  entry_price: number;
  current_price: number;
  status: "open" | "closed" | "settled";
  pnl: number;
  created_at: string;
}

/** P&L summary for a platform or aggregated */
export interface PnlSummaryData {
  platform: string;
  total_pnl: number;
  total_trades: number;
  roi_percent: number;
  winning_trades: number;
  losing_trades: number;
  total_invested: number;
}
