/**
 * Category classification for prediction markets.
 * Mirrors the bot's keyword patterns to produce standardized categories
 * (Sports, Politics, Crypto, Economics, World, Entertainment, Science).
 */

const CATEGORY_KEYWORDS: Record<string, RegExp> = {
  Sports: /\b(nfl|nba|mlb|nhl|soccer|football|basketball|baseball|championship|super bowl|playoffs|world cup|ufc|mma|boxing|tennis|golf|f1|nascar|olympic|premier league|la liga|ucl|epl|march madness|cfb|ncaa|wrestl)\b/i,
  Politics: /\b(trump|biden|president|congress|senate|governor|democrat|republican|vote|election|political|government|cabinet|impeach|poll|gop|dnc|rnc)\b/i,
  Crypto: /\b(bitcoin|btc|ethereum|eth|solana|sol|crypto|binance|token|defi|nft|blockchain|altcoin|doge|xrp|ada|avax|link|matic|dot|atom|uni|aave|coin)\b/i,
  Economics: /\b(fed|interest rate|inflation|gdp|recession|tariff|economy|stock|market|s&p|nasdaq|dow|cpi|jobs|unemployment|treasury|debt ceiling|trade deficit)\b/i,
  World: /\b(war|ukraine|russia|china|israel|iran|military|conflict|peace|nato|sanctions|greenland|venezuela|mideast|eu\b|united nations)\b/i,
  Entertainment: /\b(oscar|grammy|emmy|golden globe|movie|music|film|tv|streaming|netflix|spotify|celebrity|album|award|box office)\b/i,
  Science: /\b(nasa|space|climate|weather|hurricane|earthquake|ai\b|artificial intelligence|vaccine|pandemic|fda)\b/i,
};

/** Kalshi ticker prefix patterns (from bot's CATEGORY_PATTERNS) */
const KALSHI_TICKER_CATEGORIES: Record<string, string[]> = {
  Sports: [
    "KXSB", "KXNFL", "KXNBA", "KXNHL", "KXMLB", "KXNCAAF", "KXMARMAD",
    "KXCFB", "KXCBB", "KXPREMIERLEAGUE", "KXLALIGA", "KXUCL", "KXSOCCER",
    "KXEPL", "KXUFC", "KXMMA", "KXBOXING", "KXTENNIS", "KXGOLF", "KXF1",
    "KXNASCAR", "KXOLYMPIC", "KXTEAMSINSB",
  ],
  Politics: [
    "KXPRES", "KXCONTROL", "KXSENATE", "KXGOV", "KXCAB", "KXTRUMP",
    "KXLEADERS", "KXLEAVE", "KXARREST", "KXBIDEN", "KXHOUSE", "KXCONGRESS",
    "KXELECTION", "KXVOTE", "KXPOLICY",
  ],
  Economics: [
    "KXFED", "KXGOVT", "RECSSNBER", "KXGOVSHUT", "KXINFLATION", "KXCPI",
    "KXGDP", "KXJOBS", "KXRATE", "KXSP500", "KXSTOCK", "KXMARKET",
    "KXDOW", "KXNASDAQ",
  ],
  Crypto: [
    "KXBTC", "KXETH", "KXSOL", "KXCRYPTO", "KXCOIN", "KXDOGE", "KXXRP",
    "KXADA", "KXAVAX", "KXLINK", "KXMATIC", "BITCOIN", "ETHEREUM", "CRYPTO",
  ],
  World: [
    "KXKHAMENEI", "KXGREENLAND", "KXVENEZUELA", "KXCHINA", "KXRUSSIA",
    "KXUKRAINE", "KXEU", "KXWAR", "KXPEACE", "KXNATO", "KXUN", "KXMIDEAST",
  ],
  Entertainment: [
    "KXOSCAR", "KXGRAM", "KXMEDIA", "KXEMMY", "KXGOLDEN", "KXTV",
    "KXMOVIE", "KXMUSIC", "KXAWARD", "KXCELEB",
  ],
};

/** Normalize raw tag labels / API categories to standard names */
const TAG_ALIASES: Record<string, string> = {
  "politics": "Politics",
  "sports": "Sports",
  "crypto": "Crypto",
  "pop culture": "Entertainment",
  "entertainment": "Entertainment",
  "culture": "Entertainment",
  "science": "Science",
  "business": "Economics",
  "finance": "Economics",
  "economy": "Economics",
  "economics": "Economics",
  "world": "World",
  "global": "World",
  "sentiment": "World",
};

/**
 * Classify a market into a standard category.
 * Uses ticker prefix for Kalshi, raw category normalization, then title keyword matching.
 */
export function classifyCategory(title: string, rawCategory?: string, tickerOrId?: string): string {
  // 1. Try Kalshi ticker prefix matching
  if (tickerOrId) {
    const upper = tickerOrId.toUpperCase();
    for (const [cat, prefixes] of Object.entries(KALSHI_TICKER_CATEGORIES)) {
      if (prefixes.some((p) => upper.startsWith(p))) return cat;
    }
  }

  // 2. Normalize raw category if it matches a known alias
  if (rawCategory) {
    const normalized = TAG_ALIASES[rawCategory.toLowerCase()];
    if (normalized) return normalized;
    // If raw category already matches a standard name, use it
    const standard = Object.keys(CATEGORY_KEYWORDS);
    const match = standard.find((s) => s.toLowerCase() === rawCategory.toLowerCase());
    if (match) return match;
  }

  // 3. Keyword matching on title
  for (const [cat, re] of Object.entries(CATEGORY_KEYWORDS)) {
    if (re.test(title)) return cat;
  }

  // 4. Return raw category or empty
  return rawCategory || "";
}
