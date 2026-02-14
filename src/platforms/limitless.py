"""
Limitless Exchange platform implementation.
Prediction market on Base chain using CLOB API.
"""

import asyncio
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional, Tuple
import time

from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

from limitless_sdk.api import HttpClient as LimitlessHttpClient
from limitless_sdk.markets import MarketFetcher
from limitless_sdk.orders import OrderClient
from limitless_sdk.types import Side, OrderType

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

# Limitless API endpoints
LIMITLESS_API_BASE = "https://api.limitless.exchange"

# USDC on Base
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Limitless Categories (ID -> Name mapping)
LIMITLESS_CATEGORIES = {
    "29": "Hourly",
    "30": "Daily",
    "31": "Weekly",
    "2": "Crypto",
    "1": "Sports",
    "49": "Football Matches",
    "50": "Off the Pitch",
    "23": "Economy",
    "43": "Pre-TGE",
    "19": "Company News",
    "48": "This vs That",
    "42": "Korean Market",
    "5": "Other",
}

# ERC20 ABI for USDC transfers
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

# CTF (Conditional Token Framework) ABI for redemption
CTF_REDEEM_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "index", "type": "uint256"}
        ],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

# FixedProductMarketMaker ABI for AMM trading (Gnosis-style)
FPMM_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "investmentAmount", "type": "uint256"},
            {"name": "outcomeIndex", "type": "uint256"},
            {"name": "minOutcomeTokensToBuy", "type": "uint256"}
        ],
        "name": "buy",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "returnAmount", "type": "uint256"},
            {"name": "outcomeIndex", "type": "uint256"},
            {"name": "maxOutcomeTokensToSell", "type": "uint256"}
        ],
        "name": "sell",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "investmentAmount", "type": "uint256"},
            {"name": "outcomeIndex", "type": "uint256"}
        ],
        "name": "calcBuyAmount",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "returnAmount", "type": "uint256"},
            {"name": "outcomeIndex", "type": "uint256"}
        ],
        "name": "calcSellAmount",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "collateralToken",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "fee",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]


