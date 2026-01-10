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
        logger.info(
            "Kalshi platform initialized",
            api_key_set=bool(self._api_key),
            fee_collection=fee_enabled,
            fee_bps=self._fee_bps if fee_enabled else 0,
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

        data = await self._metadata_request("GET", "/api/v1/markets", params=params)

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
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by ticker."""
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

    # ===================
    # Order Book
    # ===================

    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
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
        expected_output = Decimal(str(data.get("outAmount", 0)))
        if side == "buy":
            expected_output = expected_output / Decimal(10**self.collateral_decimals)

        price_per_token = amount / expected_output if expected_output > 0 else Decimal(0)

        logger.debug(
            "Calculated quote price",
            input_amount=str(amount),
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
            input_amount=amount,
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
            # feeAccount must be a USDC token account (ATA), not a wallet address
            # platformFeeMode=inputMint collects fees in USDC (the input token)
            if self._fee_account and len(self._fee_account) >= 32:
                params["feeAccount"] = self._fee_account
                params["platformFeeBps"] = self._fee_bps
                params["platformFeeMode"] = "inputMint"  # Collect fees in USDC
                logger.debug(
                    "Fee collection enabled",
                    fee_account=self._fee_account[:8] + "...",
                    fee_bps=self._fee_bps,
                    fee_mode="inputMint",
                )

            response = await self._trading_request(
                "GET",
                "/order",
                params=params,
            )

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


# Singleton instance
kalshi_platform = KalshiPlatform()
