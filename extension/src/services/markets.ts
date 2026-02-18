/**
 * Platform market fetchers.
 *
 * Polymarket → Gamma API (direct, public) — handled in polymarket.ts
 * Kalshi, Opinion, Limitless, Myriad → Bot API via background worker (API keys stay server-side)
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";
import { getBotMarkets, searchBotMarkets } from "@/lib/messaging";

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

// ── All non-Polymarket platforms (via Bot API — API keys stay server-side) ─

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
      category: first.category ?? platform,
    });
  }

  // Add simple (non-grouped) markets
  for (const m of simple) {
    events.push(botMarketToEvent(m));
  }

  return events;
}
