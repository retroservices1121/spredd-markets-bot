"""
Opinion Labs platform implementation using CLOB SDK.
AI-oracle powered prediction market on BNB Chain.
"""

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
    
    async def initialize(self) -> None:
        """Initialize Opinion Labs API client."""
        headers = {
            "Content-Type": "application/json",
        }
        if settings.opinion_api_key:
            headers["Authorization"] = f"Bearer {settings.opinion_api_key}"
        
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
                apikey=settings.opinion_api_key or "",
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
        # Opinion uses different field names
        market_id = str(data.get("market_id") or data.get("marketId") or data.get("id"))
        
        # Extract pricing from tokens
        tokens = data.get("tokens", [])
        yes_token = None
        no_token = None
        yes_price = None
        no_price = None
        
        for token in tokens:
            outcome = token.get("outcome", "").lower()
            if outcome == "yes" or token.get("index") == 0:
                yes_token = token.get("token_id") or token.get("tokenId")
                yes_price = Decimal(str(token.get("price", 0.5)))
            elif outcome == "no" or token.get("index") == 1:
                no_token = token.get("token_id") or token.get("tokenId")
                no_price = Decimal(str(token.get("price", 0.5)))
        
        # Fallback to top-level prices
        if yes_price is None:
            yes_price = Decimal(str(data.get("yes_price") or data.get("yesPrice", 0.5)))
        if no_price is None:
            no_price = Decimal(str(data.get("no_price") or data.get("noPrice", 0.5)))
        
        # Status
        status = data.get("status", "").lower()
        is_active = status in ("active", "activated", "open", "")
        
        return Market(
            platform=Platform.OPINION,
            chain=Chain.BSC,
            market_id=market_id,
            event_id=data.get("event_id") or data.get("eventId"),
            title=data.get("market_title") or data.get("title") or data.get("question", ""),
            description=data.get("description") or data.get("subtitle"),
            category=data.get("category") or data.get("topic_type"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume_24h") or data.get("volume", 0))),
            liquidity=Decimal(str(data.get("liquidity") or data.get("open_interest", 0))),
            is_active=is_active,
            close_time=data.get("end_time") or data.get("close_time") or data.get("endTime"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
        )
    
    # ===================
    # Market Discovery
    # ===================
    
    async def get_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Opinion.

        Args:
            limit: Maximum number of markets to return
            offset: Number of markets to skip (for pagination)
            active_only: Only return active markets
        """
        # Convert offset to page number (1-indexed)
        page = (offset // limit) + 1 if limit > 0 else 1

        params = {
            "page": page,
            "limit": limit,
        }
        if active_only:
            params["status"] = "ACTIVATED"

        try:
            data = await self._api_request("GET", "/api/v1/markets", params=params)

            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            return markets

        except Exception as e:
            logger.error("Failed to get markets", error=str(e))
            return []
    
    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets by query."""
        params = {
            "q": query,
            "limit": limit,
            "status": "ACTIVATED",
        }
        
        try:
            data = await self._api_request("GET", "/api/v1/markets/search", params=params)
            
            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data
            
            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))
            
            return markets
            
        except Exception as e:
            # Fallback: get all markets and filter
            logger.warning("Search failed, falling back to filter", error=str(e))
            all_markets = await self.get_markets(limit=100)
            query_lower = query.lower()
            return [
                m for m in all_markets 
                if query_lower in m.title.lower() or 
                   (m.description and query_lower in m.description.lower())
            ][:limit]
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ID."""
        try:
            data = await self._api_request("GET", f"/api/v1/markets/{market_id}")
            
            market_data = data.get("result", {}).get("data", data)
            return self._parse_market(market_data)
            
        except PlatformError:
            return None
    
    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending markets by volume."""
        params = {
            "limit": limit,
            "order_by": "volume",
            "status": "ACTIVATED",
        }
        
        try:
            data = await self._api_request("GET", "/api/v1/markets", params=params)
            
            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data
            
            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))
            
            return markets
            
        except Exception as e:
            logger.error("Failed to get trending markets", error=str(e))
            return []
    
    # ===================
    # Order Book
    # ===================
    
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
    ) -> OrderBook:
        """Get order book from Opinion API."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.OPINION)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.OPINION)
        
        try:
            data = await self._api_request("GET", f"/api/v1/orderbook/{token_id}")
            
            orderbook_data = data.get("result", data)
            
            bids = []
            asks = []
            
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

            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=bids,
                asks=asks,
            )
            
        except Exception as e:
            logger.warning("Failed to get orderbook", error=str(e))
            # Return empty orderbook with market prices
            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=[(market.yes_price if outcome == Outcome.YES else market.no_price, Decimal(100))] if market.yes_price else [],
                asks=[(market.yes_price if outcome == Outcome.YES else market.no_price, Decimal(100))] if market.yes_price else [],
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
        order_type: str = "market",
    ) -> Quote:
        """Get a quote for a trade.

        Note: token_id is accepted for API compatibility but ignored -
        Opinion determines tokens from market data.
        Note: order_type is accepted for API compatibility but Opinion only supports market orders.
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
        else:
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id
            output_token = usdt_address
        
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
            platform_fee=amount * Decimal("0.01"),  # 1% estimate
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
    ) -> TradeResult:
        """
        Execute a trade on Opinion Labs.
        Uses the opinion-clob-sdk for order execution.
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
            from opinion_clob_sdk.chain.py_order_utils.model.order_type import MARKET_ORDER
            
            # Initialize SDK client
            client = Client(
                host=settings.opinion_api_url,
                apikey=settings.opinion_api_key or "",
                chain_id=56,
                rpc_url=settings.bsc_rpc_url,
                private_key=private_key.key.hex(),
                multi_sig_addr=settings.opinion_multi_sig_addr,
            )
            
            token_id = quote.quote_data["token_id"]
            market_id = int(quote.quote_data["market_id"])
            
            # Create order
            order_side = OrderSide.BUY if quote.side == "buy" else OrderSide.SELL
            
            order = PlaceOrderDataInput(
                marketId=market_id,
                tokenId=token_id,
                side=order_side,
                orderType=MARKET_ORDER,
                price="0",  # Market order ignores price
                makerAmountInQuoteToken=float(quote.input_amount) if quote.side == "buy" else None,
                makerAmountInBaseToken=float(quote.input_amount) if quote.side == "sell" else None,
            )
            
            result = client.place_order(order, check_approval=True)
            
            if result.errno != 0:
                raise PlatformError(
                    f"Order failed: {result.errmsg}",
                    Platform.OPINION,
                )
            
            order_id = result.result.data.order_id if result.result else None
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


# Singleton instance
opinion_platform = OpinionPlatform()
