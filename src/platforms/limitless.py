"""
Limitless Exchange platform implementation.
Prediction market on Base chain using CLOB API.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional, Tuple
from datetime import datetime
import json
import time
import secrets

import httpx
from eth_account.messages import encode_typed_data
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


class LimitlessPlatform(BasePlatform):
    """
    Limitless Exchange prediction market platform.
    Uses CLOB API on Base chain.
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

    def _parse_market(self, data: dict) -> Market:
        """Parse Limitless market data into Market object."""
        # Extract prices
        yes_price = None
        no_price = None

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

        return Market(
            platform=Platform.LIMITLESS,
            chain=Chain.BASE,
            market_id=market_id,
            event_id=slug,  # Store slug in event_id for reference
            title=data.get("title") or data.get("question", ""),
            description=data.get("description"),
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume if volume else None,
            liquidity=Decimal(str(liquidity)) if liquidity else None,
            is_active=data.get("status") in ("active", "FUNDED", "ACTIVE") or data.get("isActive", True),
            # Prefer expirationTimestamp (milliseconds) for accurate time, fallback to date strings
            close_time=data.get("expirationTimestamp") or data.get("expirationDate") or data.get("endDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
        )

    async def get_markets(
        self,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Limitless."""
        # API uses 1-indexed pages
        page = (offset // limit) + 1 if limit > 0 else 1
        params = {
            "limit": limit,
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

        return markets[:limit]

    async def search_markets(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Market]:
        """Search markets by query."""
        try:
            data = await self._api_request(
                "GET",
                "/markets/search",
                params={"query": query, "limit": limit}
            )
        except Exception as e:
            logger.error("Failed to search markets", error=str(e))
            # Fallback to fetching all and filtering
            all_markets = await self.get_markets(limit=100)
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

    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ID (numeric) or slug."""
        # If market_id is numeric, try to get slug from cache first
        lookup_id = market_id
        if market_id.isdigit():
            cached_slug = self._id_to_slug_cache.get(market_id)
            if cached_slug:
                lookup_id = cached_slug
                logger.debug("Using cached slug for market", numeric_id=market_id, slug=cached_slug)

        # Try direct lookup by slug
        try:
            data = await self._api_request("GET", f"/markets/{lookup_id}")
            return self._parse_market(data)
        except Exception as e:
            logger.debug("Direct market lookup failed", market_id=lookup_id, error=str(e))

        # If we haven't tried the original market_id yet (different from lookup_id), try it
        if lookup_id != market_id:
            try:
                data = await self._api_request("GET", f"/markets/{market_id}")
                return self._parse_market(data)
            except Exception as e:
                logger.debug("Fallback market lookup failed", market_id=market_id, error=str(e))

        # Try searching - for numeric IDs, fetch all markets to find the match
        if market_id.isdigit():
            # Fetch recent markets to find one with matching ID
            try:
                all_markets = await self.get_markets(limit=100)
                for m in all_markets:
                    if m.market_id == market_id:
                        return m
            except Exception as e:
                logger.debug("Market list search failed", error=str(e))

        return None

    async def get_trending_markets(self, limit: int = 20) -> list[Market]:
        """Get trending markets by volume."""
        return await self.get_markets(limit=limit, active_only=True)

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 20,
    ) -> list[Market]:
        """Get markets filtered by category ID."""
        try:
            data = await self._api_request(
                "GET",
                f"/markets/active/{category}",
                params={"limit": limit, "page": 1}
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
        # Try with provided ID first, then with slug if that fails
        endpoints_to_try = [market_id]
        if slug and slug != market_id:
            endpoints_to_try.append(slug)

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

        # Parse orderbook based on outcome
        outcome_key = "yes" if outcome == Outcome.YES else "no"

        orderbook_data = data.get(outcome_key) or data.get("orderbook", {}).get(outcome_key) or data

        for bid in orderbook_data.get("bids", []):
            price = Decimal(str(bid.get("price", bid[0] if isinstance(bid, list) else 0)))
            size = Decimal(str(bid.get("size", bid.get("quantity", bid[1] if isinstance(bid, list) else 0))))
            bids.append((price, size))

        for ask in orderbook_data.get("asks", []):
            price = Decimal(str(ask.get("price", ask[0] if isinstance(ask, list) else 0)))
            size = Decimal(str(ask.get("size", ask.get("quantity", ask[1] if isinstance(ask, list) else 0))))
            asks.append((price, size))

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
    ) -> Quote:
        """Get a quote for a trade."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.LIMITLESS)

        # Get token ID
        if not token_id:
            token_id = market.yes_token if outcome == Outcome.YES else market.no_token

        # Get orderbook for pricing (pass slug for fallback lookup)
        orderbook = await self.get_orderbook(market_id, outcome, token_id=token_id, slug=market.event_id)

        if side == "buy":
            price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price
            input_token = USDC_BASE
            output_token = token_id or "outcome_token"
        else:
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id or "outcome_token"
            output_token = USDC_BASE

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
            quote_data={
                "token_id": token_id,
                "market_slug": market.event_id or market_id,  # Use actual slug, not numeric ID
                "price": str(price),
                "market": market.raw_data,
            },
        )

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
    ) -> dict:
        """Build and sign EIP-712 order for Limitless."""
        wallet = Web3.to_checksum_address(private_key.address)
        exchange = venue.get("exchange", venue.get("address"))

        logger.debug("Building EIP-712 order", venue=venue, exchange=exchange)

        if not exchange:
            raise PlatformError("Exchange address not found in venue", Platform.LIMITLESS)

        # Calculate tick size from price (number of decimal places)
        # e.g. price=0.806 has 3 decimals, so tick_size=3, round to nearest 1000
        price_str = str(price)
        if '.' in price_str:
            tick_size = len(price_str.split('.')[1])
        else:
            tick_size = 0
        tick_round = 10 ** tick_size if tick_size > 0 else 1

        # Calculate amounts (USDC has 6 decimals)
        # contracts must be rounded so that price * contracts is a whole number
        if side == "buy":
            # makerAmount = USDC to spend, takerAmount = tokens (contracts) to receive
            raw_contracts = int((amount / price) * Decimal(10 ** 6))
            # Round down to tick size
            taker_amount = (raw_contracts // tick_round) * tick_round
            # Recalculate maker_amount based on rounded contracts
            maker_amount = int(Decimal(taker_amount) * price)
            order_side = 0  # BUY
        else:
            # makerAmount = tokens to sell, takerAmount = USDC to receive
            maker_amount = int(amount * Decimal(10 ** 6))
            # Round maker_amount to tick size
            maker_amount = (maker_amount // tick_round) * tick_round
            taker_amount = int(Decimal(maker_amount) * price)
            order_side = 1  # SELL

        # Build order struct - API requires numbers, not strings for numeric fields
        order = {
            "salt": secrets.randbelow(2 ** 256),
            "maker": wallet,
            "signer": wallet,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),  # tokenId stays as string (large number)
            "makerAmount": maker_amount,  # Must be number
            "takerAmount": taker_amount,  # Must be number
            "expiration": "0",  # Must be "0" - expiration not currently supported
            "nonce": 0,  # Must be 0 per API requirement
            "feeRateBps": fee_rate_bps,  # Must be number
            "side": order_side,
            "signatureType": 0,  # EOA
        }

        # EIP-712 domain - must use "Limitless CTF Exchange" as domain name
        exchange_checksum = Web3.to_checksum_address(exchange)

        # Build message data for signing (all values must be correct types)
        message_data = {
            "salt": int(order["salt"]),
            "maker": wallet,
            "signer": wallet,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id) if str(token_id).isdigit() else int(token_id, 16) if token_id.startswith("0x") else 0,
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": 0,
            "nonce": 0,
            "feeRateBps": fee_rate_bps,
            "side": order_side,
            "signatureType": 0,
        }

        # Use full_message format for EIP-712 encoding (more explicit)
        full_message = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"},
                ],
            },
            "primaryType": "Order",
            "domain": {
                "name": "Limitless CTF Exchange",
                "version": "1",
                "chainId": 8453,
                "verifyingContract": exchange_checksum,
            },
            "message": message_data,
        }

        # Sign order using full_message format
        signable_message = encode_typed_data(full_message=full_message)

        signed = private_key.sign_message(signable_message)

        # Signature must have 0x prefix
        signature_hex = signed.signature.hex()
        if not signature_hex.startswith("0x"):
            signature_hex = "0x" + signature_hex
        order["signature"] = signature_hex

        # Add price field (required by API) - price as decimal
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

            # Ensure USDC approval for buys
            if quote.side == "buy":
                await self._ensure_approval(private_key, exchange)

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
            )

            # Submit order
            payload = {
                "order": order,
                "orderType": "GTC",  # Good Till Cancelled
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
            )

            result = await self._api_request(
                "POST",
                "/orders",
                session_cookie=session,
                json=payload,
            )

            order_id = result.get("orderId") or result.get("id") or result.get("transactionHash", "")

            logger.info(
                "Trade executed",
                platform="limitless",
                market_id=market_slug,
                order_id=order_id,
            )

            # Collect platform fee after successful trade
            if self._fee_account and self._fee_bps > 0 and quote.side == "buy":
                fee_amount = (quote.input_amount * Decimal(self._fee_bps) / Decimal(10000)).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                if fee_amount > 0:
                    self._collect_platform_fee(private_key, fee_amount)

            return TradeResult(
                success=True,
                tx_hash=order_id,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
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

    def _collect_platform_fee(
        self,
        private_key: LocalAccount,
        amount_usdc: Decimal,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Collect platform fee by transferring USDC."""
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

    # ===================
    # Resolution & Redemption
    # ===================

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """Check if market has resolved."""
        try:
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            status = market.raw_data.get("status", "")
            resolved = status == "resolved" or market.raw_data.get("resolved", False)

            if not resolved:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            resolution = market.raw_data.get("resolution") or market.raw_data.get("winningOutcome")
            winning = None
            if resolution:
                if resolution.lower() in ["yes", "0", "true"]:
                    winning = "yes"
                elif resolution.lower() in ["no", "1", "false"]:
                    winning = "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning,
                resolution_time=market.raw_data.get("resolutionTime"),
            )

        except Exception as e:
            logger.error("Failed to check resolution", error=str(e))
            return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """Redeem winning tokens from resolved market."""
        # This would require calling the CTF contract similar to Polymarket
        # Implementation depends on Limitless's specific contract interface
        return RedemptionResult(
            success=False,
            tx_hash=None,
            amount_redeemed=None,
            error_message="Redemption not yet implemented for Limitless",
            explorer_url=None,
        )

    def get_explorer_url(self, tx_hash: str) -> str:
        """Get Base block explorer URL."""
        return f"https://basescan.org/tx/{tx_hash}"


# Singleton instance
limitless_platform = LimitlessPlatform()
