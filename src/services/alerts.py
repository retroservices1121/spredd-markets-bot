"""
Price alerts and arbitrage monitoring service.
Monitors market prices and sends Telegram notifications.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from src.config import settings
from src.db.models import Platform
from src.platforms import get_platform
from src.services.dome import dome_client
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PriceAlert:
    """User price alert configuration."""
    id: str
    user_telegram_id: int
    platform: Platform
    market_id: str
    market_title: str
    outcome: str  # "yes" or "no"
    condition: str  # "above" or "below"
    target_price: Decimal
    current_price: Optional[Decimal] = None
    triggered: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    triggered_at: Optional[datetime] = None

    def check(self, current_price: Decimal) -> bool:
        """Check if alert should trigger."""
        self.current_price = current_price
        if self.condition == "above":
            return current_price >= self.target_price
        else:  # below
            return current_price <= self.target_price


@dataclass
class ArbitrageOpportunity:
    """Cross-platform arbitrage opportunity."""
    id: str
    market_title: str
    platform_a: Platform
    platform_b: Platform
    market_id_a: str
    market_id_b: str
    price_a: Decimal  # YES price on platform A
    price_b: Decimal  # YES price on platform B
    spread: Decimal  # Absolute difference
    spread_percent: Decimal
    direction: str  # "BUY_A_SELL_B" or "BUY_B_SELL_A"
    detected_at: datetime = field(default_factory=datetime.utcnow)


class AlertsService:
    """
    Service for managing price alerts and arbitrage monitoring.
    """

    def __init__(self):
        self._alerts: dict[str, PriceAlert] = {}
        self._arbitrage_cache: dict[str, ArbitrageOpportunity] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._arbitrage_task: Optional[asyncio.Task] = None
        self._bot = None  # Set by main.py
        self._running = False

        # Arbitrage settings
        self.min_arbitrage_spread = Decimal("0.03")  # 3% minimum
        self.arbitrage_check_interval = 60  # seconds
        self.price_check_interval = 30  # seconds

        # In-memory alert subscriptions for arbitrage
        self._arbitrage_subscribers: set[int] = set()  # telegram_ids

    def set_bot(self, bot) -> None:
        """Set the Telegram bot instance for sending notifications."""
        self._bot = bot

    # ===================
    # Price Alerts
    # ===================

    async def create_alert(
        self,
        user_telegram_id: int,
        platform: Platform,
        market_id: str,
        market_title: str,
        outcome: str,
        condition: str,
        target_price: Decimal,
    ) -> PriceAlert:
        """
        Create a new price alert.

        Args:
            user_telegram_id: User's Telegram ID
            platform: Trading platform
            market_id: Market identifier
            market_title: Human-readable market title
            outcome: "yes" or "no"
            condition: "above" or "below"
            target_price: Price threshold (0-1)

        Returns:
            Created PriceAlert
        """
        alert = PriceAlert(
            id=str(uuid4())[:8],
            user_telegram_id=user_telegram_id,
            platform=platform,
            market_id=market_id,
            market_title=market_title,
            outcome=outcome,
            condition=condition,
            target_price=target_price,
        )

        self._alerts[alert.id] = alert

        logger.info(
            "Price alert created",
            alert_id=alert.id,
            user=user_telegram_id,
            market=market_id,
            condition=f"{outcome} {condition} {target_price}",
        )

        return alert

    async def delete_alert(self, alert_id: str, user_telegram_id: int) -> bool:
        """Delete an alert by ID."""
        alert = self._alerts.get(alert_id)
        if alert and alert.user_telegram_id == user_telegram_id:
            del self._alerts[alert_id]
            logger.info("Price alert deleted", alert_id=alert_id)
            return True
        return False

    async def get_user_alerts(self, user_telegram_id: int) -> list[PriceAlert]:
        """Get all alerts for a user."""
        return [
            a for a in self._alerts.values()
            if a.user_telegram_id == user_telegram_id and not a.triggered
        ]

    async def _check_alerts(self) -> None:
        """Check all active alerts against current prices."""
        if not self._alerts:
            return

        # Group alerts by platform and market for efficient fetching
        alerts_by_market: dict[tuple[Platform, str], list[PriceAlert]] = {}
        for alert in list(self._alerts.values()):
            if alert.triggered:
                continue
            key = (alert.platform, alert.market_id)
            alerts_by_market.setdefault(key, []).append(alert)

        # Check each market
        for (platform, market_id), alerts in alerts_by_market.items():
            try:
                platform_client = get_platform(platform)
                market = await platform_client.get_market(market_id)

                if not market:
                    continue

                for alert in alerts:
                    price = market.yes_price if alert.outcome == "yes" else market.no_price

                    if price and alert.check(price):
                        alert.triggered = True
                        alert.triggered_at = datetime.utcnow()
                        await self._send_alert_notification(alert)

            except Exception as e:
                logger.error(
                    "Failed to check alerts for market",
                    platform=platform.value,
                    market_id=market_id,
                    error=str(e),
                )

    async def _send_alert_notification(self, alert: PriceAlert) -> None:
        """Send Telegram notification for triggered alert."""
        if not self._bot:
            logger.warning("Bot not set, cannot send alert notification")
            return

        try:
            direction = "📈" if alert.condition == "above" else "📉"
            current_cents = int(alert.current_price * 100) if alert.current_price else "?"
            target_cents = int(alert.target_price * 100)

            message = f"""
{direction} <b>Price Alert Triggered!</b>

