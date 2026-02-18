/**
 * Bot API market adapter.
 * Converts flat Bot API market responses into PolymarketEvent shape
 * so existing UI components (MarketCard, MarketDetailPage) work unchanged.
 */

import type { PolymarketEvent, MarketInfo, MarketOutcome, Platform } from "@/core/markets";

/** Shape of a market from Bot API /api/v1/markets */
export interface BotApiMarket {
  id: string;
  platform: string;
  title: string;
  question?: string;
  description?: string;
  image_url?: string;
  yes_price?: number;
  no_price?: number;
  volume?: number;
  liquidity?: number;
  category?: string;
  active?: boolean;
  closed?: boolean;
  end_date?: string;
  outcomes?: string[];
}

/** Convert a Bot API market to a PolymarketEvent for UI compatibility */
export function botMarketToEvent(m: BotApiMarket): PolymarketEvent {
  const yesPrice = m.yes_price ?? 0.5;
  const noPrice = m.no_price ?? 1 - yesPrice;

  const outcomes: MarketOutcome[] = [
    { name: "Yes", price: yesPrice, tokenId: "" },
    { name: "No", price: noPrice, tokenId: "" },
  ];

  const market: MarketInfo = {
    conditionId: m.id,
    question: m.question || m.title,
    outcomes,
    clobTokenIds: ["", ""],
    isNegRisk: false,
    eventSlug: `${m.platform}/${m.id}`,
  };

  return {
    id: m.id,
    slug: `${m.platform}/${m.id}`,
    title: m.title,
    description: m.description ?? "",
    image: m.image_url ?? "",
    markets: [market],
    volume: m.volume ?? 0,
    liquidity: m.liquidity ?? 0,
    startDate: "",
    endDate: m.end_date ?? "",
    active: m.active ?? true,
    closed: m.closed ?? false,
    category: m.category ?? (m.platform as string),
  };
}

/** Convert an array of Bot API markets to events */
export function botMarketsToEvents(markets: BotApiMarket[]): PolymarketEvent[] {
  return markets.map(botMarketToEvent);
}
