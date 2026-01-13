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
            return response.json()

        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.LIMITLESS,
                str(e.response.status_code),
            )

    async def _get_session(self, private_key: LocalAccount) -> str:
        """Get or create authenticated session for wallet."""
        wallet = private_key.address

        # Check cache
        cached = self._session_cache.get(wallet)
        if cached and cached.get("expires_at", 0) > time.time():
            return cached["session"]

        # Authenticate with Limitless
        checksum_address = Web3.to_checksum_address(wallet)

        # Step 1: Get signing message
        message_resp = await self._api_request(
            "GET",
            f"/auth/signing-message?account={checksum_address}"
        )
        signing_message = message_resp.get("message") or message_resp.get("signingMessage")
        if not signing_message:
            raise PlatformError("Failed to get signing message", Platform.LIMITLESS)

        # Step 2: Sign the message
        signature = private_key.sign_message(
            encode_typed_data(text=signing_message) if isinstance(signing_message, str)
            else signing_message
        )

        # For simple message signing
        from eth_account.messages import encode_defunct
        message = encode_defunct(text=signing_message)
        signed = private_key.sign_message(message)

        # Step 3: Submit for session
        login_resp = await self._api_request(
            "POST",
            "/auth/login",
            headers={
                "x-account": checksum_address,
                "x-signing-message": signing_message.encode().hex() if isinstance(signing_message, str) else signing_message,
                "x-signature": signed.signature.hex(),
            }
        )

        session = login_resp.get("session") or login_resp.get("token")
        if not session:
            # Try to extract from cookies
            raise PlatformError("Failed to authenticate", Platform.LIMITLESS)

        # Cache session (29 days)
        self._session_cache[wallet] = {
            "session": session,
            "expires_at": time.time() + 29 * 24 * 3600,
        }

        return session

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

        # Volume
        volume = data.get("volume") or data.get("volume24h") or data.get("volumeUsd") or 0
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
            volume_24h=Decimal(str(volume)) if volume else None,
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
        # Try direct lookup by ID first
        try:
            data = await self._api_request("GET", f"/markets/{market_id}")
            return self._parse_market(data)
        except Exception as e:
            logger.debug("Direct market lookup failed", market_id=market_id, error=str(e))

        # If market_id is numeric, also try lookup as slug in search results
        # Try searching if direct lookup fails
        try:
            markets = await self.search_markets(market_id, limit=10)
            for m in markets:
                # Match by ID, slug, or partial slug match
                if (m.market_id == market_id or
                    m.event_id == market_id or
                    market_id in str(m.market_id) or
                    market_id in str(m.event_id)):
                    return m
        except Exception as e:
            logger.warning("Market search fallback failed", market_id=market_id, error=str(e))

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
                "market_slug": market_id,
                "price": str(price),
                "market": market.raw_data,
            },
        )

    async def _get_venue(self, market_id: str) -> dict:
        """Get venue (exchange contract) info for a market."""
        if market_id in self._venue_cache:
            return self._venue_cache[market_id]

        market = await self.get_market(market_id)
        if not market or not market.raw_data:
            raise PlatformError("Market not found", Platform.LIMITLESS)

        venue = market.raw_data.get("venue", {})
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
    ) -> dict:
        """Build and sign EIP-712 order for Limitless."""
        wallet = Web3.to_checksum_address(private_key.address)
        exchange = venue.get("exchange", venue.get("address"))

        if not exchange:
            raise PlatformError("Exchange address not found in venue", Platform.LIMITLESS)

        # Calculate amounts (USDC has 6 decimals)
        if side == "buy":
            # makerAmount = USDC to spend, takerAmount = tokens to receive
            maker_amount = int(amount * Decimal(10 ** 6))
            taker_amount = int((amount / price) * Decimal(10 ** 6))
            order_side = 0  # BUY
        else:
            # makerAmount = tokens to sell, takerAmount = USDC to receive
            maker_amount = int(amount * Decimal(10 ** 6))
            taker_amount = int((amount * price) * Decimal(10 ** 6))
            order_side = 1  # SELL

        # Build order struct
        order = {
            "salt": secrets.randbelow(2 ** 256),
            "maker": wallet,
            "signer": wallet,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": str(int(time.time()) + 3600),  # 1 hour
            "nonce": str(int(time.time() * 1000)),
            "feeRateBps": "0",
            "side": order_side,
            "signatureType": 0,  # EOA
        }

        # EIP-712 domain
        domain = {
            "name": "Limitless Exchange",
            "version": "1",
            "chainId": 8453,  # Base
            "verifyingContract": Web3.to_checksum_address(exchange),
        }

        # EIP-712 types
        types = {
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
            ]
        }

        # Sign order
        signable_message = encode_typed_data(
            domain_data=domain,
            message_types=types,
            message_data={
                "salt": int(order["salt"]),
                "maker": order["maker"],
                "signer": order["signer"],
                "taker": order["taker"],
                "tokenId": int(order["tokenId"]) if order["tokenId"].isdigit() else 0,
                "makerAmount": int(order["makerAmount"]),
                "takerAmount": int(order["takerAmount"]),
                "expiration": int(order["expiration"]),
                "nonce": int(order["nonce"]),
                "feeRateBps": int(order["feeRateBps"]),
                "side": order["side"],
                "signatureType": order["signatureType"],
            }
        )

        signed = private_key.sign_message(signable_message)
        order["signature"] = signed.signature.hex()

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
            )

            # Get session for authenticated request
            # Note: Some orders may work without authentication
            session = None
            try:
                session = await self._get_session(private_key)
            except Exception as e:
                logger.warning("Session auth failed, trying without", error=str(e))

            # Submit order
            payload = {
                "order": order,
                "orderType": "FOK",  # Fill-or-Kill for market orders
                "marketSlug": market_slug,
            }

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
