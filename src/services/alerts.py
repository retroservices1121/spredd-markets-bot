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
    buy_platform: Platform  # Platform to buy on (cheaper)
    sell_platform: Platform  # Platform to sell on (more expensive)
    buy_market_id: str
    sell_market_id: str
    buy_price: Decimal  # YES price on buy platform (lower)
    sell_price: Decimal  # YES price on sell platform (higher)
    spread_cents: int  # Spread in cents (e.g., 5 = 5¢)
    profit_potential: Decimal  # Estimated profit % after ~4% fees
    buy_title: str = ""  # Market title on buy platform
    sell_title: str = ""  # Market title on sell platform
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
        Find arbitrage opportunities across all 5 platforms:
        Polymarket, Kalshi, Limitless, Opinion Labs, and Myriad.

        Uses real orderbook prices for accurate arbitrage calculation:
        - Buy price = best ask (what you pay to buy)
        - Sell price = best bid (what you get when selling)
        - Real spread = sell_bid - buy_ask
        """
        opportunities = []

        try:
            # Fetch markets from all platforms concurrently
            from src.platforms.polymarket import polymarket_platform
            from src.platforms.kalshi import kalshi_platform
            from src.platforms.limitless import limitless_platform
            from src.platforms.opinion import opinion_platform
            from src.platforms.myriad import myriad_platform
            from src.db.models import Outcome

            # Platform instances for orderbook fetching
            platform_instances = {
                Platform.POLYMARKET: polymarket_platform,
                Platform.KALSHI: kalshi_platform,
                Platform.LIMITLESS: limitless_platform,
                Platform.OPINION: opinion_platform,
                Platform.MYRIAD: myriad_platform,
            }

            # Fetch all markets in parallel
            results = await asyncio.gather(
                polymarket_platform.get_markets(limit=50, active_only=True),
                kalshi_platform.get_markets(limit=50, active_only=True),
                limitless_platform.get_markets(limit=50, active_only=True),
                opinion_platform.get_markets(limit=50, active_only=True),
                myriad_platform.get_markets(limit=50, active_only=True),
                return_exceptions=True,
            )

            # Organize markets by platform
            platform_markets: dict[Platform, list] = {
                Platform.POLYMARKET: [],
                Platform.KALSHI: [],
                Platform.LIMITLESS: [],
                Platform.OPINION: [],
                Platform.MYRIAD: [],
            }

            platforms_list = [Platform.POLYMARKET, Platform.KALSHI, Platform.LIMITLESS, Platform.OPINION, Platform.MYRIAD]

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to fetch {platforms_list[i].value} markets", error=str(result))
                    continue
                platform_markets[platforms_list[i]] = result or []

            logger.info(
                "Fetched markets for arbitrage",
                polymarket=len(platform_markets[Platform.POLYMARKET]),
                kalshi=len(platform_markets[Platform.KALSHI]),
                limitless=len(platform_markets[Platform.LIMITLESS]),
                opinion=len(platform_markets[Platform.OPINION]),
                myriad=len(platform_markets[Platform.MYRIAD]),
            )

            # Extract key identifiers from titles for matching
            def extract_match_key(title: str) -> set[str]:
                """Extract meaningful words for matching."""
                title_lower = title.lower()
                # Remove common prediction market phrases
                for phrase in ["will", "win", "beat", "defeat", "vs", "vs.", "to win", "winner", "over", "under"]:
                    title_lower = title_lower.replace(phrase, " ")

                words = set(title_lower.split())
                # Remove stop words and short words
                stop_words = {"the", "a", "an", "to", "in", "on", "at", "be", "or", "and", "?", "of", "for", "-", "by"}
                return {w for w in words if w not in stop_words and len(w) > 2}

            # Helper to fetch real orderbook prices for a market
            async def get_orderbook_prices(platform: Platform, market) -> tuple[Decimal | None, Decimal | None]:
                """
                Fetch real orderbook prices for a market.
                Returns (best_ask, best_bid) - what you pay to buy, what you get to sell.
                """
                try:
                    platform_instance = platform_instances.get(platform)
                    if not platform_instance:
                        return market.yes_price, market.yes_price

                    # Get slug for platforms that need it (Limitless, Myriad)
                    slug = None
                    if market.raw_data and isinstance(market.raw_data, dict):
                        slug = market.raw_data.get("slug") or market.event_id

                    orderbook = await platform_instance.get_orderbook(market.market_id, Outcome.YES, slug=slug)

                    if orderbook:
                        best_ask = orderbook.best_ask or market.yes_price
                        best_bid = orderbook.best_bid or market.yes_price
                        return best_ask, best_bid

                    return market.yes_price, market.yes_price
                except Exception as e:
                    logger.debug(f"Orderbook fetch failed for {platform.value}:{market.market_id[:10]}", error=str(e)[:50])
                    return market.yes_price, market.yes_price

            # Pre-compute match keys for all markets
            market_keys: dict[Platform, list[tuple]] = {}
            for platform, markets in platform_markets.items():
                market_keys[platform] = [
                    (m, extract_match_key(m.title))
                    for m in markets
                    if m.yes_price is not None
                ]

            # First pass: find candidate pairs based on title similarity
            candidate_pairs = []
            seen_pairs = set()

            for i, platform_a in enumerate(platforms_list):
                for platform_b in platforms_list[i + 1:]:  # Only compare each pair once
                    markets_a = market_keys.get(platform_a, [])
                    markets_b = market_keys.get(platform_b, [])

                    for market_a, keys_a in markets_a:
                        if not keys_a:
                            continue

                        for market_b, keys_b in markets_b:
                            if not keys_b:
                                continue

                            # Calculate Jaccard similarity
                            common = keys_a & keys_b
                            union = keys_a | keys_b
                            similarity = len(common) / len(union) if union else 0

                            # Require at least 40% similarity AND 3+ common words
                            if similarity < 0.4 or len(common) < 3:
                                continue

                            # Skip if we've seen this pair
                            pair_key = (market_a.market_id, market_b.market_id)
                            if pair_key in seen_pairs:
                                continue
                            seen_pairs.add(pair_key)

                            # Quick check: if mid-prices are too close, skip orderbook fetch
                            mid_spread = abs(market_a.yes_price - market_b.yes_price)
                            if mid_spread < Decimal("0.02"):  # Less than 2% spread in mid-price
                                continue

                            candidate_pairs.append((platform_a, market_a, platform_b, market_b))

            logger.info(f"Found {len(candidate_pairs)} candidate arbitrage pairs, fetching orderbooks...")

            # Second pass: fetch real orderbook prices for candidates
            for platform_a, market_a, platform_b, market_b in candidate_pairs[:20]:  # Limit to top 20 to avoid API spam
                try:
                    # Fetch orderbooks for both markets
                    (ask_a, bid_a), (ask_b, bid_b) = await asyncio.gather(
                        get_orderbook_prices(platform_a, market_a),
                        get_orderbook_prices(platform_b, market_b),
                    )

                    if not all([ask_a, bid_a, ask_b, bid_b]):
                        continue

                    # Calculate real arbitrage spread
                    # Option 1: Buy on A (pay ask_a), sell on B (get bid_b)
                    spread_a_to_b = bid_b - ask_a
                    # Option 2: Buy on B (pay ask_b), sell on A (get bid_a)
                    spread_b_to_a = bid_a - ask_b

                    # Pick the better direction
                    if spread_a_to_b > spread_b_to_a:
                        buy_platform, sell_platform = platform_a, platform_b
                        buy_market, sell_market = market_a, market_b
                        buy_price, sell_price = ask_a, bid_b  # Buy at ask, sell at bid
                        spread_decimal = spread_a_to_b
                    else:
                        buy_platform, sell_platform = platform_b, platform_a
                        buy_market, sell_market = market_b, market_a
                        buy_price, sell_price = ask_b, bid_a
                        spread_decimal = spread_b_to_a

                    spread_cents = int(spread_decimal * 100)

                    # Skip if spread is too small (must be > 3% to cover fees)
                    if spread_decimal < self.min_arbitrage_spread:
                        continue

                    # Calculate profit potential after fees (~4% round-trip)
                    estimated_fees = Decimal("0.04")
                    profit_potential = spread_decimal - estimated_fees
                    profit_percent = (profit_potential * 100) if profit_potential > 0 else Decimal("0")

                    # Create unique ID
                    opp_id = f"{buy_market.market_id[:6]}-{sell_market.market_id[:6]}"

                    opp = ArbitrageOpportunity(
                        id=opp_id,
                        market_title=buy_market.title[:80],
                        buy_platform=buy_platform,
                        sell_platform=sell_platform,
                        buy_market_id=buy_market.market_id,
                        sell_market_id=sell_market.market_id,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        spread_cents=spread_cents,
                        profit_potential=profit_percent,
                        buy_title=buy_market.title[:50],
                        sell_title=sell_market.title[:50],
                    )

                    # Check cache for significant changes
                    cached = self._arbitrage_cache.get(opp_id)
                    if not cached or abs(cached.spread_cents - spread_cents) >= 2:
                        self._arbitrage_cache[opp_id] = opp
                        opportunities.append(opp)

                    logger.info(
                        "Arbitrage opportunity found",
                        buy_platform=buy_platform.value,
                        sell_platform=sell_platform.value,
                        buy_price=str(buy_price),
                        sell_price=str(sell_price),
                        spread_cents=spread_cents,
                        title=buy_market.title[:40],
                    )

                except Exception as e:
                    logger.warning("Error processing arbitrage pair", error=str(e)[:100])
                    continue

            # Sort by profit potential (highest first)
            opportunities.sort(key=lambda x: x.profit_potential, reverse=True)
            return opportunities[:15]  # Return top 15

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
        """Send arbitrage alert to all subscribers with trade buttons."""
        if not self._bot or not self._arbitrage_subscribers:
            return

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            # Platform display names
            platform_names = {
                Platform.POLYMARKET: "Polymarket",
                Platform.KALSHI: "Kalshi",
                Platform.LIMITLESS: "Limitless",
                Platform.OPINION: "Opinion",
            }

            platform_emojis = {
                Platform.POLYMARKET: "🔮",
                Platform.KALSHI: "📈",
                Platform.LIMITLESS: "♾️",
                Platform.OPINION: "💭",
            }

            buy_name = platform_names.get(opp.buy_platform, opp.buy_platform.value)
            sell_name = platform_names.get(opp.sell_platform, opp.sell_platform.value)
            buy_emoji = platform_emojis.get(opp.buy_platform, "📊")
            sell_emoji = platform_emojis.get(opp.sell_platform, "📊")

            buy_price_cents = int(opp.buy_price * 100)
            sell_price_cents = int(opp.sell_price * 100)

            # Show profit potential clearly
            profit_str = f"+{opp.profit_potential:.1f}%" if opp.profit_potential > 0 else f"{opp.profit_potential:.1f}%"

            action = f"Buy YES @ {buy_price_cents}¢ on {buy_name} → Sell @ {sell_price_cents}¢ on {sell_name}"

            message = f"""
