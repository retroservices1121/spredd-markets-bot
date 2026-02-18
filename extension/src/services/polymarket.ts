/**
 * Spredd Bot API client for market data and trading.
 *
 * Market browsing uses public endpoints (no auth).
 * Trading uses authenticated endpoints (wallet signature auth via background worker).
 */

import type {
  PolymarketEvent,
  MarketInfo,
  MarketOutcome,
  Orderbook,
  OrderbookLevel,
  TradeQuote,
  TradeSide,
  OutcomeSelection,
} from "@/core/markets";

// ── API Base URL ───────────────────────────────────────────

export const API_BASE = "https://spredd-markets-bot-production.up.railway.app";

// ── Generic fetch helper ───────────────────────────────────

async function apiFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`API returned non-JSON response`);
  }
}

// ── Bot API response shape from /api/v1/markets ────────────

interface ApiMarketItem {
  id: string;
  platform: string;
  question: string;
  description?: string;
  image?: string;
  category?: string;
  outcomes: string[];
  outcomePrices: string[];
  volume?: number;
  volume24hr?: number;
  liquidity?: number;
  endDate?: string;
  slug?: string;
  active?: boolean;
}

/**
 * Convert a flat market item from the API into our PolymarketEvent shape.
 * Since the bot API returns flat markets (no event grouping), each market
 * becomes its own "event" with a single market inside.
 */
function apiMarketToEvent(m: ApiMarketItem): PolymarketEvent {
  const outcomeNames = m.outcomes ?? ["Yes", "No"];
  const outcomePrices = m.outcomePrices ?? ["0.5", "0.5"];

  const outcomes: MarketOutcome[] = outcomeNames.map((name, i) => ({
    name,
    price: parseFloat(outcomePrices[i] ?? "0.5"),
    tokenId: "", // Not available from this endpoint
  }));

  const market: MarketInfo = {
    conditionId: m.id,
    question: m.question,
    outcomes,
    clobTokenIds: ["", ""],
    isNegRisk: false,
    eventSlug: m.slug ?? m.id,
  };

  return {
    id: m.id,
    slug: m.slug ?? m.id,
    title: m.question,
    description: m.description ?? "",
    image: m.image ?? "",
    markets: [market],
    volume: m.volume24hr ?? m.volume ?? 0,
    liquidity: m.liquidity ?? 0,
    startDate: "",
    endDate: m.endDate ?? "",
    active: m.active ?? true,
    closed: false,
    category: m.category ?? "",
  };
}

// ── Public Market Endpoints ────────────────────────────────

/** Fetch active Polymarket markets ordered by volume */
export async function fetchEvents(
  limit = 20,
  _offset = 0
): Promise<PolymarketEvent[]> {
  const data = await apiFetch<ApiMarketItem[]>("/api/v1/markets", {
    platform: "polymarket",
    limit: String(limit),
    active: "true",
  });

  if (!Array.isArray(data)) return [];
  return data.map(apiMarketToEvent);
}

/** Search Polymarket markets by query text */
export async function searchEvents(query: string): Promise<PolymarketEvent[]> {
  const data = await apiFetch<{ markets: ApiSearchResult[] }>("/api/v1/markets/search", {
    q: query,
    platform: "polymarket",
    limit: "50",
  });

  const markets = data.markets ?? [];
  return markets.map((m) => {
    const yesPrice = m.yes_price ?? 0.5;
    const noPrice = m.no_price ?? 0.5;

    const outcomes: MarketOutcome[] = [
      { name: "Yes", price: yesPrice, tokenId: "" },
      { name: "No", price: noPrice, tokenId: "" },
    ];

    const market: MarketInfo = {
      conditionId: m.id,
      question: m.title,
      outcomes,
      clobTokenIds: ["", ""],
      isNegRisk: false,
      eventSlug: m.id,
    };

    return {
      id: m.id,
      slug: m.id,
      title: m.title,
      description: "",
      image: "",
      markets: [market],
      volume: parseFloat(m.volume ?? "0"),
      liquidity: 0,
      startDate: "",
      endDate: "",
      active: m.is_active ?? true,
      closed: false,
      category: "",
    } as PolymarketEvent;
  });
}

interface ApiSearchResult {
  platform: string;
  id: string;
  title: string;
  yes_price?: number;
  no_price?: number;
  volume?: string;
  is_active?: boolean;
}

/** Fetch a single market by ID via the webapp route */
export async function fetchEventBySlug(
  slug: string
): Promise<PolymarketEvent | null> {
  try {
    const data = await apiFetch<{ market: ApiMarketDetail }>(`/markets/${encodeURIComponent(slug)}`);
    const m = data.market;
    if (!m) return null;

    const yesPrice = m.yes_price ?? 0.5;
    const noPrice = m.no_price ?? 0.5;

    const outcomes: MarketOutcome[] = [
      { name: "Yes", price: yesPrice, tokenId: "" },
      { name: "No", price: noPrice, tokenId: "" },
    ];

    const market: MarketInfo = {
      conditionId: m.market_id,
      question: m.title,
      outcomes,
      clobTokenIds: ["", ""],
      isNegRisk: false,
      eventSlug: m.slug ?? m.market_id,
    };

    return {
      id: m.market_id,
      slug: m.slug ?? m.market_id,
      title: m.title,
      description: m.description ?? "",
      image: m.image ?? "",
      markets: [market],
      volume: parseFloat(m.volume_24h ?? "0"),
      liquidity: parseFloat(m.liquidity ?? "0"),
      startDate: "",
      endDate: m.close_time ?? "",
      active: m.is_active ?? true,
      closed: false,
      category: m.category ?? "",
    };
  } catch {
    return null;
  }
}

interface ApiMarketDetail {
  market_id: string;
  platform: string;
  title: string;
  description?: string;
  image?: string;
  category?: string;
  yes_price?: number;
  no_price?: number;
  volume_24h?: string;
  liquidity?: string;
  is_active?: boolean;
  close_time?: string;
  slug?: string;
  outcomes?: string[];
}

// ── Orderbook (not available via bot API — use prices from market data) ──

/** Stub: the bot API doesn't expose raw orderbooks, so we synthesize from market prices */
export async function getOrderBook(tokenId: string): Promise<Orderbook> {
  // Without orderbook data, return empty book
  // The quote will come from the bot API server-side instead
  return {
    bids: [],
    asks: [],
    midPrice: 0.5,
    spread: 0,
  };
}

/** Get midpoint price — not separately available, use market data */
export async function getMidPrice(_tokenId: string): Promise<number> {
  return 0.5;
}

// ── Trade Quote Calculation ─────────────────────────────────

/**
 * Simple quote estimate from market price (no orderbook available).
 * The actual quote comes from the bot API server-side.
 * This is just for the UI preview.
 */
export function calculateQuote(
  _orderbook: Orderbook,
  tokenId: string,
  outcome: OutcomeSelection,
  side: TradeSide,
  amount: number,
  marketPrice?: number
): TradeQuote {
  // Use market price for a simple estimate
  const price = marketPrice ?? 0.5;
  const shares = side === "buy" ? amount / price : amount;
  const payout = side === "buy" ? shares : shares * price;

  return {
    tokenId,
    outcome,
    side,
    amount,
    expectedOutput: shares,
    avgPrice: price,
    worstPrice: price,
    estimatedPayout: payout,
  };
}
