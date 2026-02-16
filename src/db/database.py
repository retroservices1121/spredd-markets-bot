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
    Partner,
    PartnerGroup,
    SystemConfig,
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
    """Get an async database session (context manager for internal use)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session (FastAPI dependency)."""
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
        # Use raw SQL with uppercase enum name to match SQLAlchemy's expectation
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET active_platform = :platform, updated_at = now() WHERE telegram_id = :tid"),
            {"platform": platform.name, "tid": telegram_id}
        )


async def update_user_country(telegram_id: int, country_code: str) -> None:
    """Update user's country (ISO 3166-1 alpha-2 code) - deprecated, use set_user_country_verified."""
    async with get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET country = :country, updated_at = now() WHERE telegram_id = :tid"),
            {"country": country_code.upper(), "tid": telegram_id}
        )


async def set_user_geo_token(telegram_id: int, token: str) -> None:
    """Set geo verification token for a user."""
    async with get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET geo_verify_token = :token, updated_at = now() WHERE telegram_id = :tid"),
            {"token": token, "tid": telegram_id}
        )


async def get_user_by_geo_token(token: str) -> Optional[User]:
    """Get user by their geo verification token."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.geo_verify_token == token)
        )
        return result.scalar_one_or_none()


async def set_user_country_verified(user_id: str, country_code: str) -> None:
    """Set user's country as verified from IP detection."""
    async with get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("""
                UPDATE users
                SET country = :country,
                    country_verified_at = now(),
                    geo_verify_token = NULL,
                    updated_at = now()
                WHERE id = :uid
            """),
            {"country": country_code.upper(), "uid": user_id}
        )


async def clear_user_geo_token(user_id: str) -> None:
    """Clear the geo verification token after use or expiry."""
    async with get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET geo_verify_token = NULL, updated_at = now() WHERE id = :uid"),
            {"uid": user_id}
        )


