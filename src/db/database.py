"""
Database connection and session management.
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from src.db.models import (
    Base,
    User,
    Wallet,
    Position,
    Order,
    MarketCache,
    FeeBalance,
    FeeTransaction,
    ChainFamily,
    Platform,
    Chain,
    OrderStatus,
    PositionStatus,
)
from src.utils.logging import get_logger
from decimal import Decimal

logger = get_logger(__name__)

# Global engine and session factory
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


async def init_db(database_url: str) -> None:
    """Initialize database connection."""
    global _engine, _session_factory
    
    # Convert postgres:// to postgresql+asyncpg://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    logger.info("Database connection initialized")


async def create_tables() -> None:
    """Create all database tables."""
    if _engine is None:
        raise RuntimeError("Database not initialized")
    
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database tables created")


async def close_db() -> None:
    """Close database connection."""
    global _engine, _session_factory
    
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ===================
# User Operations
# ===================

async def get_or_create_user(
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> User:
    """Get existing user or create new one."""
    async with get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.wallets))
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update user info if changed
            if username != user.username or first_name != user.first_name:
                user.username = username
                user.first_name = first_name
                user.last_name = last_name
            return user
        
        # Create new user
        user = User(
            id=generate_id(),
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)
        await session.flush()
        
        logger.info("Created new user", telegram_id=telegram_id)
        return user


async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID."""
    async with get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.wallets))
        )
        return result.scalar_one_or_none()


async def update_user_platform(telegram_id: int, platform: Platform) -> None:
    """Update user's active platform."""
    async with get_session() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(active_platform=platform)
        )


# ===================
# Wallet Operations
# ===================

async def create_wallet(
    user_id: str,
    chain_family: ChainFamily,
    public_key: str,
    encrypted_private_key: str,
    pin_protected: bool = False,
) -> Wallet:
    """Create a new wallet for user."""
    async with get_session() as session:
        wallet = Wallet(
            id=generate_id(),
            user_id=user_id,
            chain_family=chain_family,
            public_key=public_key,
            encrypted_private_key=encrypted_private_key,
            pin_protected=pin_protected,
        )
        session.add(wallet)
        await session.flush()

        logger.info(
            "Created wallet",
            user_id=user_id,
            chain_family=chain_family.value,
            pin_protected=pin_protected,
        )
        return wallet


async def get_wallet(user_id: str, chain_family: ChainFamily) -> Optional[Wallet]:
    """Get user's wallet for a chain family."""
    async with get_session() as session:
        result = await session.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .where(Wallet.chain_family == chain_family)
        )
        return result.scalar_one_or_none()


async def get_user_wallets(user_id: str) -> list[Wallet]:
    """Get all wallets for a user."""
    async with get_session() as session:
        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        return list(result.scalars().all())


async def delete_user_wallets(user_id: str) -> bool:
    """Delete all wallets for a user."""
    async with get_session() as session:
        result = await session.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        wallets = list(result.scalars().all())

        for wallet in wallets:
            await session.delete(wallet)

        await session.commit()
        logger.info("Deleted user wallets", user_id=user_id, count=len(wallets))
        return True


# ===================
# Position Operations
# ===================

async def create_position(
    user_id: str,
    platform: Platform,
    chain: Chain,
    market_id: str,
    market_title: str,
    outcome: str,
    token_id: str,
    token_amount: str,
    entry_price: float,
    event_id: Optional[str] = None,
) -> Position:
    """Create a new position."""
    from src.db.models import Outcome as OutcomeEnum
    
    async with get_session() as session:
        position = Position(
            id=generate_id(),
            user_id=user_id,
            platform=platform,
            chain=chain,
            market_id=market_id,
            market_title=market_title,
            event_id=event_id,
            outcome=OutcomeEnum(outcome.lower()),
            token_id=token_id,
            token_amount=token_amount,
            entry_price=entry_price,
        )
        session.add(position)
        await session.flush()
        
        logger.info("Created position", user_id=user_id, market_id=market_id)
        return position


