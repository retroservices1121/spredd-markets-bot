"""
Kalshi platform implementation using DFlow API.
Trades Kalshi prediction markets on Solana.
"""

import asyncio
from decimal import Decimal
from typing import Any, Optional
from datetime import datetime

import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
import base64
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import settings
from src.db.models import Chain, Outcome, Platform
from src.platforms.base import (
    BasePlatform,
    Market,
    Quote,
    TradeResult,
    OrderBook,
    PlatformError,
    MarketNotFoundError,
    RateLimitError,
    RedemptionResult,
    MarketResolution,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class KalshiPlatform(BasePlatform):
    """
    Kalshi prediction market platform via DFlow.
    First CFTC-regulated prediction market on-chain.
    """
    
    platform = Platform.KALSHI
    chain = Chain.SOLANA
    
    name = "Kalshi"
    description = "CFTC-regulated prediction markets on Solana"
    website = "https://kalshi.com"
    
    collateral_symbol = "USDC"
    collateral_decimals = 6
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._solana_client: Optional[SolanaClient] = None
        self._api_key = settings.dflow_api_key
        self._fee_account = settings.kalshi_fee_account
        self._fee_bps = settings.kalshi_fee_bps
    
    async def initialize(self) -> None:
        """Initialize DFlow API client."""
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key

        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
        )

        self._solana_client = SolanaClient(settings.solana_rpc_url)

        fee_enabled = bool(self._fee_account and len(self._fee_account) >= 32)
        # platformFeeScale = fee_bps // 2 (e.g., 100 bps -> scale 50)
        fee_scale = self._fee_bps // 2 if fee_enabled else 0
        logger.info(
            "Kalshi platform initialized",
            api_key_set=bool(self._api_key),
            fee_collection=fee_enabled,
            fee_scale=fee_scale,
        )
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._solana_client:
            await self._solana_client.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def _metadata_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to DFlow metadata API with retry on rate limit."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")

        url = f"{settings.dflow_metadata_url}{endpoint}"

        try:
            response = await self._http_client.request(method, url, **kwargs)

            if response.status_code == 429:
                logger.warning("Rate limited on metadata API, retrying...")
                raise RateLimitError("Rate limit exceeded", Platform.KALSHI)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.KALSHI,
                str(e.response.status_code),
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def _trading_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to DFlow trading API with retry on rate limit."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")

        url = f"{settings.dflow_api_base_url}{endpoint}"

        try:
            response = await self._http_client.request(method, url, **kwargs)

            if response.status_code == 429:
                logger.warning("Rate limited on trading API, retrying...")
                raise RateLimitError("Rate limit exceeded", Platform.KALSHI)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            # Log response body for debugging
            try:
                error_body = e.response.text
                logger.error("DFlow API error", status=e.response.status_code, body=error_body)
            except:
                pass
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.KALSHI,
                str(e.response.status_code),
            )
    
    # USDC mint address on Solana
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # Kalshi public API for market metadata (names, etc.)
    KALSHI_PUBLIC_API = "https://api.elections.kalshi.com/trade-api/v2"

    async def _fetch_kalshi_event_names(self, event_id: str) -> dict[str, str]:
        """Fetch market names from Kalshi's public API.

        Returns a dict mapping ticker -> outcome name (e.g., "KXNFLMVP-26-PMAH" -> "Patrick Mahomes")
        """
        names: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.KALSHI_PUBLIC_API}/events/{event_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    for market in data.get("markets", []):
                        ticker = market.get("ticker")
                        # yes_sub_title contains the outcome name (e.g., "Patrick Mahomes")
                        name = market.get("yes_sub_title") or market.get("subtitle")
                        if ticker and name:
                            names[ticker] = name
                    logger.debug(
                        "Fetched Kalshi event names",
                        event_id=event_id,
                        count=len(names),
                    )
        except Exception as e:
            logger.warning("Failed to fetch Kalshi event names", event_id=event_id, error=str(e))
        return names

    def _parse_market(self, data: dict) -> Market:
        """Parse DFlow market data into Market object."""
        # Extract pricing (API returns decimal strings like "0.3600")
        yes_price = None
        no_price = None

        # Log raw price data for debugging
        logger.debug(
            "Market price data",
            ticker=data.get("ticker"),
            yesAsk=data.get("yesAsk"),
            noAsk=data.get("noAsk"),
            yesBid=data.get("yesBid"),
            noBid=data.get("noBid"),
            lastYesPrice=data.get("lastYesPrice"),
            lastNoPrice=data.get("lastNoPrice"),
        )

        if "yesAsk" in data and data["yesAsk"]:
            yes_price = Decimal(str(data["yesAsk"]))
        if "noAsk" in data and data["noAsk"]:
            no_price = Decimal(str(data["noAsk"]))

        # Extract tokens from accounts structure (keyed by collateral mint)
        yes_token = None
        no_token = None
        accounts = data.get("accounts", {})
        if self.USDC_MINT in accounts:
            usdc_accounts = accounts[self.USDC_MINT]
            yes_token = usdc_accounts.get("yesMint")
            no_token = usdc_accounts.get("noMint")

        # Extract resolution criteria from various possible fields
        resolution_criteria = (
            data.get("rules_primary") or
            data.get("rulesPrimary") or
            data.get("rules") or
            data.get("settlement_rules") or
            data.get("settlementRules") or
            data.get("resolution_rules") or
            data.get("resolutionRules")
        )

        return Market(
            platform=Platform.KALSHI,
            chain=Chain.SOLANA,
            market_id=data.get("ticker") or data.get("market_ticker"),
            event_id=data.get("eventTicker") or data.get("event_ticker"),
            title=data.get("title") or data.get("question", ""),
            description=data.get("subtitle"),
            category=data.get("category"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
            liquidity=Decimal(str(data.get("openInterest", 0))) if data.get("openInterest") else None,
            is_active=data.get("status") == "active" or data.get("result") is None,
            close_time=data.get("closeTime") or data.get("close_time"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            resolution_criteria=resolution_criteria,
        )
    
    # ===================
    # Market Discovery
    # ===================
    
    # Cache for first-page markets (general browsing)
    _markets_cache: list[Market] = []
    _markets_cache_time: float = 0
    CACHE_TTL = 300  # 5 minutes

    # Cache for ALL markets across all pages (for ticker-based filtering)
    _all_markets_cache: list[Market] = []
    _all_markets_cache_time: float = 0
    ALL_MARKETS_CACHE_TTL = 300  # 5 minutes

    async def get_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from DFlow.

        Args:
            limit: Maximum number of markets to return
            offset: Number of markets to skip (for pagination)
            active_only: Only return active markets

        Note: DFlow API doesn't support offset/pagination, so we fetch all
        markets and paginate client-side with caching.
        """
        import time

        # Check if cache is still valid
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self.CACHE_TTL:
            # Return from cache with offset/limit
            return self._markets_cache[offset:offset + limit]

        # Fetch all markets (API ignores offset param)
        params = {
            "limit": 200,  # Fetch all available
        }
        if active_only:
            params["status"] = "active"

        data = await self._metadata_request("GET", "/api/v1/markets", params=params)

        markets = []
        for item in data.get("markets", data.get("data", [])):
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))

        # Detect multi-outcome events by grouping by event_id
        from collections import defaultdict
        event_groups = defaultdict(list)
        for m in markets:
            if m.event_id:
                event_groups[m.event_id].append(m)

        # Mark multi-outcome markets and fetch names from Kalshi public API
        for event_id, group in event_groups.items():
            if len(group) > 1:
                # Fetch outcome names from Kalshi's public API
                kalshi_names = await self._fetch_kalshi_event_names(event_id)

                for m in group:
                    m.is_multi_outcome = True
                    m.related_market_count = len(group)

                    # Try to get name from Kalshi API first (most reliable)
                    outcome_name = kalshi_names.get(m.market_id)

                    # Fallback: try DFlow fields
                    if not outcome_name:
                        raw = m.raw_data or {}
                        if raw.get("yesSubtitle"):
                            outcome_name = raw["yesSubtitle"]
                        elif m.description and m.description != m.title:
                            outcome_name = m.description

                    # Last resort: ticker suffix
                    if not outcome_name and m.market_id and "-" in m.market_id:
                        ticker_parts = m.market_id.split("-")
                        if len(ticker_parts) >= 3:
                            outcome_name = ticker_parts[-1]

                    m.outcome_name = outcome_name[:50] if outcome_name else None

        # Update cache
        self._markets_cache = markets
        self._markets_cache_time = now

        # Return requested slice
        return markets[offset:offset + limit]

    async def _fetch_all_markets(self) -> list[Market]:
        """Fetch ALL markets across all pages using cursor-based pagination.

        The DFlow API has 4000+ active markets spread across many pages of 200.
        This method paginates through all of them and caches the result.
        Used by get_15m_markets() and get_hourly_markets() which need to find
        specific ticker patterns that may be on any page.
        """
        import time

        now = time.time()
        if self._all_markets_cache and (now - self._all_markets_cache_time) < self.ALL_MARKETS_CACHE_TTL:
            return self._all_markets_cache

        all_markets = []
        cursor = None
        max_pages = 25  # Safety limit

        for page in range(max_pages):
            params = {"limit": 200, "status": "active"}
            if cursor is not None:
                params["cursor"] = cursor

            try:
                data = await self._metadata_request("GET", "/api/v1/markets", params=params)
            except Exception as e:
                logger.warning("Failed to fetch markets page", page=page, error=str(e))
                break

            page_markets = data.get("markets", data.get("data", []))
            for item in page_markets:
                try:
                    all_markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Check for next page
            new_cursor = data.get("cursor")
            if not new_cursor or not page_markets:
                break
            cursor = new_cursor

        logger.info("Fetched all DFlow markets", total=len(all_markets), pages=page + 1)

        # Update cache
        self._all_markets_cache = all_markets
        self._all_markets_cache_time = now

        # Also update the first-page cache if it's stale
        if not self._markets_cache or (now - self._markets_cache_time) >= self.CACHE_TTL:
            self._markets_cache = all_markets[:200]
            self._markets_cache_time = now

        return all_markets

    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets by query with client-side filtering."""
        # Use get_markets which fetches 200 and caches for 5 min
        all_markets = await self.get_markets(limit=200)

        # Filter by query (case-insensitive search in title and question)
        query_lower = query.lower()
        filtered = [
            m for m in all_markets
            if query_lower in m.title.lower() or query_lower in m.question.lower()
        ]

        return filtered[:limit]
    
    async def get_market(self, market_id: str, search_title: Optional[str] = None, include_closed: bool = False) -> Optional[Market]:
        """Get a specific market by ticker.

        Note: search_title and include_closed are accepted for API compatibility but not used.

        First tries to find the market in the cache (which has multi-outcome info),
        then falls back to fetching directly from the API.
        """
        import time

        # First, try to find in caches (which have multi-outcome detection)
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self.CACHE_TTL:
            for m in self._markets_cache:
                if m.market_id == market_id:
                    return m
        # Also check the all-markets cache (for 15m/hourly markets)
        if self._all_markets_cache and (now - self._all_markets_cache_time) < self.ALL_MARKETS_CACHE_TTL:
            for m in self._all_markets_cache:
                if m.market_id == market_id:
                    return m

        # If not in cache or cache expired, populate cache first
        try:
            await self.get_markets(limit=200, offset=0, active_only=True)
            # Now search cache again
            for m in self._markets_cache:
                if m.market_id == market_id:
                    return m
        except Exception:
            pass

        # Fallback: fetch directly from API (won't have multi-outcome info)
        try:
            data = await self._metadata_request("GET", f"/api/v1/market/{market_id}")
            return self._parse_market(data.get("market", data))
        except PlatformError:
            return None
    
    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending markets by volume."""
        params = {
            "limit": limit,
            "sort": "volume",
            "status": "active",
        }

        data = await self._metadata_request("GET", "/api/v1/markets", params=params)

        markets = []
        for item in data.get("markets", data.get("data", [])):
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))

        return markets

    async def get_related_markets(self, event_id: str) -> list[Market]:
        """Get all markets related to an event (for multi-outcome events).

        Args:
            event_id: The event ticker (Kalshi event_ticker)

        Returns:
            List of markets belonging to the same event, sorted by probability (highest first)
        """
        try:
            # Use cached markets to find related ones
            all_markets = await self.get_markets(limit=200, offset=0, active_only=True)

            # Filter by event_id
            related = [m for m in all_markets if m.event_id == event_id]

            if len(related) <= 1:
                return []  # Not a multi-outcome event

            # Sort by yes_price (probability) descending
            related.sort(key=lambda m: m.yes_price or Decimal(0), reverse=True)
            return related

        except Exception as e:
            logger.warning("Failed to get related markets", event_id=event_id, error=str(e))
            return []

    # ===================
    # Categories (inferred from ticker patterns)
    # ===================

    # Ticker pattern to category mapping
    CATEGORY_PATTERNS = {
        "sports": [
            "KXSB", "KXNFL", "KXNBA", "KXNHL", "KXMLB",  # US Sports
            "KXNCAAF", "KXMARMAD", "KXCFB", "KXCBB",  # College sports
            "KXPREMIERLEAGUE", "KXLALIGA", "KXUCL", "KXSOCCER", "KXEPL",  # Soccer
            "KXTEAMSINSB", "KXNFLGAME", "KXNFLMVP", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP",
            "KXNFLCOTY", "KXNFLOPOTY", "KXNFLOROTY", "KXNFLDPOTY", "KXNFLPROP",
            "KXNBAMVP", "KXNBADPOY", "KXNBAEAST", "KXNBAWEST", "KXNBAPROP",
            "KXUFC", "KXMMA", "KXBOXING", "KXWRESTL", "KXTENNIS", "KXGOLF",
            "KXF1", "KXNASCAR", "KXOLYMPIC",
        ],
        "politics": [
            "KXPRES", "KXCONTROL", "KXSENATE", "KXGOV", "KXCAB",
            "KXTRUMP", "KXLEADERS", "KXLEAVE", "KXARREST", "KXBIDEN",
            "KXHOUSE", "KXCONGRESS", "KXELECTION", "KXVOTE", "KXPOLICY",
        ],
        "economics": [
            "KXFED", "KXGOVT", "RECSSNBER", "KXGOVSHUT",
            "KXINFLATION", "KXCPI", "KXGDP", "KXJOBS", "KXRATE",
            "KXSP500", "KXSTOCK", "KXMARKET", "KXDOW", "KXNASDAQ",
        ],
        "crypto": [
            "KXBTC", "KXETH", "KXSOL", "KXCRYPTO", "KXCOIN",
            "KXDOGE", "KXXRP", "KXADA", "KXAVAX", "KXLINK",
            "KXMATIC", "KXDOT", "KXATOM", "KXUNI", "KXAAVE",
            "BITCOIN", "ETHEREUM", "CRYPTO",  # Catch-all patterns
        ],
        "world": [
            "KXKHAMENEI", "KXGREENLAND", "KXGREENTER", "KXVENEZUELA",
            "KXDJTVO", "KXCHINA", "KXRUSSIA", "KXUKRAINE", "KXEU",
            "KXWAR", "KXPEACE", "KXNATO", "KXUN", "KXMIDEAST",
        ],
        "entertainment": [
            "KXOSCAR", "KXGRAM", "KXMEDIA", "KXEMMY", "KXGOLDEN",
            "KXTV", "KXMOVIE", "KXMUSIC", "KXAWARD", "KXCELEB",
        ],
    }

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories.

        Returns list of dicts with 'id', 'label', and 'emoji' keys.
        """
        return [
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "economics", "label": "Economics", "emoji": "📊"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "world", "label": "World", "emoji": "🌍"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
        ]

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 100,
    ) -> list[Market]:
        """Get markets filtered by category.

        Categories are inferred from ticker patterns and title/description
        since DFlow API doesn't have a categories endpoint.
        """
        # Get all markets (uses cache if available)
        all_markets = await self.get_markets(limit=200, offset=0, active_only=True)

        # Get patterns for this category
        patterns = self.CATEGORY_PATTERNS.get(category.lower(), [])
        if not patterns:
            return []

        # Also define title/description keywords for each category
        # Note: Be careful with short keywords to avoid false positives
        CATEGORY_KEYWORDS = {
            "crypto": ["bitcoin", " btc ", "ethereum", " eth ", "solana", "cryptocurrency"],  # Removed ambiguous: "crypto", "token", "coin"
            "sports": ["super bowl", "championship", "playoff", "touchdown", "quarterback"],  # More specific
            "politics": ["president", "election", "senate", "congress", "vote", "political"],
            "economics": ["inflation", "interest rate", "gdp", "recession", "federal reserve"],
            "world": ["ukraine", "russia", "international", "global conflict"],
            "entertainment": ["oscar", "grammy", "emmy", "academy award"],
        }
        keywords = CATEGORY_KEYWORDS.get(category.lower(), [])

        # Filter markets by ticker pattern OR title/description keywords
        filtered = []
        seen_ids = set()
        for market in all_markets:
            if market.market_id in seen_ids:
                continue

            ticker = market.market_id.upper()
            title_lower = (market.title or "").lower()
            desc_lower = (market.description or "").lower()

            # Match by ticker pattern
            if any(ticker.startswith(pattern) for pattern in patterns):
                filtered.append(market)
                seen_ids.add(market.market_id)
                continue

            # Match by title/description keywords
            if keywords:
                for keyword in keywords:
                    if keyword in title_lower or keyword in desc_lower:
                        filtered.append(market)
                        seen_ids.add(market.market_id)
                        break

        return filtered[:limit]

    async def get_15m_markets(self, limit: int = 50) -> list[Market]:
        """Get 15-minute interval Kalshi markets.

        These are fast-expiring crypto price markets with tickers like:
        - KXBTC15M (Bitcoin 15-minute)
        - KXETH15M (Ethereum 15-minute)
        - KXSOL15M (Solana 15-minute)
        - KXXRP15M (XRP 15-minute)
        - KXDOGE15M (Dogecoin 15-minute)

        Returns:
            List of active 15-minute markets sorted by expiration time
        """
        # Fetch ALL markets across all pages (DFlow has 4000+ markets)
        all_markets = await self._fetch_all_markets()

        # 15-minute market ticker patterns
        patterns_15m = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]

        # Filter for 15-minute markets
        filtered = []
        for market in all_markets:
            ticker = market.market_id.upper()
            if any(ticker.startswith(pattern) for pattern in patterns_15m):
                filtered.append(market)

        # Sort by expiration time (soonest first)
        filtered.sort(key=lambda m: m.close_time or "", reverse=False)

        return filtered[:limit]

    async def get_hourly_markets(self, limit: int = 50) -> list[Market]:
        """Get hourly interval Kalshi crypto markets.

        These are crypto price above/below markets with tickers like:
        - KXBTCD (Bitcoin hourly)
        - KXETHD (Ethereum hourly)
        - KXSOLD (Solana hourly)
        - KXXRPD (XRP hourly)
        - KXDOGED (Dogecoin hourly)

        Returns:
            List of active hourly markets sorted by expiration time
        """
        # Fetch ALL markets across all pages (DFlow has 4000+ markets)
        all_markets = await self._fetch_all_markets()

        # Hourly market ticker patterns (KXBTCD but NOT KXBTC15M etc)
        patterns_hourly = ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED"]

        filtered = []
        for market in all_markets:
            ticker = market.market_id.upper()
            if any(ticker.startswith(pattern) for pattern in patterns_hourly):
                filtered.append(market)

        # Sort by expiration time (soonest first)
        filtered.sort(key=lambda m: m.close_time or "", reverse=False)

        return filtered[:limit]

    # ===================
    # Order Book
    # ===================

    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        slug: str = None,  # Accepted for API compatibility, not used
    ) -> OrderBook:
        """Get order book for a market."""
        data = await self._metadata_request("GET", f"/api/v1/orderbook/{market_id}")

        # DFlow returns dict format: {"yes_bids": {"0.35": 100, ...}, "no_bids": {...}}
        # Prices are already decimals (0-1 scale), quantities are integers
        bids = []
        asks = []

        side_key = "yes" if outcome == Outcome.YES else "no"
        opposite_key = "no" if outcome == Outcome.YES else "yes"

        # Parse bids (buy orders for this outcome)
        bids_data = data.get(f"{side_key}_bids", {})
        for price_str, quantity in bids_data.items():
            bids.append((Decimal(price_str), Decimal(str(quantity))))
        bids.sort(key=lambda x: x[0], reverse=True)  # Highest bid first

        # Asks are implied from opposite side bids (buying NO = selling YES)
        opposite_bids = data.get(f"{opposite_key}_bids", {})
        for price_str, quantity in opposite_bids.items():
            # Ask price for YES = 1 - bid price for NO
            ask_price = Decimal("1") - Decimal(price_str)
            asks.append((ask_price, Decimal(str(quantity))))
        asks.sort(key=lambda x: x[0])  # Lowest ask first

        return OrderBook(
            market_id=market_id,
            outcome=outcome,
            bids=bids,
            asks=asks,
        )
    
    # ===================
    # Trading
    # ===================
    
    async def get_quote(
        self,
        market_id: str,
        outcome: Outcome,
        side: str,
        amount: Decimal,
        token_id: str = None,
    ) -> Quote:
        """Get a quote for a trade via DFlow.

        Note: token_id is accepted for API compatibility but ignored -
        Kalshi determines tokens from market data.
        """
        # Get market to find token addresses
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.KALSHI)
        
        # Determine tokens
        if outcome == Outcome.YES:
            output_token = market.yes_token
        else:
            output_token = market.no_token
        
        if not output_token:
            raise PlatformError(
                f"Token not found for {outcome.value}",
                Platform.KALSHI,
            )

        input_token = self.USDC_MINT
        
        # Convert amount to smallest unit (USDC has 6 decimals)
        amount_raw = int(amount * Decimal(10**self.collateral_decimals))
        
        # Build quote request
        params = {
            "inputMint": input_token if side == "buy" else output_token,
            "outputMint": output_token if side == "buy" else input_token,
            "amount": str(amount_raw),
            "slippageBps": 100,  # 1%
        }

        logger.debug("Quote request params", params=params)
        data = await self._trading_request("GET", "/order", params=params)

        # Log quote response for debugging
        logger.debug(
            "Quote response data",
            inAmount=data.get("inAmount"),
            outAmount=data.get("outAmount"),
            price=data.get("price"),
            priceImpactPct=data.get("priceImpactPct"),
        )

        # Parse quote response
        # inAmount = actual USDC to spend, outAmount = tokens to receive
        in_amount_raw = Decimal(str(data.get("inAmount", 0)))
        out_amount_raw = Decimal(str(data.get("outAmount", 0)))

        # Convert from smallest units (6 decimals)
        actual_input = in_amount_raw / Decimal(10**self.collateral_decimals)
        expected_output = out_amount_raw / Decimal(10**self.collateral_decimals)

        # Price per token = what you pay / what you get
        price_per_token = actual_input / expected_output if expected_output > 0 else Decimal(0)

        logger.debug(
            "Calculated quote price",
            actual_input=str(actual_input),
            expected_output=str(expected_output),
            price_per_token=str(price_per_token),
        )
        
        # Handle nullable fields
        price_impact_raw = data.get("priceImpactPct")
        price_impact = Decimal(str(price_impact_raw)) if price_impact_raw is not None else Decimal(0)

        platform_fee_raw = data.get("platformFee")
        platform_fee = Decimal(str(platform_fee_raw)) / Decimal(10**6) if platform_fee_raw is not None else Decimal(0)

        return Quote(
            platform=Platform.KALSHI,
            chain=Chain.SOLANA,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token if side == "buy" else output_token,
            input_amount=actual_input,
            output_token=output_token if side == "buy" else input_token,
            expected_output=expected_output,
            price_per_token=price_per_token,
            price_impact=price_impact,
            platform_fee=platform_fee,
            network_fee_estimate=Decimal("0.001"),  # ~0.001 SOL
            expires_at=None,
            quote_data=data,
        )
    
    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """Execute a trade using the DFlow order endpoint."""
        if not isinstance(private_key, Keypair):
            raise PlatformError(
                "Invalid private key type, expected Solana Keypair",
                Platform.KALSHI,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.KALSHI)

        try:
            # Get transaction from DFlow /order endpoint with userPublicKey
            # This returns the transaction directly, no need for /swap
            params = {
                "inputMint": quote.input_token,
                "outputMint": quote.output_token,
                "amount": str(int(quote.input_amount * Decimal(10**self.collateral_decimals))),
                "slippageBps": 100,
                "userPublicKey": str(private_key.pubkey()),
            }

            # Add platform fee collection if configured with valid Solana address
            # For prediction market (outcome token) trades, must use platformFeeScale
            # instead of platformFeeBps. platformFeeMode is ignored for outcome tokens.
            # Fee formula: k * p * (1 - p) * amount, where k = scale/1000
            # feeAccount must be a USDC token account (ATA) for the settlement mint
            fee_enabled = bool(self._fee_account and len(self._fee_account) >= 32)
            if fee_enabled:
                params["feeAccount"] = self._fee_account
                # Use platformFeeScale for prediction markets (not platformFeeBps)
                # Scale of 50 = 0.050, gives ~1% fee at typical probabilities
                params["platformFeeScale"] = str(self._fee_bps // 2)  # Convert bps to scale
                logger.debug(
                    "Fee collection enabled",
                    fee_account=self._fee_account[:8] + "...",
                    fee_scale=params["platformFeeScale"],
                )

            try:
                response = await self._trading_request(
                    "GET",
                    "/order",
                    params=params,
                )
            except PlatformError as e:
                # If route not found with fee params, retry without fees
                if "route_not_found" in str(e).lower() and fee_enabled:
                    logger.warning(
                        "Route not found with fee params, retrying without fees",
                        market_id=quote.market_id,
                    )
                    params.pop("feeAccount", None)
                    params.pop("platformFeeScale", None)
                    response = await self._trading_request(
                        "GET",
                        "/order",
                        params=params,
                    )
                else:
                    raise

            # Decode and sign transaction (returned directly from /order)
            tx_data = base64.b64decode(response["transaction"])
            tx = VersionedTransaction.from_bytes(tx_data)

            # Debug: Log transaction structure
            num_signers = tx.message.header.num_required_signatures
            account_keys = tx.message.account_keys
            user_pubkey = private_key.pubkey()

            logger.debug(
                "Transaction structure",
                num_required_signatures=num_signers,
                num_account_keys=len(account_keys),
                user_pubkey=str(user_pubkey),
                first_signers=[str(account_keys[i]) for i in range(min(num_signers, len(account_keys)))],
                num_existing_sigs=len(tx.signatures),
            )

            # Verify our public key is in the expected signers
            if user_pubkey not in account_keys[:num_signers]:
                logger.error(
                    "User public key not found in signers",
                    user_pubkey=str(user_pubkey),
                    expected_signers=[str(account_keys[i]) for i in range(num_signers)],
                )
                raise RuntimeError(f"User public key {user_pubkey} not found in transaction signers")

            # Create a new signed transaction using the keypair directly
            # This is the proper way to sign a versioned transaction in solders
            signed_tx = VersionedTransaction(tx.message, [private_key])

            logger.debug(
                "Signed transaction",
                sig_count=len(signed_tx.signatures),
                first_sig=str(signed_tx.signatures[0])[:20] + "..." if signed_tx.signatures else "none",
            )
            
            # Submit to Solana
            if not self._solana_client:
                raise RuntimeError("Solana client not initialized")

            result = await self._solana_client.send_transaction(
                signed_tx,
                opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed),
            )
            
            tx_hash = str(result.value)
            
            logger.info(
                "Trade executed",
                platform="kalshi",
                market_id=quote.market_id,
                tx_hash=tx_hash,
            )
            
            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash),
            )
            
        except Exception as e:
            logger.error("Trade execution failed", error=str(e))
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=str(e),
                explorer_url=None,
            )

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """
        Check if a Kalshi market has resolved and what the outcome is.

        Uses the DFlow metadata API to check market status.
        """
        try:
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Check status from market data
            status = market.raw_data.get("status", "")
            result = market.raw_data.get("result")

            # Kalshi uses "settled" or "finalized" for resolved markets
            is_resolved = status.lower() in ["settled", "finalized", "closed"]

            if not is_resolved:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Determine winning outcome from result
            winning_outcome = None
            if result:
                result_lower = str(result).lower()
                if result_lower in ["yes", "1", "true"]:
                    winning_outcome = "yes"
                elif result_lower in ["no", "0", "false"]:
                    winning_outcome = "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning_outcome,
                resolution_time=market.raw_data.get("settledAt") or market.raw_data.get("close_time"),
            )

        except Exception as e:
            logger.error("Failed to check market resolution", error=str(e), market_id=market_id)
            return MarketResolution(
                is_resolved=False,
                winning_outcome=None,
                resolution_time=None,
            )

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """
        Redeem winning tokens from a resolved Kalshi market via DFlow.

        Uses the DFlow /redeem endpoint to claim winnings.
        """
        if not isinstance(private_key, Keypair):
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message="Invalid private key type, expected Solana Keypair",
                explorer_url=None,
            )

        try:
            # Check if market is resolved
            resolution = await self.get_market_resolution(market_id)
            if not resolution.is_resolved:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Market has not resolved yet",
                    explorer_url=None,
                )

            # Check if user holds winning outcome
            if resolution.winning_outcome and resolution.winning_outcome.lower() != outcome.value.lower():
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message=f"Your {outcome.value.upper()} tokens lost. The market resolved to {resolution.winning_outcome.upper()}.",
                    explorer_url=None,
                )

            # Get market to find token address
            market = await self.get_market(market_id)
            if not market:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Market not found",
                    explorer_url=None,
                )

            # Get the outcome token address
            token_mint = market.yes_token if outcome == Outcome.YES else market.no_token
            if not token_mint:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Token address not found",
                    explorer_url=None,
                )

            # Call DFlow /redeem endpoint
            amount_raw = int(token_amount * Decimal(10**self.collateral_decimals))

            params = {
                "tokenMint": token_mint,
                "amount": str(amount_raw),
                "userPublicKey": str(private_key.pubkey()),
            }

            try:
                response = await self._trading_request("GET", "/redeem", params=params)
            except PlatformError as e:
                # If /redeem endpoint doesn't exist, try selling at $1
                if "not found" in str(e).lower() or "404" in str(e):
                    logger.warning("DFlow /redeem endpoint not available, attempting sell instead")
                    # For resolved markets, winning tokens are worth $1
                    # Try to sell them back
                    quote = await self.get_quote(
                        market_id=market_id,
                        outcome=outcome,
                        side="sell",
                        amount=token_amount,
                    )
                    result = await self.execute_trade(quote, private_key)
                    return RedemptionResult(
                        success=result.success,
                        tx_hash=result.tx_hash,
                        amount_redeemed=result.output_amount,
                        error_message=result.error_message,
                        explorer_url=result.explorer_url,
                    )
                raise

            # Get and sign the redemption transaction
            tx_data = response.get("transaction")
            if not tx_data:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="No transaction returned from API",
                    explorer_url=None,
                )

            # Decode and sign transaction
            tx_bytes = base64.b64decode(tx_data)
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Sign the transaction
            tx.sign([private_key])

            # Send transaction
            result = await self._solana_client.send_transaction(
                tx,
                opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
            )

            tx_hash = str(result.value)

            logger.info(
                "Redemption transaction sent",
                tx_hash=tx_hash,
                market_id=market_id,
                outcome=outcome.value,
            )

            # Confirm transaction
            await self._solana_client.confirm_transaction(
                result.value,
                commitment=Confirmed,
            )

            # Calculate redeemed amount (winning tokens worth $1)
            amount_redeemed = token_amount

            logger.info(
                "Redemption confirmed",
                tx_hash=tx_hash,
                amount_redeemed=str(amount_redeemed),
            )

            return RedemptionResult(
                success=True,
                tx_hash=tx_hash,
                amount_redeemed=amount_redeemed,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash),
            )

        except Exception as e:
            logger.error("Redemption failed", error=str(e), market_id=market_id)
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message=str(e),
                explorer_url=None,
            )

    async def get_token_balance(
        self,
        wallet_pubkey: str,
        token_mint: str,
    ) -> Decimal:
        """
        Get the actual on-chain balance of a specific token for a wallet.

        Args:
            wallet_pubkey: The wallet's public key
            token_mint: The token mint address

        Returns:
            Token balance as Decimal (in human-readable units, not raw)
        """
        try:
            if not self._solana_client:
                await self.initialize()

            from solders.pubkey import Pubkey
            from solana.rpc.types import TokenAccountOpts

            # Query token accounts for this specific mint
            response = await self._solana_client.get_token_accounts_by_owner_json_parsed(
                Pubkey.from_string(wallet_pubkey),
                TokenAccountOpts(mint=Pubkey.from_string(token_mint)),
            )

            if response.value:
                for account in response.value:
                    parsed = account.account.data.parsed
                    if parsed and "info" in parsed:
                        token_amount = parsed["info"].get("tokenAmount", {})
                        ui_amount = token_amount.get("uiAmount", 0)
                        if ui_amount:
                            return Decimal(str(ui_amount))

            return Decimal("0")

        except Exception as e:
            logger.error(
                "Failed to get token balance",
                error=str(e),
                wallet=wallet_pubkey[:8] + "...",
                mint=token_mint[:8] + "...",
            )
            return Decimal("0")


# Singleton instance
kalshi_platform = KalshiPlatform()
