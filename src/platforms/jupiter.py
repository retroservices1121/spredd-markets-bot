"""
Jupiter Prediction Markets platform implementation.
Mirrors Polymarket events on Solana via Jupiter (api.jup.ag/prediction/v1).
"""

import asyncio
import base64
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx
from solders.keypair import Keypair
from solders.presigner import Presigner
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.services.signer import SolanaSigner, LegacySolanaSigner

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

# USDC mint on Solana
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class JupiterPlatform(BasePlatform):
    """
    Jupiter Prediction Markets platform.
    Mirrors Polymarket events on Solana via Jupiter's prediction API.
    """

    platform = Platform.JUPITER
    chain = Chain.SOLANA

    name = "Jupiter"
    description = "Polymarket on Solana via Jupiter"
    website = "https://jup.ag"

    collateral_symbol = "USDC"
    collateral_decimals = 6

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._solana_client: Optional[SolanaClient] = None
        self._api_key = settings.jupiter_api_key
        self._base_url = settings.jupiter_api_url.rstrip("/")

    async def initialize(self) -> None:
        """Initialize Jupiter API client."""
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key

        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30),
        )
        self._solana_client = SolanaClient(settings.solana_rpc_url)

        logger.info(
            "Jupiter platform initialized",
            api_key_set=bool(self._api_key),
            base_url=self._base_url,
        )

    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._solana_client:
            await self._solana_client.close()

    # ===================
    # HTTP helpers
    # ===================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def _api_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Any:
        """Make request to Jupiter Prediction API with retry on rate limit."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")

        url = f"{self._base_url}{endpoint}"

        try:
            response = await self._http_client.request(method, url, **kwargs)

            if response.status_code == 429:
                logger.warning("Jupiter rate limited, retrying...")
                raise RateLimitError("Rate limit exceeded", Platform.JUPITER)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            # Extract human-readable message from Jupiter error response
            error_msg = f"API error: {e.response.status_code}"
            try:
                error_body = e.response.json()
                api_message = error_body.get("message", "")
                if api_message:
                    error_msg = api_message
                logger.error("Jupiter API error", status=e.response.status_code, body=error_body)
            except Exception:
                logger.error("Jupiter API error", status=e.response.status_code)
            raise PlatformError(
                error_msg,
                Platform.JUPITER,
                str(e.response.status_code),
            )

    # ===================
    # Market parsing
    # ===================

    def _parse_market(
        self,
        data: dict,
        parent_event_id: Optional[str] = None,
        event_title: Optional[str] = None,
    ) -> Market:
        """Parse Jupiter market data into Market object.

        Jupiter prices are in micro-USD (divide by 1_000_000).
        When event_title is provided and differs from the market-level title,
        the event title becomes the market title and the market-level title
        becomes the outcome_name (e.g. "Gavin Newsom" under "Democratic Nominee 2028").
        """
        market_id = data.get("marketId", "")
        event_id = data.get("event") or data.get("eventId") or parent_event_id

        metadata = data.get("metadata", {})
        market_title = metadata.get("title") or data.get("title", "")

        # Use event title as the main title for multi-outcome sub-markets
        outcome_name = None
        if event_title and market_title and event_title != market_title:
            title = event_title
            outcome_name = market_title
        else:
            title = market_title

        pricing = data.get("pricing", {})
        yes_price_raw = pricing.get("buyYesPriceUsd", 0)
        no_price_raw = pricing.get("buyNoPriceUsd", 0)
        volume_raw = pricing.get("volumeUsd", 0)

        # Convert from micro-USD
        yes_price = Decimal(str(yes_price_raw)) / Decimal("1000000") if yes_price_raw else None
        no_price = Decimal(str(no_price_raw)) / Decimal("1000000") if no_price_raw else None
        volume = Decimal(str(volume_raw)) / Decimal("1000000") if volume_raw else None

        # Close time — unix timestamp to ISO
        close_time = None
        close_ts = data.get("closeTime")
        if close_ts:
            try:
                close_time = datetime.fromtimestamp(int(close_ts), tz=timezone.utc).isoformat()
            except (ValueError, TypeError, OSError):
                close_time = str(close_ts)

        is_active = data.get("status", "").lower() == "open"

        return Market(
            platform=Platform.JUPITER,
            chain=Chain.SOLANA,
            market_id=market_id,
            event_id=event_id,
            title=title,
            outcome_name=outcome_name,
            description=metadata.get("description"),
            category=metadata.get("category"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume,
            liquidity=None,
            is_active=is_active,
            close_time=close_time,
            yes_token=data.get("yesMint"),
            no_token=data.get("noMint"),
            raw_data=data,
        )

    # ===================
    # Market Discovery
    # ===================

    _markets_cache: list[Market] = []
    _markets_cache_time: float = 0
    CACHE_TTL = 300  # 5 minutes

    async def _fetch_all_markets(self) -> list[Market]:
        """Fetch all events from Jupiter and flatten into markets."""
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self.CACHE_TTL:
            return self._markets_cache

        all_markets: list[Market] = []

        try:
            data = await self._api_request(
                "GET",
                "/events",
                params={
                    "provider": "polymarket",
                    "includeMarkets": "true",
                    "sortBy": "volume",
                    "sortDirection": "desc",
                    "start": "0",
                    "end": "20",
                },
            )

            events = data if isinstance(data, list) else data.get("data", data.get("events", []))

            for event in events:
                event_id = event.get("eventId") or event.get("id", "")
                event_meta = event.get("metadata", {})
                event_title = event_meta.get("title") or ""
                markets_data = event.get("markets", [])

                for market_data in markets_data:
                    try:
                        m = self._parse_market(
                            market_data,
                            parent_event_id=event_id,
                            event_title=event_title,
                        )
                        all_markets.append(m)
                    except Exception as e:
                        logger.warning("Failed to parse Jupiter market", error=str(e))

        except Exception as e:
            logger.error("Failed to fetch Jupiter events", error=str(e))
            # Return stale cache if available
            if self._markets_cache:
                return self._markets_cache
            raise

        # Detect multi-outcome events
        event_groups: dict[str, list[Market]] = defaultdict(list)
        for m in all_markets:
            if m.event_id:
                event_groups[m.event_id].append(m)

        for event_id, group in event_groups.items():
            if len(group) > 1:
                for m in group:
                    m.is_multi_outcome = True
                    m.related_market_count = len(group)

        logger.info("Fetched Jupiter markets", total=len(all_markets))

        self._markets_cache = all_markets
        self._markets_cache_time = now

        return all_markets

    async def get_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets, deduplicated by event.

        For multi-outcome events, returns the highest-volume sub-market
        as the representative so the browse page shows one entry per event.
        """
        all_markets = await self._fetch_all_markets()
        if active_only:
            all_markets = [m for m in all_markets if m.is_active]

        # Deduplicate: keep highest-volume market per event
        seen_events: dict[str, Market] = {}
        for m in all_markets:
            key = m.event_id or m.market_id
            existing = seen_events.get(key)
            if not existing or (m.volume_24h or 0) > (existing.volume_24h or 0):
                seen_events[key] = m

        unique = list(seen_events.values())
        return unique[offset:offset + limit]

    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets via Jupiter search endpoint, fallback to client-side."""
        try:
            data = await self._api_request(
                "GET",
                "/events/search",
                params={"query": query, "limit": limit},
            )

            events = data if isinstance(data, list) else data.get("data", data.get("events", []))
            results: list[Market] = []
            for event in events:
                event_id = event.get("eventId") or event.get("id", "")
                event_meta = event.get("metadata", {})
                event_title = event_meta.get("title") or ""
                for market_data in event.get("markets", []):
                    try:
                        results.append(self._parse_market(
                            market_data,
                            parent_event_id=event_id,
                            event_title=event_title,
                        ))
                    except Exception:
                        pass
            return results[:limit]

        except Exception:
            # Fallback to client-side filtering
            all_markets = await self._fetch_all_markets()
            query_lower = query.lower()
            return [
                m for m in all_markets
                if query_lower in m.title.lower()
                or (m.description and query_lower in m.description.lower())
            ][:limit]

    async def get_market(
        self,
        market_id: str,
        search_title: Optional[str] = None,
        include_closed: bool = False,
    ) -> Optional[Market]:
        """Get a specific market by ID."""
        # Try cache first
        try:
            all_markets = await self._fetch_all_markets()
            for m in all_markets:
                if m.market_id == market_id:
                    return m
        except Exception:
            pass

        # Fallback: fetch directly
        try:
            data = await self._api_request("GET", f"/markets/{market_id}")
            return self._parse_market(data)
        except PlatformError:
            return None

    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending markets (volume-sorted)."""
        markets = await self.get_markets(limit=limit, active_only=True)
        return markets

    async def get_related_markets(self, event_id: str) -> list[Market]:
        """Get all markets in the same event."""
        try:
            all_markets = await self._fetch_all_markets()
            related = [m for m in all_markets if m.event_id == event_id]
            if len(related) <= 1:
                return []
            related.sort(key=lambda m: m.yes_price or Decimal(0), reverse=True)
            return related
        except Exception as e:
            logger.warning("Failed to get related Jupiter markets", error=str(e))
            return []

    # ===================
    # Categories
    # ===================

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories."""
        return [
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "economics", "label": "Economics", "emoji": "📊"},
            {"id": "culture", "label": "Culture", "emoji": "🎭"},
            {"id": "tech", "label": "Tech", "emoji": "💻"},
        ]

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 25,
    ) -> list[Market]:
        """Get markets filtered by category via Jupiter events API."""
        try:
            data = await self._api_request(
                "GET",
                "/events",
                params={
                    "provider": "polymarket",
                    "includeMarkets": "true",
                    "sortBy": "volume",
                    "sortDirection": "desc",
                    "category": category.lower(),
                    "start": "0",
                    "end": "20",
                },
            )

            events = data if isinstance(data, list) else data.get("data", data.get("events", []))

            all_markets: list[Market] = []
            for event in events:
                event_id = event.get("eventId") or event.get("id", "")
                event_meta = event.get("metadata", {})
                event_title = event_meta.get("title") or ""
                for market_data in event.get("markets", []):
                    try:
                        m = self._parse_market(
                            market_data,
                            parent_event_id=event_id,
                            event_title=event_title,
                        )
                        all_markets.append(m)
                    except Exception:
                        pass

            # Detect multi-outcome
            event_groups: dict[str, list[Market]] = defaultdict(list)
            for m in all_markets:
                if m.event_id:
                    event_groups[m.event_id].append(m)
            for eid, group in event_groups.items():
                if len(group) > 1:
                    for m in group:
                        m.is_multi_outcome = True
                        m.related_market_count = len(group)

            # Deduplicate by event — keep highest-volume representative
            seen: dict[str, Market] = {}
            for m in all_markets:
                if m.is_active:
                    key = m.event_id or m.market_id
                    existing = seen.get(key)
                    if not existing or (m.volume_24h or 0) > (existing.volume_24h or 0):
                        seen[key] = m

            return list(seen.values())[:limit]

        except Exception as e:
            logger.error("Failed to fetch Jupiter category markets",
                         category=category, error=str(e))
            raise

    # ===================
    # Order Book
    # ===================

    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        slug: str = None,
    ) -> OrderBook:
        """Get order book for a market."""
        data = await self._api_request("GET", f"/orderbook/{market_id}")

        bids: list[tuple[Decimal, Decimal]] = []
        asks: list[tuple[Decimal, Decimal]] = []

        for entry in data.get("bids", []):
            price = Decimal(str(entry.get("price", 0)))
            size = Decimal(str(entry.get("size", 0)))
            bids.append((price, size))

        for entry in data.get("asks", []):
            price = Decimal(str(entry.get("price", 0)))
            size = Decimal(str(entry.get("size", 0)))
            asks.append((price, size))

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
        """Get a quote by looking up market pricing."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.JUPITER)

        # Determine price
        if outcome == Outcome.YES:
            price = market.yes_price or Decimal("0.5")
            output_token = market.yes_token or ""
        else:
            price = market.no_price or Decimal("0.5")
            output_token = market.no_token or ""

        # Calculate expected output
        # amount in USDC, price per share = price, shares = amount / price
        expected_output = amount / price if price > 0 else Decimal(0)

        return Quote(
            platform=Platform.JUPITER,
            chain=Chain.SOLANA,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=USDC_MINT,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal(0),
            platform_fee=Decimal(0),
            network_fee_estimate=Decimal("0.001"),  # ~0.001 SOL
            expires_at=None,
            quote_data={
                "market_id": market_id,
                "outcome": outcome.value,
                "side": side,
            },
        )

    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """Execute a trade via Jupiter Prediction API.

        POST /orders → returns unsigned Solana transaction → sign → submit.
        Accepts either a Solana Keypair (legacy) or SolanaSigner (Privy).
        """
        # Unwrap signer types
        if isinstance(private_key, SolanaSigner):
            if isinstance(private_key, LegacySolanaSigner):
                private_key = private_key.keypair
            else:
                # Privy signer — use async signing path
                return await self._execute_trade_with_signer(quote, private_key)

        if not isinstance(private_key, Keypair):
            raise PlatformError(
                "Invalid private key type, expected Solana Keypair or SolanaSigner",
                Platform.JUPITER,
            )

        try:
            # Convert amount to USDC smallest units (6 decimals)
            deposit_amount = int(quote.input_amount * Decimal(10**self.collateral_decimals))

            is_yes = quote.outcome == Outcome.YES
            is_buy = quote.side == "buy"

            order_payload = {
                "ownerPubkey": str(private_key.pubkey()),
                "marketId": quote.market_id,
                "isYes": is_yes,
                "isBuy": is_buy,
                "depositAmount": str(deposit_amount),
                "depositMint": USDC_MINT,
            }

            logger.info("Jupiter order request", payload=order_payload)

            response = await self._api_request(
                "POST",
                "/orders",
                json=order_payload,
            )

            # Response contains base64-encoded transaction
            tx_b64 = response.get("transaction")
            if not tx_b64:
                raise PlatformError("No transaction in order response", Platform.JUPITER)

            logger.info("Jupiter order created, signing transaction",
                        order_id=response.get("externalOrderId"))

            # Decode, sign, and submit
            tx_data = base64.b64decode(tx_b64)
            tx = VersionedTransaction.from_bytes(tx_data)

            # The transaction may be partially signed by Jupiter's co-signer.
            # Preserve existing signatures and add the user's.
            signers = [private_key]
            num_required = tx.message.header.num_required_signatures
            account_keys = tx.message.account_keys

            for i in range(num_required):
                pubkey = account_keys[i]
                if pubkey == private_key.pubkey():
                    continue  # We'll sign this ourselves
                existing_sig = tx.signatures[i]
                if existing_sig != Signature.default():
                    signers.append(Presigner(pubkey, existing_sig))

            signed_tx = VersionedTransaction(tx.message, signers)

            # Submit to Solana
            if not self._solana_client:
                raise RuntimeError("Solana client not initialized")

            logger.info("Submitting signed transaction to Solana")

            result = await self._solana_client.send_transaction(
                signed_tx,
                opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed),
            )

            tx_hash = str(result.value)

            logger.info(
                "Jupiter trade executed",
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

        except PlatformError:
            raise  # Let API errors (geo-block, minimum, etc.) propagate clearly
        except Exception as e:
            error_str = str(e)
            logger.error("Jupiter trade execution failed",
                         error=error_str, error_type=type(e).__name__)
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=f"{type(e).__name__}: {error_str}",
                explorer_url=None,
            )

    async def _execute_trade_with_signer(
        self,
        quote: Quote,
        signer: SolanaSigner,
    ) -> TradeResult:
        """Execute a trade using a SolanaSigner (Privy wallet)."""
        try:
            deposit_amount = int(quote.input_amount * Decimal(10**self.collateral_decimals))
            is_yes = quote.outcome == Outcome.YES
            is_buy = quote.side == "buy"

            order_payload = {
                "ownerPubkey": signer.public_key,
                "marketId": quote.market_id,
                "isYes": is_yes,
                "isBuy": is_buy,
                "depositAmount": str(deposit_amount),
                "depositMint": USDC_MINT,
            }

            response = await self._api_request("POST", "/orders", json=order_payload)
            tx_b64 = response.get("transaction")
            if not tx_b64:
                raise PlatformError("No transaction in order response", Platform.JUPITER)

            # Sign via signer and submit
            tx_data = base64.b64decode(tx_b64)
            signed_tx_bytes = await signer.sign_transaction(tx_data)
            signed_tx = VersionedTransaction.from_bytes(signed_tx_bytes)

            if not self._solana_client:
                raise RuntimeError("Solana client not initialized")

            result = await self._solana_client.send_transaction(
                signed_tx,
                opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed),
            )
            tx_hash = str(result.value)

            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash),
            )

        except PlatformError:
            raise
        except Exception as e:
            error_str = str(e)
            logger.error("Jupiter trade execution failed (signer)", error=error_str)
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=f"{type(e).__name__}: {error_str}",
                explorer_url=None,
            )

    # ===================
    # Sell / Claim
    # ===================

    async def _sign_and_submit(self, tx_b64: str, private_key: Keypair) -> str:
        """Decode a base64 transaction, sign it, and submit to Solana.

        Preserves any existing signatures (e.g. Jupiter co-signer) and adds
        the user's signature.  Returns the transaction hash.
        """
        tx_data = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(tx_data)

        signers = [private_key]
        num_required = tx.message.header.num_required_signatures
        account_keys = tx.message.account_keys

        for i in range(num_required):
            pubkey = account_keys[i]
            if pubkey == private_key.pubkey():
                continue
            existing_sig = tx.signatures[i]
            if existing_sig != Signature.default():
                signers.append(Presigner(pubkey, existing_sig))

        signed_tx = VersionedTransaction(tx.message, signers)

        if not self._solana_client:
            raise RuntimeError("Solana client not initialized")

        result = await self._solana_client.send_transaction(
            signed_tx,
            opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed),
        )
        return str(result.value)

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
        token_id: str = None,
    ) -> RedemptionResult:
        """Claim winnings from a resolved Jupiter market.

        POST /positions/{positionPubkey}/claim → unsigned tx → sign + submit.
        """
        # Unwrap LegacySolanaSigner
        if isinstance(private_key, LegacySolanaSigner):
            private_key = private_key.keypair

        if not isinstance(private_key, Keypair):
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message="Invalid private key type, expected Solana Keypair or SolanaSigner",
                explorer_url=None,
            )

        try:
            # For Jupiter, the position pubkey is typically the market_id
            # or derived from the user's pubkey + market. The caller passes
            # the position identifier via market_id.
            response = await self._api_request(
                "POST",
                f"/positions/{market_id}/claim",
            )

            tx_b64 = response.get("transaction")
            if not tx_b64:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="No transaction in claim response",
                    explorer_url=None,
                )

            tx_hash = await self._sign_and_submit(tx_b64, private_key)

            logger.info("Jupiter claim executed", market_id=market_id, tx_hash=tx_hash)

            return RedemptionResult(
                success=True,
                tx_hash=tx_hash,
                amount_redeemed=token_amount,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash),
            )

        except Exception as e:
            logger.error("Jupiter claim failed", error=str(e), market_id=market_id)
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message=str(e),
                explorer_url=None,
            )

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """Check if a Jupiter market has resolved."""
        try:
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            status = market.raw_data.get("status", "").lower()
            is_resolved = status in ("resolved", "settled", "closed")

            if not is_resolved:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            result = market.raw_data.get("result")
            winning_outcome = None
            if result:
                result_lower = str(result).lower()
                if result_lower in ("yes", "1", "true"):
                    winning_outcome = "yes"
                elif result_lower in ("no", "0", "false"):
                    winning_outcome = "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning_outcome,
                resolution_time=market.raw_data.get("resolvedAt"),
            )

        except Exception as e:
            logger.error("Failed to check Jupiter market resolution", error=str(e))
            return MarketResolution(
                is_resolved=False,
                winning_outcome=None,
                resolution_time=None,
            )


# Singleton instance
jupiter_platform = JupiterPlatform()