async def get_user_positions(
    user_id: str,
    platform: Optional[Platform] = None,
    status: Optional[PositionStatus] = None,
) -> list[Position]:
    """Get user's positions with optional filters."""
    async with get_session() as session:
        query = select(Position).where(Position.user_id == user_id)
        
        if platform:
            query = query.where(Position.platform == platform)
        if status:
            query = query.where(Position.status == status)
        
        query = query.order_by(Position.created_at.desc())
        
        result = await session.execute(query)
        return list(result.scalars().all())


async def update_position(
    position_id: str,
    **kwargs,
) -> None:
    """Update a position."""
    async with get_session() as session:
        await session.execute(
            update(Position)
            .where(Position.id == position_id)
            .values(**kwargs)
        )


# ===================
# Order Operations
# ===================

async def create_order(
    user_id: str,
    platform: Platform,
    chain: Chain,
    market_id: str,
    outcome: str,
    side: str,
    input_token: str,
    input_amount: str,
    output_token: str,
    expected_output: str,
    event_id: Optional[str] = None,
    price: Optional[float] = None,
) -> Order:
    """Create a new order."""
    from src.db.models import Outcome as OutcomeEnum, OrderSide
    
    async with get_session() as session:
        order = Order(
            id=generate_id(),
            user_id=user_id,
            platform=platform,
            chain=chain,
            market_id=market_id,
            event_id=event_id,
            outcome=OutcomeEnum(outcome.lower()),
            side=OrderSide(side.lower()),
            input_token=input_token,
            input_amount=input_amount,
            output_token=output_token,
            expected_output=expected_output,
            price=price,
        )
        session.add(order)
        await session.flush()
        
        logger.info("Created order", user_id=user_id, order_id=order.id)
        return order


async def update_order(
    order_id: str,
    **kwargs,
) -> None:
    """Update an order."""
    async with get_session() as session:
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(**kwargs)
        )


async def get_user_orders(
    user_id: str,
    platform: Optional[Platform] = None,
    limit: int = 20,
) -> list[Order]:
    """Get user's order history."""
    async with get_session() as session:
        query = select(Order).where(Order.user_id == user_id)
        
        if platform:
            query = query.where(Order.platform == platform)
        
        query = query.order_by(Order.created_at.desc()).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())


# ===================
# Market Cache Operations
# ===================

async def cache_market(
    platform: Platform,
    market_id: str,
    title: str,
    **kwargs,
) -> MarketCache:
    """Cache market data (upsert)."""
    async with get_session() as session:
        # Check if exists
        result = await session.execute(
            select(MarketCache)
            .where(MarketCache.platform == platform)
            .where(MarketCache.market_id == market_id)
        )
        market = result.scalar_one_or_none()
        
        if market:
            # Update existing
            for key, value in kwargs.items():
                if hasattr(market, key):
                    setattr(market, key, value)
            market.title = title
        else:
            # Create new
            market = MarketCache(
                id=generate_id(),
                platform=platform,
                market_id=market_id,
                title=title,
                **kwargs,
            )
            session.add(market)
        
        await session.flush()
        return market


async def get_cached_markets(
    platform: Platform,
    limit: int = 20,
    active_only: bool = True,
) -> list[MarketCache]:
    """Get cached markets for a platform."""
    async with get_session() as session:
        query = select(MarketCache).where(MarketCache.platform == platform)

        if active_only:
            query = query.where(MarketCache.is_active == True)

        query = query.order_by(MarketCache.updated_at.desc()).limit(limit)

        result = await session.execute(query)
        return list(result.scalars().all())


# ===================
# Referral Operations
# ===================

def generate_referral_code(telegram_id: int) -> str:
    """Generate referral code from Telegram ID."""
    return str(telegram_id)


async def get_or_create_referral_code(user_id: str) -> str:
    """Get user's referral code or create one if not exists."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError(f"User {user_id} not found")

        if user.referral_code:
            return user.referral_code

        # Use Telegram ID as referral code
        code = generate_referral_code(user.telegram_id)

        user.referral_code = code
        await session.flush()

        logger.info("Generated referral code", user_id=user_id, code=code)
        return code


async def get_user_by_referral_code(referral_code: str) -> Optional[User]:
    """Get user by their referral code."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.referral_code == referral_code)
        )
        return result.scalar_one_or_none()


