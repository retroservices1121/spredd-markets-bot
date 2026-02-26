"""
Dome API client for prediction market data.
Provides candlesticks, trade history, wallet PnL, and cross-platform matching.
https://docs.domeapi.io/
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from datetime import datetime, timedelta

import httpx

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

DOME_API_BASE = "https://api.domeapi.io/v1"


@dataclass
class Candlestick:
    """OHLCV candlestick data."""
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class Trade:
    """Trade/order data."""
    token_id: str
    token_label: str  # "Yes" or "No"
    side: str  # "BUY" or "SELL"
    market_slug: str
    shares: Decimal
    price: Decimal
    timestamp: int
    user: str
    taker: Optional[str] = None


@dataclass
class PnLDataPoint:
    """Profit & Loss data point."""
    timestamp: int
    pnl_to_date: Decimal


@dataclass
class WalletPnL:
    """Wallet profit and loss over time."""
    wallet_address: str
    granularity: str
    start_time: int
    end_time: int
    pnl_over_time: list[PnLDataPoint]


@dataclass
class MatchedMarket:
    """Cross-platform matched market."""
    platform: str  # "POLYMARKET" or "KALSHI"
    identifier: str  # market_slug or event_ticker
    token_ids: Optional[list[str]] = None  # For Polymarket
    market_tickers: Optional[list[str]] = None  # For Kalshi


@dataclass
class ArbitrageOpportunity:
    """Arbitrage opportunity between platforms."""
    market_title: str
    polymarket_slug: str
    kalshi_ticker: str
    polymarket_yes_price: Decimal
    kalshi_yes_price: Decimal
    price_diff: Decimal
    price_diff_percent: Decimal
    recommended_action: str  # "BUY_POLY_SELL_KALSHI" or "BUY_KALSHI_SELL_POLY"


@dataclass
class PriceAlert:
    """Price alert configuration."""
    id: str
    user_id: int
    platform: str
    market_id: str
    market_title: str
    condition: str  # "above" or "below"
    target_price: Decimal
    current_price: Optional[Decimal] = None
    triggered: bool = False
    created_at: Optional[datetime] = None


class DomeAPIClient:
    """
    Client for Dome API.
    Provides market data, analytics, and cross-platform features.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, 'dome_api_key', None)
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize HTTP client."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key

        self._http_client = httpx.AsyncClient(
            base_url=DOME_API_BASE,
            timeout=30.0,
            headers=headers,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30),
        )
        logger.info("Dome API client initialized", has_api_key=bool(self.api_key))

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        **kwargs,
    ) -> Any:
        """Make API request."""
        if not self._http_client:
            await self.initialize()

        try:
            response = await self._http_client.request(
                method, endpoint, params=params, **kwargs
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Dome API error",
                status=e.response.status_code,
                endpoint=endpoint,
                error=e.response.text[:200] if e.response.text else "",
            )
            raise
        except Exception as e:
            logger.error("Dome API request failed", endpoint=endpoint, error=str(e))
            raise

    # ===================
    # Candlestick Data
    # ===================

    async def get_candlesticks(
        self,
        condition_id: str,
        interval: str = "1h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> list[Candlestick]:
        """
        Get historical candlestick data for a market.

        Args:
            condition_id: Market condition ID
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            start_time: Start timestamp (Unix seconds)
            end_time: End timestamp (Unix seconds)
            limit: Max candles to return

        Returns:
            List of Candlestick objects
        """
        params = {
            "condition_id": condition_id,
            "interval": interval,
            "limit": limit,
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            data = await self._request("GET", "/polymarket/candlesticks", params=params)
            candles = []
            for c in data.get("candlesticks", data.get("data", [])):
                candles.append(Candlestick(
                    timestamp=c.get("timestamp", 0),
                    open=Decimal(str(c.get("open", 0))),
                    high=Decimal(str(c.get("high", 0))),
                    low=Decimal(str(c.get("low", 0))),
                    close=Decimal(str(c.get("close", 0))),
                    volume=Decimal(str(c.get("volume", 0))),
                ))
            return candles
        except Exception as e:
            logger.error("Failed to get candlesticks", error=str(e))
            return []

    # ===================
    # Trade History
    # ===================

    async def get_trade_history(
        self,
        market_slug: Optional[str] = None,
        condition_id: Optional[str] = None,
        token_id: Optional[str] = None,
        user: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> list[Trade]:
        """
        Get trade history with optional filters.

        Args:
            market_slug: Filter by market
            condition_id: Filter by condition
            token_id: Filter by token
            user: Filter by wallet address
            start_time: Start timestamp
            end_time: End timestamp
            limit: Max results

        Returns:
            List of Trade objects
        """
        params = {"limit": limit}
        if market_slug:
            params["market_slug"] = market_slug
        if condition_id:
            params["condition_id"] = condition_id
        if token_id:
            params["token_id"] = token_id
        if user:
            params["user"] = user
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            data = await self._request("GET", "/polymarket/orders", params=params)
            trades = []
            for t in data.get("orders", []):
                trades.append(Trade(
                    token_id=t.get("token_id", ""),
                    token_label=t.get("token_label", ""),
                    side=t.get("side", ""),
                    market_slug=t.get("market_slug", ""),
                    shares=Decimal(str(t.get("shares_normalized", t.get("shares", 0)))),
                    price=Decimal(str(t.get("price", 0))),
                    timestamp=t.get("timestamp", 0),
                    user=t.get("user", ""),
                    taker=t.get("taker"),
                ))
            return trades
        except Exception as e:
            logger.error("Failed to get trade history", error=str(e))
            return []

    # ===================
    # Wallet PnL
    # ===================

    async def get_wallet_pnl(
        self,
        wallet_address: str,
        granularity: str = "day",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[WalletPnL]:
        """
        Get realized profit and loss for a wallet.

        Args:
            wallet_address: Ethereum wallet address
            granularity: Time bucketing (day, week, month, year, all)
            start_time: Start timestamp
            end_time: End timestamp

        Returns:
            WalletPnL object or None
        """
        params = {"granularity": granularity}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            data = await self._request(
                "GET",
                f"/polymarket/wallet/pnl/{wallet_address}",
                params=params
            )

            pnl_points = []
            for p in data.get("pnl_over_time", []):
                pnl_points.append(PnLDataPoint(
                    timestamp=p.get("timestamp", 0),
                    pnl_to_date=Decimal(str(p.get("pnl_to_date", 0))),
                ))

            return WalletPnL(
                wallet_address=data.get("wallet_address", wallet_address),
                granularity=data.get("granularity", granularity),
                start_time=data.get("start_time", 0),
                end_time=data.get("end_time", 0),
                pnl_over_time=pnl_points,
            )
        except Exception as e:
            logger.error("Failed to get wallet PnL", error=str(e))
            return None

    # ===================
    # Markets
    # ===================

    async def search_markets(
        self,
        search: Optional[str] = None,
        tags: Optional[list[str]] = None,
        status: Optional[str] = None,
        min_volume: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Search Polymarket markets.

        Args:
            search: Keyword search
            tags: Category tags
            status: "open" or "closed"
            min_volume: Minimum USD volume
            limit: Max results

        Returns:
            List of market dicts
        """
        params = {"limit": limit}
        if search:
            params["search"] = search
        if tags:
            params["tags"] = ",".join(tags)
        if status:
            params["status"] = status
        if min_volume:
            params["min_volume"] = min_volume

        try:
            data = await self._request("GET", "/polymarket/markets", params=params)
            return data.get("markets", [])
        except Exception as e:
            logger.error("Failed to search markets", error=str(e))
            return []

    async def get_market_price(
        self,
        token_id: str,
        at_time: Optional[int] = None,
    ) -> Optional[Decimal]:
        """
        Get current or historical market price.

        Args:
            token_id: Token ID
            at_time: Historical timestamp (optional)

        Returns:
            Price as Decimal or None
        """
        params = {"token_id": token_id}
        if at_time:
            params["at_time"] = at_time

        try:
            data = await self._request("GET", "/polymarket/price", params=params)
            price = data.get("price")
            return Decimal(str(price)) if price is not None else None
        except Exception as e:
            logger.error("Failed to get market price", error=str(e))
            return None

    # ===================
    # Cross-Platform Matching
    # ===================

    async def get_matching_sports_markets(
        self,
        polymarket_slugs: Optional[list[str]] = None,
        kalshi_tickers: Optional[list[str]] = None,
    ) -> dict[str, list[MatchedMarket]]:
        """
        Find equivalent markets across Polymarket and Kalshi.

        Args:
            polymarket_slugs: List of Polymarket market slugs
            kalshi_tickers: List of Kalshi event tickers

        Returns:
            Dict mapping input identifiers to matched markets
        """
        params = {}
        if polymarket_slugs:
            for slug in polymarket_slugs:
                params.setdefault("polymarket_market_slug", []).append(slug)
        if kalshi_tickers:
            for ticker in kalshi_tickers:
                params.setdefault("kalshi_event_ticker", []).append(ticker)

        try:
            data = await self._request(
                "GET",
                "/matching-markets/sports",
                params=params
            )

            result = {}
            markets_data = data.get("markets", {})

            for identifier, matches in markets_data.items():
                matched_list = []
                for m in matches:
                    matched_list.append(MatchedMarket(
                        platform=m.get("platform", ""),
                        identifier=m.get("market_slug") or m.get("event_ticker", ""),
                        token_ids=m.get("token_ids"),
                        market_tickers=m.get("market_tickers"),
                    ))
                result[identifier] = matched_list

            return result
        except Exception as e:
            logger.error("Failed to get matching markets", error=str(e))
            return {}

    async def find_arbitrage_opportunities(
        self,
        min_diff_percent: Decimal = Decimal("3.0"),
    ) -> list[ArbitrageOpportunity]:
        """
        Find arbitrage opportunities between Polymarket and Kalshi.

        Args:
            min_diff_percent: Minimum price difference to report

        Returns:
            List of ArbitrageOpportunity objects
        """
        opportunities = []

        try:
            # Get active sports markets from Polymarket
            poly_markets = await self.search_markets(
                tags=["sports"],
                status="open",
                min_volume=10000,
                limit=50,
            )

            if not poly_markets:
                return []

            # Extract slugs
            slugs = [m.get("slug") for m in poly_markets if m.get("slug")]

            if not slugs:
                return []

            # Find matching Kalshi markets
            matches = await self.get_matching_sports_markets(polymarket_slugs=slugs[:20])

            # For each match, compare prices
            for poly_slug, matched in matches.items():
                kalshi_match = next(
                    (m for m in matched if m.platform == "KALSHI"),
                    None
                )

                if not kalshi_match:
                    continue

                # Get Polymarket price
                poly_market = next(
                    (m for m in poly_markets if m.get("slug") == poly_slug),
                    None
                )

                if not poly_market:
                    continue

                # Parse prices
                try:
                    poly_prices = poly_market.get("outcomePrices", [])
                    if len(poly_prices) >= 1:
                        poly_yes = Decimal(str(poly_prices[0]))
                    else:
                        continue

                    # TODO: Fetch Kalshi price via their API
                    # For now, we can't compare without Kalshi prices
                    # This would require Kalshi API integration

                except Exception:
                    continue

            return opportunities

        except Exception as e:
            logger.error("Failed to find arbitrage", error=str(e))
            return []


# Singleton instance
dome_client = DomeAPIClient()
