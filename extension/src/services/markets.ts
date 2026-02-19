/**
 * Platform market fetchers.
 *
 * Polymarket → Gamma API (direct, public) — handled in polymarket.ts
 * All others → background worker fetches directly from each platform's API.
 *              API keys are served by Bot API at unlock time, never in source code.
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";
import {
  getBotMarkets,
  searchBotMarkets,
  fetchPlatformMarketsDirect,
  searchPlatformMarketsDirect,
} from "@/lib/messaging";
import { classifyCategory } from "@/lib/categories";

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
    category: classifyCategory(title, opts.category) || platform,
  };
}

// ── Raw response → BotApiMarket normalizers per platform ──────

type RawMarket = Record<string, unknown>;

function normalizeKalshi(m: RawMarket): BotApiMarket {
  const yesPrice = parseFloat(String(m.yesAsk ?? m.lastYesPrice ?? "")) || 0.5;
  const ticker = String(m.ticker ?? m.market_id ?? "");
  const eventTicker = String(m.eventTicker ?? m.event_ticker ?? "");
  const title = String(m.title || m.question || m.ticker || "");
  return {
    id: ticker,
    platform: "kalshi",
    question: title,
    description: String(m.subtitle ?? ""),
    yes_price: yesPrice,
    no_price: parseFloat(String(m.noAsk ?? m.lastNoPrice ?? "")) || 1 - yesPrice,
    volume: Number(m.volume ?? 0),
    liquidity: Number(m.openInterest ?? 0),
    endDate: String(m.closeTime ?? ""),
    event_id: eventTicker,
    is_multi_outcome: false, // will be detected by grouping logic
    outcome_name: String(m.yesSubtitle ?? m.subtitle ?? ""),
    category: classifyCategory(title, undefined, eventTicker || ticker),
  };
}

function normalizeOpinion(m: RawMarket): BotApiMarket {
  // Opinion API uses "tokens" array with price per outcome
  const tokens = m.tokens as { outcome?: string; index?: number; price?: number }[] | undefined;
  let yesPrice = 0.5;
  let noPrice = 0.5;
  if (tokens && tokens.length >= 2) {
    for (const t of tokens) {
      const outcome = String(t.outcome ?? "").toLowerCase();
      if (outcome === "yes" || t.index === 0) yesPrice = Number(t.price ?? 0.5);
      if (outcome === "no" || t.index === 1) noPrice = Number(t.price ?? 0.5);
    }
  } else {
    yesPrice = Number(m.yesPrice ?? m.yes_price ?? 0.5);
    noPrice = Number(m.noPrice ?? m.no_price ?? 0.5);
  }

  // cutoffAt is a Unix timestamp
  let endDate = "";
  if (m.cutoffAt) {
    try { endDate = new Date(Number(m.cutoffAt) * 1000).toISOString(); } catch { /* ignore */ }
  }

  const title = String(m.marketTitle ?? m.market_title ?? m.title ?? "");
  const rawCat = String(m.category ?? m.topicType ?? "");
  return {
    id: String(m.marketId ?? m.market_id ?? m.id ?? ""),
    platform: "opinion",
    question: title,
    description: String(m.rules ?? m.description ?? ""),
    image: String(m.image ?? m.icon ?? ""),
    yes_price: yesPrice,
    no_price: noPrice,
    volume: Number(m.volume24h ?? m.volume_24h ?? m.volume ?? 0),
    liquidity: Number(m.liquidity ?? m.openInterest ?? 0),
    endDate,
    category: classifyCategory(title, rawCat),
  };
}

