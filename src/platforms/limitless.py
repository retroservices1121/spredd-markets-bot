"""
Limitless Exchange platform implementation.
Prediction market on Base chain using CLOB API.
"""

import asyncio
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional, Tuple
from datetime import datetime
import json
import time
import secrets

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

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
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3: Optional[AsyncWeb3] = None
        self._sync_web3: Optional[Web3] = None
        self._fee_account = settings.evm_fee_account
        self._fee_bps = settings.evm_fee_bps
        # Session cache per wallet
        self._session_cache: dict[str, dict] = {}
        # Market venue cache
        self._venue_cache: dict[str, dict] = {}
        # Approval cache
        self._approval_cache: dict[str, set[str]] = {}
        # ID to slug cache (numeric ID -> slug for API lookups)
        self._id_to_slug_cache: dict[str, str] = {}
        # Group market cache (slug -> raw group data for nested markets)
        self._group_market_cache: dict[str, dict] = {}

    async def initialize(self) -> None:
        """Initialize Limitless API clients."""
        self._http_client = httpx.AsyncClient(
            base_url=LIMITLESS_API_BASE,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

        # Async Web3 for Base
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.base_rpc_url)
        )

        # Sync Web3 for fee collection
        self._sync_web3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))

        fee_enabled = bool(self._fee_account and Web3.is_address(self._fee_account))
        logger.info(
            "Limitless platform initialized",
            fee_collection=fee_enabled,
            fee_bps=self._fee_bps if fee_enabled else 0,
        )

    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()

    # ===================
    # API Helpers
    # ===================

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        session_cookie: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Make request to Limitless API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")

        try:
            headers = kwargs.pop("headers", {})
            if session_cookie:
                headers["Cookie"] = f"limitless_session={session_cookie}"

            response = await self._http_client.request(
                method, endpoint, headers=headers, **kwargs
            )

            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.LIMITLESS)

            response.raise_for_status()

            # Handle empty responses
            if not response.content:
                return {}

            # Try to parse JSON
            try:
                return response.json()
            except Exception as e:
                # Log the raw response for debugging
                logger.debug(
                    "Non-JSON response from Limitless API",
                    endpoint=endpoint,
                    status=response.status_code,
                    content_preview=response.text[:200] if response.text else "empty",
                )
                raise

        except httpx.HTTPStatusError as e:
            # Log the error response body for debugging
            error_body = ""
            try:
                error_body = e.response.text[:500] if e.response.text else ""
            except:
                pass
            logger.error(
                "Limitless API error",
                status=e.response.status_code,
                endpoint=endpoint,
                error_body=error_body,
            )
            raise PlatformError(
                f"API error: {e.response.status_code} - {error_body[:100]}",
                Platform.LIMITLESS,
                str(e.response.status_code),
            )

    async def _get_session(self, private_key: LocalAccount) -> Tuple[str, str, int]:
        """Get or create authenticated session for wallet.

        Returns: (session_cookie, owner_id, fee_rate_bps)
        """
        wallet = private_key.address

        # Check cache
        cached = self._session_cache.get(wallet)
        if cached and cached.get("expires_at", 0) > time.time():
            return cached["session"], cached.get("owner_id", ""), cached.get("fee_rate_bps", 300)

        # Authenticate with Limitless
        checksum_address = Web3.to_checksum_address(wallet)

        # Step 1: Get signing message (returns plain text, not JSON)
        logger.debug("Requesting signing message", account=checksum_address)
        if not self._http_client:
            raise RuntimeError("Client not initialized")

        response = await self._http_client.get(f"/auth/signing-message")
        response.raise_for_status()
        signing_message = response.text.strip()

        if not signing_message:
            logger.warning("Empty signing message response")
            raise PlatformError("Failed to get signing message", Platform.LIMITLESS)

        logger.debug("Got signing message", message_preview=signing_message[:50])

        # Step 2: Sign the message using EIP-191 (personal_sign)
        from eth_account.messages import encode_defunct
        message = encode_defunct(text=signing_message)
        signed = private_key.sign_message(message)

        # Step 3: Submit for session
        # Both message and signature need 0x prefix
        message_hex = "0x" + signing_message.encode("utf-8").hex()
        signature_hex = signed.signature.hex()
        if not signature_hex.startswith("0x"):
            signature_hex = "0x" + signature_hex

        login_response = await self._http_client.post(
            "/auth/login",
            headers={
                "x-account": checksum_address,
                "x-signing-message": message_hex,
                "x-signature": signature_hex,
            },
            json={"client": "eoa"}
        )
        login_response.raise_for_status()

        login_data = login_response.json()
        logger.debug("Login response", data=login_data)

        # Extract owner_id from response
        owner_id = login_data.get("id") or login_data.get("ownerId") or ""

        # Extract feeRateBps from user's rank
        rank_data = login_data.get("rank", {})
        fee_rate_bps = rank_data.get("feeRateBps", 300) if rank_data else 300

        # Extract session cookie
        session_cookie = None
        for cookie in login_response.cookies.jar:
            if cookie.name == "limitless_session":
                session_cookie = cookie.value
                break

        if not session_cookie:
            # Try to get from response
            session_cookie = login_data.get("session") or login_data.get("token")

        if not session_cookie:
            raise PlatformError("Failed to get session cookie", Platform.LIMITLESS)

        logger.info("Limitless authentication successful", owner_id=owner_id, fee_rate_bps=fee_rate_bps)

        # Cache session (29 days)
        self._session_cache[wallet] = {
            "session": session_cookie,
            "owner_id": owner_id,
            "fee_rate_bps": fee_rate_bps,
            "expires_at": time.time() + 29 * 24 * 3600,
        }

        return session_cookie, owner_id, fee_rate_bps

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
        limit: int = 25,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Limitless."""
        # API limit is 25 max
        api_limit = min(limit, 25)
        # API uses 1-indexed pages
        page = (offset // api_limit) + 1 if api_limit > 0 else 1
        params = {
            "limit": api_limit,
            "page": page,
        }

        try:
            data = await self._api_request("GET", "/markets/active", params=params)
        except Exception as e:
            logger.error("Failed to fetch markets", error=str(e))
            return []

        markets = []
        items = data if isinstance(data, list) else data.get("data", data.get("markets", []))

        for item in items:
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
                    # Common patterns: "Will X win?", "X to win", "Team X", etc.
                    title = m.title
                    outcome_name = None

                    # Try to extract meaningful name from title
                    if " - " in title:
                        outcome_name = title.split(" - ")[-1]
                    elif ":" in title:
                        outcome_name = title.split(":")[-1].strip()
                    elif title.lower().startswith("will "):
                        # "Will X win?" -> "X"
                        outcome_name = title[5:].replace(" win?", "").replace("?", "").strip()
                    elif " to " in title.lower():
                        # "X to win Y" -> "X"
                        outcome_name = title.split(" to ")[0].strip()
                    else:
                        # Use full title as outcome name
                        outcome_name = title

                    m.outcome_name = outcome_name[:50] if outcome_name else None

        return markets[:limit]

    async def search_markets(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Market]:
        """Search markets by query."""
        # API limit is 25 max
        api_limit = min(limit, 25)
        try:
            data = await self._api_request(
                "GET",
                "/markets/search",
                params={"query": query, "limit": api_limit}
            )
        except Exception as e:
            logger.error("Failed to search markets", error=str(e))
            # Fallback to fetching markets with pagination and filtering (API limit is 25)
            all_markets = []
            for page_num in range(4):  # Search up to 100 markets
                page_markets = await self.get_markets(limit=25, offset=page_num * 25)
                if not page_markets:
                    break
                all_markets.extend(page_markets)
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
                data = await self._api_request("GET", f"/markets/{lookup_id}")
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
                data = await self._api_request("GET", f"/markets/{market_id}")
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
            data = await self._api_request("GET", f"/markets/{event_id}")
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
            data = await self._api_request(
                "GET",
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
                data = await self._api_request("GET", f"/markets/{endpoint_id}/orderbook")
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
        """Get venue (exchange contract) info for a market."""
        if market_id in self._venue_cache:
            cached = self._venue_cache[market_id]
            logger.debug("Using cached venue", market_id=market_id, exchange=cached.get("exchange"))
            return cached

        market = await self.get_market(market_id)
        if not market or not market.raw_data:
            raise PlatformError("Market not found", Platform.LIMITLESS)

        venue = market.raw_data.get("venue", {})
        logger.debug("Got venue from market", market_id=market_id, venue=venue, exchange=venue.get("exchange"))
        self._venue_cache[market_id] = venue
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

    def _build_eip712_order(
        self,
        private_key: LocalAccount,
        market: dict,
        token_id: str,
        side: str,
        amount: Decimal,
        price: Decimal,
        venue: dict,
        fee_rate_bps: int = 300,
        is_market_order: bool = True,
    ) -> dict:
        """Build and sign EIP-712 order for Limitless.

        Args:
            is_market_order: If True, use FOK (market order with takerAmount=1).
                            If False, use GTC limit order with calculated takerAmount.
        """
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        wallet = Web3.to_checksum_address(private_key.address)
        exchange = venue.get("exchange", venue.get("address"))

        logger.debug("Building EIP-712 order", venue=venue, exchange=exchange, is_market_order=is_market_order)

        if not exchange:
            raise PlatformError("Exchange address not found in venue", Platform.LIMITLESS)

        exchange_checksum = Web3.to_checksum_address(exchange)

        # Calculate amounts (USDC has 6 decimals)
        # For FOK (market) orders: Limitless API requires takerAmount=1
        # For GTC (limit) orders: use calculated takerAmount for price protection

        if side == "buy":
            # makerAmount = USDC to spend
            maker_amount = int(amount * Decimal(10 ** 6))
            order_side = 0  # BUY

            if is_market_order:
                # FOK orders MUST have takerAmount=1 per Limitless API
                taker_amount = 1
                logger.debug(
                    "Buy FOK order amounts",
                    maker_amount_usdc=amount,
                    quoted_price=price,
                    taker_amount=taker_amount,
                )
            else:
                # GTC limit order - calculate taker amount for price protection
                taker_amount = int((amount / price) * Decimal(10 ** 6))
                logger.debug(
                    "Buy GTC order amounts",
                    maker_amount_usdc=amount,
                    price=price,
                    min_tokens=Decimal(taker_amount) / Decimal(10 ** 6),
                )
        else:
            # makerAmount = tokens to sell
            maker_amount = int(amount * Decimal(10 ** 6))
            order_side = 1  # SELL

            if is_market_order:
                # FOK orders MUST have takerAmount=1 per Limitless API
                taker_amount = 1
                logger.debug(
                    "Sell FOK order amounts",
                    maker_amount_tokens=amount,
                    quoted_price=price,
                    taker_amount=taker_amount,
                )
            else:
                # GTC limit order - calculate taker amount for price protection
                taker_amount = int(Decimal(maker_amount) * price)
                logger.debug(
                    "Sell GTC order amounts",
                    maker_amount_tokens=amount,
                    price=price,
                    min_usdc=Decimal(taker_amount) / Decimal(10 ** 6),
                )

        # Parse tokenId as integer (can be very large uint256)
        if str(token_id).isdigit():
            token_id_int = int(token_id)
        elif str(token_id).startswith("0x"):
            token_id_int = int(token_id, 16)
        else:
            token_id_int = 0

        # Generate salt - use 2^53 range for JSON number precision safety
        # JSON numbers are IEEE 754 doubles, safe up to 2^53 - 1
        salt = secrets.randbelow(2 ** 53)

        # Build order struct for API
        order = {
            "salt": salt,  # Number within JSON safe range
            "maker": wallet,
            "signer": wallet,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),  # Must be string for large uint256
            "makerAmount": maker_amount,  # Must be number
            "takerAmount": taker_amount,  # Must be number
            "expiration": "0",  # Must be "0" - expiration not currently supported
            "nonce": 0,  # Must be 0 per API requirement
            "feeRateBps": fee_rate_bps,  # Must be number
            "side": order_side,
            "signatureType": 0,  # EOA
        }

        # EIP-712 Type Hashes (must match the contract exactly)
        EIP712_DOMAIN_TYPEHASH = keccak(
            text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
        )
        ORDER_TYPEHASH = keccak(
            text="Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)"
        )

        # Compute domain separator
        domain_separator = keccak(
            abi_encode(
                ["bytes32", "bytes32", "bytes32", "uint256", "address"],
                [
                    EIP712_DOMAIN_TYPEHASH,
                    keccak(text="Limitless CTF Exchange"),
                    keccak(text="1"),
                    8453,  # Base chain ID
                    exchange_checksum,  # Address as checksummed string
                ]
            )
        )

        # Zero address for taker
        zero_address = "0x0000000000000000000000000000000000000000"

        # Compute struct hash
        struct_hash = keccak(
            abi_encode(
                ["bytes32", "uint256", "address", "address", "address", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint8", "uint8"],
                [
                    ORDER_TYPEHASH,
                    salt,
                    wallet,       # maker
                    wallet,       # signer
                    zero_address, # taker
                    token_id_int,
                    maker_amount,
                    taker_amount,
                    0,  # expiration
                    0,  # nonce
                    fee_rate_bps,
                    order_side,
                    0,  # signatureType (EOA)
                ]
            )
        )

        # Compute final digest: keccak256("\x19\x01" + domainSeparator + structHash)
        digest = keccak(b"\x19\x01" + domain_separator + struct_hash)

        logger.debug(
            "EIP-712 signing",
            domain_separator=domain_separator.hex(),
            struct_hash=struct_hash.hex(),
            digest=digest.hex(),
            wallet=wallet,
            exchange=exchange_checksum,
            salt=salt,
            token_id=token_id_int,
            maker_amount=maker_amount,
            taker_amount=taker_amount,
            fee_rate_bps=fee_rate_bps,
        )

        # Sign the digest directly using Account._sign_hash
        from eth_account import Account
        signed = Account._sign_hash(digest, private_key.key)

        # Format signature: r (32 bytes) + s (32 bytes) + v (1 byte)
        signature_hex = "0x" + signed.signature.hex()
        order["signature"] = signature_hex

        logger.debug(
            "Order signed",
            signature=signature_hex[:20] + "...",
            v=signed.v,
            recovered_address=Account._recover_hash(digest, signature=signed.signature),
        )

        # Add price field only for GTC orders (FOK market orders don't have price)
        if not is_market_order:
            order["price"] = float(price)

        return order

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

            # Get session for authenticated request (need fee_rate_bps for order)
            session = None
            owner_id = None
            fee_rate_bps = 300  # default
            try:
                session, owner_id, fee_rate_bps = await self._get_session(private_key)
                logger.debug("Got session", has_session=bool(session), owner_id=owner_id, fee_rate_bps=fee_rate_bps)
            except Exception as e:
                logger.error("Session auth failed", error=str(e))
                return TradeResult(
                    success=False,
                    tx_hash=None,
                    input_amount=quote.input_amount,
                    output_amount=Decimal(0),
                    error_message=f"Authentication failed: {str(e)}",
                    explorer_url=None,
                )

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
                                f"No liquidity available for market orders on this market. "
                                f"The orderbook has no {'asks' if quote.side == 'buy' else 'bids'} "
                                f"for {quote.outcome.value.upper()}. "
                                f"Try using a limit order instead, or try a different market."
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

            logger.info(
                "Building order",
                order_type=order_type,
                is_market_order=is_market_order,
                price=price,
            )

            # Build EIP-712 signed order
            order = self._build_eip712_order(
                private_key=private_key,
                market=quote.quote_data.get("market", {}),
                token_id=token_id or "0",
                side=quote.side,
                amount=quote.input_amount,
                price=price,
                venue=venue,
                fee_rate_bps=fee_rate_bps,
                is_market_order=is_market_order,
            )

            # Submit order - FOK for market orders (immediate), GTC for limit orders
            api_order_type = "FOK" if is_market_order else "GTC"
            payload = {
                "order": order,
                "orderType": api_order_type,
                "marketSlug": market_slug,
            }

            # Add ownerId if we have it (must be integer)
            if owner_id:
                payload["ownerId"] = int(owner_id) if isinstance(owner_id, str) else owner_id

            logger.debug(
                "Submitting order",
                market_slug=market_slug,
                owner_id=payload.get("ownerId"),
                order_side=order.get("side"),
                order_price=order.get("price"),
                token_id=order.get("tokenId"),
                order_type=api_order_type,
                maker_amount=order.get("makerAmount"),
                taker_amount=order.get("takerAmount"),
            )

            # Submit with retry for allowance propagation delay
            result = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = await self._api_request(
                        "POST",
                        "/orders",
                        session_cookie=session,
                        json=payload,
                    )
                    break  # Success
                except Exception as api_err:
                    error_str = str(api_err).lower()

                    # Handle specific Limitless API errors with better messages
                    if "order_id" in error_str and "null" in error_str:
                        # FOK order failed due to no matching liquidity
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
                        # Allowance not yet visible to API, wait and retry
                        logger.info(
                            "Allowance not yet visible, retrying...",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )
                        await asyncio.sleep(3)
                        continue
                    raise  # Re-raise if not handled error or max retries

            order_id = result.get("orderId") or result.get("id") or result.get("transactionHash", "")

            # Check if order was filled
            # FOK orders return makerMatches when filled
            order_status = result.get("status", "").upper()
            maker_matches = result.get("makerMatches", [])
            filled_amount = result.get("filledAmount") or result.get("matchedAmount") or result.get("filled")

            # Calculate actual filled amount from matches
            total_matched = sum(int(m.get("matchedSize", 0)) for m in maker_matches)

            logger.info(
                "Trade executed",
                platform="limitless",
                market_id=market_slug,
                order_id=order_id,
                order_status=order_status,
                filled_amount=filled_amount,
                maker_matches_count=len(maker_matches),
                total_matched=total_matched,
            )

            # FOK orders are filled if they have makerMatches
            is_filled = bool(maker_matches) or order_status in ("MATCHED", "FILLED", "COMPLETE", "COMPLETED")

            # Determine actual output - use matched size if available
            if total_matched > 0:
                # Convert from 6 decimal USDC to actual amount
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
