/**
 * Platform market fetchers.
 *
 * Polymarket → Gamma API (direct, public) — handled in polymarket.ts
 * Kalshi → Public Kalshi API (direct, no auth)
 * Myriad → Myriad API v2 (direct, no auth required)
 * Opinion → Bot API via background worker (needs API key)
 * Limitless → Bot API via background worker (needs API key)
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";
import { getBotMarkets, searchBotMarkets } from "@/lib/messaging";

// ── API base URLs ───────────────────────────────────────────

/** Public Kalshi API (no auth needed for event/market listings) */
const KALSHI_PUBLIC_API = "https://api.elections.kalshi.com/trade-api/v2";

/** Myriad API v2 (no auth required for market listings) */
const MYRIAD_API = "https://api-v2.myriadprotocol.com";

// ── Shared helpers ──────────────────────────────────────────

function makeEvent(
  id: string,
  platform: Platform,
  title: string,
  yesPrice: number,
  noPrice: number,
  opts: {
    description?: string;
    image?: string;
    volume?: number;
    liquidity?: number;
    category?: string;
    endDate?: string;
  } = {}
): PolymarketEvent {
  const outcomes: MarketOutcome[] = [
    { name: "Yes", price: yesPrice || 0.5, tokenId: "" },
    { name: "No", price: noPrice || 0.5, tokenId: "" },
  ];

  const market: MarketInfo = {
    conditionId: id,
    question: title,
    outcomes,
    clobTokenIds: ["", ""],
    isNegRisk: false,
    eventSlug: `${platform}/${id}`,
  };

  return {
    id,
    slug: `${platform}/${id}`,
    title,
    description: opts.description ?? "",
    image: opts.image ?? "",
    markets: [market],
    volume: opts.volume ?? 0,
    liquidity: opts.liquidity ?? 0,
    startDate: "",
    endDate: opts.endDate ?? "",
    active: true,
    closed: false,
    category: opts.category ?? platform,
  };
}

async function fetchJson<T>(url: string, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

// ── Kalshi (Public API — no auth) ───────────────────────────

interface KalshiEvent {
  event_ticker: string;
  title?: string;
  category?: string;
  markets?: KalshiEventMarket[];
}

interface KalshiEventMarket {
  ticker: string;
  title?: string;
  subtitle?: string;
  yes_sub_title?: string;
  yes_ask?: number;
  no_ask?: number;
  last_price?: number;
  volume_24h?: number;
  volume?: number;
  open_interest?: number;
  close_time?: string;
  status?: string;
  result?: string;
}

export async function fetchKalshiMarkets(limit = 20): Promise<PolymarketEvent[]> {
  const url = `${KALSHI_PUBLIC_API}/events?status=open&limit=${Math.min(limit, 50)}`;
  const data = await fetchJson<{ events?: KalshiEvent[]; cursor?: string }>(url);
  const events = data?.events ?? [];

  const results: PolymarketEvent[] = [];
  for (const evt of events) {
    if (!evt.markets || evt.markets.length === 0) continue;
    // Use the first market in each event for the card
    const m = evt.markets[0];
    const yesPrice = (m.yes_ask ?? m.last_price ?? 50) / 100;
    const noPrice = (m.no_ask ?? (100 - (m.yes_ask ?? 50))) / 100;
    results.push(
      makeEvent(
        m.ticker,
        "kalshi",
        evt.title || m.title || m.ticker,
        yesPrice,
        noPrice,
        {
          description: m.subtitle,
          volume: m.volume_24h ?? m.volume,
          liquidity: m.open_interest,
          category: evt.category,
          endDate: m.close_time,
        }
      )
    );
    if (results.length >= limit) break;
  }
  return results;
}

export async function searchKalshiMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  // Kalshi public API has no search — fetch and filter client-side
  const all = await fetchKalshiMarkets(50);
  const q = query.toLowerCase();
  return all.filter((e) => e.title.toLowerCase().includes(q)).slice(0, limit);
}

// ── Myriad (API v2 — no auth required for listings) ────────

interface MyriadOutcome {
  id?: number;
  title?: string;
  price?: number;
}

interface MyriadMarket {
  id?: number;
  slug?: string;
  title?: string;
  description?: string;
  outcomes?: MyriadOutcome[];
  volume24h?: number;
  volume?: number;
  liquidity?: number;
  state?: string;
  expiresAt?: string;
  topics?: string[];
}