⚡ <b>Arbitrage Opportunity!</b>

<b>{opp.market_title}</b>

{buy_emoji} {buy_name}: <b>{buy_price_cents}¢</b> (BUY)
{sell_emoji} {sell_name}: <b>{sell_price_cents}¢</b> (SELL)

💰 <b>Spread: {opp.spread_cents}¢</b>
📈 Est. Profit (after fees): <b>{profit_str}</b>

🎯 <i>{action}</i>

<i>⚠️ Fees ~4% round-trip. Execute quickly!</i>
"""

            # Create trade buttons
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🟢 Buy YES on {buy_name}",
                        callback_data=f"arb_trade:{opp.buy_platform.value}:{opp.buy_market_id}:yes:buy"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"🔴 Sell YES on {sell_name}",
                        callback_data=f"arb_trade:{opp.sell_platform.value}:{opp.sell_market_id}:yes:sell"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"{buy_emoji} View {buy_name}",
                        callback_data=f"view_market:{opp.buy_platform.value}:{opp.buy_market_id}"
                    ),
                    InlineKeyboardButton(
                        f"{sell_emoji} View {sell_name}",
                        callback_data=f"view_market:{opp.sell_platform.value}:{opp.sell_market_id}"
                    ),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            for telegram_id in list(self._arbitrage_subscribers):
                try:
                    await self._bot.send_message(
                        chat_id=telegram_id,
                        text=message,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
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
                spread_cents=opp.spread_cents,
                profit_potential=str(opp.profit_potential),
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
