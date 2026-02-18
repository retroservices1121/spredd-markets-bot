/**
 * Bot API market adapter.
 * Converts Bot API market responses into PolymarketEvent shape
 * so existing UI components (MarketCard, MarketDetailPage) work unchanged.
 *
 * The Bot API /api/v1/markets returns:
 *   { id, platform, question, description, image, category, outcomes,
 *     outcomePrices: ["0.65","0.35"], volume, volume24hr, liquidity,
 *     endDate, slug, active }
 *
 * The Bot API /api/v1/markets/search returns (inside { markets: [...] }):
 *   { id, platform, title, yes_price, no_price, volume, is_active }
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome } from "@/core/markets";

/** Flexible shape that handles both /markets and /markets/search responses */
export interface BotApiMarket {
  id: string;
  platform: string;
  // /markets uses "question", /search uses "title"
  question?: string;
  title?: string;
  description?: string;
  // /markets uses "image", adapter also checks "image_url"
  image?: string;
  image_url?: string;
  // /markets uses outcomePrices: ["0.65","0.35"]
  outcomePrices?: string[];
  // /search uses yes_price / no_price as numbers
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

/** Convert a Bot API market to a PolymarketEvent for UI compatibility */
export function botMarketToEvent(m: BotApiMarket): PolymarketEvent {
  // Parse prices from either format
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

  const outcomes: MarketOutcome[] = [
    { name: "Yes", price: yesPrice, tokenId: "" },
    { name: "No", price: noPrice, tokenId: "" },
  ];

  const market: MarketInfo = {
    conditionId: m.id,
    question: displayTitle,
    outcomes,
    clobTokenIds: ["", ""],
    isNegRisk: false,
    eventSlug: m.slug || `${m.platform}/${m.id}`,
  };

  const slug = m.slug
    ? (m.slug.includes("/") ? m.slug : `${m.platform}/${m.slug}`)
    : `${m.platform}/${m.id}`;

  return {
    id: m.id,
    slug,
    title: displayTitle,
    description: m.description ?? "",
    image: m.image || m.image_url || "",
    markets: [market],
    volume: m.volume24hr ?? m.volume ?? 0,
    liquidity: m.liquidity ?? 0,
    startDate: "",
    endDate: m.endDate || m.end_date || "",
    active: m.active ?? m.is_active ?? true,
    closed: m.closed ?? false,
    category: m.category ?? m.platform,
  };
}

/** Convert an array of Bot API markets to events */
export function botMarketsToEvents(markets: BotApiMarket[]): PolymarketEvent[] {
  if (!Array.isArray(markets)) return [];
  return markets.map(botMarketToEvent);
}
