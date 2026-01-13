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
    LIMITLESS = "limitless"


class Chain(str, Enum):
    """Specific blockchain networks."""
    SOLANA = "solana"
    POLYGON = "polygon"
    BSC = "bsc"
    BASE = "base"
    MONAD = "monad"


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

    # Referral system
    referral_code: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True, index=True)
    referred_by_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

    # Partner attribution (for revenue sharing)
    partner_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("partners.id"), nullable=True, index=True)
    partner_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # TG group where user was attributed

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
    referred_by: Mapped[Optional["User"]] = relationship("User", remote_side=[id], foreign_keys=[referred_by_id])
    fee_balances: Mapped[list["FeeBalance"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    partner: Mapped[Optional["Partner"]] = relationship(back_populates="users", foreign_keys=[partner_id])


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
    pin_protected: Mapped[bool] = mapped_column(Boolean, default=False)

    # Export PIN hash - for verifying PIN during key export
    # PIN itself is never stored, only the hash for verification
    export_pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

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


class FeeBalance(Base):
    """
    Tracks referral fee earnings for users by chain family.
    Each user has separate balances for Solana and EVM chains.
    Earnings come from referral commissions on trading fees.
    """

    __tablename__ = "fee_balances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))

    # Chain family - separate balances for Solana vs EVM
    chain_family: Mapped[ChainFamily] = mapped_column(
        SQLEnum(ChainFamily),
        default=ChainFamily.EVM
    )

    # Claimable balance (in USDC, stored as string for precision)
    claimable_usdc: Mapped[str] = mapped_column(String(78), default="0")

    # Total earned (lifetime)
    total_earned_usdc: Mapped[str] = mapped_column(String(78), default="0")

    # Total withdrawn
    total_withdrawn_usdc: Mapped[str] = mapped_column(String(78), default="0")

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
    user: Mapped["User"] = relationship(back_populates="fee_balances")

    # One balance per chain family per user
    __table_args__ = (
        Index("ix_fee_balances_user_chain", "user_id", "chain_family", unique=True),
    )


class FeeTransaction(Base):
    """
    Records individual fee transactions for audit trail.
    Tracks both fee collection and referral distributions.
    """

    __tablename__ = "fee_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # The user who earned/paid the fee
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))

    # Related order (if applicable)
    order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("orders.id"), nullable=True)

    # Chain family - which chain the fee was earned on
    chain_family: Mapped[ChainFamily] = mapped_column(
        SQLEnum(ChainFamily),
        default=ChainFamily.EVM
    )

    # Transaction type
    tx_type: Mapped[str] = mapped_column(String(32))  # "fee_collected", "referral_tier1", "referral_tier2", "referral_tier3", "withdrawal"

    # Amount in USDC
    amount_usdc: Mapped[str] = mapped_column(String(78))

    # For referral earnings, track the source user who generated the fee
    source_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

    # Tier level for referral transactions (1, 2, or 3)
    tier: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Withdrawal details
    withdrawal_tx_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    withdrawal_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (
        Index("ix_fee_tx_user", "user_id"),
        Index("ix_fee_tx_type", "tx_type"),
        Index("ix_fee_tx_order", "order_id"),
        Index("ix_fee_tx_chain", "chain_family"),
    )


# ===================
# Partner Revenue Sharing
# ===================

class Partner(Base):
    """
    Partner entities for revenue sharing program.
    Partners can add the bot to their groups and earn a percentage of fees
    generated by users who come from their groups.
    """

    __tablename__ = "partners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Partner identification
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # Unique partner code

    # Contact info
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # Partner's TG user ID
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Email, etc.

    # Revenue share configuration (in basis points, e.g., 1000 = 10%)
    revenue_share_bps: Mapped[int] = mapped_column(Integer, default=1000)  # Default 10%

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Stats (denormalized for quick access)
    total_users: Mapped[int] = mapped_column(Integer, default=0)
    total_volume_usdc: Mapped[str] = mapped_column(String(78), default="0")
    total_fees_usdc: Mapped[str] = mapped_column(String(78), default="0")
    total_paid_usdc: Mapped[str] = mapped_column(String(78), default="0")  # Amount already paid out

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
    groups: Mapped[list["PartnerGroup"]] = relationship(back_populates="partner", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="partner", foreign_keys="User.partner_id")


class PartnerGroup(Base):
    """
    Maps Telegram groups to partners.
    When bot is added to a group via partner link, the group is tracked here.
    """

    __tablename__ = "partner_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    partner_id: Mapped[str] = mapped_column(String(36), ForeignKey("partners.id", ondelete="CASCADE"))

    # Telegram group info
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32), default="group")  # group, supergroup, channel

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_removed: Mapped[bool] = mapped_column(Boolean, default=False)  # True if bot was kicked

    # Revenue share override (nullable - falls back to partner default if not set)
    revenue_share_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Stats
    users_attributed: Mapped[int] = mapped_column(Integer, default=0)

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
    partner: Mapped["Partner"] = relationship(back_populates="groups")