async def set_user_proof_verified(user_id: str) -> None:
    """Mark user's Solana wallet as DFlow Proof KYC verified."""
    async with get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET proof_verified_at = now(), updated_at = now() WHERE id = :uid"),
            {"uid": user_id}
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
    export_pin_hash: Optional[str] = None,
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
            export_pin_hash=export_pin_hash,
        )
        session.add(wallet)
        await session.flush()

        logger.info(
            "Created wallet",
            user_id=user_id,
            chain_family=chain_family.value,
            has_export_pin=bool(export_pin_hash),
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


async def get_position_by_id(position_id: str) -> Optional[Position]:
    """Get a position by its ID."""
    async with get_session() as session:
        result = await session.execute(
            select(Position).where(Position.id == position_id)
        )
        return result.scalar_one_or_none()


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


async def delete_position_by_token_id(token_id: str) -> int:
    """Delete a position by its token_id. Returns number of deleted rows."""
    async with get_session() as session:
        result = await session.execute(
            delete(Position).where(Position.token_id == token_id)
        )
        return result.rowcount


async def delete_position_by_id(position_id: str) -> bool:
    """Delete a position by its ID. Returns True if deleted."""
    async with get_session() as session:
        result = await session.execute(
            delete(Position).where(Position.id == position_id)
        )
        return result.rowcount > 0


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
    market_title: Optional[str] = None,
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
            market_title=market_title,
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


async def get_order_by_id(order_id: str) -> Optional[Order]:
    """Get a specific order by ID."""
    async with get_session() as session:
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()


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


# ===================
# Partner Management
# ===================

async def create_partner(
    name: str,
    code: str,
    revenue_share_bps: int = 1000,
    telegram_user_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
    contact_info: Optional[str] = None,
) -> Partner:
    """Create a new partner for revenue sharing."""
    async with get_session() as session:
        partner = Partner(
            id=generate_id(),
            name=name,
            code=code.lower(),
            revenue_share_bps=revenue_share_bps,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            contact_info=contact_info,
        )
        session.add(partner)
        await session.commit()
        await session.refresh(partner)
        return partner


async def get_partner_by_code(code: str) -> Optional[Partner]:
    """Get partner by their unique code."""
    async with get_session() as session:
        result = await session.execute(
            select(Partner).where(Partner.code == code.lower())
        )
        return result.scalar_one_or_none()


async def get_partner_by_id(partner_id: str) -> Optional[Partner]:
    """Get partner by ID."""
    async with get_session() as session:
        result = await session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        return result.scalar_one_or_none()


async def get_all_partners(active_only: bool = True) -> list[Partner]:
    """Get all partners."""
    async with get_session() as session:
        query = select(Partner).order_by(Partner.created_at.desc())
        if active_only:
            query = query.where(Partner.is_active == True)
        result = await session.execute(query)
        return list(result.scalars().all())


async def update_partner(
    partner_id: str,
    name: Optional[str] = None,
    revenue_share_bps: Optional[int] = None,
    is_active: Optional[bool] = None,
    telegram_user_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
    contact_info: Optional[str] = None,
) -> Optional[Partner]:
    """Update partner details."""
    async with get_session() as session:
        result = await session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        partner = result.scalar_one_or_none()
        if not partner:
            return None

        if name is not None:
            partner.name = name
        if revenue_share_bps is not None:
            partner.revenue_share_bps = revenue_share_bps
        if is_active is not None:
            partner.is_active = is_active
        if telegram_user_id is not None:
            partner.telegram_user_id = telegram_user_id
        if telegram_username is not None:
            partner.telegram_username = telegram_username
        if contact_info is not None:
            partner.contact_info = contact_info

        await session.commit()
        await session.refresh(partner)
        return partner


async def create_partner_group(
    partner_id: str,
    telegram_chat_id: int,
    chat_title: Optional[str] = None,
    chat_type: str = "group",
) -> PartnerGroup:
    """Create a new partner group mapping."""
    async with get_session() as session:
        group = PartnerGroup(
            id=generate_id(),
            partner_id=partner_id,
            telegram_chat_id=telegram_chat_id,
            chat_title=chat_title,
            chat_type=chat_type,
        )
        session.add(group)
        await session.commit()
        await session.refresh(group)
        return group


async def get_partner_group_by_chat_id(chat_id: int) -> Optional[PartnerGroup]:
    """Get partner group by Telegram chat ID."""
    async with get_session() as session:
        result = await session.execute(
            select(PartnerGroup).where(PartnerGroup.telegram_chat_id == chat_id)
        )
        return result.scalar_one_or_none()


async def update_partner_group(
    chat_id: int,
    chat_title: Optional[str] = None,
    is_active: Optional[bool] = None,
    bot_removed: Optional[bool] = None,
    revenue_share_bps: Optional[int] = None,
) -> Optional[PartnerGroup]:
    """Update partner group details."""
    async with get_session() as session:
        result = await session.execute(
            select(PartnerGroup).where(PartnerGroup.telegram_chat_id == chat_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            return None

        if chat_title is not None:
            group.chat_title = chat_title
        if is_active is not None:
            group.is_active = is_active
        if bot_removed is not None:
            group.bot_removed = bot_removed
        if revenue_share_bps is not None:
            group.revenue_share_bps = revenue_share_bps

        await session.commit()
        await session.refresh(group)
        return group


async def clear_partner_group_share(chat_id: int) -> bool:
    """Clear group-specific revenue share (revert to partner default)."""
    async with get_session() as session:
        result = await session.execute(
            select(PartnerGroup).where(PartnerGroup.telegram_chat_id == chat_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            return False

        group.revenue_share_bps = None
        await session.commit()
        return True


async def get_effective_revenue_share(user_id: str) -> tuple[Optional[int], Optional[str], Optional[int]]:
    """
    Get the effective revenue share for a user based on their attributed group.
    Returns (share_bps, partner_id, group_chat_id) or (None, None, None) if not attributed.

    Priority: Group-specific share > Partner default share
    """
    async with get_session() as session:
        # Get user
        user_result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user or not user.partner_id:
            return None, None, None

        # Get partner
        partner_result = await session.execute(
            select(Partner).where(Partner.id == user.partner_id)
        )
        partner = partner_result.scalar_one_or_none()
        if not partner or not partner.is_active:
            return None, None, None

        # Check if user has a group attribution with custom share
        if user.partner_group_id:
            group_result = await session.execute(
                select(PartnerGroup).where(PartnerGroup.telegram_chat_id == user.partner_group_id)
            )
            group = group_result.scalar_one_or_none()
            if group and group.revenue_share_bps is not None:
                # Use group-specific share
                return group.revenue_share_bps, partner.id, user.partner_group_id

        # Fall back to partner default share
        return partner.revenue_share_bps, partner.id, user.partner_group_id


async def attribute_user_to_partner(
    user_id: str,
    partner_id: str,
    partner_group_id: int,
) -> Optional[User]:
    """Attribute a user to a partner (one-time, first interaction)."""
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        # Only attribute if not already attributed
        if user.partner_id is None:
            user.partner_id = partner_id
            user.partner_group_id = partner_group_id

            # Update partner stats
            partner_result = await session.execute(
                select(Partner).where(Partner.id == partner_id)
            )
            partner = partner_result.scalar_one_or_none()
            if partner:
                partner.total_users += 1

            # Update group stats
            group_result = await session.execute(
                select(PartnerGroup).where(PartnerGroup.telegram_chat_id == partner_group_id)
            )
            group = group_result.scalar_one_or_none()
            if group:
                group.users_attributed += 1

            await session.commit()
            await session.refresh(user)

        return user


async def get_partner_stats(partner_id: str) -> dict:
    """Get detailed statistics for a partner."""
    async with get_session() as session:
        # Get partner
        partner_result = await session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        partner = partner_result.scalar_one_or_none()
        if not partner:
            return {}

        # Get groups
        groups_result = await session.execute(
            select(PartnerGroup).where(PartnerGroup.partner_id == partner_id)
        )
        groups = list(groups_result.scalars().all())

        # Get attributed users
        users_result = await session.execute(
            select(User).where(User.partner_id == partner_id)
        )
        users = list(users_result.scalars().all())

        # Calculate total volume from orders
        total_volume = Decimal("0")
        total_fees = Decimal("0")

        for user in users:
            orders_result = await session.execute(
                select(Order).where(
                    Order.user_id == user.id,
                    Order.status == OrderStatus.CONFIRMED,
                )
            )
            orders = list(orders_result.scalars().all())
            for order in orders:
                try:
                    total_volume += Decimal(order.input_amount) / Decimal("1000000")  # USDC decimals
                except:
                    pass

        return {
            "partner": partner,
            "groups": groups,
            "users": users,
            "total_users": len(users),
            "total_groups": len(groups),
            "total_volume_usdc": total_volume,
            "total_fees_usdc": total_fees,
            "revenue_share_bps": partner.revenue_share_bps,
            "owed_usdc": (total_fees * Decimal(partner.revenue_share_bps)) / Decimal("10000"),
        }


async def update_partner_volume(partner_id: str, volume_usdc: Decimal, fee_usdc: Decimal) -> None:
    """Update partner volume and fee stats after a trade."""
    async with get_session() as session:
        result = await session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        partner = result.scalar_one_or_none()
        if partner:
            current_volume = Decimal(partner.total_volume_usdc)
            current_fees = Decimal(partner.total_fees_usdc)
            partner.total_volume_usdc = str(current_volume + volume_usdc)
            partner.total_fees_usdc = str(current_fees + fee_usdc)
            await session.commit()


# ============================================================================
# Analytics Functions
# ============================================================================

from datetime import datetime, timedelta
from sqlalchemy import func as sql_func

async def get_analytics_stats(
    since: Optional[datetime] = None,
    platform: Optional[Platform] = None,
) -> dict:
    """
    Get analytics stats for admin dashboard.

    Args:
        since: Optional start date for filtering
        platform: Optional platform to filter by

    Returns:
        Dict with user_count, new_users, trade_volume, fee_revenue
    """
    async with get_session() as session:
        # Count total users
        total_users_query = select(sql_func.count(User.id))
        total_users_result = await session.execute(total_users_query)
        total_users = total_users_result.scalar() or 0

        # Count new users in period
        new_users_query = select(sql_func.count(User.id))
        if since:
            new_users_query = new_users_query.where(User.created_at >= since)
        new_users_result = await session.execute(new_users_query)
        new_users = new_users_result.scalar() or 0

        # Get trade volume from confirmed orders
        volume_query = select(Order).where(Order.status == OrderStatus.CONFIRMED)
        if since:
            volume_query = volume_query.where(Order.created_at >= since)
        if platform:
            volume_query = volume_query.where(Order.platform == platform)

        volume_result = await session.execute(volume_query)
        orders = list(volume_result.scalars().all())

        trade_volume = Decimal("0")
        trade_count = 0
        for order in orders:
            try:
                trade_volume += Decimal(order.input_amount) / Decimal("1000000")
                trade_count += 1
            except:
                pass

        # Calculate fee revenue as 2% of trade volume
        # Fee is 200 basis points (2%) on every trade
        fee_revenue = trade_volume * Decimal("0.02")

        # Get referral payouts from fee_transactions
        referral_query = select(FeeTransaction).where(
            FeeTransaction.tx_type.in_(["referral_tier1", "referral_tier2", "referral_tier3"])
        )
        if since:
            referral_query = referral_query.where(FeeTransaction.created_at >= since)

        referral_result = await session.execute(referral_query)
        referral_transactions = list(referral_result.scalars().all())

        referral_payouts = Decimal("0")
        referral_count = 0
        for ref_tx in referral_transactions:
            try:
                referral_payouts += Decimal(ref_tx.amount_usdc)
                referral_count += 1
            except:
                pass

        # Net revenue = fees collected - referral payouts
        net_revenue = fee_revenue - referral_payouts

        return {
            "total_users": total_users,
            "new_users": new_users,
            "trade_volume": trade_volume,
            "trade_count": trade_count,
            "fee_revenue": fee_revenue,
            "referral_payouts": referral_payouts,
            "referral_count": referral_count,
            "net_revenue": net_revenue,
        }


async def get_analytics_by_platform(
    since: Optional[datetime] = None,
) -> dict:
    """
    Get analytics stats broken down by platform.

    Args:
        since: Optional start date for filtering

    Returns:
        Dict with stats per platform
    """
    async with get_session() as session:
        results = {}

        for plat in Platform:
            # Get trade volume from confirmed orders for this platform
            volume_query = select(Order).where(
                Order.status == OrderStatus.CONFIRMED,
                Order.platform == plat,
            )
            if since:
                volume_query = volume_query.where(Order.created_at >= since)

            volume_result = await session.execute(volume_query)
            orders = list(volume_result.scalars().all())

            trade_volume = Decimal("0")
            trade_count = 0
            for order in orders:
                try:
                    trade_volume += Decimal(order.input_amount) / Decimal("1000000")
                    trade_count += 1
                except:
                    pass

            # Calculate fee revenue as 2% of trade volume
            fee_revenue = trade_volume * Decimal("0.02")

            # Get unique users who traded on this platform
            user_query = select(sql_func.count(sql_func.distinct(Order.user_id))).where(
                Order.status == OrderStatus.CONFIRMED,
                Order.platform == plat,
            )
            if since:
                user_query = user_query.where(Order.created_at >= since)

            user_result = await session.execute(user_query)
            active_users = user_result.scalar() or 0

            results[plat.value] = {
                "trade_volume": trade_volume,
                "trade_count": trade_count,
                "active_users": active_users,
                "fee_revenue": fee_revenue,
            }

        return results


async def get_top_traders(
    since: Optional[datetime] = None,
    limit: int = 10,
) -> list:
    """
    Get top traders by volume.

    Args:
        since: Optional start date for filtering
        limit: Number of top traders to return

    Returns:
        List of dicts with user info and trading stats
    """
    async with get_session() as session:
        # Get all confirmed orders grouped by user
        order_query = select(Order).where(Order.status == OrderStatus.CONFIRMED)
        if since:
            order_query = order_query.where(Order.created_at >= since)

        order_result = await session.execute(order_query)
        orders = list(order_result.scalars().all())

        # Aggregate by user
        user_stats = {}
        for order in orders:
            user_id = order.user_id
            if user_id not in user_stats:
                user_stats[user_id] = {
                    "user_id": user_id,
                    "volume": Decimal("0"),
                    "trade_count": 0,
                }
            try:
                user_stats[user_id]["volume"] += Decimal(order.input_amount) / Decimal("1000000")
                user_stats[user_id]["trade_count"] += 1
            except:
                pass

        # Sort by volume and take top N
        sorted_traders = sorted(
            user_stats.values(),
            key=lambda x: x["volume"],
            reverse=True
        )[:limit]

        # Get user details for top traders
        result = []
        for trader in sorted_traders:
            user_result = await session.execute(
                select(User).where(User.id == trader["user_id"])
            )
            user = user_result.scalar_one_or_none()
            if user:
                result.append({
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "volume": trader["volume"],
                    "trade_count": trader["trade_count"],
                    "fees_paid": trader["volume"] * Decimal("0.02"),
                })

        return result


async def get_user_trading_volume(user_id: str) -> Decimal:
    """
    Get total trading volume for a user.

    Args:
        user_id: The user's ID

    Returns:
        Total trading volume in USD
    """
    async with get_session() as session:
        volume_query = select(Order).where(
            Order.user_id == user_id,
            Order.status == OrderStatus.CONFIRMED,
        )

        volume_result = await session.execute(volume_query)
        orders = list(volume_result.scalars().all())

        total_volume = Decimal("0")
        for order in orders:
            try:
                total_volume += Decimal(order.input_amount) / Decimal("1000000")
            except:
                pass

        return total_volume


async def get_top_referrers(
    since: Optional[datetime] = None,
    limit: int = 10,
) -> list:
    """
    Get top referrers by earnings.

    Args:
        since: Optional start date for filtering
        limit: Number of top referrers to return

    Returns:
        List of dicts with user info and referral stats
    """
    async with get_session() as session:
        # Get all referral transactions
        referral_query = select(FeeTransaction).where(
            FeeTransaction.tx_type.in_(["referral_tier1", "referral_tier2", "referral_tier3"])
        )
        if since:
            referral_query = referral_query.where(FeeTransaction.created_at >= since)

        referral_result = await session.execute(referral_query)
        transactions = list(referral_result.scalars().all())

        # Aggregate by user (the recipient of referral earnings)
        user_stats = {}
        for tx in transactions:
            user_id = tx.user_id
            if user_id not in user_stats:
                user_stats[user_id] = {
                    "user_id": user_id,
                    "total_earned": Decimal("0"),
                    "tier1_earned": Decimal("0"),
                    "tier2_earned": Decimal("0"),
                    "tier3_earned": Decimal("0"),
                    "referral_count": 0,
                }
            try:
                amount = Decimal(tx.amount_usdc)
                user_stats[user_id]["total_earned"] += amount
                user_stats[user_id]["referral_count"] += 1

                if tx.tx_type == "referral_tier1":
                    user_stats[user_id]["tier1_earned"] += amount
                elif tx.tx_type == "referral_tier2":
                    user_stats[user_id]["tier2_earned"] += amount
                elif tx.tx_type == "referral_tier3":
                    user_stats[user_id]["tier3_earned"] += amount
            except:
                pass

        # Sort by total earned and take top N
        sorted_referrers = sorted(
            user_stats.values(),
            key=lambda x: x["total_earned"],
            reverse=True
        )[:limit]

        # Get user details and referral counts
        result = []
        for referrer in sorted_referrers:
            user_result = await session.execute(
                select(User).where(User.id == referrer["user_id"])
            )
            user = user_result.scalar_one_or_none()

            # Count direct referrals (users who have this user as referred_by_id)
            direct_count_result = await session.execute(
                select(sql_func.count(User.id)).where(User.referred_by_id == referrer["user_id"])
            )
            direct_referrals = direct_count_result.scalar() or 0

            if user:
                result.append({
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "referral_code": user.referral_code,
                    "total_earned": referrer["total_earned"],
                    "tier1_earned": referrer["tier1_earned"],
                    "tier2_earned": referrer["tier2_earned"],
                    "tier3_earned": referrer["tier3_earned"],
                    "payout_count": referrer["referral_count"],
                    "direct_referrals": direct_referrals,
                })

        return result


# ===================
# System Configuration
# ===================

async def get_config(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a system configuration value by key."""
    async with get_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        if config:
            return config.value
        return default


async def set_config(key: str, value: str, description: Optional[str] = None) -> None:
    """Set a system configuration value."""
    async with get_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = value
            if description:
                config.description = description
        else:
            config = SystemConfig(
                key=key,
                value=value,
                description=description,
            )
            session.add(config)

        await session.commit()
        logger.info("Config updated", key=key, value=value)


async def delete_config(key: str) -> bool:
    """Delete a system configuration value."""
    async with get_session() as session:
        result = await session.execute(
            delete(SystemConfig).where(SystemConfig.key == key)
        )
        await session.commit()
        return result.rowcount > 0


async def get_all_config() -> dict[str, str]:
    """Get all system configuration values."""
    async with get_session() as session:
        result = await session.execute(select(SystemConfig))
        configs = result.scalars().all()
        return {c.key: c.value for c in configs}


# ===================
# ACP (Agent Commerce Protocol) Functions
# ===================

async def get_acp_agent_balance(agent_id: str, chain: str) -> Optional[Decimal]:
    """Get an ACP agent's balance on a specific chain."""
    from src.db.models import ACPAgentBalance

    async with get_session() as session:
        result = await session.execute(
            select(ACPAgentBalance).where(
                ACPAgentBalance.agent_id == agent_id,
                ACPAgentBalance.chain == chain,
            )
        )
        balance = result.scalar_one_or_none()
        if balance:
            return Decimal(balance.balance)
        return None


async def get_acp_agent_wallet(agent_id: str) -> Optional[str]:
    """Get an ACP agent's wallet address."""
    from src.db.models import ACPAgentBalance

    async with get_session() as session:
        result = await session.execute(
            select(ACPAgentBalance.agent_wallet).where(
                ACPAgentBalance.agent_id == agent_id
            ).limit(1)
        )
        wallet = result.scalar_one_or_none()
        return wallet


async def upsert_acp_agent_balance(
    agent_id: str,
    agent_wallet: str,
    chain: str,
    balance: Decimal,
) -> None:
    """Create or update an ACP agent's balance."""
    from src.db.models import ACPAgentBalance

    async with get_session() as session:
        result = await session.execute(
            select(ACPAgentBalance).where(
                ACPAgentBalance.agent_id == agent_id,
                ACPAgentBalance.chain == chain,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.balance = str(balance)
            existing.agent_wallet = agent_wallet
        else:
            new_balance = ACPAgentBalance(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                agent_wallet=agent_wallet,
                chain=chain,
                balance=str(balance),
            )
            session.add(new_balance)

        await session.commit()


async def get_all_acp_agent_balances(agent_id: str) -> dict[str, Decimal]:
    """Get all balances for an ACP agent across chains."""
    from src.db.models import ACPAgentBalance

    async with get_session() as session:
        result = await session.execute(
            select(ACPAgentBalance).where(ACPAgentBalance.agent_id == agent_id)
        )
        balances = result.scalars().all()
        return {b.chain: Decimal(b.balance) for b in balances}


async def get_acp_agent_positions(agent_id: str) -> list[dict]:
    """Get all open positions for an ACP agent."""
    from src.db.models import ACPAgentPosition, PositionStatus

    async with get_session() as session:
        result = await session.execute(
            select(ACPAgentPosition).where(
                ACPAgentPosition.agent_id == agent_id,
                ACPAgentPosition.status == PositionStatus.OPEN,
            )
        )
        positions = result.scalars().all()

        return [
            {
                "platform": pos.platform.value,
                "market_id": pos.market_id,
                "market_title": pos.market_title,
                "outcome": pos.outcome.value,
                "amount": pos.token_amount,
                "entry_price": float(pos.entry_price),
                "current_price": float(pos.current_price) if pos.current_price else float(pos.entry_price),
            }
            for pos in positions
        ]


async def create_acp_position(
    agent_id: str,
    platform: str,
    market_id: str,
    market_title: str,
    outcome: str,
    amount: Decimal,
    entry_price: Decimal,
) -> str:
    """Create a new position for an ACP agent."""
    from src.db.models import ACPAgentPosition, Platform, Outcome, PositionStatus

    async with get_session() as session:
        position = ACPAgentPosition(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            platform=Platform(platform),
            market_id=market_id,
            market_title=market_title,
            outcome=Outcome(outcome),
            token_id="",  # Set later
            token_amount=str(amount),
            entry_price=entry_price,
            status=PositionStatus.OPEN,
        )
        session.add(position)
        await session.commit()
        return position.id


async def log_acp_job(
    job_id: str,
    job_type: str,
    agent_id: str,
    agent_wallet: Optional[str],
    service_requirements: Optional[dict],
    deliverable: Optional[dict],
    success: bool,
    error_message: Optional[str] = None,
    fee_amount: Optional[Decimal] = None,
) -> None:
    """Log an ACP job for audit trail."""
    from src.db.models import ACPJobLog
    import json
    from datetime import datetime, timezone

    async with get_session() as session:
        log = ACPJobLog(
            id=str(uuid.uuid4()),
            job_id=job_id,
            job_type=job_type,
            agent_id=agent_id,
            agent_wallet=agent_wallet,
            service_requirements=json.dumps(service_requirements) if service_requirements else None,
            deliverable=json.dumps(deliverable) if deliverable else None,
            success=success,
            error_message=error_message,
            fee_amount=str(fee_amount) if fee_amount else None,
            completed_at=datetime.now(timezone.utc) if success else None,
        )
        session.add(log)
        await session.commit()


async def record_acp_trade_volume(
    agent_id: str,
    platform: str,
    amount: Decimal,
    side: str,
    tx_hash: Optional[str] = None,
) -> None:
    """Record a trade for ACP volume analytics."""
    from src.db.models import ACPTradeVolume

    async with get_session() as session:
        trade = ACPTradeVolume(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            platform=platform,
            side=side,
            amount_usdc=str(amount),
            tx_hash=tx_hash,
        )
        session.add(trade)
        await session.commit()


async def record_acp_bridge_volume(
    agent_id: str,
    source_chain: str,
    dest_chain: str,
    amount: Decimal,
    tx_hash: Optional[str] = None,
) -> None:
    """Record a bridge for ACP volume analytics."""
    from src.db.models import ACPBridgeVolume

    async with get_session() as session:
        bridge = ACPBridgeVolume(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            source_chain=source_chain,
            dest_chain=dest_chain,
            amount_usdc=str(amount),
            tx_hash=tx_hash,
        )
        session.add(bridge)
        await session.commit()


async def get_acp_analytics(
    days: int = 30,
) -> dict:
    """
    Get ACP analytics for the specified period.
    Returns volume, trade counts, unique agents, etc.
    """
    from src.db.models import ACPTradeVolume, ACPBridgeVolume, ACPJobLog
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func as sql_func

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with get_session() as session:
        # Trade volume by platform
        trade_result = await session.execute(
            select(
                ACPTradeVolume.platform,
                sql_func.sum(sql_func.cast(ACPTradeVolume.amount_usdc, Numeric)),
                sql_func.count(ACPTradeVolume.id),
            )
            .where(ACPTradeVolume.created_at >= cutoff)
            .group_by(ACPTradeVolume.platform)
        )
        trade_by_platform = {}
        total_trade_volume = Decimal(0)
        total_trade_count = 0

        for platform, volume, count in trade_result:
            vol = Decimal(str(volume or 0))
            trade_by_platform[platform] = {
                "volume": float(vol),
                "count": count,
            }
            total_trade_volume += vol
            total_trade_count += count

        # Bridge volume
        bridge_result = await session.execute(
            select(
                sql_func.sum(sql_func.cast(ACPBridgeVolume.amount_usdc, Numeric)),
                sql_func.count(ACPBridgeVolume.id),
            )
            .where(ACPBridgeVolume.created_at >= cutoff)
        )
        bridge_row = bridge_result.one()
        total_bridge_volume = Decimal(str(bridge_row[0] or 0))
        total_bridge_count = bridge_row[1] or 0

        # Unique agents (from trades)
        agents_result = await session.execute(
            select(sql_func.count(sql_func.distinct(ACPTradeVolume.agent_id)))
            .where(ACPTradeVolume.created_at >= cutoff)
        )
        unique_agents = agents_result.scalar() or 0

        # Job counts by type
        jobs_result = await session.execute(
            select(
                ACPJobLog.job_type,
                sql_func.count(ACPJobLog.id),
                sql_func.sum(sql_func.case((ACPJobLog.success == True, 1), else_=0)),
            )
            .where(ACPJobLog.created_at >= cutoff)
            .group_by(ACPJobLog.job_type)
        )
        jobs_by_type = {}
        for job_type, total, successful in jobs_result:
            jobs_by_type[job_type] = {
                "total": total,
                "successful": successful or 0,
                "success_rate": round((successful or 0) / total * 100, 1) if total > 0 else 0,
            }

        # All-time stats
        all_time_trade = await session.execute(
            select(
                sql_func.sum(sql_func.cast(ACPTradeVolume.amount_usdc, Numeric)),
                sql_func.count(ACPTradeVolume.id),
            )
        )
        all_time_row = all_time_trade.one()
        all_time_volume = Decimal(str(all_time_row[0] or 0))
        all_time_count = all_time_row[1] or 0

        all_time_agents = await session.execute(
            select(sql_func.count(sql_func.distinct(ACPTradeVolume.agent_id)))
        )
        all_time_unique_agents = all_time_agents.scalar() or 0

        return {
            "period_days": days,
            "trade_volume": {
                "by_platform": trade_by_platform,
                "total": float(total_trade_volume),
                "count": total_trade_count,
            },
            "bridge_volume": {
                "total": float(total_bridge_volume),
                "count": total_bridge_count,
            },
            "unique_agents": unique_agents,
            "jobs_by_type": jobs_by_type,
            "all_time": {
                "trade_volume": float(all_time_volume),
                "trade_count": all_time_count,
                "unique_agents": all_time_unique_agents,
            },
        }


async def get_acp_top_agents(limit: int = 10) -> list[dict]:
    """Get top ACP agents by trading volume."""
    from src.db.models import ACPTradeVolume
    from sqlalchemy import func as sql_func

    async with get_session() as session:
        result = await session.execute(
            select(
                ACPTradeVolume.agent_id,
                sql_func.sum(sql_func.cast(ACPTradeVolume.amount_usdc, Numeric)).label("volume"),
                sql_func.count(ACPTradeVolume.id).label("trades"),
            )
            .group_by(ACPTradeVolume.agent_id)
            .order_by(sql_func.sum(sql_func.cast(ACPTradeVolume.amount_usdc, Numeric)).desc())
            .limit(limit)
        )

        return [
            {
                "agent_id": row.agent_id[:16] + "...",  # Truncate for display
                "volume": float(row.volume or 0),
                "trades": row.trades,
            }
            for row in result
        ]


async def get_all_user_telegram_ids() -> list[int]:
    """Get all user telegram IDs (for broadcast messages)."""
    async with get_session() as session:
        result = await session.execute(select(User.telegram_id))
        return list(result.scalars().all())
