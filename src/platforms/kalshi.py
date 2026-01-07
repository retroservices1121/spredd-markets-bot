"""
Kalshi platform implementation using DFlow API.
Trades Kalshi prediction markets on Solana.
"""

from decimal import Decimal
from typing import Any, Optional
from datetime import datetime

import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.commitment import Confirmed
import base64

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
        self._builder_code = settings.kalshi_builder_code
    
    async def initialize(self) -> None:
        """Initialize DFlow API client."""
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
        )
        
        self._solana_client = SolanaClient(settings.solana_rpc_url)
        
        logger.info("Kalshi platform initialized")
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._solana_client:
            await self._solana_client.close()
    
    async def _metadata_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to DFlow metadata API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        url = f"{settings.dflow_metadata_url}{endpoint}"
        
        try:
            response = await self._http_client.request(method, url, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.KALSHI)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.KALSHI,
                str(e.response.status_code),
            )
    
    async def _trading_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to DFlow trading API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        url = f"{settings.dflow_api_base_url}{endpoint}"
        
        try:
            response = await self._http_client.request(method, url, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.KALSHI)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.KALSHI,
                str(e.response.status_code),
            )
    
    def _parse_market(self, data: dict) -> Market:
        """Parse DFlow market data into Market object."""
        # Extract pricing
        yes_price = None
        no_price = None
        
        if "yesAsk" in data and data["yesAsk"]:
            yes_price = Decimal(str(data["yesAsk"])) / 100
        if "noAsk" in data and data["noAsk"]:
            no_price = Decimal(str(data["noAsk"])) / 100
        
        # Extract tokens
        yes_token = data.get("yesTokenMint") or data.get("yes_token_mint")
        no_token = data.get("noTokenMint") or data.get("no_token_mint")
        
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
            volume_24h=Decimal(str(data.get("volume24h", 0))) if data.get("volume24h") else None,
            liquidity=Decimal(str(data.get("openInterest", 0))) if data.get("openInterest") else None,
            is_active=data.get("status") == "active" or data.get("result") is None,
            close_time=data.get("closeTime") or data.get("close_time"),
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
        """Get list of markets from DFlow."""
        params = {
            "limit": limit,
        }
        if active_only:
            params["status"] = "active"
        
        data = await self._metadata_request("GET", "/v1/markets", params=params)
        
        markets = []
        for item in data.get("markets", data.get("data", [])):
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
        
        data = await self._metadata_request("GET", "/v1/markets/search", params=params)
        
        markets = []
        for item in data.get("markets", data.get("data", [])):
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))
        
        return markets
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ticker."""
        try:
            data = await self._metadata_request("GET", f"/v1/markets/{market_id}")
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
        
        data = await self._metadata_request("GET", "/v1/markets", params=params)
        
        markets = []
        for item in data.get("markets", data.get("data", [])):
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
        """Get order book for a market."""
        data = await self._metadata_request("GET", f"/v1/markets/{market_id}/orderbook")
        
        orderbook_data = data.get("orderbook", data)
        
        bids = []
        asks = []
        
        side_key = "yes" if outcome == Outcome.YES else "no"
        
        for bid in orderbook_data.get(f"{side_key}Bids", []):
            bids.append((
                Decimal(str(bid["price"])) / 100,
                Decimal(str(bid["quantity"])),
            ))
        
        for ask in orderbook_data.get(f"{side_key}Asks", []):
            asks.append((
                Decimal(str(ask["price"])) / 100,
                Decimal(str(ask["quantity"])),
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
        """Get a quote for a trade via DFlow."""
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
        
        # USDC on Solana
        input_token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        
        # Convert amount to smallest unit (USDC has 6 decimals)
        amount_raw = int(amount * Decimal(10**self.collateral_decimals))
        
        # Build quote request
        params = {
            "inputMint": input_token if side == "buy" else output_token,
            "outputMint": output_token if side == "buy" else input_token,
            "amount": str(amount_raw),
            "slippageBps": 100,  # 1%
        }
        
        if self._builder_code:
            params["platformFeeBps"] = 50  # 0.5% to builder
        
        data = await self._trading_request("GET", "/v1/order", params=params)
        
        # Parse quote response
        expected_output = Decimal(str(data.get("outAmount", 0)))
        if side == "buy":
            expected_output = expected_output / Decimal(10**self.collateral_decimals)
        
        price_per_token = amount / expected_output if expected_output > 0 else Decimal(0)
        
        return Quote(
            platform=Platform.KALSHI,
            chain=Chain.SOLANA,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token if side == "buy" else output_token,
            input_amount=amount,
            output_token=output_token if side == "buy" else input_token,
            expected_output=expected_output,
            price_per_token=price_per_token,
            price_impact=Decimal(str(data.get("priceImpactPct", 0))),
            platform_fee=Decimal(str(data.get("platformFee", 0))) / Decimal(10**6),
            network_fee_estimate=Decimal("0.001"),  # ~0.001 SOL
            expires_at=None,
            quote_data=data,
        )
    
    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """Execute a trade using the DFlow swap endpoint."""
        if not isinstance(private_key, Keypair):
            raise PlatformError(
                "Invalid private key type, expected Solana Keypair",
                Platform.KALSHI,
            )
        
        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.KALSHI)
        
        try:
            # Get swap transaction from DFlow
            swap_data = {
                "userPublicKey": str(private_key.pubkey()),
                "quoteResponse": quote.quote_data,
            }
            
            if self._builder_code:
                swap_data["feeAccount"] = self._builder_code
            
            response = await self._trading_request(
                "POST",
                "/v1/swap",
                json=swap_data,
            )
            
            # Decode and sign transaction
            tx_data = base64.b64decode(response["swapTransaction"])
            tx = VersionedTransaction.from_bytes(tx_data)
            
            # Sign with user's keypair
            tx.sign([private_key])
            
            # Submit to Solana
            if not self._solana_client:
                raise RuntimeError("Solana client not initialized")
            
            result = await self._solana_client.send_transaction(
                tx,
                opts={"skip_preflight": False, "preflight_commitment": Confirmed},
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


# Singleton instance
kalshi_platform = KalshiPlatform()
