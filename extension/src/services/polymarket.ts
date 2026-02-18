/**
 * Spredd Bot API client for market data and trading.
 *
 * Market browsing uses public endpoints (no auth).
 * Trading uses authenticated endpoints (wallet signature auth).
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

// ── Public API (Market Browsing — no auth) ─────────────────

async function apiFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ── Bot API response shapes ────────────────────────────────

interface ApiMarketResponse {
  id: string;
  question: string;
  description?: string;
  image?: string;
  icon?: string;
  category?: string;
  outcomes: string[];
  outcomePrices: string[];
  clobTokenIds: string[];
  volume?: number;
  volume24hr?: number;
  liquidity?: number;
  endDate?: string;
  startDate?: string;
  active: boolean;
  closed: boolean;
  slug?: string;
  platform: string;
  eventId?: string;
  eventTitle?: string;
  eventSlug?: string;
  isMultiOutcome?: boolean;
  outcomeCount?: number;
  groupItemTitle?: string;
  negRisk?: boolean;
  conditionId?: string;
}

interface ApiEventResponse {
  id: string;
  slug: string;
  title: string;
  description?: string;
  image?: string;
  volume?: number;
  liquidity?: number;
  startDate?: string;
  endDate?: string;
  active: boolean;
  closed: boolean;
  category?: string;
  markets: ApiMarketResponse[];
}

interface ApiOrderbookResponse {
  bids: Array<{ price: string; size: string }>;
  asks: Array<{ price: string; size: string }>;
}

function parseApiMarket(m: ApiMarketResponse, eventSlug: string): MarketInfo {
  const outcomeNames = m.outcomes ?? ["Yes", "No"];
  const outcomePrices = m.outcomePrices ?? ["0.5", "0.5"];
  const clobTokenIds = m.clobTokenIds ?? ["", ""];

  const outcomes: MarketOutcome[] = outcomeNames.map((name, i) => ({
    name,
    price: parseFloat(outcomePrices[i] ?? "0.5"),
    tokenId: clobTokenIds[i] ?? "",
  }));

  return {
    conditionId: m.conditionId ?? m.id,
    question: m.question,
    outcomes,
    clobTokenIds: [clobTokenIds[0] ?? "", clobTokenIds[1] ?? ""],
    isNegRisk: m.negRisk ?? false,
    eventSlug,
  };
}

function parseApiEvent(e: ApiEventResponse): PolymarketEvent {
  const activeMarkets = (e.markets ?? []).filter(
    (m) => m.active !== false && m.closed !== true
  );

  return {
    id: e.id,
    slug: e.slug,
    title: e.title,
    description: e.description ?? "",
    image: e.image ?? "",
    markets: activeMarkets.map((m) => parseApiMarket(m, e.slug)),
    volume: e.volume ?? 0,
    liquidity: e.liquidity ?? 0,
    startDate: e.startDate ?? "",
    endDate: e.endDate ?? "",
    active: e.active ?? true,
    closed: e.closed ?? false,
    category: e.category ?? "",
  };
}

// ── Public Market Endpoints ────────────────────────────────

/** Fetch active Polymarket events ordered by volume */
export async function fetchEvents(
  limit = 20,
  offset = 0
): Promise<PolymarketEvent[]> {
  const data = await apiFetch<ApiEventResponse[]>("/polymarket/events", {
    limit: String(limit),
    active: "true",
    order: "volume24hr",
    ascending: "false",
  });

  if (!Array.isArray(data)) return [];
  return data
    .slice(offset, offset + limit)
    .map(parseApiEvent)
    .filter((e) => e.markets.length > 0);
}

