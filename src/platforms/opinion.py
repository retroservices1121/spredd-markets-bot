"""
Opinion Labs platform implementation using CLOB SDK.
AI-oracle powered prediction market on BNB Chain.
"""

import asyncio
from decimal import Decimal
from typing import Any, Optional
from datetime import datetime

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware

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
    MarketResolution,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OpinionPlatform(BasePlatform):
    """
    Opinion Labs prediction market platform.
    Uses CLOB SDK on BNB Chain with AI oracles.
    """

    platform = Platform.OPINION
    chain = Chain.BSC

    name = "Opinion Labs"
    description = "AI-oracle powered prediction markets on BNB Chain"
    website = "https://opinion.trade"

    collateral_symbol = "USDT"
    collateral_decimals = 18  # USDT on BSC has 18 decimals

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3: Optional[AsyncWeb3] = None
        self._sdk_client: Any = None
        # Read-only SDK client for orderbook queries (no trading)
        self._readonly_sdk_client: Any = None
        # Cache SDK clients per wallet address for faster repeat trades
        self._sdk_client_cache: dict[str, Any] = {}
        # Track wallets that have already enabled trading
        self._trading_enabled_wallets: set[str] = set()
    
    async def initialize(self) -> None:
        """Initialize Opinion Labs API client."""
        headers = {
            "Content-Type": "application/json",
        }
        # Opinion uses 'apikey' header, not Bearer token
        # Strip whitespace to handle env vars with trailing spaces
        if settings.opinion_api_key:
            headers["apikey"] = settings.opinion_api_key.strip()

        self._http_client = httpx.AsyncClient(
            base_url=settings.opinion_api_url,
            timeout=30.0,
            headers=headers,
        )

        # Web3 for BSC
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.bsc_rpc_url)
        )
        self._web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # Initialize read-only SDK client for orderbook queries
        # Uses a dummy key since we only need read access
        try:
            from opinion_clob_sdk import Client

            # Generate dummy values for read-only operations
            # These won't be used for signing transactions
            dummy_key = "0x" + "1" * 64  # Valid 32-byte hex key
            # Use configured multi_sig_addr or a dummy address if not set
            multi_sig = settings.opinion_multi_sig_addr or "0x" + "0" * 40
            self._readonly_sdk_client = Client(
                host=settings.opinion_api_url,
                apikey=(settings.opinion_api_key or "").strip(),
                chain_id=56,  # BNB Chain mainnet
                rpc_url=settings.bsc_rpc_url,
                private_key=dummy_key,
                multi_sig_addr=multi_sig,
            )
            logger.info("Opinion SDK read-only client initialized")
        except ImportError:
            logger.warning("opinion-clob-sdk not installed, orderbook queries will use fallback")
            self._readonly_sdk_client = None
        except Exception as e:
            logger.warning("Failed to initialize Opinion SDK read-only client", error=str(e))
            self._readonly_sdk_client = None

        logger.info("Opinion Labs platform initialized")
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
    
    def _init_sdk_client(self, private_key: str) -> Any:
        """Initialize the Opinion CLOB SDK client."""
        try:
            from opinion_clob_sdk import Client
            
            return Client(
                host=settings.opinion_api_url,
                apikey=(settings.opinion_api_key or "").strip(),
                chain_id=56,  # BNB Chain mainnet
                rpc_url=settings.bsc_rpc_url,
                private_key=private_key,
                multi_sig_addr=settings.opinion_multi_sig_addr,
            )
        except ImportError:
            logger.warning("opinion-clob-sdk not installed")
            return None
    
    async def _api_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to Opinion API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._http_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.OPINION)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.OPINION,
                str(e.response.status_code),
            )
    
    def _parse_market(self, data: dict) -> Market:
        """Parse Opinion market data into Market object."""
        # Opinion API uses camelCase field names
        market_id = str(data.get("marketId") or data.get("market_id") or data.get("id"))

        # Token IDs
        yes_token = data.get("yesTokenId") or data.get("yes_token_id")
        no_token = data.get("noTokenId") or data.get("no_token_id")

        # Extract pricing from tokens array if present
        tokens = data.get("tokens", [])
        yes_price = None
        no_price = None

        for token in tokens:
            outcome = token.get("outcome", "").lower()
            if outcome == "yes" or token.get("index") == 0:
                if not yes_token:
                    yes_token = token.get("tokenId") or token.get("token_id")
                yes_price = Decimal(str(token.get("price", 0.5)))
            elif outcome == "no" or token.get("index") == 1:
                if not no_token:
                    no_token = token.get("tokenId") or token.get("token_id")
                no_price = Decimal(str(token.get("price", 0.5)))

        # Fallback to top-level prices (default to 0.5 if not available)
        if yes_price is None:
            yes_price = Decimal(str(data.get("yesPrice") or data.get("yes_price") or "0.5"))
        if no_price is None:
            no_price = Decimal(str(data.get("noPrice") or data.get("no_price") or "0.5"))

        # Status - Opinion uses statusEnum or numeric status
        status_enum = data.get("statusEnum", "").lower()
        status_num = data.get("status")
        is_active = status_enum in ("activated", "active", "open") or status_num == 2

        # End time - Opinion uses cutoffAt (Unix timestamp)
        close_time = data.get("cutoffAt") or data.get("close_time") or data.get("endTime")
        if close_time and isinstance(close_time, (int, float)):
            close_time = datetime.fromtimestamp(close_time).isoformat()

        # Resolution criteria - Opinion uses 'rules' field for settlement rules
        resolution_criteria = data.get("rules") or data.get("resolutionRules") or data.get("description")

        return Market(
            platform=Platform.OPINION,
            chain=Chain.BSC,
            market_id=market_id,
            event_id=data.get("eventId") or data.get("event_id"),
            title=data.get("marketTitle") or data.get("market_title") or data.get("title") or "",
            description=data.get("rules") or data.get("description"),
            category=data.get("category") or data.get("topicType"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume24h") or data.get("volume_24h") or data.get("volume") or 0)),
            liquidity=Decimal(str(data.get("liquidity") or data.get("openInterest") or 0)),
            is_active=is_active,
            close_time=close_time,
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            resolution_criteria=resolution_criteria,
        )
    
    # ===================
    # Orderbook Price Enrichment
    # ===================

    async def _fetch_orderbook_price(self, market: Market) -> tuple[str, Decimal | None, Decimal | None]:
        """Fetch best bid/ask prices for a single market from orderbook."""
        try:
            if not market.yes_token:
                return (market.market_id, None, None)

            # Fetch YES orderbook
            yes_orderbook = await self.get_orderbook(market.market_id, Outcome.YES)
            yes_price = yes_orderbook.best_ask  # Price to buy YES

            # Calculate NO price as 1 - YES price (for binary markets)
            no_price = Decimal("1") - yes_price if yes_price else None

            return (market.market_id, yes_price, no_price)
        except Exception as e:
            logger.debug("Failed to fetch orderbook price", market_id=market.market_id, error=str(e))
            return (market.market_id, None, None)

    async def _enrich_markets_with_orderbook_prices(self, markets: list[Market], max_markets: int = 30) -> list[Market]:
        """
        Enrich markets with real orderbook prices.
        Fetches orderbooks in parallel for efficiency.

        Args:
            markets: List of markets to enrich
            max_markets: Maximum number of markets to fetch orderbooks for (to limit API calls)
        """
        if not self._readonly_sdk_client:
            # SDK not available, return markets as-is
            return markets

        # Only fetch orderbooks for the first N markets to limit API calls
        markets_to_enrich = markets[:max_markets]

        # Fetch orderbook prices in parallel
        tasks = [self._fetch_orderbook_price(m) for m in markets_to_enrich]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build a map of market_id -> (yes_price, no_price)
        price_map: dict[str, tuple[Decimal | None, Decimal | None]] = {}
        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                market_id, yes_price, no_price = result
                if yes_price is not None:
                    price_map[market_id] = (yes_price, no_price)

        # Update market prices
        enriched_count = 0
        for market in markets:
            if market.market_id in price_map:
                yes_price, no_price = price_map[market.market_id]
                if yes_price is not None:
                    market.yes_price = yes_price
                    market.no_price = no_price or Decimal("1") - yes_price
                    enriched_count += 1

        logger.info("Enriched markets with orderbook prices", total=len(markets), enriched=enriched_count)
        return markets

    # ===================
    # Market Discovery
    # ===================

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Opinion.

        Args:
            limit: Maximum number of markets to return
            offset: Number of markets to skip (for pagination)
            active_only: Only return active markets
        """
        # Opinion API uses /openapi/market endpoint
        # sortBy: 5 = volume (descending)
        # Note: API may have internal limits, but we request more to be safe
        params = {
            "limit": min(limit, 200),  # Request up to 200
            "sortBy": 5,  # Sort by 24h volume
        }
        if active_only:
            params["status"] = "activated"
        if offset > 0:
            params["offset"] = offset

        try:
            data = await self._api_request("GET", "/openapi/market", params=params)

            # Response structure: {"errno": 0, "errmsg": "ok", "result": {"list": [...], "total": N}}
            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Enrich with orderbook prices
            markets = await self._enrich_markets_with_orderbook_prices(markets)

            return markets

        except Exception as e:
            logger.error("Failed to get markets", error=str(e))
            return []

    async def search_markets(
        self,
        query: str,
        limit: int = 50,
    ) -> list[Market]:
        """Search markets by query."""
        # Opinion API uses keyword parameter for search
        params = {
            "keyword": query,
            "limit": min(limit, 100),
            "status": "activated",
        }

        try:
            data = await self._api_request("GET", "/openapi/market", params=params)

            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Enrich with orderbook prices
            markets = await self._enrich_markets_with_orderbook_prices(markets)

            return markets

        except Exception as e:
            # Fallback: get all markets and filter client-side
            logger.warning("Search failed, falling back to filter", error=str(e))
            all_markets = await self.get_markets(limit=100)
            query_lower = query.lower()
            return [
                m for m in all_markets
                if query_lower in m.title.lower() or
                   (m.description and query_lower in m.description.lower())
            ][:limit]

    async def get_market(self, market_id: str, search_title: Optional[str] = None, include_closed: bool = False) -> Optional[Market]:
        """Get a specific market by ID.

        Note: search_title and include_closed are accepted for API compatibility but not used.
        """
        try:
            # Opinion uses /openapi/market/{market_id} or /openapi/market?marketId=X
            data = await self._api_request("GET", f"/openapi/market/{market_id}")

            market_data = data.get("result", {}).get("data", data)
            if isinstance(market_data, dict) and market_data:
                return self._parse_market(market_data)

            # Fallback: try with query param
            data = await self._api_request("GET", "/openapi/market", params={"marketId": market_id})
            market_data = data.get("result", {}).get("list", [])
            if market_data:
                return self._parse_market(market_data[0])

            return None

        except PlatformError:
            return None

    async def get_trending_markets(self, limit: int = 50) -> list[Market]:
        """Get trending markets by volume."""
        # sortBy: 5 = 24h volume descending
        params = {
            "limit": min(limit, 100),
            "sortBy": 5,
            "status": "activated",
        }

        try:
            data = await self._api_request("GET", "/openapi/market", params=params)

            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Enrich with orderbook prices
            markets = await self._enrich_markets_with_orderbook_prices(markets)

            return markets

        except Exception as e:
            logger.error("Failed to get trending markets", error=str(e))
            return []

    # ===================
    # Categories
    # ===================

    # Keywords to match in market titles for each category
    CATEGORY_KEYWORDS = {
        "crypto": [
            "bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
            "binance", "token", "defi", "nft", "blockchain", "altcoin",
        ],
        "politics": [
            "trump", "biden", "election", "president", "congress", "senate",
            "governor", "democrat", "republican", "vote", "political", "government",
        ],
        "sports": [
            "nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball",
            "baseball", "championship", "super bowl", "playoffs", "world cup",
        ],
        "economics": [
            "fed", "interest rate", "inflation", "gdp", "recession", "tariff",
            "economy", "stock", "market", "s&p", "nasdaq", "dow",
        ],
        "world": [
            "war", "ukraine", "russia", "china", "israel", "iran", "military",
            "conflict", "peace", "nato", "un", "sanctions",
        ],
        "entertainment": [
            "movie", "oscar", "grammy", "album", "netflix", "spotify",
            "celebrity", "music", "film", "tv", "streaming",
        ],
    }

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories.

        Returns list of dicts with 'id', 'label', and 'emoji' keys.
        """
        return [
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "economics", "label": "Economics", "emoji": "📊"},
            {"id": "world", "label": "World", "emoji": "🌍"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
        ]

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 50,
    ) -> list[Market]:
        """Get markets filtered by category.

        Categories are inferred from market title keywords since Opinion API
        doesn't have a categories field.
        """
        # Get all active markets for filtering
        all_markets = await self.get_markets(limit=200, offset=0, active_only=True)

        # Get keywords for this category
        keywords = self.CATEGORY_KEYWORDS.get(category.lower(), [])
        if not keywords:
            return []

        # Filter markets by title keywords
        filtered = []
        for market in all_markets:
            title_lower = market.title.lower()
            if any(keyword in title_lower for keyword in keywords):
                filtered.append(market)

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
        """Get order book from Opinion SDK or API."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.OPINION)

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.OPINION)

        try:
            bids = []
            asks = []

            # Try SDK method first (preferred)
            if self._readonly_sdk_client:
                logger.info("Fetching Opinion orderbook via SDK", token_id=token_id[:20] + "...", market_id=market_id, outcome=outcome.value)
                # Run synchronous SDK call in thread pool to avoid blocking
                result = await asyncio.to_thread(
                    self._readonly_sdk_client.get_orderbook,
                    token_id=token_id,
                )

                if result.errno == 0 and result.result:
                    # Handle different response structures - try result.result directly first
                    orderbook_data = result.result
                    # If result.result has a data attribute, use that instead
                    if hasattr(orderbook_data, 'data') and orderbook_data.data:
                        orderbook_data = orderbook_data.data

                    # Get bids and asks from the response
                    raw_bids = getattr(orderbook_data, 'bids', None) or []
                    raw_asks = getattr(orderbook_data, 'asks', None) or []

                    logger.info(
                        "Opinion SDK orderbook response",
                        response_type=type(orderbook_data).__name__,
                        has_bids=len(raw_bids),
                        has_asks=len(raw_asks),
                    )

                    for bid in raw_bids:
                        if isinstance(bid, dict):
                            price = bid.get('price', 0)
                            size = bid.get('size') or bid.get('quantity', 0)
                        else:
                            price = getattr(bid, 'price', 0)
                            size = getattr(bid, 'size', None) or getattr(bid, 'quantity', 0)
                        bids.append((Decimal(str(price)), Decimal(str(size or 0))))

                    for ask in raw_asks:
                        if isinstance(ask, dict):
                            price = ask.get('price', 0)
                            size = ask.get('size') or ask.get('quantity', 0)
                        else:
                            price = getattr(ask, 'price', 0)
                            size = getattr(ask, 'size', None) or getattr(ask, 'quantity', 0)
                        asks.append((Decimal(str(price)), Decimal(str(size or 0))))
                else:
                    logger.warning(
                        "Opinion SDK orderbook returned error",
                        errno=result.errno,
                        errmsg=getattr(result, 'errmsg', 'unknown'),
                    )
                    raise PlatformError(f"SDK error: {getattr(result, 'errmsg', 'unknown')}", Platform.OPINION)
            else:
                # Fallback to REST API
                logger.info("Fetching Opinion orderbook via REST API", token_id=token_id[:20] + "...", market_id=market_id)
                data = await self._api_request("GET", f"/openapi/orderbook/{token_id}")

                orderbook_data = data.get("result", data)
                logger.info("Opinion REST orderbook response", has_bids=len(orderbook_data.get("bids", [])), has_asks=len(orderbook_data.get("asks", [])))

                for bid in orderbook_data.get("bids", []):
                    bids.append((
                        Decimal(str(bid.get("price", 0))),
                        Decimal(str(bid.get("size") or bid.get("quantity", 0))),
                    ))

                for ask in orderbook_data.get("asks", []):
                    asks.append((
                        Decimal(str(ask.get("price", 0))),
                        Decimal(str(ask.get("size") or ask.get("quantity", 0))),
                    ))

            # Sort bids descending (highest first) - best_bid = highest price buyers will pay
            bids.sort(key=lambda x: x[0], reverse=True)
            # Sort asks ascending (lowest first) - best_ask = lowest price sellers will accept
            asks.sort(key=lambda x: x[0])

            logger.info(
                "Opinion orderbook parsed",
                market_id=market_id,
                outcome=outcome.value,
                num_bids=len(bids),
                num_asks=len(asks),
                best_bid=str(bids[0][0]) if bids else "none",
                best_ask=str(asks[0][0]) if asks else "none",
            )

            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=bids,
                asks=asks,
            )

        except Exception as e:
            logger.warning("Failed to get Opinion orderbook, using market prices", error=str(e), market_id=market_id)
            # Return empty orderbook with market prices
            fallback_price = market.yes_price if outcome == Outcome.YES else market.no_price
            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=[(fallback_price, Decimal(100))] if fallback_price else [],
                asks=[(fallback_price, Decimal(100))] if fallback_price else [],
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
        """Get a quote for a trade.

        Note: token_id is accepted for API compatibility but ignored -
        Opinion determines tokens from market data.
        """
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.OPINION)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.OPINION)
        
        # Get current price from orderbook
        orderbook = await self.get_orderbook(market_id, outcome)

        # USDT on BSC
        usdt_address = "0x55d398326f99059fF775485246999027B3197955"

        if side == "buy":
            price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price
            input_token = usdt_address
            output_token = token_id
            logger.info(
                "Opinion quote (buy)",
                market_id=market_id,
                outcome=outcome.value,
                orderbook_best_ask=str(orderbook.best_ask) if orderbook.best_ask else "none",
                market_price=str(market.yes_price if outcome == Outcome.YES else market.no_price),
                final_price=str(price),
            )
        else:
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id
            output_token = usdt_address
            logger.info(
                "Opinion quote (sell)",
                market_id=market_id,
                outcome=outcome.value,
                orderbook_best_bid=str(orderbook.best_bid) if orderbook.best_bid else "none",
                market_price=str(market.yes_price if outcome == Outcome.YES else market.no_price),
                final_price=str(price),
            )
        
        return Quote(
            platform=Platform.OPINION,
            chain=Chain.BSC,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal("0.01"),
            platform_fee=amount * Decimal("0.02"),  # 2% estimate
            network_fee_estimate=Decimal("0.001"),  # BNB
            expires_at=None,
            quote_data={
                "token_id": token_id,
                "market_id": market_id,
                "price": str(price),
                "market": market.raw_data,
            },
        )
    
    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
        order_type: str = "market",  # "market" or "limit"
        limit_price: Optional[Decimal] = None,
    ) -> TradeResult:
        """
        Execute a trade on Opinion Labs.
        Uses the opinion-clob-sdk for order execution.

        Args:
            quote: Quote object with trade details
            private_key: EVM LocalAccount with private key
            order_type: "market" for market order, "limit" for limit order
            limit_price: Price for limit orders (required if order_type="limit")
        """
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.OPINION,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.OPINION)

        try:
            # Import Opinion SDK
            from opinion_clob_sdk import Client
            from opinion_clob_sdk.chain.py_order_utils.model.order import PlaceOrderDataInput
            from opinion_clob_sdk.chain.py_order_utils.model.sides import OrderSide
            from opinion_clob_sdk.chain.py_order_utils.model.order_type import MARKET_ORDER, LIMIT_ORDER

            wallet_address = private_key.address.lower()

            # Use cached SDK client or create new one
            if wallet_address in self._sdk_client_cache:
                client = self._sdk_client_cache[wallet_address]
                logger.debug("Using cached Opinion SDK client", wallet=wallet_address[:10])
            else:
                # Initialize SDK client
                client = Client(
                    host=settings.opinion_api_url,
                    apikey=(settings.opinion_api_key or "").strip(),
                    chain_id=56,  # BNB Chain mainnet
                    rpc_url=settings.bsc_rpc_url,
                    private_key=private_key.key.hex(),
                    multi_sig_addr=settings.opinion_multi_sig_addr or "",
                )
                self._sdk_client_cache[wallet_address] = client
                logger.debug("Created new Opinion SDK client", wallet=wallet_address[:10])

            # Enable trading only if not already done for this wallet
            if wallet_address not in self._trading_enabled_wallets:
                try:
                    client.enable_trading()
                    self._trading_enabled_wallets.add(wallet_address)
                    logger.debug("Trading enabled for wallet", wallet=wallet_address[:10])
                except Exception as e:
                    # If it fails, wallet might already be enabled - mark as done
                    self._trading_enabled_wallets.add(wallet_address)
                    logger.debug("enable_trading call", note=str(e))

            token_id = quote.quote_data["token_id"]
            market_id = int(quote.quote_data["market_id"])

            # Create order
            order_side = OrderSide.BUY if quote.side == "buy" else OrderSide.SELL
            sdk_order_type = LIMIT_ORDER if order_type == "limit" else MARKET_ORDER

            # Price: use limit_price for limit orders, "0" for market orders
            price = str(limit_price) if order_type == "limit" and limit_price else "0"

            order = PlaceOrderDataInput(
                marketId=market_id,
                tokenId=token_id,
                side=order_side,
                orderType=sdk_order_type,
                price=price,
                makerAmountInQuoteToken=float(quote.input_amount) if quote.side == "buy" else None,
                makerAmountInBaseToken=float(quote.input_amount) if quote.side == "sell" else None,
            )

            logger.info(
                "Placing Opinion order",
                market_id=market_id,
                token_id=token_id,
                side=quote.side,
                order_type=order_type,
                amount=float(quote.input_amount),
            )

            result = client.place_order(order, check_approval=True)

            if result.errno != 0:
                raise PlatformError(
                    f"Order failed: {result.errmsg}",
                    Platform.OPINION,
                )

            order_id = result.result.data.order_id if result.result and result.result.data else None
            tx_hash = str(order_id) if order_id else None

            logger.info(
                "Trade executed",
                platform="opinion",
                market_id=quote.market_id,
                order_id=order_id,
            )

            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash and tx_hash.startswith("0x") else None,
            )

        except ImportError:
            logger.error("opinion-clob-sdk not installed")
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message="Opinion SDK not installed. Install with: pip install opinion-clob-sdk",
                explorer_url=None,
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
        """Check if market has resolved.

        Opinion uses statusEnum field for resolution:
        - "settled" or "resolved" = market has resolved
        - "expired" = deadline passed
        - The winning outcome can be in 'resolution' or 'winningOutcome' fields
        """
        try:
            market = await self.get_market(market_id, include_closed=True)
            if not market or not market.raw_data:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            raw = market.raw_data

            # Check status for resolution indicators
            status_enum = str(raw.get("statusEnum", "")).lower()
            status_num = raw.get("status")

            # Market is resolved if status indicates settled/resolved/expired
            resolved = status_enum in ("settled", "resolved", "expired") or status_num in (3, 4, 5)

            if not resolved:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            # Determine winning outcome
            winning = None

            # Check various fields for winning outcome
            resolution = (
                raw.get("resolution") or
                raw.get("winningOutcome") or
                raw.get("winning_outcome") or
                raw.get("outcome")
            )

            if resolution is not None:
                resolution_str = str(resolution).lower()
                if resolution_str in ["yes", "0", "true", "y"]:
                    winning = "yes"
                elif resolution_str in ["no", "1", "false", "n"]:
                    winning = "no"

            # Also check winning_index if available
            winning_index = raw.get("winning_index") or raw.get("winningIndex")
            if winning_index is not None and winning is None:
                winning = "yes" if winning_index == 0 else "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning,
                resolution_time=raw.get("resolvedAt") or raw.get("settledAt"),
            )
        except Exception as e:
            logger.warning("Failed to check market resolution", market_id=market_id, error=str(e))
            return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)


# Singleton instance
opinion_platform = OpinionPlatform()
