"""
SQLAlchemy database models for Spredd Markets Bot.
Supports multi-platform trading with shared EVM wallets.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""
    pass


# ===================
# Enums
# ===================

class ChainFamily(str, Enum):
    """Blockchain families for wallet organization."""
    SOLANA = "solana"  # For Kalshi/DFlow
    EVM = "evm"        # For Polymarket (Polygon) and Opinion (BSC)


class Platform(str, Enum):
    """Supported prediction market platforms."""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"
    OPINION = "opinion"


class Chain(str, Enum):
    """Specific blockchain networks."""
    SOLANA = "solana"
    POLYGON = "polygon"
    BSC = "bsc"


class Outcome(str, Enum):
    """Prediction market outcomes."""
    YES = "yes"
    NO = "no"


class OrderSide(str, Enum):
    """Order sides."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order execution status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PositionStatus(str, Enum):
    """Position status."""
    OPEN = "open"
    CLOSED = "closed"
    REDEEMED = "redeemed"
    EXPIRED = "expired"


# ===================
# Models
# ===================

class User(Base):
    """Telegram user with platform preferences."""
    
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Platform preference
    active_platform: Mapped[Platform] = mapped_column(
        SQLEnum(Platform), 
        default=Platform.KALSHI
    )
    
    # Trading preferences
    default_slippage_bps: Mapped[int] = mapped_column(Integer, default=100)  # 1%
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    
    # Relationships
    wallets: Mapped[list["Wallet"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    positions: Mapped[list["Position"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Wallet(Base):
    """
    User wallets organized by chain family.
    One Solana wallet + one EVM wallet per user.
    EVM wallet is shared between Polygon and BSC.
    """

    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))

    # Chain family determines wallet type
    chain_family: Mapped[ChainFamily] = mapped_column(SQLEnum(ChainFamily))

    # Wallet addresses
    public_key: Mapped[str] = mapped_column(String(255), index=True)

    # Encrypted private key (AES-256-GCM)
    encrypted_private_key: Mapped[str] = mapped_column(Text)

    # PIN protection - if True, user PIN is required to decrypt
    # PIN is never stored, only used in key derivation
    pin_protected: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="wallets")

    # One wallet per chain family per user
    __table_args__ = (
        Index("ix_wallets_user_chain", "user_id", "chain_family", unique=True),
    )


class Position(Base):
    """User's prediction market positions across platforms."""
    
    __tablename__ = "positions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    
    # Platform and chain
    platform: Mapped[Platform] = mapped_column(SQLEnum(Platform))
    chain: Mapped[Chain] = mapped_column(SQLEnum(Chain))
    
    # Market information
    market_id: Mapped[str] = mapped_column(String(255))
    market_title: Mapped[str] = mapped_column(Text)
    event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Position details
    outcome: Mapped[Outcome] = mapped_column(SQLEnum(Outcome))
    token_id: Mapped[str] = mapped_column(String(255))  # Token mint/address
    
    # Amounts (stored as string for precision)
    token_amount: Mapped[str] = mapped_column(String(78))  # BigInt as string
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    
    # Status
    status: Mapped[PositionStatus] = mapped_column(
        SQLEnum(PositionStatus),
        default=PositionStatus.OPEN
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="positions")
    
    __table_args__ = (
        Index("ix_positions_user_status", "user_id", "status"),
        Index("ix_positions_market", "market_id"),
    )


class Order(Base):
    """Order history across all platforms."""
    
    __tablename__ = "orders"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    
    # Platform and chain
    platform: Mapped[Platform] = mapped_column(SQLEnum(Platform))
    chain: Mapped[Chain] = mapped_column(SQLEnum(Chain))
    
    # Market information
    market_id: Mapped[str] = mapped_column(String(255))
    event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Order details
    outcome: Mapped[Outcome] = mapped_column(SQLEnum(Outcome))
    side: Mapped[OrderSide] = mapped_column(SQLEnum(OrderSide))
    
    # Amounts
    input_token: Mapped[str] = mapped_column(String(255))  # e.g., USDC address
    input_amount: Mapped[str] = mapped_column(String(78))
    output_token: Mapped[str] = mapped_column(String(255))
    expected_output: Mapped[str] = mapped_column(String(78))
    actual_output: Mapped[Optional[str]] = mapped_column(String(78), nullable=True)
    
    # Price info
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    
    # Execution
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus),
        default=OrderStatus.PENDING
    )
    tx_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="orders")
    
    __table_args__ = (
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_tx", "tx_hash"),
    )


class MarketCache(Base):
    """Cached market data for quick lookups."""
    
    __tablename__ = "market_cache"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    platform: Mapped[Platform] = mapped_column(SQLEnum(Platform))
    
    # Market identification
    market_id: Mapped[str] = mapped_column(String(255))
    event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Market info
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Pricing
    yes_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    no_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    
    # Volume
    volume_24h: Mapped[Optional[str]] = mapped_column(String(78), nullable=True)
    liquidity: Mapped[Optional[str]] = mapped_column(String(78), nullable=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    close_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Token addresses
    yes_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    no_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Cache timestamp
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    
    __table_args__ = (
        Index("ix_market_cache_platform_market", "platform", "market_id", unique=True),
        Index("ix_market_cache_active", "is_active"),
    )