function normalizeLimitless(m: RawMarket): BotApiMarket {
  const prices = m.prices as { yes?: number; no?: number } | undefined;
  const title = String(m.title || m.question || "");
  const rawCat = String(m.category ?? "");
  return {
    id: String(m.id ?? m.address ?? ""),
    platform: "limitless",
    question: title,
    description: String(m.description ?? ""),
    image: String(m.ogImageURI ?? m.imageUrl ?? m.image ?? ""),
    yes_price: Number(prices?.yes ?? m.yesPrice ?? 0.5),
    no_price: Number(prices?.no ?? m.noPrice ?? 0.5),
    volume: Number(m.volumeFormatted ?? m.volume ?? 0),
    liquidity: Number(m.liquidityFormatted ?? m.liquidity ?? 0),
    endDate: String(m.deadline ?? m.expirationDate ?? ""),
    category: classifyCategory(title, rawCat),
    event_id: String(m.negRiskMarketId ?? (m.group as Record<string, unknown> | undefined)?.id ?? ""),
    is_multi_outcome: false,
    outcome_name: String(m.outcomeName ?? ""),
  };
}

function normalizeMyriad(m: RawMarket): BotApiMarket {
  const outcomes = m.outcomes as { title?: string; price?: number }[] | undefined;
  let yesPrice = 0.5;
  let noPrice = 0.5;
  if (outcomes && outcomes.length >= 2) {
    yesPrice = Number(outcomes[0]?.price ?? 0.5);
    noPrice = Number(outcomes[1]?.price ?? 0.5);
  }
  const title = String(m.title || m.question || "");
  const rawCat = String(m.category ?? "");
  return {
    id: String(m.id ?? m.slug ?? ""),
    platform: "myriad",
    question: title,
    description: String(m.description ?? ""),
    image: String(m.imageUrl ?? m.image ?? ""),
    yes_price: yesPrice,
    no_price: noPrice,
    volume: Number(m.volume24h ?? m.volume ?? 0),
    liquidity: Number(m.liquidity ?? 0),
    endDate: String(m.expiresAt ?? m.closeTime ?? ""),
    category: classifyCategory(title, rawCat),
    slug: String(m.slug ?? ""),
  };
}

function normalizeRawMarkets(platform: Platform, raw: RawMarket[]): BotApiMarket[] {
  const normalizers: Partial<Record<Platform, (m: RawMarket) => BotApiMarket>> = {
    kalshi: normalizeKalshi,
    opinion: normalizeOpinion,
    limitless: normalizeLimitless,
    myriad: normalizeMyriad,
  };
  const normalizer = normalizers[platform];
  if (!normalizer) return [];
  return raw.map((m) => {
    try { return normalizer(m); } catch { return null; }
  }).filter((m): m is BotApiMarket => m !== null);
}

// ── Direct platform fetching (fast, background worker has keys) ─

async function fetchDirect(
  platform: Platform,
  limit = 20
): Promise<PolymarketEvent[]> {
  const res = await fetchPlatformMarketsDirect({ platform, limit });
  if (res.success && res.data) {
    const raw = Array.isArray(res.data) ? res.data : [];
    const normalized = normalizeRawMarkets(platform, raw);
    // Detect multi-outcome groups for Kalshi/Limitless
    detectMultiOutcome(normalized);
    return botMarketsToEvents(normalized);
  }
  // Fall back to Bot API if direct fetch fails (e.g. no API key configured)
  return fetchViaBotApi(platform, limit);
}

async function searchDirect(
  platform: Platform,
  query: string,
  limit = 20
): Promise<PolymarketEvent[]> {
  const res = await searchPlatformMarketsDirect({ platform, query, limit });
  if (res.success && res.data) {
    const raw = Array.isArray(res.data) ? res.data : [];
    const normalized = normalizeRawMarkets(platform, raw);
    detectMultiOutcome(normalized);
    return botMarketsToEvents(normalized);
  }
  return searchViaBotApi(platform, query, limit);
}

/** Detect multi-outcome events by grouping on event_id */
function detectMultiOutcome(markets: BotApiMarket[]): void {
  const groups = new Map<string, BotApiMarket[]>();
  for (const m of markets) {
    if (m.event_id) {
      const g = groups.get(m.event_id);
      if (g) g.push(m);
      else groups.set(m.event_id, [m]);
    }
  }
  for (const [, group] of groups) {
    if (group.length > 1) {
      for (const m of group) {
        m.is_multi_outcome = true;
        m.related_market_count = group.length;
      }
    }
  }
}