<b>{alert.market_title[:50]}...</b>

{alert.outcome.upper()} price is now {current_cents}¢
Target: {alert.condition} {target_cents}¢

Platform: {alert.platform.value.title()}
"""

            await self._bot.send_message(
                chat_id=alert.user_telegram_id,
                text=message,
                parse_mode="HTML",
            )

            logger.info(
                "Alert notification sent",
                alert_id=alert.id,
                user=alert.user_telegram_id,
            )

        except Exception as e:
            logger.error(
                "Failed to send alert notification",
                alert_id=alert.id,
                error=str(e),
            )

    # ===================
    # Arbitrage Monitoring
    # ===================

    async def subscribe_arbitrage(self, user_telegram_id: int) -> None:
        """Subscribe user to arbitrage alerts."""
        self._arbitrage_subscribers.add(user_telegram_id)
        logger.info("User subscribed to arbitrage alerts", user=user_telegram_id)

    async def unsubscribe_arbitrage(self, user_telegram_id: int) -> None:
        """Unsubscribe user from arbitrage alerts."""
        self._arbitrage_subscribers.discard(user_telegram_id)
        logger.info("User unsubscribed from arbitrage alerts", user=user_telegram_id)

    def is_subscribed_arbitrage(self, user_telegram_id: int) -> bool:
        """Check if user is subscribed to arbitrage alerts."""
        return user_telegram_id in self._arbitrage_subscribers

    async def find_arbitrage_opportunities(self) -> list[ArbitrageOpportunity]:
        """
        Find arbitrage opportunities between Polymarket and Kalshi.
        Compares YES prices for matching markets.
        """
        opportunities = []

        try:
            # Get Polymarket sports markets
            from src.platforms.polymarket import polymarket_platform
            poly_markets = await polymarket_platform.get_markets(limit=50, active_only=True)

            # Get Kalshi markets
            from src.platforms.kalshi import kalshi_platform
            kalshi_markets = await kalshi_platform.get_markets(limit=50, active_only=True)

            # Simple matching by title keywords
            # More sophisticated matching would use Dome API's matching endpoint
            for poly_m in poly_markets:
                poly_title_lower = poly_m.title.lower()

                for kalshi_m in kalshi_markets:
                    kalshi_title_lower = kalshi_m.title.lower()

                    # Check for significant title overlap
                    poly_words = set(poly_title_lower.split())
                    kalshi_words = set(kalshi_title_lower.split())
                    common_words = poly_words & kalshi_words

                    # Remove common stop words
                    stop_words = {"will", "the", "a", "an", "to", "in", "on", "at", "be", "or", "and", "?"}
                    meaningful_common = common_words - stop_words

                    if len(meaningful_common) < 3:
                        continue

                    # Calculate spread
                    poly_yes = poly_m.yes_price or Decimal("0.5")
                    kalshi_yes = kalshi_m.yes_price or Decimal("0.5")
                    spread = abs(poly_yes - kalshi_yes)
                    spread_percent = (spread / min(poly_yes, kalshi_yes)) * 100 if min(poly_yes, kalshi_yes) > 0 else Decimal("0")

                    if spread < self.min_arbitrage_spread:
                        continue

                    # Determine direction
                    if poly_yes < kalshi_yes:
                        direction = "BUY_POLY_SELL_KALSHI"
                    else:
                        direction = "BUY_KALSHI_SELL_POLY"

                    opp = ArbitrageOpportunity(
                        id=f"{poly_m.market_id[:8]}-{kalshi_m.market_id[:8]}",
                        market_title=poly_m.title[:100],
                        platform_a=Platform.POLYMARKET,
                        platform_b=Platform.KALSHI,
                        market_id_a=poly_m.market_id,
                        market_id_b=kalshi_m.market_id,
                        price_a=poly_yes,
                        price_b=kalshi_yes,
                        spread=spread,
                        spread_percent=spread_percent,
                        direction=direction,
                    )

                    # Check if this is a new opportunity
                    cache_key = opp.id
                    cached = self._arbitrage_cache.get(cache_key)

                    if not cached or abs(cached.spread - spread) > Decimal("0.01"):
                        self._arbitrage_cache[cache_key] = opp
                        opportunities.append(opp)

            return opportunities

        except Exception as e:
            logger.error("Failed to find arbitrage opportunities", error=str(e))
            return []

    async def _check_arbitrage(self) -> None:
        """Check for arbitrage opportunities and notify subscribers."""
        if not self._arbitrage_subscribers:
            return

        opportunities = await self.find_arbitrage_opportunities()

        for opp in opportunities:
            await self._send_arbitrage_notification(opp)

    async def _send_arbitrage_notification(self, opp: ArbitrageOpportunity) -> None:
        """Send arbitrage alert to all subscribers."""
        if not self._bot or not self._arbitrage_subscribers:
            return

        try:
            price_a_cents = int(opp.price_a * 100)
            price_b_cents = int(opp.price_b * 100)

            if opp.direction == "BUY_POLY_SELL_KALSHI":
                action = f"Buy YES on Polymarket ({price_a_cents}¢) → Sell on Kalshi ({price_b_cents}¢)"
            else:
                action = f"Buy YES on Kalshi ({price_b_cents}¢) → Sell on Polymarket ({price_a_cents}¢)"

            message = f"""