export async function fetchMyriadMarkets(limit = 20): Promise<PolymarketEvent[]> {
  const url = `${MYRIAD_API}/markets?limit=${limit}&sort=volume_24h&order=desc&state=open`;
  const data = await fetchJson<{ data?: MyriadMarket[] }>(url);
  const markets = data?.data ?? [];

  return markets.slice(0, limit).map((m) => {
    const id = m.slug || String(m.id ?? "");
    const yesPrice = m.outcomes?.[0]?.price ?? 0.5;
    const noPrice = m.outcomes?.[1]?.price ?? 0.5;
    return makeEvent(id, "myriad", m.title || "Unknown", yesPrice, noPrice, {
      description: m.description,
      volume: m.volume24h ?? m.volume,
      liquidity: m.liquidity,
      category: m.topics?.[0],
      endDate: m.expiresAt,
    });
  });
}

export async function searchMyriadMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${MYRIAD_API}/markets?keyword=${encodeURIComponent(query)}&limit=${limit}&state=open`;
  const data = await fetchJson<{ data?: MyriadMarket[] }>(url);
  const markets = data?.data ?? [];

  return markets.slice(0, limit).map((m) => {
    const id = m.slug || String(m.id ?? "");
    const yesPrice = m.outcomes?.[0]?.price ?? 0.5;
    const noPrice = m.outcomes?.[1]?.price ?? 0.5;
    return makeEvent(id, "myriad", m.title || "Unknown", yesPrice, noPrice, {
      description: m.description,
      volume: m.volume24h ?? m.volume,
      liquidity: m.liquidity,
      category: m.topics?.[0],
      endDate: m.expiresAt,
    });
  });
}

// ── Opinion & Limitless (via Bot API — need API keys) ───────

async function fetchViaBotApi(
  platform: Platform,
  limit = 20
): Promise<PolymarketEvent[]> {
  const res = await getBotMarkets({ platform, limit, active: true });
  if (res.success && res.data) {
    const data = Array.isArray(res.data) ? res.data : [];
    return botMarketsToEvents(data);
  }
  throw new Error(res.error ?? `Failed to load ${platform} markets`);
}

async function searchViaBotApi(
  platform: Platform,
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  const res = await searchBotMarkets({ query, platform });
  if (res.success && res.data) {
    // Search endpoint wraps in { markets: [...] }
    const raw = res.data as unknown;
    const arr = Array.isArray(raw)
      ? raw
      : (raw as { markets?: unknown[] })?.markets ?? [];
    return botMarketsToEvents(arr as BotApiMarket[]);
  }
  throw new Error(res.error ?? `Search failed for ${platform}`);
}

// ── Unified fetch by platform ───────────────────────────────

export async function fetchPlatformMarkets(
  platform: Platform,
  limit = 20
): Promise<PolymarketEvent[]> {
  switch (platform) {
    case "kalshi":
      return fetchKalshiMarkets(limit);
    case "myriad":
      return fetchMyriadMarkets(limit);
    case "opinion":
    case "limitless":
      return fetchViaBotApi(platform, limit);
    default:
      return [];
  }
}

export async function searchPlatformMarkets(
  platform: Platform,
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  switch (platform) {
    case "kalshi":
      return searchKalshiMarkets(query, limit);
    case "myriad":
      return searchMyriadMarkets(query, limit);
    case "opinion":
    case "limitless":
      return searchViaBotApi(platform, query, limit);
    default:
      return [];
  }
}

// ── Legacy Bot API adapter (for Opinion/Limitless + detail) ─

export interface BotApiMarket {
  id: string;
  platform: string;
  question?: string;
  title?: string;
  description?: string;
  image?: string;
  image_url?: string;
  outcomePrices?: string[];
  yes_price?: number;
  no_price?: number;
  volume?: number;
  volume24hr?: number;
  liquidity?: number;
  category?: string;
  active?: boolean;
  is_active?: boolean;
  closed?: boolean;
  endDate?: string;
  end_date?: string;
  slug?: string;
  outcomes?: string[];
}

export function botMarketToEvent(m: BotApiMarket): PolymarketEvent {
  let yesPrice = 0.5;
  let noPrice = 0.5;
  if (m.outcomePrices && m.outcomePrices.length >= 2) {
    yesPrice = parseFloat(m.outcomePrices[0]) || 0.5;
    noPrice = parseFloat(m.outcomePrices[1]) || 0.5;
  } else if (m.yes_price != null || m.no_price != null) {
    yesPrice = Number(m.yes_price) || 0.5;
    noPrice = Number(m.no_price) || 1 - yesPrice;
  }
  const displayTitle = m.question || m.title || "Unknown Market";
  return makeEvent(m.id, m.platform as Platform, displayTitle, yesPrice, noPrice, {
    description: m.description,
    image: m.image || m.image_url,
    volume: m.volume24hr ?? m.volume,
    liquidity: m.liquidity,
    category: m.category,
    endDate: m.endDate || m.end_date,
  });
}

export function botMarketsToEvents(markets: BotApiMarket[]): PolymarketEvent[] {
  if (!Array.isArray(markets)) return [];
  return markets.map(botMarketToEvent);
}