// ── Bot API fallback ────────────────────────────────────────

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
      // Kalshi uses the backend API (cache-warmed every 60s with guaranteed
      // rapid markets) instead of direct DFlow pagination which is slow and
      // may miss 15-min/5-min/hourly markets buried deep in the list.
      return fetchViaBotApi(platform, Math.max(limit, 200));
    case "opinion":
    case "limitless":
    case "myriad":
      return fetchDirect(platform, limit);
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
      // Use backend API search for Kalshi (has full market cache)
      return searchViaBotApi(platform, query, limit);
    case "opinion":
    case "limitless":
    case "myriad":
      return searchDirect(platform, query, limit);
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
  // Multi-outcome grouping
  event_id?: string;
  is_multi_outcome?: boolean;
  outcome_name?: string;
  related_market_count?: number;
}

/** Extract yes price from a Bot API market */
function getYesPrice(m: BotApiMarket): number {
  if (m.outcomePrices && m.outcomePrices.length >= 1) {
    return parseFloat(m.outcomePrices[0]) || 0.5;
  }
  if (m.yes_price != null) return Number(m.yes_price) || 0.5;
  return 0.5;
}

/** Convert a single Bot API market to an event (no grouping) */
export function botMarketToEvent(m: BotApiMarket): PolymarketEvent {
  const yesPrice = getYesPrice(m);
  let noPrice = 0.5;
  if (m.outcomePrices && m.outcomePrices.length >= 2) {
    noPrice = parseFloat(m.outcomePrices[1]) || 0.5;
  } else if (m.no_price != null) {
    noPrice = Number(m.no_price) || 1 - yesPrice;
  } else {
    noPrice = 1 - yesPrice;
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

/**
 * Convert Bot API markets to events, grouping multi-outcome markets
 * by event_id into a single PolymarketEvent with multiple MarketInfo entries.
 */
export function botMarketsToEvents(markets: BotApiMarket[]): PolymarketEvent[] {
  if (!Array.isArray(markets)) return [];

  // Separate multi-outcome markets from simple ones
  const grouped = new Map<string, BotApiMarket[]>();
  const simple: BotApiMarket[] = [];

  for (const m of markets) {
    if (m.is_multi_outcome && m.event_id) {
      const group = grouped.get(m.event_id);
      if (group) {
        group.push(m);
      } else {
        grouped.set(m.event_id, [m]);
      }
    } else {
      simple.push(m);
    }
  }

  const events: PolymarketEvent[] = [];

  // Build grouped events (multi-outcome)
  for (const [eventId, group] of grouped) {
    const first = group[0];
    const platform = (first.platform || "kalshi") as Platform;

    // Each market in the group becomes a MarketInfo with its outcome name
    const marketInfos: MarketInfo[] = group.map((m) => {
      const yesPrice = getYesPrice(m);
      const outcomeName = m.outcome_name || m.question || m.title || m.id;
      return {
        conditionId: m.id,
        question: outcomeName,
        outcomes: [
          { name: "Yes", price: yesPrice, tokenId: "" },
          { name: "No", price: 1 - yesPrice, tokenId: "" },
        ],
        clobTokenIds: ["", ""] as [string, string],
        isNegRisk: false,
        eventSlug: `${platform}/${eventId}`,
      };
    });

    // Use the common event title (strip outcome-specific suffix from first market's title)
    const eventTitle = first.question || first.title || eventId;
    const totalVolume = group.reduce((sum, m) => sum + (m.volume24hr ?? m.volume ?? 0), 0);
    const totalLiquidity = group.reduce((sum, m) => sum + (m.liquidity ?? 0), 0);

    events.push({
      id: eventId,
      slug: `${platform}/${eventId}`,
      title: eventTitle,
      description: first.description ?? "",
      image: first.image || first.image_url || "",
      markets: marketInfos,
      volume: totalVolume,
      liquidity: totalLiquidity,
      startDate: "",
      endDate: first.endDate || first.end_date || "",
      active: true,
      closed: false,
      category: classifyCategory(eventTitle, first.category, eventId) || platform,
    });
  }

  // Add simple (non-grouped) markets
  for (const m of simple) {
    events.push(botMarketToEvent(m));
  }

  return events;
}
