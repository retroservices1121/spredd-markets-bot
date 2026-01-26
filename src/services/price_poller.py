"""
Polling-based price updater for platforms without WebSocket support.

Periodically fetches prices from REST APIs and updates the shared price cache.
Used for: Kalshi, Limitless, Opinion Labs
"""

import asyncio
from decimal import Decimal
from typing import Optional, Set
from dataclasses import dataclass

from src.services.websocket_manager import (
    PriceCache,
    PriceUpdate,
    OrderBookUpdate,
    price_cache,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MarketSubscription:
    """Subscription info for a market."""
    platform: str
    market_id: str
    yes_token: Optional[str] = None
    no_token: Optional[str] = None


class PricePoller:
    """
    Polls REST APIs periodically to update the price cache.

    For platforms without WebSocket support (Kalshi, Limitless, Opinion),
    this provides near-real-time price updates via periodic polling.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        poll_interval: float = 5.0,  # Poll every 5 seconds
        batch_size: int = 10,  # Max markets per batch
    ):
        self.price_cache = price_cache
        self.poll_interval = poll_interval
        self.batch_size = batch_size

        self._subscriptions: dict[str, MarketSubscription] = {}  # key -> subscription
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _make_key(self, platform: str, market_id: str) -> str:
        return f"{platform}:{market_id}"

    async def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Price poller started", interval=self.poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Price poller stopped")

    def subscribe(
        self,
        platform: str,
        market_id: str,
        yes_token: Optional[str] = None,
        no_token: Optional[str] = None,
    ) -> None:
        """Subscribe to price updates for a market."""
        key = self._make_key(platform, market_id)
        self._subscriptions[key] = MarketSubscription(
            platform=platform,
            market_id=market_id,
            yes_token=yes_token,
            no_token=no_token,
        )
        logger.debug("Subscribed to market", platform=platform, market_id=market_id[:20])

    def unsubscribe(self, platform: str, market_id: str) -> None:
        """Unsubscribe from a market."""
        key = self._make_key(platform, market_id)
        self._subscriptions.pop(key, None)

    def get_subscribed_platforms(self) -> Set[str]:
        """Get set of platforms with active subscriptions."""
        return {sub.platform for sub in self._subscriptions.values()}

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all_platforms()
            except Exception as e:
                logger.error("Polling error", error=str(e))

            await asyncio.sleep(self.poll_interval)

    async def _poll_all_platforms(self) -> None:
        """Poll all platforms with subscriptions."""
        # Group subscriptions by platform
        by_platform: dict[str, list[MarketSubscription]] = {}
        for sub in self._subscriptions.values():
            if sub.platform not in by_platform:
                by_platform[sub.platform] = []
            by_platform[sub.platform].append(sub)

        # Poll each platform concurrently
        tasks = []
        for platform, subs in by_platform.items():
            tasks.append(self._poll_platform(platform, subs))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_platform(self, platform: str, subscriptions: list[MarketSubscription]) -> None:
        """Poll a single platform for all subscribed markets."""
        try:
            if platform == "kalshi":
                await self._poll_kalshi(subscriptions)
            elif platform == "limitless":
                await self._poll_limitless(subscriptions)
            elif platform == "opinion":
                await self._poll_opinion(subscriptions)
            else:
                logger.warning("Unknown platform for polling", platform=platform)
        except Exception as e:
            logger.error("Platform polling failed", platform=platform, error=str(e))

    async def _poll_kalshi(self, subscriptions: list[MarketSubscription]) -> None:
        """Poll Kalshi markets via DFlow API."""
        from src.platforms import platform_registry
        from src.db.models import Platform, Outcome

        kalshi = platform_registry.get(Platform.KALSHI)
        if not kalshi:
            return

        for sub in subscriptions[:self.batch_size]:
            try:
                # Get orderbook for YES outcome
                orderbook = await kalshi.get_orderbook(sub.market_id, Outcome.YES)

                if sub.yes_token:
                    update = PriceUpdate(
                        platform="kalshi",
                        market_id=sub.market_id,
                        token_id=sub.yes_token,
                        best_bid=orderbook.best_bid,
                        best_ask=orderbook.best_ask,
                    )
                    await self.price_cache.update_price(update)

                    # Also cache orderbook
                    ob_update = OrderBookUpdate(
                        platform="kalshi",
                        market_id=sub.market_id,
                        token_id=sub.yes_token,
                        bids=orderbook.bids,
                        asks=orderbook.asks,
                    )
                    await self.price_cache.update_orderbook(ob_update)

            except Exception as e:
                logger.debug("Kalshi poll failed", market_id=sub.market_id[:20], error=str(e))

    async def _poll_limitless(self, subscriptions: list[MarketSubscription]) -> None:
        """Poll Limitless markets."""
        from src.platforms import platform_registry
        from src.db.models import Platform, Outcome

        limitless = platform_registry.get(Platform.LIMITLESS)
        if not limitless:
            return

        for sub in subscriptions[:self.batch_size]:
            try:
                # Get market data which includes prices
                market = await limitless.get_market(sub.market_id)
                if not market:
                    continue

                # Update YES token price
                if sub.yes_token and market.yes_price:
                    update = PriceUpdate(
                        platform="limitless",
                        market_id=sub.market_id,
                        token_id=sub.yes_token,
                        best_bid=market.yes_price - Decimal("0.01"),  # Estimate spread
                        best_ask=market.yes_price,
                    )
                    await self.price_cache.update_price(update)

                # Update NO token price
                if sub.no_token and market.no_price:
                    update = PriceUpdate(
                        platform="limitless",
                        market_id=sub.market_id,
                        token_id=sub.no_token,
                        best_bid=market.no_price - Decimal("0.01"),
                        best_ask=market.no_price,
                    )
                    await self.price_cache.update_price(update)

            except Exception as e:
                logger.debug("Limitless poll failed", market_id=sub.market_id[:20], error=str(e))

    async def _poll_opinion(self, subscriptions: list[MarketSubscription]) -> None:
        """Poll Opinion Labs markets."""
        from src.platforms import platform_registry
        from src.db.models import Platform, Outcome

        opinion = platform_registry.get(Platform.OPINION)
        if not opinion:
            return

        for sub in subscriptions[:self.batch_size]:
            try:
                # Get orderbook
                orderbook = await opinion.get_orderbook(sub.market_id, Outcome.YES)

                if sub.yes_token:
                    update = PriceUpdate(
                        platform="opinion",
                        market_id=sub.market_id,
                        token_id=sub.yes_token,
                        best_bid=orderbook.best_bid,
                        best_ask=orderbook.best_ask,
                    )
                    await self.price_cache.update_price(update)

                    ob_update = OrderBookUpdate(
                        platform="opinion",
                        market_id=sub.market_id,
                        token_id=sub.yes_token,
                        bids=orderbook.bids,
                        asks=orderbook.asks,
                    )
                    await self.price_cache.update_orderbook(ob_update)

            except Exception as e:
                logger.debug("Opinion poll failed", market_id=sub.market_id[:20], error=str(e))


# Global poller instance
price_poller = PricePoller(price_cache=price_cache, poll_interval=5.0)


async def start_price_poller() -> None:
    """Start the price poller (call on app startup)."""
    await price_poller.start()


async def stop_price_poller() -> None:
    """Stop the price poller (call on app shutdown)."""
    await price_poller.stop()
