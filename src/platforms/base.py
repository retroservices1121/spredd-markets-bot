"""
Platform abstraction layer for prediction markets.
All platforms implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from src.db.models import Chain, Outcome, Platform


@dataclass
class Market:
    """Unified market representation across platforms."""
    platform: Platform
    chain: Chain

    # Identification
    market_id: str
    event_id: Optional[str]

    # Display info
    title: str
    description: Optional[str]
    category: Optional[str]

    # Pricing (0-1 scale, representing probability)
    yes_price: Optional[Decimal]
    no_price: Optional[Decimal]

    # Liquidity
    volume_24h: Optional[Decimal]
    liquidity: Optional[Decimal]

    # Status
    is_active: bool
    close_time: Optional[str]

    # Token addresses for trading
    yes_token: Optional[str]
    no_token: Optional[str]

    # Platform-specific data
    raw_data: Optional[dict] = None

    # Multi-outcome support
    outcome_name: Optional[str] = None  # Short name for this outcome (e.g., "Trump", "Biden")
    is_multi_outcome: bool = False  # True if part of a multi-outcome event
    related_market_count: int = 0  # Number of related markets in the same event
    
    @property
    def yes_probability(self) -> Optional[float]:
        """YES probability as percentage."""
        if self.yes_price:
            return float(self.yes_price * 100)
        return None
    
    @property
    def no_probability(self) -> Optional[float]:
        """NO probability as percentage."""
        if self.no_price:
            return float(self.no_price * 100)
        return None


@dataclass
class Quote:
    """Quote for a potential trade."""
    platform: Platform
    chain: Chain
    market_id: str

    # Trade details
    outcome: Outcome
    side: str  # "buy" or "sell"

    # Input
    input_token: str
    input_amount: Decimal

    # Output
    output_token: str
    expected_output: Decimal

    # Pricing
    price_per_token: Decimal
    price_impact: Optional[Decimal]

    # Fees
    platform_fee: Optional[Decimal]
    network_fee_estimate: Optional[Decimal]

    # Expiry
    expires_at: Optional[str]

    # Platform-specific quote data needed for execution
    quote_data: Optional[dict] = None


@dataclass
class TradeResult:
    """Result of an executed trade."""
    success: bool

    # Transaction
    tx_hash: Optional[str]

    # Amounts
    input_amount: Decimal
    output_amount: Optional[Decimal]

    # Error
    error_message: Optional[str]

    # Block explorer link
    explorer_url: Optional[str]


@dataclass
class RedemptionResult:
    """Result of redeeming a resolved position."""
    success: bool

    # Transaction
    tx_hash: Optional[str]

    # Amount redeemed in collateral (USDC)
    amount_redeemed: Optional[Decimal]

    # Error
    error_message: Optional[str]

    # Block explorer link
    explorer_url: Optional[str]


@dataclass
class MarketResolution:
    """Market resolution status and outcome."""
    is_resolved: bool
    winning_outcome: Optional[str]  # "yes", "no", or None if not resolved
    resolution_time: Optional[str]


@dataclass
class OrderBook:
    """Order book snapshot."""
    market_id: str
    outcome: Outcome
    
    # Bids: list of (price, size) tuples
    bids: list[tuple[Decimal, Decimal]]
    
    # Asks: list of (price, size) tuples
    asks: list[tuple[Decimal, Decimal]]
    
    @property
    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0][0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0][0] if self.asks else None
    
    @property
    def spread(self) -> Optional[Decimal]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


class PlatformError(Exception):
    """Base exception for platform errors."""
    def __init__(self, message: str, platform: Platform, code: Optional[str] = None):
        self.message = message
        self.platform = platform
        self.code = code
        super().__init__(f"[{platform.value}] {message}")


class InsufficientBalanceError(PlatformError):
    """Raised when user has insufficient balance."""
    pass


class MarketNotFoundError(PlatformError):
    """Raised when market is not found."""
    pass


class MarketClosedError(PlatformError):
    """Raised when market is closed."""
    pass


class RateLimitError(PlatformError):
    """Raised when rate limit is hit."""
    pass


class BasePlatform(ABC):
    """Abstract base class for prediction market platforms."""
    
    # Platform identification
    platform: Platform
    chain: Chain
    
    # Display
    name: str
    description: str
    website: str
    
    # Collateral token
    collateral_symbol: str
    collateral_decimals: int
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the platform client."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close connections and cleanup."""
        pass
    
    # ===================
    # Market Discovery
    # ===================
    
    @abstractmethod
    async def get_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets with pagination support."""
        pass
    
    @abstractmethod
    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets by query."""
        pass
    
    @abstractmethod
    async def get_market(self, market_id: str, search_title: Optional[str] = None) -> Optional[Market]:
        """Get a specific market by ID.

        Args:
            market_id: The market identifier
            search_title: Optional title hint for platforms that need it for lookup
        """
        pass
    
    @abstractmethod
    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending/popular markets."""
        pass

    async def get_related_markets(self, event_id: str) -> list[Market]:
        """Get all markets related to an event (for multi-outcome events).

        Args:
            event_id: The event identifier

        Returns:
            List of markets belonging to the same event, sorted by probability
        """
        # Default implementation - platforms should override for multi-outcome support
        return []

    # ===================
    # Order Book
    # ===================
    
    @abstractmethod
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
    ) -> OrderBook:
        """Get order book for a market outcome."""
        pass
    
    # ===================
    # Trading
    # ===================
    
    @abstractmethod
    async def get_quote(
        self,
        market_id: str,
        outcome: Outcome,
        side: str,
        amount: Decimal,
        token_id: str = None,
    ) -> Quote:
        """
        Get a quote for a potential trade.

        Args:
            market_id: Market identifier
            outcome: YES or NO
            side: "buy" or "sell"
            amount: Amount in collateral (e.g., USDC)
            token_id: Optional token ID (used by Polymarket for sells)

        Returns:
            Quote with expected output and fees
        """
        pass
    
    @abstractmethod
    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,  # Type depends on chain
    ) -> TradeResult:
        """
        Execute a trade from a quote.
        
        Args:
            quote: Quote obtained from get_quote
            private_key: User's private key for signing
            
        Returns:
            TradeResult with transaction hash
        """
        pass

    # ===================
    # Redemption
    # ===================

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """
        Check if a market has resolved and what the outcome is.

        Args:
            market_id: Market identifier

        Returns:
            MarketResolution with resolution status and winning outcome
        """
        # Default implementation - subclasses should override
        return MarketResolution(
            is_resolved=False,
            winning_outcome=None,
            resolution_time=None,
        )

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """
        Redeem winning tokens from a resolved market.

        Args:
            market_id: Market identifier
            outcome: The outcome tokens to redeem (YES or NO)
            token_amount: Amount of tokens to redeem
            private_key: User's private key for signing

        Returns:
            RedemptionResult with transaction hash and amount redeemed
        """
        # Default implementation - subclasses should override
        return RedemptionResult(
            success=False,
            tx_hash=None,
            amount_redeemed=None,
            error_message="Redemption not supported on this platform",
            explorer_url=None,
        )

    # ===================
    # Utilities
    # ===================
    
    def format_price(self, price: Decimal) -> str:
        """Format price for display (0-100 cents)."""
        cents = int(price * 100)
        return f"{cents}¢"
    
    def format_probability(self, price: Decimal) -> str:
        """Format price as probability percentage."""
        return f"{float(price * 100):.1f}%"
    
    def get_explorer_url(self, tx_hash: str) -> str:
        """Get block explorer URL for transaction."""
        explorers = {
            Chain.SOLANA: f"https://solscan.io/tx/{tx_hash}",
            Chain.POLYGON: f"https://polygonscan.com/tx/{tx_hash}",
            Chain.BSC: f"https://bscscan.com/tx/{tx_hash}",
            Chain.BASE: f"https://basescan.org/tx/{tx_hash}",
            Chain.MONAD: f"https://monadscan.com/tx/{tx_hash}",
        }
        return explorers.get(self.chain, tx_hash)