async def set_user_referrer(user_id: str, referrer_id: str) -> bool:
    """Set a user's referrer (only if not already set)."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        # Don't overwrite existing referrer
        if user.referred_by_id:
            return False

        # Don't allow self-referral
        if user_id == referrer_id:
            return False

        user.referred_by_id = referrer_id
        await session.flush()

        logger.info("Set user referrer", user_id=user_id, referrer_id=referrer_id)
        return True


async def get_referral_chain(user_id: str) -> list[User]:
    """
    Get the referral chain for a user (up to 3 tiers).
    Returns [tier1_referrer, tier2_referrer, tier3_referrer] or fewer if chain is shorter.
    """
    chain = []
    current_id = user_id

    async with get_session() as session:
        for _ in range(3):
            result = await session.execute(
                select(User).where(User.id == current_id)
            )
            user = result.scalar_one_or_none()

            if not user or not user.referred_by_id:
                break

            # Get the referrer
            referrer_result = await session.execute(
                select(User).where(User.id == user.referred_by_id)
            )
            referrer = referrer_result.scalar_one_or_none()

            if referrer:
                chain.append(referrer)
                current_id = referrer.id
            else:
                break

    return chain


async def get_referral_stats(user_id: str) -> dict:
    """Get referral statistics for a user."""
    async with get_session() as session:
        # Count tier 1 (direct referrals)
        tier1_result = await session.execute(
            select(User).where(User.referred_by_id == user_id)
        )
        tier1_users = list(tier1_result.scalars().all())
        tier1_count = len(tier1_users)

        # Count tier 2
        tier2_count = 0
        tier2_user_ids = []
        for t1_user in tier1_users:
            t2_result = await session.execute(
                select(User).where(User.referred_by_id == t1_user.id)
            )
            t2_users = list(t2_result.scalars().all())
            tier2_count += len(t2_users)
            tier2_user_ids.extend([u.id for u in t2_users])

        # Count tier 3
        tier3_count = 0
        for t2_id in tier2_user_ids:
            t3_result = await session.execute(
                select(User).where(User.referred_by_id == t2_id)
            )
            tier3_count += len(list(t3_result.scalars().all()))

        return {
            "tier1": tier1_count,
            "tier2": tier2_count,
            "tier3": tier3_count,
            "total": tier1_count + tier2_count + tier3_count,
        }


# ===================
# Fee Balance Operations
# ===================

async def get_or_create_fee_balance(user_id: str, chain_family: ChainFamily) -> FeeBalance:
    """Get or create fee balance for a user on a specific chain."""
    async with get_session() as session:
        result = await session.execute(
            select(FeeBalance)
            .where(FeeBalance.user_id == user_id)
            .where(FeeBalance.chain_family == chain_family)
        )
        balance = result.scalar_one_or_none()

        if balance:
            return balance

        balance = FeeBalance(
            id=generate_id(),
            user_id=user_id,
            chain_family=chain_family,
            claimable_usdc="0",
            total_earned_usdc="0",
            total_withdrawn_usdc="0",
        )
        session.add(balance)
        await session.flush()

        return balance


async def add_referral_earnings(
    user_id: str,
    amount_usdc: str,
    source_user_id: str,
    order_id: str,
    tier: int,
    chain_family: ChainFamily,
) -> None:
    """Add referral earnings to a user's balance for a specific chain."""
    async with get_session() as session:
        # Get or create fee balance for this chain
        result = await session.execute(
            select(FeeBalance)
            .where(FeeBalance.user_id == user_id)
            .where(FeeBalance.chain_family == chain_family)
        )
        balance = result.scalar_one_or_none()

        if not balance:
            balance = FeeBalance(
                id=generate_id(),
                user_id=user_id,
                chain_family=chain_family,
                claimable_usdc="0",
                total_earned_usdc="0",
                total_withdrawn_usdc="0",
            )
            session.add(balance)

        # Update balances
        current_claimable = Decimal(balance.claimable_usdc)
        current_total = Decimal(balance.total_earned_usdc)
        add_amount = Decimal(amount_usdc)

        balance.claimable_usdc = str(current_claimable + add_amount)
        balance.total_earned_usdc = str(current_total + add_amount)

        # Create transaction record
        tx_type = f"referral_tier{tier}"
        tx = FeeTransaction(
            id=generate_id(),
            user_id=user_id,
            order_id=order_id,
            chain_family=chain_family,
            tx_type=tx_type,
            amount_usdc=amount_usdc,
            source_user_id=source_user_id,
            tier=tier,
        )
        session.add(tx)

        await session.flush()

        logger.info(
            "Added referral earnings",
            user_id=user_id,
            amount=amount_usdc,
            tier=tier,
            chain=chain_family.value,
            source_user_id=source_user_id,
        )


