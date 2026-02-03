"""Pydantic schemas for API responses."""
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
from pydantic import BaseModel, Field


class MarketResponse(BaseModel):
    """Market data response."""
    id: str
    question: str
    description: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    outcomes: list[str] = []
    outcomePrices: list[str] = []
    clobTokenIds: list[str] = []
    volume: Optional[float] = None
    volume24hr: Optional[float] = None
    liquidity: Optional[float] = None
    openInterest: Optional[float] = None
    endDate: Optional[str] = None
    startDate: Optional[str] = None
    active: bool = True
    closed: bool = False
    slug: Optional[str] = None
    platform: str = "polymarket"

    # Additional fields
    negRisk: Optional[bool] = None
    groupItemTitle: Optional[str] = None
    marketType: Optional[str] = None
    subtitle: Optional[str] = None

    # Event grouping fields for multi-outcome markets
    eventId: Optional[str] = None
    eventTitle: Optional[str] = None
    eventSlug: Optional[str] = None
    isMultiOutcome: bool = False  # True if part of a multi-outcome event
    outcomeCount: Optional[int] = None  # Number of outcomes in the event

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    """Event (grouped markets) response."""
    id: str
    title: str
    description: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    slug: Optional[str] = None
    markets: list[MarketResponse] = []
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    category: Optional[str] = None
    featured: bool = False
    volume: Optional[float] = None
    volume24hr: Optional[float] = None
    liquidity: Optional[float] = None
    platform: str = "polymarket"

    class Config:
        from_attributes = True


class PricePointResponse(BaseModel):
    """Price history point."""
    t: int  # timestamp
    p: float  # price


class OrderBookEntryResponse(BaseModel):
    """Order book entry."""
    price: str
    size: str


class OrderBookResponse(BaseModel):
    """Order book response."""
    bids: list[OrderBookEntryResponse] = []
    asks: list[OrderBookEntryResponse] = []


class MarketStatsResponse(BaseModel):
    """24h market stats."""
    volume24h: float = 0
    priceChange24h: float = 0
    priceChangePercent24h: float = 0
    high24h: float = 0
    low24h: float = 0
    trades24h: int = 0


class TradeResponse(BaseModel):
    """Recent trade."""
    id: str
    timestamp: int
    price: float
    size: float
    side: str  # BUY or SELL


class CategoryResponse(BaseModel):
    """Category with count."""
    id: str
    label: str
    emoji: str
    count: int = 0


class TagResponse(BaseModel):
    """Tag response."""
    id: str
    label: str
    slug: str


class TrendingTagResponse(BaseModel):
    """Trending tag with stats."""
    tag: str
    slug: str
    eventCount: int
    totalVolume: float
    score: float


class HealthResponse(BaseModel):
    """Health check response."""
    healthy: bool
    platforms: dict[str, bool] = {}


class ArbitrageOpportunityResponse(BaseModel):
    """Cross-platform arbitrage opportunity."""
    id: str
    market_title: str
    buy_platform: str  # Platform to buy on (cheaper)
    sell_platform: str  # Platform to sell on (more expensive)
    buy_market_id: str
    sell_market_id: str
    buy_price: float  # YES price on buy platform
    sell_price: float  # YES price on sell platform
    spread_cents: int  # Spread in cents (e.g., 5 = 5¢)
    profit_potential: float  # Estimated profit % after fees
    buy_title: str = ""
    sell_title: str = ""
    detected_at: Optional[str] = None


class ArbitrageResponse(BaseModel):
    """Arbitrage opportunities response."""
    opportunities: list[ArbitrageOpportunityResponse] = []
    count: int = 0
    timestamp: str
