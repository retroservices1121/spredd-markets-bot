/**
 * Direct public API fetchers for each prediction market platform.
 * Market data is fetched directly from each platform's public API —
 * no auth or Bot API needed. Only trading goes through the Bot API.
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";

// ── Platform API base URLs ──────────────────────────────────

const KALSHI_API = "https://c.prediction-markets-api.dflow.net";
const OPINION_API = "https://proxy.opinion.trade:8443";
const MYRIAD_API = "https://myriad.markets";
// Limitless uses its own REST API
const LIMITLESS_API = "https://api.limitless.exchange";

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

async function fetchWithTimeout<T>(
  url: string,
  timeoutMs = 10000
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
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

// ── Kalshi (DFlow Metadata API) ─────────────────────────────

interface KalshiMarket {
  ticker: string;
  eventTicker?: string;
  title?: string;
  question?: string;
  subtitle?: string;
  yesAsk?: string;
  noAsk?: string;
  volume?: number;
  openInterest?: number;
  status?: string;
  result?: string | null;
  closeTime?: string;
}

export async function fetchKalshiMarkets(
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${KALSHI_API}/api/v1/markets?limit=${Math.min(limit, 200)}&status=active`;
  const data = await fetchWithTimeout<{ markets?: KalshiMarket[] }>(url);
  const markets = data?.markets ?? [];

  return markets.slice(0, limit).map((m) => {
    const yesPrice = parseFloat(m.yesAsk ?? "") || 0.5;
    const noPrice = parseFloat(m.noAsk ?? "") || 1 - yesPrice;
    return makeEvent(m.ticker, "kalshi", m.title || m.question || m.ticker, yesPrice, noPrice, {
      description: m.subtitle,
      volume: m.volume,
      liquidity: m.openInterest,
      endDate: m.closeTime,
    });
  });
}

export async function searchKalshiMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  // Kalshi has no search endpoint — fetch and filter client-side
  const all = await fetchKalshiMarkets(200);
  const q = query.toLowerCase();
  return all
    .filter((e) => e.title.toLowerCase().includes(q))
    .slice(0, limit);
}

// ── Opinion (proxy.opinion.trade) ───────────────────────────

interface OpinionMarket {
  marketId?: string;
  id?: string;
  marketTitle?: string;
  title?: string;
  rules?: string;
  description?: string;
  tokens?: { price?: number; tokenId?: string }[];
  yesPrice?: number;
  noPrice?: number;
  volume24h?: number;
  volume?: number;
  liquidity?: number;
  statusEnum?: string;
  cutoffAt?: number;
  endTime?: string;
}

export async function fetchOpinionMarkets(
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${OPINION_API}/openapi/market?limit=${limit}&offset=0&sortBy=5&status=activated`;
  const data = await fetchWithTimeout<{ result?: { list?: OpinionMarket[] } }>(url);
  const markets = data?.result?.list ?? [];

  return markets.slice(0, limit).map((m) => {
    const id = m.marketId || m.id || "";
    const title = m.marketTitle || m.title || "Unknown";
    const yesPrice = m.tokens?.[0]?.price ?? m.yesPrice ?? 0.5;
    const noPrice = m.tokens?.[1]?.price ?? m.noPrice ?? 0.5;
    const endDate = m.cutoffAt
      ? new Date(m.cutoffAt * 1000).toISOString()
      : m.endTime ?? "";

    return makeEvent(id, "opinion", title, yesPrice, noPrice, {
      description: m.rules || m.description,
      volume: m.volume24h ?? m.volume,
      liquidity: m.liquidity,
      endDate,
    });
  });
}

export async function searchOpinionMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${OPINION_API}/openapi/market?keyword=${encodeURIComponent(query)}&limit=${limit}&offset=0`;
  const data = await fetchWithTimeout<{ result?: { list?: OpinionMarket[] } }>(url);
  const markets = data?.result?.list ?? [];

  return markets.slice(0, limit).map((m) => {
    const id = m.marketId || m.id || "";
    const title = m.marketTitle || m.title || "Unknown";
    const yesPrice = m.tokens?.[0]?.price ?? m.yesPrice ?? 0.5;
    const noPrice = m.tokens?.[1]?.price ?? m.noPrice ?? 0.5;
    return makeEvent(id, "opinion", title, yesPrice, noPrice, {
      description: m.rules || m.description,
      volume: m.volume24h ?? m.volume,
      liquidity: m.liquidity,
    });
  });
}

// ── Myriad (myriad.markets) ─────────────────────────────────

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

export async function fetchMyriadMarkets(
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${MYRIAD_API}/markets?limit=${limit}&sort=volume_24h&order=desc&state=open`;
  const data = await fetchWithTimeout<{ data?: MyriadMarket[] }>(url);
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
  const data = await fetchWithTimeout<{ data?: MyriadMarket[] }>(url);
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

// ── Limitless (api.limitless.exchange) ──────────────────────

interface LimitlessMarket {
  id?: string;
  slug?: string;
  title?: string;
  description?: string;
  volume24h?: number;
  volume?: number;
  liquidity?: number;
  expiresAt?: string;
  prices?: number[];
  outcomes?: { name?: string; price?: number }[];
  category?: string;
}

export async function fetchLimitlessMarkets(
  limit = 20
): Promise<PolymarketEvent[]> {
  const url = `${LIMITLESS_API}/markets?limit=${limit}&sort=volume24h&order=desc&status=active`;
  const data = await fetchWithTimeout<LimitlessMarket[] | { data?: LimitlessMarket[] }>(url);
  const markets = Array.isArray(data) ? data : (data as { data?: LimitlessMarket[] })?.data ?? [];

  return markets.slice(0, limit).map((m) => {
    const id = m.slug || m.id || "";
    let yesPrice = 0.5;
    let noPrice = 0.5;
    if (m.prices && m.prices.length >= 2) {
      yesPrice = m.prices[0] ?? 0.5;
      noPrice = m.prices[1] ?? 0.5;
    } else if (m.outcomes && m.outcomes.length >= 2) {
      yesPrice = m.outcomes[0]?.price ?? 0.5;
      noPrice = m.outcomes[1]?.price ?? 0.5;
    }
    return makeEvent(id, "limitless", m.title || "Unknown", yesPrice, noPrice, {
      description: m.description,
      volume: m.volume24h ?? m.volume,
      liquidity: m.liquidity,
      category: m.category,
      endDate: m.expiresAt,
    });
  });
}

export async function searchLimitlessMarkets(
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  // Limitless may not have search — fetch and filter client-side
  const all = await fetchLimitlessMarkets(100);
  const q = query.toLowerCase();
  return all
    .filter((e) => e.title.toLowerCase().includes(q))
    .slice(0, limit);
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
      return fetchOpinionMarkets(limit);
    case "myriad":
      return fetchMyriadMarkets(limit);
    case "limitless":
      return fetchLimitlessMarkets(limit);
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
      return searchOpinionMarkets(query, limit);
    case "myriad":
      return searchMyriadMarkets(query, limit);
    case "limitless":
      return searchLimitlessMarkets(query, limit);
    default:
      return [];
  }
}

// ── Legacy Bot API adapter (kept for market detail fallback) ─

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