⚡ <b>Arbitrage Opportunity!</b>

<b>{opp.market_title}</b>

📊 Polymarket: {price_a_cents}¢
📈 Kalshi: {price_b_cents}¢

💰 <b>Spread: {opp.spread_percent:.1f}%</b>

🎯 {action}

<i>Note: Consider fees, slippage, and execution time.</i>
"""

            for telegram_id in list(self._arbitrage_subscribers):
                try:
                    await self._bot.send_message(
                        chat_id=telegram_id,
                        text=message,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to send arbitrage alert to user",
                        user=telegram_id,
                        error=str(e),
                    )

            logger.info(
                "Arbitrage alert sent",
                opportunity_id=opp.id,
                spread=str(opp.spread_percent),
                subscribers=len(self._arbitrage_subscribers),
            )

        except Exception as e:
            logger.error("Failed to send arbitrage notification", error=str(e))

    # ===================
    # Background Tasks
    # ===================

    async def start_monitoring(self) -> None:
        """Start background monitoring tasks."""
        if self._running:
            return

        self._running = True

        # Start price alert monitoring
        self._monitoring_task = asyncio.create_task(self._price_monitoring_loop())

        # Start arbitrage monitoring
        self._arbitrage_task = asyncio.create_task(self._arbitrage_monitoring_loop())

        logger.info("Alert monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop background monitoring tasks."""
        self._running = False

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        if self._arbitrage_task:
            self._arbitrage_task.cancel()
            try:
                await self._arbitrage_task
            except asyncio.CancelledError:
                pass

        logger.info("Alert monitoring stopped")

    async def _price_monitoring_loop(self) -> None:
        """Background loop for checking price alerts."""
        while self._running:
            try:
                await self._check_alerts()
            except Exception as e:
                logger.error("Error in price monitoring loop", error=str(e))

            await asyncio.sleep(self.price_check_interval)

    async def _arbitrage_monitoring_loop(self) -> None:
        """Background loop for checking arbitrage opportunities."""
        while self._running:
            try:
                await self._check_arbitrage()
            except Exception as e:
                logger.error("Error in arbitrage monitoring loop", error=str(e))

            await asyncio.sleep(self.arbitrage_check_interval)


# Singleton instance
alerts_service = AlertsService()
