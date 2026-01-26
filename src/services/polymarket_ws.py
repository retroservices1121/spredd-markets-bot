"""
Polymarket CLOB WebSocket client for real-time market data.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market
for live orderbook updates, price changes, and trade notifications.
"""

import asyncio
import time
from decimal import Decimal
from typing import Any, Optional

from src.services.websocket_manager import (
    BaseWebSocketClient,
    PriceCache,
    PriceUpdate,
    OrderBookUpdate,
    price_cache,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Polymarket WebSocket endpoints
POLYMARKET_WS_MARKET = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLYMARKET_WS_USER = "wss://ws-subscriptions-clob.polymarket.com/ws/user"


class PolymarketWebSocketClient(BaseWebSocketClient):
    """
    Polymarket CLOB WebSocket client for real-time market data.

    Handles:
    - book: Full orderbook snapshots
    - price_change: Incremental price updates with best bid/ask
    - last_trade_price: Trade execution notifications
    - tick_size_change: Tick size updates at price extremes
    """

    def __init__(
        self,
        price_cache: PriceCache,
        ping_interval: float = 10.0,  # Polymarket requires ping every 10s
    ):
        super().__init__(
            url=POLYMARKET_WS_MARKET,
            price_cache=price_cache,
            ping_interval=ping_interval,
        )
        # Track market_id -> token_id mapping for reverse lookups
        self._token_to_market: dict[str, str] = {}
        # Track condition_id -> token_ids for multi-outcome markets
        self._condition_tokens: dict[str, list[str]] = {}

    @property
    def platform(self) -> str:
        return "polymarket"

    def register_token(self, market_id: str, token_id: str, condition_id: Optional[str] = None) -> None:
        """Register a token with its market mapping."""
        self._token_to_market[token_id] = market_id
        if condition_id:
            if condition_id not in self._condition_tokens:
                self._condition_tokens[condition_id] = []
            if token_id not in self._condition_tokens[condition_id]:
                self._condition_tokens[condition_id].append(token_id)

    async def _build_subscribe_message(self, token_ids: list[str]) -> dict:
        """Build Polymarket subscription message."""
        return {
            "assets_ids": token_ids,
            "type": "market",
        }

    async def _build_unsubscribe_message(self, token_ids: list[str]) -> dict:
        """Build Polymarket unsubscription message."""
        return {
            "assets_ids": token_ids,
            "type": "market",
            "action": "unsubscribe",
        }

    async def _handle_message(self, message: dict) -> None:
        """Handle incoming Polymarket WebSocket messages."""
        event_type = message.get("event_type") or message.get("type")

        if event_type == "book":
            await self._handle_book(message)
        elif event_type == "price_change":
            await self._handle_price_change(message)
        elif event_type == "last_trade_price":
            await self._handle_last_trade(message)
        elif event_type == "tick_size_change":
            await self._handle_tick_size_change(message)
        elif event_type == "best_bid_ask":
            await self._handle_best_bid_ask(message)
        elif event_type in ("subscribed", "unsubscribed", "connected"):
            logger.debug("WebSocket event", platform=self.platform, event=event_type)
        else:
            logger.debug(
                "Unknown message type",
                platform=self.platform,
                event_type=event_type,
                keys=list(message.keys()),
            )

    async def _handle_book(self, message: dict) -> None:
        """
        Handle full orderbook snapshot.

        Example message:
        {
            "event_type": "book",
            "asset_id": "token_id",
            "market": "condition_id",
            "timestamp": 1234567890123,
            "bids": [{"price": "0.50", "size": "100"}],
            "asks": [{"price": "0.52", "size": "50"}]
        }
        """
        token_id = message.get("asset_id")
        if not token_id:
            return

        market_id = self._token_to_market.get(token_id, message.get("market", ""))

        # Parse bids and asks
        bids = []
        asks = []

        for bid in message.get("bids", []):
            price = Decimal(str(bid.get("price", 0)))
            size = Decimal(str(bid.get("size", 0)))
            if price > 0 and size > 0:
                bids.append((price, size))

        for ask in message.get("asks", []):
            price = Decimal(str(ask.get("price", 0)))
            size = Decimal(str(ask.get("size", 0)))
            if price > 0 and size > 0:
                asks.append((price, size))

        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])

        # Update orderbook cache
        orderbook_update = OrderBookUpdate(
            platform=self.platform,
            market_id=market_id,
            token_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=message.get("timestamp", time.time() * 1000) / 1000,
        )
        await self.price_cache.update_orderbook(orderbook_update)

        # Also update price cache with best bid/ask
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None

        if best_bid is not None or best_ask is not None:
            price_update = PriceUpdate(
                platform=self.platform,
                market_id=market_id,
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                timestamp=orderbook_update.timestamp,
            )
            await self.price_cache.update_price(price_update)

        logger.debug(
            "Orderbook updated",
            platform=self.platform,
            token_id=token_id[:16] + "...",
            bids=len(bids),
            asks=len(asks),
            best_bid=str(best_bid) if best_bid else None,
            best_ask=str(best_ask) if best_ask else None,
        )

    async def _handle_price_change(self, message: dict) -> None:
        """
        Handle incremental price change updates.

        Example message:
        {
            "event_type": "price_change",
            "changes": [{
                "asset_id": "token_id",
                "price": "0.51",
                "side": "BUY",
                "size": "50",
                "best_bid": "0.50",
                "best_ask": "0.52"
            }]
        }
        """
        changes = message.get("changes", [])
        if not changes and "asset_id" in message:
            # Single change format
            changes = [message]

        for change in changes:
            token_id = change.get("asset_id")
            if not token_id:
                continue

            market_id = self._token_to_market.get(token_id, "")

            best_bid = change.get("best_bid")
            best_ask = change.get("best_ask")

            price_update = PriceUpdate(
                platform=self.platform,
                market_id=market_id,
                token_id=token_id,
                best_bid=Decimal(str(best_bid)) if best_bid else None,
                best_ask=Decimal(str(best_ask)) if best_ask else None,
                timestamp=message.get("timestamp", time.time() * 1000) / 1000,
            )
            await self.price_cache.update_price(price_update)

            logger.debug(
                "Price change",
                platform=self.platform,
                token_id=token_id[:16] + "...",
                best_bid=best_bid,
                best_ask=best_ask,
            )

    async def _handle_last_trade(self, message: dict) -> None:
        """
        Handle trade execution notifications.

        Example message:
        {
            "event_type": "last_trade_price",
            "asset_id": "token_id",
            "price": "0.51",
            "side": "BUY",
            "size": "25",
            "timestamp": 1234567890123
        }
        """
        token_id = message.get("asset_id")
        if not token_id:
            return

        market_id = self._token_to_market.get(token_id, "")

        price = message.get("price")
        size = message.get("size")
        side = message.get("side")

        price_update = PriceUpdate(
            platform=self.platform,
            market_id=market_id,
            token_id=token_id,
            last_trade_price=Decimal(str(price)) if price else None,
            last_trade_size=Decimal(str(size)) if size else None,
            last_trade_side=side,
            timestamp=message.get("timestamp", time.time() * 1000) / 1000,
        )
        await self.price_cache.update_price(price_update)

        logger.debug(
            "Trade executed",
            platform=self.platform,
            token_id=token_id[:16] + "...",
            price=price,
            size=size,
            side=side,
        )

    async def _handle_tick_size_change(self, message: dict) -> None:
        """Handle tick size change notifications (for prices near 0 or 1)."""
        logger.debug(
            "Tick size change",
            platform=self.platform,
            old_tick=message.get("old_tick_size"),
            new_tick=message.get("new_tick_size"),
        )

    async def _handle_best_bid_ask(self, message: dict) -> None:
        """
        Handle best bid/ask updates (feature-flagged).

        Example message:
        {
            "event_type": "best_bid_ask",
            "asset_id": "token_id",
            "best_bid": "0.50",
            "best_ask": "0.52",
            "spread": "0.02"
        }
        """
        token_id = message.get("asset_id")
        if not token_id:
            return

        market_id = self._token_to_market.get(token_id, "")

        price_update = PriceUpdate(
            platform=self.platform,
            market_id=market_id,
            token_id=token_id,
            best_bid=Decimal(str(message["best_bid"])) if message.get("best_bid") else None,
            best_ask=Decimal(str(message["best_ask"])) if message.get("best_ask") else None,
            timestamp=message.get("timestamp", time.time() * 1000) / 1000,
        )
        await self.price_cache.update_price(price_update)


