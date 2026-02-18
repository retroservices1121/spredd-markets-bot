/**
 * Platform market fetchers.
 *
 * Polymarket → Gamma API (direct, public) — handled in polymarket.ts
 * Kalshi → DFlow Metadata API (direct, no auth required)
 * Opinion, Limitless, Myriad → Bot API via background worker (need API keys)
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";
import { getBotMarkets, searchBotMarkets } from "@/lib/messaging";

// ── API base URLs ───────────────────────────────────────────

/** DFlow Metadata API — Kalshi market data (no auth required) */
const DFLOW_API = "https://c.prediction-markets-api.dflow.net";

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

// ── Kalshi (DFlow Metadata API — no auth) ───────────────────

interface DFlowMarket {
  ticker: string;
  eventTicker?: string;
  title?: string;
  question?: string;
  subtitle?: string;
  yesAsk?: string;
  noAsk?: string;
  lastYesPrice?: string;
  lastNoPrice?: string;
  volume?: number;
  openInterest?: number;
  status?: string;
  result?: string | null;
  closeTime?: string;
}

export async function fetchKalshiMarkets(limit = 20): Promise<PolymarketEvent[]> {
  // Fetch a single page of active markets (max 200 per page)
  const fetchLimit = Math.min(limit * 2, 200); // fetch extra to filter
  const url = `${DFLOW_API}/api/v1/markets?limit=${fetchLimit}&status=active`;
  const data = await fetchJson<{ markets?: DFlowMarket[]; data?: DFlowMarket[] }>(url);
  const markets = data?.markets ?? data?.data ?? [];

  return markets.slice(0, limit).map((m) => {
    const yesPrice = parseFloat(m.yesAsk ?? m.lastYesPrice ?? "") || 0.5;
    const noPrice = parseFloat(m.noAsk ?? m.lastNoPrice ?? "") || 1 - yesPrice;
    return makeEvent(
      m.ticker,
      "kalshi",
      m.title || m.question || m.ticker,
      yesPrice,
      noPrice,
      {
        description: m.subtitle,
        volume: m.volume,
        liquidity: m.openInterest,
        endDate: m.closeTime,
      }
    );
  });
}

export async function searchKalshiMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  // DFlow API has no search — fetch a large batch and filter client-side
  const all = await fetchKalshiMarkets(200);
  const q = query.toLowerCase();
  return all.filter((e) => e.title.toLowerCase().includes(q)).slice(0, limit);
}

// ── Opinion, Limitless, Myriad (via Bot API — need API keys) ─

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
  _limit = 20
): Promise<PolymarketEvent[]> {
  const res = await searchBotMarkets({ query, platform });
  if (res.success && res.data) {
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
    case "opinion":
    case "limitless":
    case "myriad":
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
    case "opinion":
    case "limitless":
    case "myriad":
      return searchViaBotApi(platform, query, limit);
    default:
      return [];
  }
}

// ── Bot API adapter (for Opinion/Limitless/Myriad + detail) ─

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