/** Search Polymarket markets by query text */
export async function searchEvents(query: string): Promise<PolymarketEvent[]> {
  const data = await apiFetch<ApiMarketResponse[]>("/polymarket/markets/search", {
    q: query,
    limit: "50",
  });

  if (!Array.isArray(data)) return [];

  // Group search results by event
  const eventMap = new Map<string, PolymarketEvent>();

  for (const m of data) {
    const eventSlug = m.eventSlug ?? m.slug ?? m.id;
    const eventId = m.eventId ?? m.id;

    if (!eventMap.has(eventId)) {
      eventMap.set(eventId, {
        id: eventId,
        slug: eventSlug,
        title: m.eventTitle ?? m.question,
        description: m.description ?? "",
        image: m.image ?? m.icon ?? "",
        markets: [],
        volume: m.volume24hr ?? m.volume ?? 0,
        liquidity: m.liquidity ?? 0,
        startDate: m.startDate ?? "",
        endDate: m.endDate ?? "",
        active: m.active,
        closed: m.closed,
        category: m.category ?? "",
      });
    }

    const event = eventMap.get(eventId)!;
    event.markets.push(parseApiMarket(m, eventSlug));
  }

  return Array.from(eventMap.values()).filter((e) => e.markets.length > 0);
}

/** Fetch a single event by slug/ID */
export async function fetchEventBySlug(
  slug: string
): Promise<PolymarketEvent | null> {
  try {
    const data = await apiFetch<ApiEventResponse>(`/polymarket/events/${slug}`);
    if (!data) return null;
    return parseApiEvent(data);
  } catch {
    return null;
  }
}

/** Get orderbook for a token via bot API */
export async function getOrderBook(tokenId: string): Promise<Orderbook> {
  const data = await apiFetch<ApiOrderbookResponse>(
    `/polymarket/price/orderbook/${tokenId}`
  );

  const bids: OrderbookLevel[] = (data.bids ?? []).map((l) => ({
    price: parseFloat(l.price),
    size: parseFloat(l.size),
  }));
  const asks: OrderbookLevel[] = (data.asks ?? []).map((l) => ({
    price: parseFloat(l.price),
    size: parseFloat(l.size),
  }));

  bids.sort((a, b) => b.price - a.price);
  asks.sort((a, b) => a.price - b.price);

  const bestBid = bids[0]?.price ?? 0;
  const bestAsk = asks[0]?.price ?? 1;
  const midPrice = (bestBid + bestAsk) / 2;
  const spread = bestAsk - bestBid;

  return { bids, asks, midPrice, spread };
}

/** Get midpoint price for a token */
export async function getMidPrice(tokenId: string): Promise<number> {
  try {
    const data = await apiFetch<{ midpoint: number }>(
      `/polymarket/clob/midpoint/${tokenId}`
    );
    return data.midpoint ?? 0.5;
  } catch {
    return 0.5;
  }
}

// ── Trade Quote Calculation (client-side from orderbook) ───

export function calculateQuote(
  orderbook: Orderbook,
  tokenId: string,
  outcome: OutcomeSelection,
  side: TradeSide,
  amount: number
): TradeQuote {
  const levels = side === "buy" ? orderbook.asks : orderbook.bids;
  let remaining = amount;
  let totalShares = 0;
  let worstPrice = 0;

  for (const level of levels) {
    if (remaining <= 0) break;

    const levelValue = level.price * level.size;
    const fill = side === "buy"
      ? Math.min(remaining, levelValue)
      : Math.min(remaining, level.size);

    if (side === "buy") {
      totalShares += fill / level.price;
      remaining -= fill;
    } else {
      totalShares += fill * level.price;
      remaining -= fill;
    }
    worstPrice = level.price;
  }

  const filled = amount - remaining;
  const avgPrice = side === "buy"
    ? (filled > 0 ? filled / totalShares : 0)
    : (totalShares > 0 ? totalShares / filled : 0);

  const estimatedPayout = side === "buy" ? totalShares : totalShares;

  return {
    tokenId,
    outcome,
    side,
    amount: filled,
    expectedOutput: totalShares,
    avgPrice,
    worstPrice,
    estimatedPayout,
  };
}