class PolymarketWebSocketManager:
    """
    High-level manager for Polymarket WebSocket connections.

    Handles:
    - Automatic connection management
    - Market subscription lifecycle
    - Integration with trading platform
    """

    def __init__(self):
        self._client: Optional[PolymarketWebSocketClient] = None
        self._started = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def start(self) -> None:
        """Start WebSocket connection."""
        if self._started:
            return

        self._client = PolymarketWebSocketClient(price_cache=price_cache)
        await self._client.connect()
        self._started = True

        logger.info("Polymarket WebSocket manager started")

    async def stop(self) -> None:
        """Stop WebSocket connection."""
        if not self._started:
            return

        if self._client:
            await self._client.disconnect()
            self._client = None

        self._started = False
        logger.info("Polymarket WebSocket manager stopped")

    async def subscribe_market(
        self,
        market_id: str,
        yes_token: str,
        no_token: Optional[str] = None,
        condition_id: Optional[str] = None,
    ) -> None:
        """
        Subscribe to real-time updates for a market.

        Args:
            market_id: Market identifier
            yes_token: YES outcome token ID
            no_token: NO outcome token ID (optional for binary markets)
            condition_id: Condition ID for multi-outcome markets
        """
        if not self._client:
            await self.start()

        # Register token mappings
        self._client.register_token(market_id, yes_token, condition_id)
        if no_token:
            self._client.register_token(market_id, no_token, condition_id)

        # Subscribe to tokens
        tokens = [yes_token]
        if no_token:
            tokens.append(no_token)

        await self._client.subscribe(tokens)

        logger.debug(
            "Subscribed to market",
            market_id=market_id[:20] + "...",
            tokens=len(tokens),
        )

    async def unsubscribe_market(
        self,
        yes_token: str,
        no_token: Optional[str] = None,
    ) -> None:
        """Unsubscribe from a market's updates."""
        if not self._client:
            return

        tokens = [yes_token]
        if no_token:
            tokens.append(no_token)

        await self._client.unsubscribe(tokens)

    async def get_live_price(
        self,
        token_id: str,
    ) -> Optional[PriceUpdate]:
        """Get cached live price for a token."""
        return await price_cache.get_price("polymarket", token_id)

    async def get_live_orderbook(
        self,
        token_id: str,
    ) -> Optional[OrderBookUpdate]:
        """Get cached live orderbook for a token."""
        return await price_cache.get_orderbook("polymarket", token_id)


# Global manager instance
polymarket_ws_manager = PolymarketWebSocketManager()


async def start_polymarket_websocket() -> None:
    """Start the Polymarket WebSocket connection (call on app startup)."""
    await polymarket_ws_manager.start()


async def stop_polymarket_websocket() -> None:
    """Stop the Polymarket WebSocket connection (call on app shutdown)."""
    await polymarket_ws_manager.stop()