class LimitlessPlatform(BasePlatform):
    """
    Limitless Exchange prediction market platform.
    Uses CLOB API on Base chain, with support for AMM markets.
    """

    platform = Platform.LIMITLESS
    chain = Chain.BASE

    name = "Limitless"
    description = "Prediction market on Base"
    website = "https://limitless.exchange"

    collateral_symbol = "USDC"
    collateral_decimals = 6

    def __init__(self):
        self._sdk_client: Optional[LimitlessHttpClient] = None
        self._market_fetcher: Optional[MarketFetcher] = None
        self._web3: Optional[AsyncWeb3] = None
        self._sync_web3: Optional[Web3] = None
        self._fee_account = settings.evm_fee_account
        self._fee_bps = settings.evm_fee_bps
        # API key authentication (required)
        self._api_key = settings.limitless_api_key
        self._api_url = settings.limitless_api_url or LIMITLESS_API_BASE
        # User info cache (for API key auth)
        self._user_info_cache: dict[str, dict] = {}
        # Per-wallet OrderClient cache (pattern from Polymarket's _get_clob_client)
        self._order_client_cache: dict[str, OrderClient] = {}
        # Approval cache
        self._approval_cache: dict[str, set[str]] = {}
        # ID to slug cache (numeric ID -> slug for API lookups)
        self._id_to_slug_cache: dict[str, str] = {}
        # Group market cache (slug -> raw group data for nested markets)
        self._group_market_cache: dict[str, dict] = {}
        # Markets cache (avoid re-fetching pages within TTL)
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self.CACHE_TTL = 300  # 5 minutes

    async def initialize(self) -> None:
        """Initialize Limitless SDK clients."""
        if not self._api_key:
            raise PlatformError(
                "Limitless API key not configured. "
                "Get your API key from https://limitless.exchange profile -> Api keys",
                Platform.LIMITLESS,
            )

        # Initialize SDK HttpClient and MarketFetcher
        self._sdk_client = LimitlessHttpClient(
            base_url=self._api_url,
            api_key=self._api_key,
        )
        self._market_fetcher = MarketFetcher(http_client=self._sdk_client)

        # Async Web3 for Base
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.base_rpc_url)
        )

        # Sync Web3 for fee collection
        self._sync_web3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))

        fee_enabled = bool(self._fee_account and Web3.is_address(self._fee_account))
        logger.info(
            "Limitless platform initialized (SDK)",
            api_url=self._api_url,
            fee_collection=fee_enabled,
            fee_bps=self._fee_bps if fee_enabled else 0,
        )

    async def close(self) -> None:
        """Close connections."""
        if self._sdk_client:
            await self._sdk_client.close()

    # ===================
    # API Helpers
    # ===================

    async def _sdk_get(self, endpoint: str, **kwargs) -> Any:
        """Make GET request via SDK HttpClient with error handling."""
        if not self._sdk_client:
            raise RuntimeError("SDK client not initialized")
        try:
            return await self._sdk_client.get(endpoint, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                raise RateLimitError("Rate limit exceeded", Platform.LIMITLESS)
            raise PlatformError(f"API error: {e}", Platform.LIMITLESS)

    async def _sdk_post(self, endpoint: str, **kwargs) -> Any:
        """Make POST request via SDK HttpClient with error handling."""
        if not self._sdk_client:
            raise RuntimeError("SDK client not initialized")
        try:
            return await self._sdk_client.post(endpoint, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                raise RateLimitError("Rate limit exceeded", Platform.LIMITLESS)
            raise PlatformError(f"API error: {e}", Platform.LIMITLESS)

    async def _get_user_info(self, wallet: str) -> Tuple[str, int]:
        """Get user info (owner_id, fee_rate_bps) via SDK client.

        Returns: (owner_id, fee_rate_bps)
        """
        # Check cache
        cached = self._user_info_cache.get(wallet)
        if cached and cached.get("expires_at", 0) > time.time():
            return cached.get("owner_id", ""), cached.get("fee_rate_bps", 300)

        try:
            user_data = await self._sdk_get("/auth/me")

            owner_id = user_data.get("id") or user_data.get("ownerId") or ""
            rank_data = user_data.get("rank", {})
            fee_rate_bps = rank_data.get("feeRateBps", 300) if rank_data else 300

            logger.info(
                "Limitless user info fetched",
                owner_id=owner_id,
                fee_rate_bps=fee_rate_bps,
            )

            # Cache user info (24 hours)
            self._user_info_cache[wallet] = {
                "owner_id": owner_id,
                "fee_rate_bps": fee_rate_bps,
                "expires_at": time.time() + 24 * 3600,
            }

            return owner_id, fee_rate_bps

        except Exception as e:
            logger.warning(
                "Failed to get user info, will use default fee rate",
                error=str(e),
            )
            return "", 300

    def _get_order_client(self, private_key: LocalAccount) -> OrderClient:
        """Get or create cached OrderClient for a wallet."""
        wallet = private_key.address
        if wallet in self._order_client_cache:
            return self._order_client_cache[wallet]
        client = OrderClient(http_client=self._sdk_client, wallet=private_key)
        self._order_client_cache[wallet] = client
        return client

    # ===================
    # Market Discovery
    # ===================

    def _is_market_active(self, data: dict) -> bool:
        """Determine if a market is still active (tradeable).

        A market is NOT active if it's resolved, expired, or closed.
        """
        status = str(data.get("status", "")).lower()
        winning_index = data.get("winning_index") or data.get("winningIndex")
        is_expired = data.get("expired", False)
        is_closed = data.get("closed", False)

        # Market is resolved if winning_index exists
        if winning_index is not None:
            return False

        # Market is not active if status indicates resolution/closure
        if status in ("resolved", "expired", "settled", "closed"):
            return False

        # Market is not active if explicitly expired or closed
        if is_expired or is_closed:
            return False

        # Otherwise check positive status indicators
        if status in ("active", "funded", "live"):
            return True

        # Fallback to isActive field with default True
        return data.get("isActive", True)

    def _parse_market(self, data: dict, parent_group: dict = None) -> Market:
        """Parse Limitless market data into Market object.

        Args:
            data: Market data from API
            parent_group: Optional parent group data for nested markets
        """
        # Check if this is a group market with nested markets
        is_group = data.get("marketType") == "group" or (
            data.get("markets") and isinstance(data.get("markets"), list) and len(data.get("markets")) > 1
        )

        # Extract prices
        # Prefer tradePrices.buy.market (actual price you'd pay) over prices (last/mid price)
        yes_price = None
        no_price = None

        # First try tradePrices which shows actual executable prices
        trade_prices = data.get("tradePrices", {})
        buy_market = trade_prices.get("buy", {}).get("market")
        if buy_market and isinstance(buy_market, list) and len(buy_market) >= 2:
            # buy.market = [YES price, NO price] - what you'd pay to buy each outcome
            yes_buy = Decimal(str(buy_market[0]))
            no_buy = Decimal(str(buy_market[1]))
            # Only use if prices look valid (not 0 or 1 which indicate no liquidity)
            if Decimal("0.01") < yes_buy < Decimal("0.99"):
                yes_price = yes_buy
                no_price = Decimal("1") - yes_price  # Calculate NO from YES for consistency
            elif Decimal("0.01") < no_buy < Decimal("0.99"):
                no_price = no_buy
                yes_price = Decimal("1") - no_price

        # Fall back to prices (last traded or mid-market price)
        if yes_price is None:
            prices = data.get("prices") or data.get("outcomePrices")
            if prices:
                if isinstance(prices, dict):
                    yes_price = Decimal(str(prices.get("yes", prices.get("0", 0.5))))
                    no_price = Decimal(str(prices.get("no", prices.get("1", 0.5))))
                elif isinstance(prices, list) and len(prices) >= 2:
                    yes_price = Decimal(str(prices[0]))
                    no_price = Decimal(str(prices[1]))

        # If no prices, try lastPrice or default
        if yes_price is None:
            last_price = data.get("lastPrice") or data.get("price")
            if last_price is not None:
                yes_price = Decimal(str(last_price))
                no_price = Decimal("1") - yes_price
            else:
                yes_price = Decimal("0.5")
                no_price = Decimal("0.5")

        # Normalize prices: if they're in 0-100 range, convert to 0-1
        if yes_price is not None and yes_price > 1:
            yes_price = yes_price / Decimal("100")
        if no_price is not None and no_price > 1:
            no_price = no_price / Decimal("100")

        # Extract token IDs
        outcomes = data.get("outcomes") or data.get("tokens") or []
        yes_token = None
        no_token = None
        if outcomes:
            if isinstance(outcomes, list):
                if len(outcomes) > 0:
                    yes_token = outcomes[0].get("tokenId") if isinstance(outcomes[0], dict) else str(outcomes[0])
                if len(outcomes) > 1:
                    no_token = outcomes[1].get("tokenId") if isinstance(outcomes[1], dict) else str(outcomes[1])
            elif isinstance(outcomes, dict):
                yes_token = outcomes.get("yes") or outcomes.get("0")
                no_token = outcomes.get("no") or outcomes.get("1")

        # Market ID - use numeric ID for shorter callbacks, keep slug in event_id for display
        # Numeric IDs are much shorter and fit within Telegram's 64-byte callback limit
        numeric_id = data.get("id")
        slug = data.get("slug") or data.get("address") or ""
        market_id = str(numeric_id) if numeric_id else slug

        # Cache the ID-to-slug mapping for later lookups
        if numeric_id and slug:
            self._id_to_slug_cache[str(numeric_id)] = slug

        # Volume - prefer volumeFormatted (already in USDC), otherwise convert raw
        volume_formatted = data.get("volumeFormatted")
        if volume_formatted:
            try:
                volume = Decimal(str(volume_formatted))
            except:
                volume = Decimal("0")
        else:
            # Raw volume is in USDC base units (6 decimals)
            raw_volume = data.get("volume") or data.get("volume24h") or data.get("volumeUsd") or 0
            if raw_volume:
                volume = Decimal(str(raw_volume)) / Decimal("1000000")
            else:
                volume = Decimal("0")

        # Liquidity
        liquidity = data.get("liquidity") or data.get("tvl") or 0

        # Category
        category = None
        if data.get("category"):
            category = data["category"].get("name") if isinstance(data["category"], dict) else data["category"]

        # NegRisk grouping for multi-outcome markets
        # negRiskMarketId groups related markets together
        neg_risk_id = data.get("negRiskMarketId") or data.get("neg_risk_market_id")
        # For nested markets in a group, use parent's negRiskMarketId
        if parent_group:
            neg_risk_id = parent_group.get("negRiskMarketId") or parent_group.get("neg_risk_market_id") or neg_risk_id
        # Use negRiskMarketId as event_id for grouping, fall back to slug
        event_id = neg_risk_id or slug

        # Resolution criteria - check multiple possible fields
        resolution_criteria = (
            data.get("rules") or
            data.get("resolutionRules") or
            data.get("resolution_rules") or
            data.get("settlementRules") or
            data.get("description")  # Fallback to description which may contain rules
        )

        # Determine if this is a multi-outcome market
        nested_markets = data.get("markets", [])
        is_multi_outcome = is_group or len(nested_markets) > 1
        related_count = len(nested_markets) if nested_markets else None

        # For nested markets, use the title as outcome name
        outcome_name = None
        if parent_group:
            outcome_name = data.get("title") or data.get("question", "")
            # Limit outcome name length
            if outcome_name and len(outcome_name) > 50:
                outcome_name = outcome_name[:47] + "..."

        return Market(
            platform=Platform.LIMITLESS,
            chain=Chain.BASE,
            market_id=market_id,
            event_id=event_id,  # Use negRiskMarketId for grouping multi-outcome markets
            title=parent_group.get("title") if parent_group else (data.get("title") or data.get("question", "")),
            description=data.get("description"),
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume if volume else None,
            liquidity=Decimal(str(liquidity)) if liquidity else None,
            is_active=self._is_market_active(data),
            # Prefer expirationTimestamp (milliseconds) for accurate time, fallback to date strings
            close_time=data.get("expirationTimestamp") or data.get("expirationDate") or data.get("endDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            resolution_criteria=resolution_criteria,
            is_multi_outcome=is_multi_outcome,
            related_market_count=related_count,
            outcome_name=outcome_name,
        )

    def _parse_group_markets(self, group_data: dict) -> list[Market]:
        """Parse a group market response into individual outcome markets.

        Group markets have marketType='group' and contain nested 'markets' array
        with individual outcomes (e.g., team markets for NBA Champion).

        Args:
            group_data: The group market response from API

        Returns:
            List of Market objects, one per outcome
        """
        nested_markets = group_data.get("markets", [])
        if not nested_markets:
            # Not a group market or no nested markets, return empty
            return []

        group_title = group_data.get("title") or group_data.get("question", "")
        neg_risk_id = group_data.get("negRiskMarketId") or group_data.get("neg_risk_market_id")
        total_outcomes = len(nested_markets)

        # Cache the group slug for later lookups
        group_slug = group_data.get("slug", "")
        group_id = group_data.get("id")
        if group_id and group_slug:
            self._id_to_slug_cache[str(group_id)] = group_slug

        markets = []
        for item in nested_markets:
            try:
                market = self._parse_market(item, parent_group=group_data)
                # Override with group-level info
                market.is_multi_outcome = True
                market.related_market_count = total_outcomes
                # Use nested market's title as outcome name
                market.outcome_name = item.get("title") or item.get("question", "")
                if market.outcome_name and len(market.outcome_name) > 50:
                    market.outcome_name = market.outcome_name[:47] + "..."
                # Use group title as the market title
                market.title = group_title
                # Use negRiskMarketId for event_id grouping
                if neg_risk_id:
                    market.event_id = neg_risk_id
                markets.append(market)
            except Exception as e:
                logger.warning("Failed to parse nested market", error=str(e))

        # Sort by YES price descending (highest probability first)
        markets.sort(key=lambda m: m.yes_price or Decimal("0"), reverse=True)

        logger.debug(
            "Parsed group market",
            group_title=group_title,
            total_outcomes=total_outcomes,
            parsed_count=len(markets),
        )

        return markets

    def _is_group_market(self, data: dict) -> bool:
        """Check if API response is a group market with nested outcomes."""
        return (
            data.get("marketType") == "group" or
            (data.get("markets") and isinstance(data.get("markets"), list) and len(data.get("markets")) > 1)
        )

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Limitless.

        Fetches all active markets and caches for 5 minutes to avoid
        repeated pagination across the 25-per-page API limit.
        """
        import time

        # Check if cache is still valid
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self.CACHE_TTL:
            return self._markets_cache[offset:offset + limit]

        # API limit is 25 per page, so paginate to fetch all
        api_page_size = 25
        max_pages = 12  # Cap at 300 markets

        all_items = []
        for page_num in range(1, max_pages + 1):
            params = {
                "limit": api_page_size,
                "page": page_num,
            }
            try:
                data = await self._sdk_get("/markets/active", params=params)
                items = data if isinstance(data, list) else data.get("data", data.get("markets", []))
                if not items:
                    break  # No more pages
                all_items.extend(items)
            except Exception as e:
                logger.error("Failed to fetch markets page", page=page_num, error=str(e))
                break

        markets = []
        for item in all_items:
            try:
                market = self._parse_market(item)
                if not active_only or market.is_active:
                    markets.append(market)
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))

        # Detect multi-outcome markets (NegRisk groups)
        # Group markets by event_id (which is negRiskMarketId for grouped markets)
        from collections import defaultdict
        event_groups = defaultdict(list)
        for m in markets:
            if m.event_id:
                event_groups[m.event_id].append(m)

        # Mark multi-outcome markets and extract outcome names
        for event_id, group in event_groups.items():
            if len(group) > 1:
                for m in group:
                    m.is_multi_outcome = True
                    m.related_market_count = len(group)

                    # Extract outcome name from title
                    title = m.title
                    outcome_name = None

                    if " - " in title:
                        outcome_name = title.split(" - ")[-1]
                    elif ":" in title:
                        outcome_name = title.split(":")[-1].strip()
                    elif title.lower().startswith("will "):
                        outcome_name = title[5:].replace(" win?", "").replace("?", "").strip()
                    elif " to " in title.lower():
                        outcome_name = title.split(" to ")[0].strip()
                    else:
                        outcome_name = title

                    m.outcome_name = outcome_name[:50] if outcome_name else None

        # Update cache
        self._markets_cache = markets
        self._markets_cache_time = now

        return markets[offset:offset + limit]

    async def search_markets(
        self,
        query: str,
        limit: int = 50,
    ) -> list[Market]:
        """Search markets by query."""
        try:
            data = await self._sdk_get(
                "/markets/search",
                params={"query": query, "limit": min(limit, 100)}
            )
        except Exception as e:
            logger.error("Failed to search markets", error=str(e))
            # Fallback: use cached markets and filter client-side
            all_markets = await self.get_markets(limit=300)
            query_lower = query.lower()
            return [
                m for m in all_markets
                if query_lower in m.title.lower() or (m.description and query_lower in m.description.lower())
            ][:limit]

        markets = []
        items = data if isinstance(data, list) else data.get("data", data.get("markets", data.get("results", [])))

        for item in items:
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market in search", error=str(e))

        return markets[:limit]

    async def get_market(self, market_id: str, search_title: Optional[str] = None, include_closed: bool = False) -> Optional[Market]:
        """Get a specific market by ID (numeric) or slug.

        Args:
            market_id: The market ID (numeric) or slug
            search_title: Optional title to search for if direct lookup fails
            include_closed: Accepted for API compatibility (not used - Limitless returns all markets)

        Note: Prefers fetching via get_markets() to get multi-outcome info.
        """
        # If market_id is numeric, try to get slug from cache first
        lookup_id = market_id
        if market_id.isdigit():
            cached_slug = self._id_to_slug_cache.get(market_id)
            if cached_slug:
                lookup_id = cached_slug
                logger.debug("Using cached slug for market", numeric_id=market_id, slug=cached_slug)

        # First, try to find via get_markets (has multi-outcome detection)
        market = None
        try:
            # Fetch markets to find one with matching ID (has multi-outcome info)
            all_markets = await self.get_markets(limit=200, offset=0, active_only=False)
            for m in all_markets:
                if m.market_id == market_id or m.event_id == market_id or m.event_id == lookup_id:
                    market = m
                    break
        except Exception as e:
            logger.debug("Market list search failed", error=str(e))

        # Fallback: try direct lookup by slug
        # This handles group markets with nested outcomes (e.g., NBA Champion)
        if not market:
            try:
                data = await self._sdk_get(f"/markets/{lookup_id}")
                # Check if this is a group market with nested outcomes
                if self._is_group_market(data):
                    logger.info("Detected group market", slug=lookup_id)
                    # Cache the raw group data for get_related_markets()
                    # Cache by both slug AND negRiskMarketId for lookup flexibility
                    self._group_market_cache[lookup_id] = data
                    neg_risk_id = data.get("negRiskMarketId") or data.get("neg_risk_market_id")
                    if neg_risk_id:
                        self._group_market_cache[neg_risk_id] = data
                    # Parse all nested markets
                    nested_markets = self._parse_group_markets(data)
                    if nested_markets:
                        market = nested_markets[0]  # Return highest probability outcome
                else:
                    market = self._parse_market(data)
            except Exception as e:
                logger.debug("Direct market lookup failed", market_id=lookup_id, error=str(e))

        # If we haven't tried the original market_id yet (different from lookup_id), try it
        if not market and lookup_id != market_id:
            try:
                data = await self._sdk_get(f"/markets/{market_id}")
                # Check if this is a group market with nested outcomes
                if self._is_group_market(data):
                    logger.info("Detected group market", slug=market_id)
                    # Cache by both slug AND negRiskMarketId
                    self._group_market_cache[market_id] = data
                    neg_risk_id = data.get("negRiskMarketId") or data.get("neg_risk_market_id")
                    if neg_risk_id:
                        self._group_market_cache[neg_risk_id] = data
                    nested_markets = self._parse_group_markets(data)
                    if nested_markets:
                        market = nested_markets[0]
                else:
                    market = self._parse_market(data)
            except Exception as e:
                logger.debug("Fallback market lookup failed", market_id=market_id, error=str(e))

        # Last resort: search by title if provided
        if not market and search_title and market_id.isdigit():
            try:
                logger.debug(f"Trying title search for market {market_id}: {search_title[:50]}...")
                search_results = await self.search_markets(search_title[:50], limit=10)
                for m in search_results:
                    if m.market_id == market_id:
                        logger.info(f"Found market {market_id} via title search")
                        market = m
                        break
            except Exception as e:
                logger.debug("Title search failed", error=str(e))

        # ALWAYS get orderbook prices - API prices can be stale
        # This ensures displayed price matches the quote price (which uses orderbook.best_ask)
        if market:
            try:
                from src.db.models import Outcome
                # Get YES orderbook for price - use best_ask since that's what buy orders use
                orderbook = await self.get_orderbook(market.market_id, Outcome.YES, slug=market.event_id)
                if orderbook.best_ask or orderbook.best_bid:
                    # For display, use best_ask (what buyers pay) to match quote price
                    yes_price = orderbook.best_ask or orderbook.best_bid
                    # Update market prices (preserve multi-outcome and resolution fields)
                    market = Market(
                        platform=market.platform,
                        chain=market.chain,
                        market_id=market.market_id,
                        event_id=market.event_id,
                        title=market.title,
                        description=market.description,
                        category=market.category,
                        yes_price=yes_price,
                        no_price=Decimal("1") - yes_price,
                        volume_24h=market.volume_24h,
                        liquidity=market.liquidity,
                        is_active=market.is_active,
                        close_time=market.close_time,
                        yes_token=market.yes_token,
                        no_token=market.no_token,
                        raw_data=market.raw_data,
                        outcome_name=market.outcome_name,
                        is_multi_outcome=market.is_multi_outcome,
                        related_market_count=market.related_market_count,
                        resolution_criteria=market.resolution_criteria,
                    )
            except Exception as e:
                logger.debug("Failed to fetch orderbook for prices", error=str(e))

        return market

    async def get_trending_markets(self, limit: int = 20) -> list[Market]:
        """Get trending markets by volume."""
        return await self.get_markets(limit=limit, active_only=True)

    async def get_related_markets(self, event_id: str) -> list[Market]:
        """Get all markets related to an event (for multi-outcome NegRisk markets).

        Args:
            event_id: The negRiskMarketId, slug, or event identifier

        Returns:
            List of markets belonging to the same NegRisk group, sorted by probability
        """
        if not event_id:
            return []

        # Check if we have cached group data from get_market()
        if event_id in self._group_market_cache:
            logger.debug("Using cached group market data", event_id=event_id)
            return self._parse_group_markets(self._group_market_cache[event_id])

        # Try to fetch directly as a group market (slug lookup)
        # This handles cases where event_id is the market slug
        try:
            data = await self._sdk_get(f"/markets/{event_id}")
            if self._is_group_market(data):
                logger.info("Fetched group market for related markets", event_id=event_id)
                self._group_market_cache[event_id] = data
                return self._parse_group_markets(data)
        except Exception as e:
            logger.debug("Group market lookup failed", event_id=event_id, error=str(e))

        # Also check by negRiskMarketId in the cache
        for slug, group_data in self._group_market_cache.items():
            neg_risk_id = group_data.get("negRiskMarketId") or group_data.get("neg_risk_market_id")
            if neg_risk_id == event_id:
                logger.debug("Found group market by negRiskMarketId", neg_risk_id=neg_risk_id)
                return self._parse_group_markets(group_data)

        # Fallback: fetch markets and filter by event_id
        # Need to fetch enough to find all related markets
        all_markets = await self.get_markets(limit=200, offset=0, active_only=False)

        related = [m for m in all_markets if m.event_id == event_id]

        # Sort by YES price descending (highest probability first)
        related.sort(key=lambda m: m.yes_price or Decimal("0"), reverse=True)

        return related

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 20,
    ) -> list[Market]:
        """Get markets filtered by category ID."""
        # API limit is 25 max
        api_limit = min(limit, 25)
        try:
            data = await self._sdk_get(
                f"/markets/active/{category}",
                params={"limit": api_limit, "page": 1}
            )

            markets = []
            items = data if isinstance(data, list) else data.get("data", data.get("markets", []))

            for item in items:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.debug(f"Skipping market: {e}")

            return markets[:limit]

        except Exception as e:
            logger.error("Failed to get markets by category", error=str(e))
            return []

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories."""
        # Map category IDs to emojis
        category_emojis = {
            "29": "⏰",  # Hourly
            "30": "📅",  # Daily
            "31": "📆",  # Weekly
            "2": "🪙",   # Crypto
            "1": "🏆",   # Sports
            "49": "⚽",  # Football Matches
            "50": "🏟️",  # Off the Pitch
            "23": "📈",  # Economy
            "43": "🚀",  # Pre-TGE
            "19": "🏢",  # Company News
            "48": "⚔️",  # This vs That
            "42": "🇰🇷", # Korean Market
            "5": "📦",   # Other
        }
        return [
            {"id": cat_id, "label": name, "emoji": category_emojis.get(cat_id, "📊")}
            for cat_id, name in LIMITLESS_CATEGORIES.items()
        ]

    # ===================
    # Order Book
    # ===================

    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        token_id: str = None,
        slug: str = None,
    ) -> OrderBook:
        """Get order book from Limitless."""
        # Limitless API requires slug for orderbook, numeric IDs don't work
        # Try slug first if available, then look up from cache, then fall back to market_id
        endpoints_to_try = []
        if slug:
            endpoints_to_try.append(slug)

        # If market_id is numeric, try to get slug from cache
        if market_id and market_id.isdigit():
            cached_slug = self._id_to_slug_cache.get(market_id)
            if cached_slug and cached_slug not in endpoints_to_try:
                endpoints_to_try.append(cached_slug)
                logger.debug("Using cached slug for orderbook", market_id=market_id, slug=cached_slug)

        # Only try market_id if it's not a numeric ID (those always fail)
        if market_id and not market_id.isdigit() and market_id not in endpoints_to_try:
            endpoints_to_try.append(market_id)

        data = None
        for endpoint_id in endpoints_to_try:
            try:
                data = await self._sdk_get(f"/markets/{endpoint_id}/orderbook")
                break
            except Exception as e:
                logger.debug(f"Orderbook lookup failed for {endpoint_id}", error=str(e))

        if data is None:
            logger.error("Failed to fetch orderbook", market_id=market_id)
            return OrderBook(market_id=market_id, outcome=outcome, bids=[], asks=[])

        bids = []
        asks = []

        # Limitless orderbooks are for the YES outcome only (the market itself is binary)
        # For NO, we need to invert: NO ask = 1 - YES bid, NO bid = 1 - YES ask
        orderbook_data = data.get("yes") or data.get("orderbook", {}).get("yes") or data

        raw_bids = orderbook_data.get("bids", [])
        raw_asks = orderbook_data.get("asks", [])

        if outcome == Outcome.YES:
            # YES orderbook: use as-is
            for bid in raw_bids:
                price = Decimal(str(bid.get("price", bid[0] if isinstance(bid, list) else 0)))
                size = Decimal(str(bid.get("size", bid.get("quantity", bid[1] if isinstance(bid, list) else 0))))
                bids.append((price, size))

            for ask in raw_asks:
                price = Decimal(str(ask.get("price", ask[0] if isinstance(ask, list) else 0)))
                size = Decimal(str(ask.get("size", ask.get("quantity", ask[1] if isinstance(ask, list) else 0))))
                asks.append((price, size))
        else:
            # NO orderbook: invert prices (NO ask = 1 - YES bid, NO bid = 1 - YES ask)
            for bid in raw_bids:
                price = Decimal(str(bid.get("price", bid[0] if isinstance(bid, list) else 0)))
                size = Decimal(str(bid.get("size", bid.get("quantity", bid[1] if isinstance(bid, list) else 0))))
                # YES bid becomes NO ask (inverted)
                asks.append((Decimal("1") - price, size))

            for ask in raw_asks:
                price = Decimal(str(ask.get("price", ask[0] if isinstance(ask, list) else 0)))
                size = Decimal(str(ask.get("size", ask.get("quantity", ask[1] if isinstance(ask, list) else 0))))
                # YES ask becomes NO bid (inverted)
                bids.append((Decimal("1") - price, size))

        # Sort bids descending, asks ascending
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

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
        order_type: str = "market",  # "market" or "limit" - default to market
    ) -> Quote:
        """Get a quote for a trade.

        Args:
            market_id: Market identifier
            outcome: YES or NO
            side: "buy" or "sell"
            amount: Amount in USDC (buy) or tokens (sell)
            token_id: Optional token ID override
            order_type: "market" for immediate fill with slippage, "limit" for exact price
        """
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.LIMITLESS)

        # Check if this is an AMM market
        is_amm = False
        if market.raw_data:
            trade_type = market.raw_data.get("tradeType", "").lower()
            is_amm = trade_type == "amm"
            logger.debug(
                "Market trade type detected",
                market_id=market_id,
                trade_type=trade_type or "unknown",
                is_amm=is_amm,
            )

        # Get token ID
        if not token_id:
            token_id = market.yes_token if outcome == Outcome.YES else market.no_token

        # Outcome index: 0 = YES, 1 = NO (standard for conditional tokens)
        outcome_index = 0 if outcome == Outcome.YES else 1

        if is_amm:
            # AMM market - get pricing from contract or tradePrices
            venue = market.raw_data.get("venue", {})
            amm_address = venue.get("exchange") or venue.get("address")

            if not amm_address:
                raise PlatformError("AMM pool address not found for this market", Platform.LIMITLESS)

            # Use tradePrices from market data for pricing
            trade_prices = market.raw_data.get("tradePrices", {})
            if side == "buy":
                buy_prices = trade_prices.get("buy", {}).get("market", [])
                if buy_prices and len(buy_prices) > outcome_index:
                    price = Decimal(str(buy_prices[outcome_index]))
                else:
                    price = market.yes_price if outcome == Outcome.YES else market.no_price
                price = price or Decimal("0.5")
                expected_output = amount / price
                input_token = USDC_BASE
                output_token = token_id or "outcome_token"
            else:
                sell_prices = trade_prices.get("sell", {}).get("market", [])
                if sell_prices and len(sell_prices) > outcome_index:
                    price = Decimal(str(sell_prices[outcome_index]))
                else:
                    price = market.yes_price if outcome == Outcome.YES else market.no_price
                price = price or Decimal("0.5")
                expected_output = amount * price
                input_token = token_id or "outcome_token"
                output_token = USDC_BASE

            # AMM markets always have liquidity (it's a pool)
            has_liquidity = True
            total_liquidity = market.liquidity or Decimal("1000")
            liquidity_warning = None

        else:
            # CLOB market - use orderbook for pricing
            orderbook = await self.get_orderbook(market_id, outcome, token_id=token_id, slug=market.event_id)

            # For FOK market orders, use realistic prices for display/estimation
            # takerAmount=1 in the signed order triggers market order semantics
            if side == "buy":
                price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
                expected_output = amount / price
                input_token = USDC_BASE
                output_token = token_id or "outcome_token"
                available_liquidity = orderbook.asks
            else:
                price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
                expected_output = amount * price
                input_token = token_id or "outcome_token"
                output_token = USDC_BASE
                available_liquidity = orderbook.bids

            # Calculate total available liquidity for user feedback
            total_liquidity = sum(size for _, size in available_liquidity[:5]) if available_liquidity else Decimal("0")
            has_liquidity = bool(available_liquidity) and total_liquidity > 0

            # Warn if low liquidity (less than 50% of what user wants)
            needed_tokens = amount / price if side == "buy" else amount
            liquidity_warning = None
            if not has_liquidity:
                liquidity_warning = "No orderbook liquidity - market orders may fail. Consider using a limit order."
            elif total_liquidity < needed_tokens * Decimal("0.5"):
                liquidity_warning = f"Low liquidity ({total_liquidity:.1f} tokens available). Order may partially fill or fail."

        # Build quote_data
        quote_data = {
            "token_id": token_id,
            "market_slug": market.event_id or market_id,  # Use actual slug, not numeric ID
            "price": str(price),
            "market": market.raw_data,
            "order_type": order_type,  # "market" or "limit"
            "has_liquidity": has_liquidity,
            "available_liquidity": str(total_liquidity),
            "liquidity_warning": liquidity_warning,
            "is_amm": is_amm,
            "outcome_index": outcome_index,
        }

        # Add AMM-specific data
        if is_amm:
            venue = market.raw_data.get("venue", {})
            quote_data["amm_address"] = venue.get("exchange") or venue.get("address")

        return Quote(
            platform=Platform.LIMITLESS,
            chain=Chain.BASE,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal("0.01"),
            platform_fee=(amount * Decimal(self._fee_bps) / Decimal(10000)),
            network_fee_estimate=Decimal("0.001"),  # ETH on Base
            expires_at=None,
            quote_data=quote_data,
        )

    async def _get_ctf_address(self, exchange_address: str) -> Optional[str]:
        """Get CTF (Conditional Token) contract address from exchange contract."""
        import asyncio

        # Cache for CTF addresses
        if not hasattr(self, "_ctf_address_cache"):
            self._ctf_address_cache = {}

        if exchange_address in self._ctf_address_cache:
            return self._ctf_address_cache[exchange_address]

        # ABI for getCtf() function
        GET_CTF_ABI = [
            {
                "inputs": [],
                "name": "getCtf",
                "outputs": [{"name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

        def sync_get_ctf():
            if not self._sync_web3:
                return None

            try:
                exchange = self._sync_web3.eth.contract(
                    address=Web3.to_checksum_address(exchange_address),
                    abi=GET_CTF_ABI
                )
                ctf_address = exchange.functions.getCtf().call()
                logger.debug("Got CTF address from exchange", exchange=exchange_address, ctf=ctf_address)
                return ctf_address
            except Exception as e:
                logger.error("Failed to get CTF address from exchange", error=str(e))
                return None

        ctf_address = await asyncio.to_thread(sync_get_ctf)
        if ctf_address:
            self._ctf_address_cache[exchange_address] = ctf_address
        return ctf_address

    async def _get_venue(self, market_id: str) -> dict:
        """Get venue (exchange contract) info for a market.

        Uses SDK's MarketFetcher which caches venue data internally.
        Falls back to raw API call if MarketFetcher doesn't return venue.
        """
        # Try SDK MarketFetcher first (handles caching internally)
        if self._market_fetcher:
            try:
                sdk_market = await self._market_fetcher.get_market(market_id)
                if sdk_market and hasattr(sdk_market, "venue") and sdk_market.venue:
                    venue = sdk_market.venue if isinstance(sdk_market.venue, dict) else {"exchange": sdk_market.venue}
                    logger.debug("Got venue via SDK MarketFetcher", market_id=market_id, exchange=venue.get("exchange"))
                    return venue
            except Exception as e:
                logger.debug("SDK MarketFetcher venue lookup failed", market_id=market_id, error=str(e))

        # Fallback to raw API call
        market = await self.get_market(market_id)
        if not market or not market.raw_data:
            raise PlatformError("Market not found", Platform.LIMITLESS)

        venue = market.raw_data.get("venue", {})
        logger.debug("Got venue from market", market_id=market_id, venue=venue, exchange=venue.get("exchange"))
        return venue

    async def _ensure_approval(
        self,
        private_key: LocalAccount,
        spender: str,
    ) -> None:
        """Ensure USDC is approved for spending."""
        import asyncio

        wallet = Web3.to_checksum_address(private_key.address)
        cached = self._approval_cache.get(wallet, set())

        if spender in cached:
            return

        def sync_approve():
            if not self._sync_web3:
                return

            usdc = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(USDC_BASE),
                abi=ERC20_ABI
            )
            spender_addr = Web3.to_checksum_address(spender)

            allowance = usdc.functions.allowance(wallet, spender_addr).call()
            if allowance >= 10 ** 12:  # Already approved
                self._approval_cache.setdefault(wallet, set()).add(spender)
                return

            logger.info("Approving Limitless exchange for USDC")
            nonce = self._sync_web3.eth.get_transaction_count(wallet)
            gas_price = self._sync_web3.eth.gas_price

            tx = usdc.functions.approve(
                spender_addr,
                2 ** 256 - 1
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gasPrice": int(gas_price * 1.2),
                "gas": 100000,
                "chainId": 8453,  # Base
            })

            signed = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed.raw_transaction)
            self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            self._approval_cache.setdefault(wallet, set()).add(spender)
            logger.info("Approval confirmed", tx_hash=tx_hash.hex())

        await asyncio.to_thread(sync_approve)

    async def _ensure_ctf_approval(
        self,
        private_key: LocalAccount,
        ctf_address: str,
        spender: str,
    ) -> None:
        """Ensure CTF (Conditional Token) contract is approved for the exchange to transfer tokens."""
        import asyncio

        wallet = Web3.to_checksum_address(private_key.address)
        cache_key = f"ctf:{ctf_address}:{spender}"
        cached = self._approval_cache.get(wallet, set())

        if cache_key in cached:
            return

        # ERC1155 setApprovalForAll ABI
        ERC1155_ABI = [
            {
                "inputs": [
                    {"name": "operator", "type": "address"},
                    {"name": "approved", "type": "bool"}
                ],
                "name": "setApprovalForAll",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [
                    {"name": "account", "type": "address"},
                    {"name": "operator", "type": "address"}
                ],
                "name": "isApprovedForAll",
                "outputs": [{"name": "", "type": "bool"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

        def sync_approve():
            if not self._sync_web3:
                return

            ctf = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(ctf_address),
                abi=ERC1155_ABI
            )
            spender_addr = Web3.to_checksum_address(spender)

            is_approved = ctf.functions.isApprovedForAll(wallet, spender_addr).call()
            if is_approved:
                self._approval_cache.setdefault(wallet, set()).add(cache_key)
                return

            logger.info("Approving CTF tokens for Limitless exchange", ctf=ctf_address, exchange=spender)
            nonce = self._sync_web3.eth.get_transaction_count(wallet)
            gas_price = self._sync_web3.eth.gas_price

            tx = ctf.functions.setApprovalForAll(
                spender_addr,
                True
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gasPrice": int(gas_price * 1.2),
                "gas": 100000,
                "chainId": 8453,  # Base
            })

            signed = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed.raw_transaction)
            self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            self._approval_cache.setdefault(wallet, set()).add(cache_key)
            logger.info("CTF approval confirmed", tx_hash=tx_hash.hex())

            # Wait for the Limitless API to pick up the on-chain approval
            import time
            time.sleep(3)

        await asyncio.to_thread(sync_approve)

    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """Execute a trade on Limitless."""
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.LIMITLESS,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.LIMITLESS)

        try:
            market_slug = quote.quote_data.get("market_slug", quote.market_id)
            token_id = quote.quote_data.get("token_id")
            price = Decimal(quote.quote_data.get("price", "0.5"))

            # Get venue info
            venue = await self._get_venue(market_slug)
            exchange = venue.get("exchange", venue.get("address"))

            if not exchange:
                return TradeResult(
                    success=False,
                    tx_hash=None,
                    input_amount=quote.input_amount,
                    output_amount=None,
                    error_message="Exchange address not found for market",
                    explorer_url=None,
                )

            # Get user info (fee rate) for order
            owner_id = None
            fee_rate_bps = 300  # default
            try:
                owner_id, fee_rate_bps = await self._get_user_info(private_key.address)
                logger.debug("Got user info", owner_id=owner_id, fee_rate_bps=fee_rate_bps)
            except Exception as e:
                logger.warning("Failed to get user info, using defaults", error=str(e))

            # Check if this is an AMM market
            is_amm = quote.quote_data.get("is_amm", False)
            outcome_index = quote.quote_data.get("outcome_index", 0)

            if is_amm:
                # AMM trading - direct contract interaction
                return await self._execute_amm_trade(
                    quote=quote,
                    private_key=private_key,
                    amm_address=exchange,
                    outcome_index=outcome_index,
                )

            # CLOB trading - ensure approvals
            if quote.side == "buy":
                # USDC approval for buys
                await self._ensure_approval(private_key, exchange)
            else:
                # CTF token approval for sells
                # Get CTF contract address from exchange contract's getCtf() function
                ctf_address = await self._get_ctf_address(exchange)
                if ctf_address:
                    await self._ensure_ctf_approval(private_key, ctf_address, exchange)

            # Determine order type from quote_data
            # "market" = FOK (fill at any price), "limit" = GTC at exact price
            order_type = quote.quote_data.get("order_type", "market")  # Default to market
            is_market_order = order_type == "market"

            # For FOK (market) orders, check orderbook liquidity BEFORE submitting
            # FOK orders fail with cryptic errors when there's no matching liquidity
            if is_market_order:
                try:
                    orderbook = await self.get_orderbook(
                        market_slug, quote.outcome,
                        token_id=token_id, slug=market_slug
                    )

                    # For buy orders, check asks; for sell orders, check bids
                    if quote.side == "buy":
                        available_liquidity = orderbook.asks
                        best_price = orderbook.best_ask
                    else:
                        available_liquidity = orderbook.bids
                        best_price = orderbook.best_bid

                    if not available_liquidity or not best_price:
                        logger.warning(
                            "No liquidity for FOK order",
                            market_slug=market_slug,
                            side=quote.side,
                            outcome=quote.outcome.value,
                        )
                        return TradeResult(
                            success=False,
                            tx_hash=None,
                            input_amount=quote.input_amount,
                            output_amount=None,
                            error_message=(
                                f"No orderbook liquidity for {quote.outcome.value.upper()}. "
                                f"This market has no {'sellers' if quote.side == 'buy' else 'buyers'} right now.\n\n"
                                f"💡 Use a LIMIT ORDER to place your order at a specific price - "
                                f"it will fill when someone matches it."
                            ),
                            explorer_url=None,
                        )

                    # Calculate total available liquidity at reasonable prices
                    total_available = sum(size for _, size in available_liquidity[:5])  # Top 5 levels
                    needed_tokens = quote.input_amount / price if quote.side == "buy" else quote.input_amount

                    if total_available < needed_tokens * Decimal("0.5"):  # Less than 50% of needed
                        logger.warning(
                            "Insufficient liquidity for FOK order",
                            market_slug=market_slug,
                            needed=str(needed_tokens),
                            available=str(total_available),
                        )
                        return TradeResult(
                            success=False,
                            tx_hash=None,
                            input_amount=quote.input_amount,
                            output_amount=None,
                            error_message=(
                                f"Insufficient liquidity for market order. "
                                f"Available: ~{total_available:.2f} tokens, needed: ~{needed_tokens:.2f}. "
                                f"Try a smaller amount or use a limit order."
                            ),
                            explorer_url=None,
                        )

                except Exception as ob_err:
                    logger.warning("Could not check orderbook liquidity", error=str(ob_err))
                    # Continue anyway - the order might still work

            # Create order via SDK OrderClient
            order_client = self._get_order_client(private_key)

            # Ensure venue is cached by fetching market via SDK
            if self._market_fetcher:
                try:
                    await self._market_fetcher.get_market(market_slug)
                except Exception:
                    pass  # Venue already fetched above, this just ensures SDK cache

            sdk_side = Side.BUY if quote.side == "buy" else Side.SELL

            logger.info(
                "Creating order via SDK",
                order_type=order_type,
                is_market_order=is_market_order,
                price=price,
                market_slug=market_slug,
            )

            # Submit with retry for allowance propagation delay
            result = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if is_market_order:
                        result = await order_client.create_order(
                            token_id=token_id or "0",
                            maker_amount=float(quote.input_amount),
                            side=sdk_side,
                            order_type=OrderType.FOK,
                            market_slug=market_slug,
                        )
                    else:
                        # GTC limit order - calculate size from amount and price
                        size = float(quote.input_amount / price) if quote.side == "buy" else float(quote.input_amount)
                        result = await order_client.create_order(
                            token_id=token_id or "0",
                            price=float(price),
                            size=size,
                            side=sdk_side,
                            order_type=OrderType.GTC,
                            market_slug=market_slug,
                        )
                    break  # Success
                except Exception as api_err:
                    error_str = str(api_err).lower()

                    # Handle specific Limitless API errors with better messages
                    if "order_id" in error_str and "null" in error_str:
                        logger.warning(
                            "FOK order rejected - no matching liquidity",
                            market_slug=market_slug,
                            error=str(api_err),
                        )
                        return TradeResult(
                            success=False,
                            tx_hash=None,
                            input_amount=quote.input_amount,
                            output_amount=None,
                            error_message=(
                                "Market order could not be filled - no matching orders in the orderbook. "
                                "This often happens with hourly markets near expiration. "
                                "Try using a limit order instead, or try a different market."
                            ),
                            explorer_url=None,
                        )

                    if "allowance" in error_str and attempt < max_retries - 1:
                        logger.info(
                            "Allowance not yet visible, retrying...",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )
                        await asyncio.sleep(3)
                        continue
                    raise  # Re-raise if not handled error or max retries

            # Map SDK response to our TradeResult
            order_obj = getattr(result, "order", None)
            order_id = ""
            order_status = ""
            maker_matches = []

            if order_obj:
                order_id = str(getattr(order_obj, "id", "")) or ""
                order_status = str(getattr(order_obj, "status", "")).upper()

            if hasattr(result, "maker_matches"):
                maker_matches = result.maker_matches or []
            elif hasattr(result, "makerMatches"):
                maker_matches = result.makerMatches or []

            # Fallback: try dict access if result is dict-like
            if not order_id and isinstance(result, dict):
                order_id = result.get("orderId") or result.get("id") or result.get("transactionHash", "")
                order_status = result.get("status", "").upper()
                maker_matches = result.get("makerMatches", [])

            # Calculate actual filled amount from matches
            total_matched = 0
            for m in maker_matches:
                matched_size = getattr(m, "matchedSize", None) or (m.get("matchedSize", 0) if isinstance(m, dict) else 0)
                total_matched += int(matched_size)

            logger.info(
                "Trade executed via SDK",
                platform="limitless",
                market_id=market_slug,
                order_id=order_id,
                order_status=order_status,
                maker_matches_count=len(maker_matches),
                total_matched=total_matched,
            )

            # Determine actual output - use matched size if available
            if total_matched > 0:
                actual_output = Decimal(total_matched) / Decimal(10 ** 6)
            else:
                actual_output = quote.expected_output

            # Collect platform fee in background (non-blocking) after successful trade
            if self._fee_account and self._fee_bps > 0 and quote.side == "buy":
                fee_amount = (quote.input_amount * Decimal(self._fee_bps) / Decimal(10000)).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                if fee_amount > 0:
                    # Fire and forget - don't block trade response
                    asyncio.create_task(self._collect_platform_fee_async(private_key, fee_amount))

            return TradeResult(
                success=True,
                tx_hash=order_id,
                input_amount=quote.input_amount,
                output_amount=actual_output,
                error_message=None,
                explorer_url=self.get_explorer_url(order_id) if order_id.startswith("0x") else None,
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

    async def _collect_platform_fee_async(
        self,
        private_key: LocalAccount,
        amount_usdc: Decimal,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Collect platform fee asynchronously (non-blocking)."""
        try:
            return await asyncio.to_thread(self._collect_platform_fee, private_key, amount_usdc)
        except Exception as e:
            logger.error("Async fee collection failed", error=str(e))
            return False, None, str(e)

    def _collect_platform_fee(
        self,
        private_key: LocalAccount,
        amount_usdc: Decimal,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Collect platform fee by transferring USDC (sync, called from background)."""
        if not self._fee_account or not self._sync_web3:
            return True, None, None

        if not Web3.is_address(self._fee_account):
            return True, None, None

        try:
            fee_account = Web3.to_checksum_address(self._fee_account)
            amount_raw = int(amount_usdc * Decimal(10 ** 6))

            if amount_raw <= 0:
                return True, None, None

            usdc = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(USDC_BASE),
                abi=ERC20_ABI
            )

            nonce = self._sync_web3.eth.get_transaction_count(private_key.address)
            gas_price = self._sync_web3.eth.gas_price

            tx = usdc.functions.transfer(
                fee_account,
                amount_raw
            ).build_transaction({
                "from": private_key.address,
                "nonce": nonce,
                "gasPrice": int(gas_price * 1.2),
                "gas": 100000,
                "chainId": 8453,
            })

            signed = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed.raw_transaction)

            logger.info("Platform fee collected", amount=str(amount_usdc), tx_hash=tx_hash.hex())
            return True, tx_hash.hex(), None

        except Exception as e:
            logger.error("Fee collection failed", error=str(e))
            return False, None, str(e)

    async def _execute_amm_trade(
        self,
        quote: Quote,
        private_key: LocalAccount,
        amm_address: str,
        outcome_index: int,
    ) -> TradeResult:
        """Execute a trade on an AMM market using the FixedProductMarketMaker contract."""
        import asyncio

        def sync_amm_trade():
            if not self._sync_web3:
                raise PlatformError("Web3 not initialized", Platform.LIMITLESS)

            wallet = Web3.to_checksum_address(private_key.address)
            amm_checksum = Web3.to_checksum_address(amm_address)

            # Create contract instance
            amm_contract = self._sync_web3.eth.contract(
                address=amm_checksum,
                abi=FPMM_ABI
            )

            # Calculate amounts (USDC has 6 decimals)
            amount_raw = int(quote.input_amount * Decimal(10 ** 6))

            if quote.side == "buy":
                # Ensure USDC is approved for the AMM
                usdc = self._sync_web3.eth.contract(
                    address=Web3.to_checksum_address(USDC_BASE),
                    abi=ERC20_ABI
                )

                # Check and set approval if needed
                current_allowance = usdc.functions.allowance(wallet, amm_checksum).call()
                if current_allowance < amount_raw:
                    nonce = self._sync_web3.eth.get_transaction_count(wallet)
                    gas_price = self._sync_web3.eth.gas_price

                    approve_tx = usdc.functions.approve(
                        amm_checksum,
                        2**256 - 1  # Max approval
                    ).build_transaction({
                        "from": wallet,
                        "nonce": nonce,
                        "gasPrice": int(gas_price * 1.2),
                        "gas": 100000,
                        "chainId": 8453,
                    })

                    signed_approve = self._sync_web3.eth.account.sign_transaction(approve_tx, private_key.key)
                    approve_hash = self._sync_web3.eth.send_raw_transaction(signed_approve.raw_transaction)
                    self._sync_web3.eth.wait_for_transaction_receipt(approve_hash, timeout=60)
                    logger.info("USDC approved for AMM", amm=amm_address)

                # Calculate minimum output (with 2% slippage tolerance)
                try:
                    expected_tokens = amm_contract.functions.calcBuyAmount(amount_raw, outcome_index).call()
                    min_tokens = int(expected_tokens * 0.98)  # 2% slippage
                except Exception as calc_err:
                    logger.warning("calcBuyAmount failed, using estimate", error=str(calc_err))
                    min_tokens = 1  # Fallback to minimum

                # Execute buy
                nonce = self._sync_web3.eth.get_transaction_count(wallet)
                gas_price = self._sync_web3.eth.gas_price

                buy_tx = amm_contract.functions.buy(
                    amount_raw,
                    outcome_index,
                    min_tokens
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": int(gas_price * 1.2),
                    "gas": 300000,
                    "chainId": 8453,
                })

                signed_buy = self._sync_web3.eth.account.sign_transaction(buy_tx, private_key.key)
                tx_hash = self._sync_web3.eth.send_raw_transaction(signed_buy.raw_transaction)

                # Wait for confirmation
                receipt = self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                return {
                    "success": receipt.status == 1,
                    "tx_hash": tx_hash.hex(),
                    "output_amount": Decimal(expected_tokens) / Decimal(10 ** 18) if expected_tokens else quote.expected_output,
                }

            else:
                # Sell: need to approve outcome tokens to AMM
                # For sells, we need to calculate how many tokens to sell for the desired USDC return
                try:
                    tokens_to_sell = amm_contract.functions.calcSellAmount(amount_raw, outcome_index).call()
                    max_tokens = int(tokens_to_sell * 1.02)  # 2% slippage
                except Exception as calc_err:
                    logger.warning("calcSellAmount failed, using estimate", error=str(calc_err))
                    # Estimate: tokens_to_sell ≈ amount / price
                    tokens_to_sell = int(quote.input_amount * Decimal(10 ** 18))
                    max_tokens = int(tokens_to_sell * 1.02)

                # Execute sell
                nonce = self._sync_web3.eth.get_transaction_count(wallet)
                gas_price = self._sync_web3.eth.gas_price

                sell_tx = amm_contract.functions.sell(
                    amount_raw,  # returnAmount (USDC we want)
                    outcome_index,
                    max_tokens  # maxOutcomeTokensToSell
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": int(gas_price * 1.2),
                    "gas": 300000,
                    "chainId": 8453,
                })

                signed_sell = self._sync_web3.eth.account.sign_transaction(sell_tx, private_key.key)
                tx_hash = self._sync_web3.eth.send_raw_transaction(signed_sell.raw_transaction)

                # Wait for confirmation
                receipt = self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                return {
                    "success": receipt.status == 1,
                    "tx_hash": tx_hash.hex(),
                    "output_amount": quote.input_amount,  # For sells, output is USDC
                }

        try:
            result = await asyncio.to_thread(sync_amm_trade)

            if result["success"]:
                tx_hash = result["tx_hash"]
                return TradeResult(
                    success=True,
                    tx_hash=tx_hash,
                    input_amount=quote.input_amount,
                    output_amount=result["output_amount"],
                    error_message=None,
                    explorer_url=f"https://basescan.org/tx/{tx_hash}",
                )
            else:
                return TradeResult(
                    success=False,
                    tx_hash=result.get("tx_hash"),
                    input_amount=quote.input_amount,
                    output_amount=None,
                    error_message="AMM transaction failed",
                    explorer_url=None,
                )

        except Exception as e:
            error_str = str(e)
            logger.error("AMM trade failed", error=error_str)

            # Provide user-friendly error messages
            if "insufficient" in error_str.lower():
                error_msg = "Insufficient balance for this trade"
            elif "slippage" in error_str.lower() or "min" in error_str.lower():
                error_msg = "Trade failed due to price movement (slippage). Try again or use a smaller amount."
            else:
                error_msg = f"AMM trade failed: {error_str[:100]}"

            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=error_msg,
                explorer_url=None,
            )

    # ===================
    # Resolution & Redemption
    # ===================

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """Check if market has resolved.

        Limitless API uses these fields for resolution:
        - winning_index: 0 = YES won, 1 = NO won, null = not resolved
        - expired: boolean indicating deadline passed
        - closed: boolean indicating market closed
        - status: may be "resolved", "RESOLVED", "expired", etc.
        - payout_numerators: oracle payout data when resolved
        """
        try:
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            raw = market.raw_data

            # Check winning_index first - this is the primary resolution indicator
            winning_index = raw.get("winning_index") or raw.get("winningIndex")

            # Also check other resolution indicators
            status = str(raw.get("status", "")).lower()
            is_expired = raw.get("expired", False)
            is_closed = raw.get("closed", False)
            has_payout = raw.get("payout_numerators") or raw.get("payoutNumerators")

            # Market is resolved if winning_index is set OR status indicates resolved
            resolved = (
                winning_index is not None or
                status in ("resolved", "expired", "settled") or
                raw.get("resolved", False) or
                (is_expired and has_payout)
            )

            if not resolved:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            # Determine winning outcome
            winning = None

            # winning_index: 0 = YES, 1 = NO
            if winning_index is not None:
                winning = "yes" if winning_index == 0 else "no"
            else:
                # Fallback to other resolution fields
                resolution = (
                    raw.get("resolution") or
                    raw.get("winningOutcome") or
                    raw.get("winning_outcome")
                )
                if resolution is not None:
                    resolution_str = str(resolution).lower()
                    if resolution_str in ["yes", "0", "true"]:
                        winning = "yes"
                    elif resolution_str in ["no", "1", "false"]:
                        winning = "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning,
                resolution_time=raw.get("resolutionTime") or raw.get("resolution_time"),
            )

        except Exception as e:
            logger.error("Failed to check resolution", error=str(e), market_id=market_id)
            return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """Redeem winning tokens from resolved Limitless market.

        Calls redeemPositions on the CTF contract.
        """
        if not isinstance(private_key, LocalAccount):
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message="Invalid private key type, expected EVM LocalAccount",
                explorer_url=None,
            )

        try:
            if not self._sync_web3:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Web3 not initialized",
                    explorer_url=None,
                )

            # Get market data
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Market not found",
                    explorer_url=None,
                )

            # Get condition ID from market data
            condition_id = market.raw_data.get("conditionId")
            if not condition_id:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Condition ID not found in market data",
                    explorer_url=None,
                )

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

            # Get venue to find exchange address
            venue = await self._get_venue(market_id)
            exchange_address = venue.get("exchange", venue.get("address"))
            if not exchange_address:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Exchange address not found for market",
                    explorer_url=None,
                )

            # Get CTF contract address from exchange
            ctf_address = await self._get_ctf_address(exchange_address)
            if not ctf_address:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="CTF contract address not found",
                    explorer_url=None,
                )

            logger.info(
                "Redeeming position",
                market_id=market_id,
                outcome=outcome.value,
                ctf_address=ctf_address,
                condition_id=condition_id,
            )

            # Build CTF contract
            ctf_contract = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(ctf_address),
                abi=CTF_REDEEM_ABI,
            )

            # Convert condition ID to bytes32
            if condition_id.startswith("0x"):
                condition_bytes = bytes.fromhex(condition_id[2:])
            else:
                condition_bytes = bytes.fromhex(condition_id)

            # Index sets: 1 for YES (binary 01), 2 for NO (binary 10)
            index_set = 1 if outcome == Outcome.YES else 2

            # Parent collection ID is null bytes32
            parent_collection_id = bytes(32)

            # Build and send transaction
            wallet_address = private_key.address
            nonce = self._sync_web3.eth.get_transaction_count(wallet_address)
            gas_price = self._sync_web3.eth.gas_price

            tx = ctf_contract.functions.redeemPositions(
                Web3.to_checksum_address(USDC_BASE),  # collateral token
                parent_collection_id,
                condition_bytes,
                [index_set],
            ).build_transaction({
                "from": wallet_address,
                "nonce": nonce,
                "gas": 200000,
                "gasPrice": int(gas_price * 1.2),
                "chainId": 8453,  # Base
            })

            # Sign and send
            signed_tx = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(
                "Redemption transaction sent",
                tx_hash=tx_hash.hex(),
                market_id=market_id,
                outcome=outcome.value,
            )

            # Wait for confirmation
            receipt = self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt.status == 1:
                # Winning tokens are worth $1 each
                amount_redeemed = token_amount

                logger.info(
                    "Redemption confirmed",
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=str(amount_redeemed),
                )

                return RedemptionResult(
                    success=True,
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=amount_redeemed,
                    error_message=None,
                    explorer_url=self.get_explorer_url(tx_hash.hex()),
                )
            else:
                return RedemptionResult(
                    success=False,
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=None,
                    error_message="Transaction failed on-chain",
                    explorer_url=self.get_explorer_url(tx_hash.hex()),
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

    def get_explorer_url(self, tx_hash: str) -> str:
        """Get Base block explorer URL."""
        return f"https://basescan.org/tx/{tx_hash}"

    async def get_token_balance(
        self,
        wallet_address: str,
        market_id: str,
        outcome: Outcome,
    ) -> Optional[Decimal]:
        """
        Check on-chain balance of CTF tokens for a specific market/outcome.
        Returns token balance in decimal format, or None if unable to check.
        """
        import asyncio

        try:
            # Get venue to find exchange address
            venue = await self._get_venue(market_id)
            exchange_address = venue.get("exchange", venue.get("address"))
            if not exchange_address:
                logger.error("Exchange address not found", market_id=market_id)
                return None

            # Get CTF contract address
            ctf_address = await self._get_ctf_address(exchange_address)
            if not ctf_address:
                logger.error("CTF address not found", exchange=exchange_address)
                return None

            # Get market to find token ID
            market = await self.get_market(market_id)
            if not market:
                logger.error("Market not found", market_id=market_id)
                return None

            # Get the token ID for the outcome
            token_id = market.yes_token if outcome == Outcome.YES else market.no_token
            if not token_id:
                logger.error("Token ID not found", market_id=market_id, outcome=outcome.value)
                return None

            # Convert token ID to int
            token_id_int = int(token_id)

            logger.debug(
                "Checking CTF token balance",
                wallet=wallet_address,
                ctf=ctf_address,
                token_id=token_id_int,
                outcome=outcome.value,
            )

            def sync_check_balance():
                if not self._sync_web3:
                    return None

                ctf_contract = self._sync_web3.eth.contract(
                    address=Web3.to_checksum_address(ctf_address),
                    abi=CTF_REDEEM_ABI,  # Has balanceOf(address, uint256)
                )

                balance = ctf_contract.functions.balanceOf(
                    Web3.to_checksum_address(wallet_address),
                    token_id_int,
                ).call()

                return balance

            balance_raw = await asyncio.to_thread(sync_check_balance)
            if balance_raw is None:
                return None

            # Convert from 6 decimals (USDC precision for CTF tokens)
            balance = Decimal(balance_raw) / Decimal(10 ** 6)

            logger.info(
                "CTF token balance checked",
                wallet=wallet_address,
                market_id=market_id,
                outcome=outcome.value,
                balance=str(balance),
                balance_raw=balance_raw,
            )

            return balance

        except Exception as e:
            logger.error(
                "Failed to check token balance",
                error=str(e),
                wallet=wallet_address,
                market_id=market_id,
            )
            return None


# Singleton instance
limitless_platform = LimitlessPlatform()
