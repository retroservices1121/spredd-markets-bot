"""
Polymarket platform implementation using CLOB API.
World's largest prediction market on Polygon.
"""

from decimal import Decimal
from typing import Any, Optional
from datetime import datetime

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3

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

# Polymarket contract addresses on Polygon
POLYMARKET_CONTRACTS = {
    "exchange": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "neg_risk_exchange": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "collateral": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC.e
    "ctf": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",  # Conditional Tokens
}


class PolymarketPlatform(BasePlatform):
    """
    Polymarket prediction market platform.
    Uses CLOB (Central Limit Order Book) API on Polygon.
    """
    
    platform = Platform.POLYMARKET
    chain = Chain.POLYGON
    
    name = "Polymarket"
    description = "World's largest prediction market on Polygon"
    website = "https://polymarket.com"
    
    collateral_symbol = "USDC"
    collateral_decimals = 6
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._gamma_client: Optional[httpx.AsyncClient] = None  # For market data
        self._web3: Optional[AsyncWeb3] = None
        self._api_creds: Optional[dict] = None
    
    async def initialize(self) -> None:
        """Initialize Polymarket API clients."""
        # CLOB API client
        self._http_client = httpx.AsyncClient(
            base_url=settings.polymarket_api_url,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )
        
        # Gamma API for market data
        self._gamma_client = httpx.AsyncClient(
            base_url="https://gamma-api.polymarket.com",
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )
        
        # Web3 for Polygon
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.polygon_rpc_url)
        )
        
        logger.info("Polymarket platform initialized")
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._gamma_client:
            await self._gamma_client.aclose()
    
    async def _clob_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to CLOB API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._http_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.POLYMARKET)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"CLOB API error: {e.response.status_code}",
                Platform.POLYMARKET,
                str(e.response.status_code),
            )
    
    async def _gamma_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Any:
        """Make request to Gamma API for market data."""
        if not self._gamma_client:
            raise RuntimeError("Gamma client not initialized")
        
        try:
            response = await self._gamma_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.POLYMARKET)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"Gamma API error: {e.response.status_code}",
                Platform.POLYMARKET,
                str(e.response.status_code),
            )
    
    def _parse_market(self, data: dict) -> Market:
        """Parse Polymarket market data into Market object."""
        # Polymarket uses different structures for events vs markets
        # Events contain multiple markets (outcomes)

        def get_price_from_market(m: dict) -> Optional[Decimal]:
            """Extract price from market data, checking multiple fields."""
            # Try different price fields in order of preference
            for field in ["price", "lastTradePrice", "bestAsk"]:
                val = m.get(field)
                if val is not None and val != "" and val != "0":
                    try:
                        price = Decimal(str(val))
                        if Decimal("0") < price <= Decimal("1"):
                            return price
                    except:
                        pass
            return None

        # Handle both event-level and market-level data
        is_event = "markets" in data

        if is_event:
            # This is an event with multiple markets
            markets = data.get("markets", [])
            yes_market = next((m for m in markets if m.get("outcome") == "Yes"), None)
            no_market = next((m for m in markets if m.get("outcome") == "No"), None)

            yes_price = get_price_from_market(yes_market) if yes_market else None
            no_price = get_price_from_market(no_market) if no_market else None

            # If we have one price but not the other, calculate it
            if yes_price and not no_price:
                no_price = Decimal("1") - yes_price
            elif no_price and not yes_price:
                yes_price = Decimal("1") - no_price

            yes_token = yes_market.get("clobTokenId") if yes_market else None
            no_token = no_market.get("clobTokenId") if no_market else None

            market_id = data.get("conditionId") or data.get("id")

        else:
            # Single market/outcome
            outcome_prices = data.get("outcomePrices", [])
            if outcome_prices and len(outcome_prices) >= 2:
                try:
                    yes_price = Decimal(str(outcome_prices[0]))
                    no_price = Decimal(str(outcome_prices[1]))
                except:
                    yes_price = None
                    no_price = None
            else:
                yes_price = None
                no_price = None

            tokens = data.get("clobTokenIds", [])
            yes_token = tokens[0] if len(tokens) > 0 else None
            no_token = tokens[1] if len(tokens) > 1 else None

            market_id = data.get("conditionId") or data.get("condition_id")
        
        # Volume
        volume = data.get("volume") or data.get("volumeNum") or 0
        liquidity = data.get("liquidity") or data.get("liquidityNum") or 0
        
        return Market(
            platform=Platform.POLYMARKET,
            chain=Chain.POLYGON,
            market_id=market_id,
            event_id=data.get("id") or data.get("slug"),
            title=data.get("title") or data.get("question", ""),
            description=data.get("description"),
            category=data.get("category") or (data.get("tags", [{}])[0].get("label") if data.get("tags") else None),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(volume)),
            liquidity=Decimal(str(liquidity)),
            is_active=data.get("active", True) and not data.get("closed", False),
            close_time=data.get("endDate") or data.get("end_date_iso"),
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
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Gamma API."""
        params = {
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false",
        }
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        
        data = await self._gamma_request("GET", "/events", params=params)
        
        markets = []
        for item in data if isinstance(data, list) else []:
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))
        
        return markets
    
    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets by query."""
        params = {
            "q": query,
            "limit": limit,
        }
        
        # Try Strapi search endpoint
        try:
            data = await self._gamma_request("GET", "/events", params={
                "_q": query,
                "active": "true",
                "_limit": limit,
            })
        except:
            # Fallback to getting all and filtering
            data = await self._gamma_request("GET", "/events", params={
                "active": "true",
                "_limit": 100,
            })
            # Filter by query
            query_lower = query.lower()
            data = [m for m in data if query_lower in m.get("title", "").lower() 
                    or query_lower in m.get("description", "").lower()][:limit]
        
        markets = []
        for item in data if isinstance(data, list) else []:
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))
        
        return markets
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by condition ID or slug."""
        try:
            # Try by condition ID first
            data = await self._gamma_request("GET", f"/events/{market_id}")
            return self._parse_market(data)
        except:
            pass
        
        try:
            # Try by slug
            data = await self._gamma_request("GET", "/events", params={"slug": market_id})
            if data and len(data) > 0:
                return self._parse_market(data[0])
        except:
            pass
        
        return None
    
    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending markets by volume."""
        params = {
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false",
            "active": "true",
        }
        
        data = await self._gamma_request("GET", "/events", params=params)
        
        markets = []
        for item in data if isinstance(data, list) else []:
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))
        
        return markets
    
    # ===================
    # Order Book
    # ===================
    
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
    ) -> OrderBook:
        """Get order book from CLOB API."""
        # Need token ID for orderbook
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.POLYMARKET)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.POLYMARKET)
        
        data = await self._clob_request("GET", f"/book?token_id={token_id}")
        
        bids = []
        asks = []
        
        for bid in data.get("bids", []):
            bids.append((
                Decimal(str(bid.get("price", 0))),
                Decimal(str(bid.get("size", 0))),
            ))
        
        for ask in data.get("asks", []):
            asks.append((
                Decimal(str(ask.get("price", 0))),
                Decimal(str(ask.get("size", 0))),
            ))
        
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
    ) -> Quote:
        """Get a quote for a trade."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.POLYMARKET)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.POLYMARKET)
        
        # Get current price from orderbook
        orderbook = await self.get_orderbook(market_id, outcome)
        
        if side == "buy":
            # Buying - use ask price
            price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price
            input_token = POLYMARKET_CONTRACTS["collateral"]
            output_token = token_id
        else:
            # Selling - use bid price
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id
            output_token = POLYMARKET_CONTRACTS["collateral"]
        
        return Quote(
            platform=Platform.POLYMARKET,
            chain=Chain.POLYGON,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal("0.01"),  # Estimate
            platform_fee=amount * Decimal("0.02"),  # 2% fee
            network_fee_estimate=Decimal("0.01"),  # MATIC
            expires_at=None,
            quote_data={
                "token_id": token_id,
                "condition_id": market_id,
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
        Execute a trade on Polymarket.
        
        Note: Full implementation requires py-clob-client SDK
        with proper order signing. This is a simplified version.
        """
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.POLYMARKET,
            )
        
        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.POLYMARKET)
        
        try:
            # Import the official Polymarket client for order execution
            # This requires py-clob-client package
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
            
            # Initialize CLOB client
            client = ClobClient(
                settings.polymarket_api_url,
                key=private_key.key.hex(),
                chain_id=137,  # Polygon
                signature_type=0,  # EOA
            )
            
            # Set API credentials
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)
            
            token_id = quote.quote_data["token_id"]
            
            # Create market order
            side = BUY if quote.side == "buy" else SELL
            
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=float(quote.input_amount),
                side=side,
            )
            
            signed_order = client.create_market_order(order_args)
            result = client.post_order(signed_order, OrderType.FOK)
            
            tx_hash = result.get("transactionHash") or result.get("orderID", "")
            
            logger.info(
                "Trade executed",
                platform="polymarket",
                market_id=quote.market_id,
                order_id=tx_hash,
            )
            
            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash.startswith("0x") else None,
            )
            
        except ImportError:
            # py-clob-client not installed
            logger.error("py-clob-client not installed for Polymarket trading")
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message="Polymarket SDK not installed. Install with: pip install py-clob-client",
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
polymarket_platform = PolymarketPlatform()