async def process_withdrawal(
    user_id: str,
    amount_usdc: str,
    tx_hash: str,
    withdrawal_address: str,
    chain_family: ChainFamily,
) -> bool:
    """Process a withdrawal from user's fee balance for a specific chain."""
    async with get_session() as session:
        result = await session.execute(
            select(FeeBalance)
            .where(FeeBalance.user_id == user_id)
            .where(FeeBalance.chain_family == chain_family)
        )
        balance = result.scalar_one_or_none()

        if not balance:
            return False

        current_claimable = Decimal(balance.claimable_usdc)
        withdraw_amount = Decimal(amount_usdc)

        if withdraw_amount > current_claimable:
            return False

        # Update balance
        balance.claimable_usdc = str(current_claimable - withdraw_amount)
        balance.total_withdrawn_usdc = str(
            Decimal(balance.total_withdrawn_usdc) + withdraw_amount
        )

        # Create transaction record
        tx = FeeTransaction(
            id=generate_id(),
            user_id=user_id,
            chain_family=chain_family,
            tx_type="withdrawal",
            amount_usdc=amount_usdc,
            withdrawal_tx_hash=tx_hash,
            withdrawal_address=withdrawal_address,
        )
        session.add(tx)

        await session.flush()

        logger.info(
            "Processed withdrawal",
            user_id=user_id,
            amount=amount_usdc,
            chain=chain_family.value,
            tx_hash=tx_hash,
        )
        return True


async def get_fee_balance(user_id: str, chain_family: ChainFamily) -> Optional[FeeBalance]:
    """Get fee balance for a user on a specific chain."""
    async with get_session() as session:
        result = await session.execute(
            select(FeeBalance)
            .where(FeeBalance.user_id == user_id)
            .where(FeeBalance.chain_family == chain_family)
        )
        return result.scalar_one_or_none()


async def get_all_fee_balances(user_id: str) -> list[FeeBalance]:
    """Get all fee balances for a user across all chains."""
    async with get_session() as session:
        result = await session.execute(
            select(FeeBalance).where(FeeBalance.user_id == user_id)
        )
        return list(result.scalars().all())


# ===================
# PnL Operations
# ===================

async def get_orders_for_pnl(
    user_id: str,
    platform: Optional[Platform] = None,
    since: Optional["datetime"] = None,
) -> list[Order]:
    """Get confirmed orders for PnL calculation."""
    from datetime import datetime

    async with get_session() as session:
        query = select(Order).where(
            Order.user_id == user_id,
            Order.status == OrderStatus.CONFIRMED,
        )

        if platform:
            query = query.where(Order.platform == platform)
        if since:
            query = query.where(Order.executed_at >= since)

        query = query.order_by(Order.executed_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())


async def get_positions_for_pnl(
    user_id: str,
    platform: Optional[Platform] = None,
    include_open: bool = True,
    include_closed: bool = True,
) -> list[Position]:
    """Get positions for PnL calculation."""
    async with get_session() as session:
        query = select(Position).where(Position.user_id == user_id)

        if platform:
            query = query.where(Position.platform == platform)

        # Filter by status
        statuses = []
        if include_open:
            statuses.append(PositionStatus.OPEN)
        if include_closed:
            statuses.extend([PositionStatus.CLOSED, PositionStatus.REDEEMED])

        if statuses:
            query = query.where(Position.status.in_(statuses))

        query = query.order_by(Position.created_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())
