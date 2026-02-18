/**
 * Polymarket market data via Gamma API (public, no auth).
 * Trading goes through the Spredd Bot API (authenticated via background worker).
 */

import type {
  PolymarketEvent,
  MarketInfo,
  MarketOutcome,
  Orderbook,
  TradeQuote,
  TradeSide,
  OutcomeSelection,
} from "@/core/markets";

// ── API Base URLs ─────────────────────────────────────────

/** Gamma API — public market data (events, markets, prices) */
const GAMMA_API = "https://gamma-api.polymarket.com";

/** Spredd Bot API — authenticated trading */
export const API_BASE = "https://spredd-markets-bot-production.up.railway.app";

// ── Gamma API response shapes ─────────────────────────────

interface GammaMarket {
  id: string;
  conditionId: string;
  question: string;
  groupItemTitle?: string;
  active: boolean;
  closed: boolean;
  endDate?: string;
  eventSlug?: string;
  slug?: string;
  outcomePrices: string | number[];
  lastTradePrice?: number;
  clobTokenIds: string | string[];
  volume?: number;
  volumeNum?: number;
  liquidity?: number;
  description?: string;
}

interface GammaEvent {
  id: string;
  slug: string;
  title: string;
  description?: string;
  image?: string;
  active: boolean;
  closed: boolean;
  endDate?: string;
  volume?: number;
  volume24hr?: number;
  liquidity?: number;
  liquidityClob?: number;
  tags?: { label: string; slug: string }[];
  markets: GammaMarket[];
}

// ── Gamma → internal type conversion ──────────────────────

function parseTokenIds(raw: string | string[]): string[] {
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as string[];
    } catch {
      return [];
    }
  }
  return Array.isArray(raw) ? raw : [];
}

function parsePrices(raw: string | number[]): number[] {
  if (typeof raw === "string") {
    try {
      return (JSON.parse(raw) as unknown[]).map(Number);
    } catch {
      return [];
    }
  }
  return Array.isArray(raw) ? raw.map(Number) : [];
}

function gammaEventToLocal(e: GammaEvent): PolymarketEvent {
  const markets: MarketInfo[] = (e.markets ?? []).map((m) => {
    const tokens = parseTokenIds(m.clobTokenIds);
    const prices = parsePrices(m.outcomePrices);

    const yesPrice = prices[0] ?? m.lastTradePrice ?? 0.5;
    const noPrice = prices[1] ?? 1 - yesPrice;

    const outcomes: MarketOutcome[] = [
      { name: "Yes", price: yesPrice, tokenId: tokens[0] ?? "" },
      { name: "No", price: noPrice, tokenId: tokens[1] ?? "" },
    ];

    return {
      conditionId: m.conditionId || m.id,
      question: m.groupItemTitle || m.question,
      outcomes,
      clobTokenIds: [tokens[0] ?? "", tokens[1] ?? ""] as [string, string],
      isNegRisk: false,
      eventSlug: m.eventSlug || e.slug,
    };
  });

  return {
    id: e.id,
    slug: e.slug,
    title: e.title,
    description: e.description ?? "",
    image: e.image ?? "",
    markets,
    volume: e.volume24hr ?? e.volume ?? 0,
    liquidity: e.liquidityClob ?? e.liquidity ?? 0,
    startDate: "",
    endDate: e.endDate ?? "",
    active: e.active ?? true,
    closed: e.closed ?? false,
    category: e.tags?.[0]?.label ?? "",
  };
}

// ── Gamma API helpers ─────────────────────────────────────

async function gammaFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, GAMMA_API);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`Gamma API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ── Public Market Endpoints (Gamma API) ───────────────────

/** Fetch active Polymarket events ordered by 24h volume */
export async function fetchEvents(
  limit = 20,
  offset = 0
): Promise<PolymarketEvent[]> {
  const data = await gammaFetch<GammaEvent[]>("/events", {
    limit: String(limit),
    offset: String(offset),
    active: "true",
    closed: "false",
    order: "volume24hr",
    ascending: "false",
  });

  if (!Array.isArray(data)) return [];
  return data.map(gammaEventToLocal);
}

/** Search Polymarket events by title */
export async function searchEvents(query: string): Promise<PolymarketEvent[]> {
  const data = await gammaFetch<GammaEvent[]>("/events", {
    title: query,
    limit: "50",
    active: "true",
    closed: "false",
  });

  if (!Array.isArray(data)) return [];
  return data.map(gammaEventToLocal);
}

/** Fetch a single event by slug */
export async function fetchEventBySlug(
  slug: string
): Promise<PolymarketEvent | null> {
  try {
    const data = await gammaFetch<GammaEvent[]>("/events", { slug });
    if (!Array.isArray(data) || data.length === 0) return null;
    return gammaEventToLocal(data[0]);
  } catch {
    return null;
  }
}

// ── Trade Quote Calculation ─────────────────────────────────

/**
 * Simple client-side quote estimate from market price.
 * The actual execution goes through the Bot API server-side.
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
