"""
WebSocket manager for real-time market data streaming.
Supports multiple prediction market platforms with auto-reconnect and price caching.
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional
from collections import defaultdict

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from src.utils.logging import get_logger

logger = get_logger(__name__)


class ConnectionState(str, Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class PriceUpdate:
    """Real-time price update from WebSocket."""
    platform: str
    market_id: str
    token_id: str
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    last_trade_price: Optional[Decimal] = None
    last_trade_size: Optional[Decimal] = None
    last_trade_side: Optional[str] = None  # "BUY" or "SELL"
    timestamp: float = field(default_factory=time.time)


@dataclass
class OrderBookUpdate:
    """Order book update from WebSocket."""
    platform: str
    market_id: str
    token_id: str
    bids: list[tuple[Decimal, Decimal]]  # (price, size)
    asks: list[tuple[Decimal, Decimal]]  # (price, size)
    timestamp: float = field(default_factory=time.time)


class PriceCache:
    """Thread-safe cache for real-time prices with TTL."""

    def __init__(self, ttl_seconds: float = 60.0):
        self._cache: dict[str, PriceUpdate] = {}
        self._orderbooks: dict[str, OrderBookUpdate] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def _cache_key(self, platform: str, token_id: str) -> str:
        return f"{platform}:{token_id}"

    async def update_price(self, update: PriceUpdate) -> None:
        """Update cached price and notify subscribers."""
        key = self._cache_key(update.platform, update.token_id)
        async with self._lock:
            existing = self._cache.get(key)
            if existing:
                # Merge updates - only overwrite non-None fields
                if update.best_bid is not None:
                    existing.best_bid = update.best_bid
                if update.best_ask is not None:
                    existing.best_ask = update.best_ask
                if update.last_trade_price is not None:
                    existing.last_trade_price = update.last_trade_price
                    existing.last_trade_size = update.last_trade_size
                    existing.last_trade_side = update.last_trade_side
                existing.timestamp = update.timestamp
            else:
                self._cache[key] = update

        # Notify subscribers
        await self._notify_subscribers(key, self._cache.get(key))

    async def update_orderbook(self, update: OrderBookUpdate) -> None:
        """Update cached orderbook."""
        key = self._cache_key(update.platform, update.token_id)
        async with self._lock:
            self._orderbooks[key] = update

    async def get_price(self, platform: str, token_id: str) -> Optional[PriceUpdate]:
        """Get cached price if not expired."""
        key = self._cache_key(platform, token_id)
        async with self._lock:
            update = self._cache.get(key)
            if update and (time.time() - update.timestamp) < self._ttl:
                return update
            return None

    async def get_orderbook(self, platform: str, token_id: str) -> Optional[OrderBookUpdate]:
        """Get cached orderbook if not expired."""
        key = self._cache_key(platform, token_id)
        async with self._lock:
            update = self._orderbooks.get(key)
            if update and (time.time() - update.timestamp) < self._ttl:
                return update
            return None

    def subscribe(self, platform: str, token_id: str, callback: Callable) -> None:
        """Subscribe to price updates for a token."""
        key = self._cache_key(platform, token_id)
        self._subscribers[key].append(callback)

    def unsubscribe(self, platform: str, token_id: str, callback: Callable) -> None:
        """Unsubscribe from price updates."""
        key = self._cache_key(platform, token_id)
        if callback in self._subscribers[key]:
            self._subscribers[key].remove(callback)

    async def _notify_subscribers(self, key: str, update: Optional[PriceUpdate]) -> None:
        """Notify all subscribers of a price update."""
        if not update:
            return
        for callback in self._subscribers.get(key, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(update)
                else:
                    callback(update)
            except Exception as e:
                logger.warning("Subscriber callback failed", error=str(e))

    async def get_all_prices(self, platform: Optional[str] = None) -> dict[str, PriceUpdate]:
        """Get all cached prices, optionally filtered by platform."""
        async with self._lock:
            now = time.time()
            result = {}
            for key, update in self._cache.items():
                if (now - update.timestamp) < self._ttl:
                    if platform is None or update.platform == platform:
                        result[key] = update
            return result


class BaseWebSocketClient(ABC):
    """Abstract base class for platform-specific WebSocket clients."""

    def __init__(
        self,
        url: str,
        price_cache: PriceCache,
        ping_interval: float = 10.0,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ):
        self.url = url
        self.price_cache = price_cache
        self.ping_interval = ping_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._state = ConnectionState.DISCONNECTED
        self._subscribed_tokens: set[str] = set()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._current_reconnect_delay = reconnect_delay

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier."""
        pass

    @abstractmethod
    async def _build_subscribe_message(self, token_ids: list[str]) -> dict:
        """Build platform-specific subscription message."""
        pass

    @abstractmethod
    async def _build_unsubscribe_message(self, token_ids: list[str]) -> dict:
        """Build platform-specific unsubscription message."""
        pass

    @abstractmethod
    async def _handle_message(self, message: dict) -> None:
        """Handle platform-specific message format."""
        pass

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self._running:
            return

        self._running = True
        self._state = ConnectionState.CONNECTING

        try:
            self._ws = await websockets.connect(
                self.url,
                ping_interval=None,  # We'll handle pings manually
                ping_timeout=30,
                close_timeout=10,
            )
            self._state = ConnectionState.CONNECTED
            self._current_reconnect_delay = self.reconnect_delay

            logger.info(
                "WebSocket connected",
                platform=self.platform,
                url=self.url,
            )

            # Start background tasks
            self._tasks = [
                asyncio.create_task(self._receive_loop()),
                asyncio.create_task(self._ping_loop()),
            ]

            # Resubscribe to any previously subscribed tokens
            if self._subscribed_tokens:
                await self._send_subscribe(list(self._subscribed_tokens))

        except Exception as e:
            logger.error("WebSocket connection failed", platform=self.platform, error=str(e))
            self._state = ConnectionState.DISCONNECTED
            await self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        self._state = ConnectionState.DISCONNECTED

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("WebSocket disconnected", platform=self.platform)

    async def subscribe(self, token_ids: list[str]) -> None:
        """Subscribe to price updates for tokens."""
        new_tokens = set(token_ids) - self._subscribed_tokens
        if not new_tokens:
            return

        self._subscribed_tokens.update(new_tokens)

        if self.is_connected:
            await self._send_subscribe(list(new_tokens))

    async def unsubscribe(self, token_ids: list[str]) -> None:
        """Unsubscribe from price updates."""
        tokens_to_remove = set(token_ids) & self._subscribed_tokens
        if not tokens_to_remove:
            return

        self._subscribed_tokens -= tokens_to_remove

        if self.is_connected:
            await self._send_unsubscribe(list(tokens_to_remove))

    async def _send_subscribe(self, token_ids: list[str]) -> None:
        """Send subscription message."""
        if not self._ws or not token_ids:
            return

        message = await self._build_subscribe_message(token_ids)
        await self._ws.send(json.dumps(message))
        logger.debug(
            "Subscribed to tokens",
            platform=self.platform,
            count=len(token_ids),
        )

    async def _send_unsubscribe(self, token_ids: list[str]) -> None:
        """Send unsubscription message."""
        if not self._ws or not token_ids:
            return

        message = await self._build_unsubscribe_message(token_ids)
        await self._ws.send(json.dumps(message))
        logger.debug(
            "Unsubscribed from tokens",
            platform=self.platform,
            count=len(token_ids),
        )

    async def _receive_loop(self) -> None:
        """Main loop for receiving messages."""
        while self._running and self._ws:
            try:
                message = await self._ws.recv()
                data = json.loads(message)
                await self._handle_message(data)
            except ConnectionClosed as e:
                logger.warning(
                    "WebSocket connection closed",
                    platform=self.platform,
                    code=e.code,
                    reason=e.reason,
                )
                break
            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON message", platform=self.platform, error=str(e))
            except Exception as e:
                logger.error("Error processing message", platform=self.platform, error=str(e))

        # Connection lost - attempt reconnect
        if self._running:
            await self._schedule_reconnect()

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep connection alive."""
        while self._running and self._ws:
            try:
                await asyncio.sleep(self.ping_interval)
                if self._ws:
                    await self._ws.ping()
            except Exception as e:
                logger.debug("Ping failed", platform=self.platform, error=str(e))
                break

    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff."""
        if not self._running:
            return

        self._state = ConnectionState.RECONNECTING

        logger.info(
            "Scheduling reconnect",
            platform=self.platform,
            delay=self._current_reconnect_delay,
        )

        await asyncio.sleep(self._current_reconnect_delay)

        # Exponential backoff
        self._current_reconnect_delay = min(
            self._current_reconnect_delay * 2,
            self.max_reconnect_delay,
        )

        # Clean up old connection
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Reconnect
        await self.connect()


# Global price cache instance
price_cache = PriceCache(ttl_seconds=60.0)
