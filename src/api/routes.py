"""
FastAPI routes for Spredd Mini App.
Exposes bot functionality via REST API.
"""

import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.database import get_session_dependency as get_session
from ..db.models import (
    Chain,
    ChainFamily,
    FeeBalance,
    Order,
    Outcome,
    Platform,
    Position,
    PositionStatus,
    User,
    Wallet,
)
from .auth import TelegramUser, get_user_from_init_data

router = APIRouter(prefix="/api/v1", tags=["Mini App API"])
settings = get_settings()


# ===================
# Pydantic Models
# ===================

class UserResponse(BaseModel):
    """User data response."""
    id: str
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    active_platform: str
    referral_code: Optional[str]
    created_at: str


class WalletBalance(BaseModel):
    """Wallet balance info."""
    chain_family: str
    public_key: str
    balances: list[dict[str, Any]]


class MarketInfo(BaseModel):
    """Market information."""
    id: str
    platform: str
    title: str
    description: Optional[str]
    yes_price: Optional[float]
    no_price: Optional[float]
    volume_24h: Optional[str]
    is_active: bool


class PositionInfo(BaseModel):
    """Position information."""
    id: str
    platform: str
    market_id: str
    market_title: str
    outcome: str
    token_amount: str
    entry_price: float
    current_price: Optional[float]
    status: str
    pnl: Optional[float]
    pnl_percent: Optional[float]


class QuoteRequest(BaseModel):
    """Quote request body."""
    platform: str
    market_id: str
    outcome: str  # "yes" or "no"
    side: str  # "buy" or "sell"
    amount: str  # Amount in USDC for buy, tokens for sell


class QuoteResponse(BaseModel):
    """Quote response."""
    platform: str
    market_id: str
    outcome: str
    side: str
    input_amount: str
    expected_output: str
    price: float
    price_impact: Optional[float]
    fees: dict[str, str]


class OrderRequest(BaseModel):
    """Order execution request."""
    platform: str
    market_id: str
    outcome: str
    side: str
    amount: str
    slippage_bps: int = Field(default=100, ge=0, le=1000)


class OrderResponse(BaseModel):
    """Order execution response."""
    order_id: str
    status: str
    tx_hash: Optional[str]
    message: str


class PnLSummary(BaseModel):
    """PnL summary for a platform."""
    platform: str
    total_pnl: float
    total_trades: int
    roi_percent: float
    winning_trades: int
    losing_trades: int


# ===================
# Dependencies
# ===================

async def get_current_user(
    request: Request,
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session)
) -> User:
    """
    Validate Telegram initData and get/create user.
    Also automatically captures user's country from IP for geo-blocking.
    """
    tg_user = get_user_from_init_data(x_telegram_init_data, settings.telegram_bot_token)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Invalid authentication")

    # Get or create user
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Create new user
        user = User(
            id=str(uuid.uuid4()),
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Auto-detect country from IP (silently, in background)
    # Check if force_geo=1 query param is present (for re-verification)
    from datetime import datetime, timezone, timedelta
    from ..utils.geo_blocking import get_country_from_ip, is_verification_valid

    force_geo = request.query_params.get("force_geo") == "1"
    should_update_geo = force_geo or not is_verification_valid(user.country_verified_at)

    if should_update_geo:
        # Get client IP from headers (for proxied requests)
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP", "")
        if not client_ip and request.client:
            client_ip = request.client.host

        if client_ip:
            try:
                country_code = await get_country_from_ip(client_ip)
                if country_code:
                    # Update user's country silently
                    from sqlalchemy import text
                    await session.execute(
                        text("""
                            UPDATE users
                            SET country = :country,
                                country_verified_at = :now,
                                geo_verify_token = NULL,
                                updated_at = :now
                            WHERE id = :uid
                        """),
                        {
                            "country": country_code.upper(),
                            "now": datetime.now(timezone.utc),
                            "uid": user.id
                        }
                    )
                    await session.commit()
                    # Update local user object
                    user.country = country_code.upper()
                    user.country_verified_at = datetime.now(timezone.utc)
            except Exception:
                pass  # Silently ignore geo lookup failures

    return user


# ===================
# User Endpoints
# ===================

@router.get("/user/me", response_model=UserResponse)
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user information."""
    return UserResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        active_platform=user.active_platform.value,
        referral_code=user.referral_code,
        created_at=user.created_at.isoformat(),
    )


@router.post("/user/platform")
async def set_active_platform(
    platform: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Set user's active platform."""
    try:
        platform_enum = Platform(platform.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    # Use .name (uppercase) to match SQLAlchemy's enum mapping
    from sqlalchemy import update as sql_update, text
    await session.execute(
        text("UPDATE users SET active_platform = :platform, updated_at = now() WHERE id = :uid"),
        {"platform": platform_enum.name, "uid": user.id}
    )
    await session.commit()

    return {"status": "success", "active_platform": platform}


@router.get("/user/wallet-status")
async def get_wallet_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Check if user has wallets set up."""
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user.id)
    )
    wallets = result.scalars().all()

    has_evm = any(w.chain_family == ChainFamily.EVM for w in wallets)
    has_solana = any(w.chain_family == ChainFamily.SOLANA for w in wallets)

    return {
        "has_wallet": len(wallets) > 0,
        "has_evm_wallet": has_evm,
        "has_solana_wallet": has_solana,
        "wallet_count": len(wallets),
    }


class CreateWalletRequest(BaseModel):
    """Request to create wallets with PIN."""
    pin: str = Field(..., min_length=4, max_length=6, pattern="^[0-9]+$")


@router.post("/user/create-wallet")
async def create_user_wallet(
    request: CreateWalletRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Create wallets for the user with PIN protection."""
    from ..services.wallet import WalletService

    # Check if user already has wallets
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user.id)
    )
    existing_wallets = result.scalars().all()

    if len(existing_wallets) > 0:
        raise HTTPException(
            status_code=400,
            detail="Wallets already exist. Cannot create new wallets."
        )

    # Validate PIN
    if not request.pin.isdigit() or len(request.pin) < 4 or len(request.pin) > 6:
        raise HTTPException(
            status_code=400,
            detail="PIN must be 4-6 digits"
        )

    # Create wallets
    wallet_service = WalletService()
    await wallet_service.initialize()

    try:
        wallets = await wallet_service.get_or_create_wallets(
            user_id=user.id,
            telegram_id=user.telegram_id,
            user_pin=request.pin,
        )

        return {
            "status": "success",
            "message": "Wallets created successfully",
            "wallets": {
                "evm": wallets[ChainFamily.EVM].public_key if ChainFamily.EVM in wallets else None,
                "solana": wallets[ChainFamily.SOLANA].public_key if ChainFamily.SOLANA in wallets else None,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create wallets: {str(e)}")


# ===================
# Wallet Endpoints
# ===================

@router.get("/wallet/balances")
async def get_wallet_balances(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get all wallet balances for the user."""
    from ..services.wallet import WalletService

    wallet_service = WalletService()
    await wallet_service.initialize()

    balances = []

    # Get user's wallets
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user.id)
    )
    wallets = result.scalars().all()

    for wallet in wallets:
        if wallet.chain_family == ChainFamily.EVM:
            # Get EVM balances (Polygon, Base, BSC, Monad)
            evm_balances = []
            try:
                evm_balances.extend(await wallet_service.get_polygon_balances(wallet.public_key))
            except Exception as e:
                print(f"Error getting Polygon balances: {e}")
            try:
                evm_balances.extend(await wallet_service.get_base_balances(wallet.public_key))
            except Exception as e:
                print(f"Error getting Base balances: {e}")
            try:
                evm_balances.extend(await wallet_service.get_bsc_balances(wallet.public_key))
            except Exception as e:
                print(f"Error getting BSC balances: {e}")
            try:
                evm_balances.extend(await wallet_service.get_monad_balances(wallet.public_key))
            except Exception as e:
                print(f"Error getting Monad balances: {e}")
            balances.append({
                "chain_family": "evm",
                "public_key": wallet.public_key,
                "balances": [
                    {"token": b.token, "amount": str(b.amount), "chain": b.chain.value}
                    for b in evm_balances
                ]
            })
        elif wallet.chain_family == ChainFamily.SOLANA:
            # Get Solana balances
            sol_balances = []
            try:
                sol_balances.append(await wallet_service.get_solana_balance(wallet.public_key))
            except Exception as e:
                print(f"Error getting SOL balance: {e}")
            try:
                sol_balances.append(await wallet_service.get_solana_usdc_balance(wallet.public_key))
            except Exception as e:
                print(f"Error getting Solana USDC balance: {e}")
            balances.append({
                "chain_family": "solana",
                "public_key": wallet.public_key,
                "balances": [
                    {"token": b.token, "amount": str(b.amount), "chain": b.chain.value}
                    for b in sol_balances
                ]
            })

    return {"wallets": balances}


@router.get("/wallet/address/{chain_family}")
async def get_wallet_address(
    chain_family: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get wallet address for a chain family."""
    try:
        family = ChainFamily(chain_family.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain family: {chain_family}")

    result = await session.execute(
        select(Wallet).where(
            Wallet.user_id == user.id,
            Wallet.chain_family == family
        )
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return {
        "chain_family": chain_family,
        "public_key": wallet.public_key
    }


# ===================
# Market Endpoints
# ===================

@router.get("/markets")
async def get_all_markets(
    platform: Optional[str] = Query(default="all", description="Platform filter: all, polymarket, kalshi, opinion, limitless"),
    limit: int = Query(default=100, le=300),
    active: bool = Query(default=True),
):
    """Get markets from all platforms for the webapp."""
    from ..platforms import platform_registry

    results = []

    # Determine which platforms to fetch
    if platform and platform.lower() != "all":
        platforms_to_fetch = [platform.lower()]
    else:
        platforms_to_fetch = ["kalshi", "polymarket", "limitless"]  # Opinion requires auth

    for plat in platforms_to_fetch:
        try:
            platform_instance = platform_registry.get(Platform(plat))
            if not platform_instance:
                continue

            markets = await platform_instance.get_markets(limit=limit, active_only=active)
            for m in markets:
                # Extract image from raw_data if available
                image = None
                if m.raw_data:
                    # Polymarket stores event image
                    if "event" in m.raw_data:
                        image = m.raw_data["event"].get("image")
                    # Direct image field
                    elif "image" in m.raw_data:
                        image = m.raw_data["image"]

                # Build slug from market_id or event_id
                slug = m.event_id or m.market_id

                results.append({
                    "id": m.market_id,
                    "platform": plat,
                    "question": m.title,
                    "description": m.description,
                    "image": image,
                    "category": m.category or "OTHER",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [
                        str(float(m.yes_price)) if m.yes_price else "0.5",
                        str(float(m.no_price)) if m.no_price else "0.5",
                    ],
                    "volume": float(m.volume_24h) if m.volume_24h else 0,
                    "volume24hr": float(m.volume_24h) if m.volume_24h else 0,
                    "liquidity": float(m.liquidity) if m.liquidity else 0,
                    "endDate": m.close_time,
                    "slug": slug,
                    "active": m.is_active,
                })
        except Exception as e:
            print(f"Error fetching {plat} markets: {e}")

    # Sort by volume
    results.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)

    return results[:limit]


@router.get("/markets/search")
async def search_markets(
    q: str = Query(..., min_length=1),
    platform: Optional[str] = None,
    limit: int = Query(default=20, le=100),
):
    """Search markets across platforms."""
    from ..platforms import platform_registry

    results = []

    # Determine which platforms to search
    platforms_to_search = []
    if platform:
        platforms_to_search = [platform.lower()]
    else:
        platforms_to_search = ["kalshi", "polymarket"]

    for plat in platforms_to_search:
        try:
            platform_instance = platform_registry.get(Platform(plat))
            if not platform_instance:
                continue

            markets = await platform_instance.search_markets(q, limit=limit)
            for m in markets:
                results.append({
                    "platform": plat,
                    "id": m.market_id,
                    "title": m.title,
                    "yes_price": float(m.yes_price) if m.yes_price else None,
                    "no_price": float(m.no_price) if m.no_price else None,
                    "volume": str(m.volume_24h) if m.volume_24h else None,
                    "is_active": m.is_active,
                })
        except Exception as e:
            print(f"Error searching {plat}: {e}")

    return {"markets": results[:limit]}


@router.get("/markets/trending")
async def get_trending_markets(
    platform: Optional[str] = None,
    limit: int = Query(default=10, le=50),
):
    """Get trending markets."""
    from ..platforms import platform_registry

    results = []

    if not platform or platform.lower() == "kalshi":
        try:
            kalshi = platform_registry.get(Platform.KALSHI)
            if kalshi:
                markets = await kalshi.get_trending_markets(limit=limit)
                for m in markets:
                    results.append({
                        "platform": "kalshi",
                        "id": m.market_id,
                        "title": m.title,
                        "yes_price": float(m.yes_price) if m.yes_price else None,
                        "no_price": float(m.no_price) if m.no_price else None,
                        "volume": str(m.volume_24h) if m.volume_24h else None,
                        "is_active": m.is_active,
                    })
        except Exception as e:
            print(f"Error getting Kalshi trending: {e}")

    if not platform or platform.lower() == "polymarket":
        try:
            poly = platform_registry.get(Platform.POLYMARKET)
            if poly:
                markets = await poly.get_trending_markets(limit=limit)
                for m in markets:
                    results.append({
                        "platform": "polymarket",
                        "id": m.market_id,
                        "title": m.title,
                        "yes_price": float(m.yes_price) if m.yes_price else None,
                        "no_price": float(m.no_price) if m.no_price else None,
                        "volume": str(m.volume_24h) if m.volume_24h else None,
                        "is_active": m.is_active,
                    })
        except Exception as e:
            print(f"Error getting Polymarket trending: {e}")

    return {"markets": results[:limit]}


@router.get("/markets/categories")
async def get_market_categories():
    """Get available market categories for Polymarket."""
    from ..platforms import platform_registry

    try:
        poly = platform_registry.get(Platform.POLYMARKET)
        if poly and hasattr(poly, 'get_available_categories'):
            categories = poly.get_available_categories()
            return {"categories": categories}
    except Exception as e:
        print(f"Error getting categories: {e}")

    # Default categories if platform not available
    return {
        "categories": [
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
            {"id": "business", "label": "Business", "emoji": "💼"},
            {"id": "science", "label": "Science", "emoji": "🔬"},
        ]
    }


@router.get("/markets/category/{category}")
async def get_markets_by_category(
    category: str,
    limit: int = Query(default=20, le=100),
):
    """Get markets by category (Polymarket only)."""
    from ..platforms import platform_registry

    try:
        poly = platform_registry.get(Platform.POLYMARKET)
        if not poly:
            raise HTTPException(status_code=400, detail="Polymarket not available")

        markets = await poly.get_markets_by_category(category, limit=limit)
        results = []
        for m in markets:
            results.append({
                "platform": "polymarket",
                "id": m.market_id,
                "title": m.title,
                "category": m.category,
                "yes_price": float(m.yes_price) if m.yes_price else None,
                "no_price": float(m.no_price) if m.no_price else None,
                "volume": str(m.volume_24h) if m.volume_24h else None,
                "is_active": m.is_active,
            })
        return {"markets": results}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching markets: {e}")


@router.get("/markets/{platform}/{market_id}")
async def get_market_details(
    platform: str,
    market_id: str,
):
    """Get detailed market information."""
    from ..platforms import platform_registry

    try:
        platform_instance = platform_registry.get(Platform(platform.lower()))
        if not platform_instance:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        market = await platform_instance.get_market(market_id)
        return {"market": market}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Market not found: {e}")


# ===================
# Trading Endpoints
# ===================

@router.post("/trading/quote", response_model=QuoteResponse)
async def get_quote(
    request: QuoteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get a quote for a trade."""
    from ..platforms import platform_registry

    try:
        platform = request.platform.lower()

        try:
            plat = platform_registry.get(Platform(platform))
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        if not plat:
            raise HTTPException(status_code=400, detail=f"Platform not initialized: {platform}")

        # Convert amount to Decimal for platform methods
        amount_decimal = Decimal(str(request.amount))

        # Convert outcome string to Outcome enum
        try:
            outcome_enum = Outcome(request.outcome.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid outcome: {request.outcome}")

        quote = await plat.get_quote(
            market_id=request.market_id,
            outcome=outcome_enum,
            side=request.side,
            amount=amount_decimal,
        )

        # Quote is a dataclass, access attributes directly
        return QuoteResponse(
            platform=platform,
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            input_amount=str(quote.input_amount),
            expected_output=str(quote.expected_output),
            price=float(quote.price_per_token),
            price_impact=float(quote.price_impact) if quote.price_impact else None,
            fees={
                "platform_fee": str(quote.platform_fee) if quote.platform_fee else "0",
                "network_fee": str(quote.network_fee_estimate) if quote.network_fee_estimate else "0",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[Quote Error] {type(e).__name__}: {e}")
        print(f"[Quote Error] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trading/execute", response_model=OrderResponse)
async def execute_order(
    request: OrderRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Execute a trade order."""
    from ..platforms import platform_registry
    from ..utils.encryption import decrypt

    try:
        platform = request.platform.lower()

        # Get platform and determine chain family
        try:
            plat = platform_registry.get(Platform(platform))
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        if not plat:
            raise HTTPException(status_code=400, detail=f"Platform not initialized: {platform}")

        # Determine chain family based on platform
        if platform == "kalshi":
            chain_family = ChainFamily.SOLANA
        elif platform == "polymarket":
            chain_family = ChainFamily.EVM
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform for trading: {platform}")

        # Get wallet
        result = await session.execute(
            select(Wallet).where(
                Wallet.user_id == user.id,
                Wallet.chain_family == chain_family
            )
        )
        wallet = result.scalar_one_or_none()

        if not wallet:
            raise HTTPException(status_code=400, detail="Wallet not found. Please create a wallet first.")

        # Decrypt private key (encrypted without PIN for trading)
        private_key = decrypt(
            wallet.encrypted_private_key,
            settings.encryption_key,
            user.telegram_id,
            "",  # No PIN required for trading
        )

        # Convert amount to Decimal for platform methods
        amount_decimal = Decimal(str(request.amount))

        # Convert outcome string to Outcome enum
        try:
            outcome_enum = Outcome(request.outcome.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid outcome: {request.outcome}")

        # Convert private key to appropriate type based on platform
        # decrypt() returns raw bytes
        if platform == "kalshi":
            from solders.keypair import Keypair
            # Solana private key is raw bytes (64 bytes)
            signing_key = Keypair.from_bytes(private_key)
        else:
            from eth_account import Account
            # EVM private key is raw bytes (32 bytes)
            signing_key = Account.from_key(private_key)

        # First get a quote
        quote = await plat.get_quote(
            market_id=request.market_id,
            outcome=outcome_enum,
            side=request.side,
            amount=amount_decimal,
        )

        # Execute the trade using the quote
        tx_result = await plat.execute_trade(
            quote=quote,
            private_key=signing_key,
        )

        # Create order record
        platform_enum = Platform(platform)
        chain_enum = Chain.SOLANA if platform == "kalshi" else Chain.POLYGON

        order = Order(
            id=str(uuid.uuid4()),
            user_id=user.id,
            platform=platform_enum,
            chain=chain_enum,
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            input_token="USDC",
            input_amount=request.amount,
            output_token=f"{request.outcome.upper()} shares",
            expected_output=str(quote.expected_output),
            actual_output=str(tx_result.output_amount) if tx_result.output_amount else None,
            status="confirmed" if tx_result.success else "failed",
            tx_hash=tx_result.tx_hash,
        )
        session.add(order)

        # Create/update Position for successful trades
        if tx_result.success:
            # Get market title
            try:
                market = await plat.get_market(request.market_id)
                market_title = market.title if market else f"Market {request.market_id[:16]}..."
            except Exception:
                market_title = f"Market {request.market_id[:16]}..."

            # Get token_id from quote_data
            token_id = quote.quote_data.get("token_id", "") if quote.quote_data else ""

            # Calculate amounts
            output_amount = str(tx_result.output_amount) if tx_result.output_amount else str(quote.expected_output)
            entry_price = float(quote.price_per_token)

            if request.side == "buy":
                # Check for existing open position to update
                existing_position = await session.execute(
                    select(Position).where(
                        Position.user_id == user.id,
                        Position.platform == platform_enum,
                        Position.market_id == request.market_id,
                        Position.outcome == outcome_enum,
                        Position.status == PositionStatus.OPEN,
                    )
                )
                existing = existing_position.scalar_one_or_none()

                if existing:
                    # Update existing position (average in)
                    old_amount = Decimal(existing.token_amount)
                    new_amount = Decimal(output_amount)
                    total_amount = old_amount + new_amount

                    # Calculate weighted average entry price
                    old_value = old_amount * existing.entry_price
                    new_value = new_amount * Decimal(str(entry_price))
                    avg_price = (old_value + new_value) / total_amount if total_amount > 0 else Decimal(str(entry_price))

                    existing.token_amount = str(total_amount)
                    existing.entry_price = avg_price
                    existing.current_price = Decimal(str(entry_price))
                else:
                    # Create new position
                    position = Position(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        platform=platform_enum,
                        chain=chain_enum,
                        market_id=request.market_id,
                        market_title=market_title,
                        outcome=outcome_enum,
                        token_id=token_id,
                        token_amount=output_amount,
                        entry_price=Decimal(str(entry_price)),
                        current_price=Decimal(str(entry_price)),
                        status=PositionStatus.OPEN,
                    )
                    session.add(position)
            else:
                # SELL: Find and update/close existing position
                existing_position = await session.execute(
                    select(Position).where(
                        Position.user_id == user.id,
                        Position.platform == platform_enum,
                        Position.market_id == request.market_id,
                        Position.outcome == outcome_enum,
                        Position.status == PositionStatus.OPEN,
                    )
                )
                existing = existing_position.scalar_one_or_none()

                if existing:
                    # Reduce position or close it
                    sell_amount = Decimal(str(request.amount)) / Decimal(str(entry_price)) if entry_price > 0 else Decimal("0")
                    remaining = Decimal(existing.token_amount) - sell_amount

                    if remaining <= 0:
                        existing.status = PositionStatus.CLOSED
                        existing.token_amount = "0"
                    else:
                        existing.token_amount = str(remaining)
                    existing.current_price = Decimal(str(entry_price))

        await session.commit()

        return OrderResponse(
            order_id=order.id,
            status=order.status,
            tx_hash=order.tx_hash,
            message=f"Trade {'completed' if tx_result.success else 'failed'}: {tx_result.error_message or 'Success'}",
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[Execute Error] {type(e).__name__}: {e}")
        print(f"[Execute Error] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=str(e))


# ===================
# Bridge Endpoints
# ===================

class BridgeQuoteRequest(BaseModel):
    """Bridge quote request."""
    source_chain: str
    amount: str


class BridgeQuoteResponse(BaseModel):
    """Bridge quote response."""
    source_chain: str
    dest_chain: str
    amount: str
    fast_bridge: Optional[dict] = None
    standard_bridge: Optional[dict] = None


class BridgeExecuteRequest(BaseModel):
    """Bridge execution request."""
    source_chain: str
    amount: str
    mode: str = "fast"  # "fast" or "standard"


class BridgeExecuteResponse(BaseModel):
    """Bridge execution response."""
    success: bool
    source_chain: str
    dest_chain: str
    amount: str
    tx_hash: Optional[str] = None
    message: str


@router.get("/bridge/chains")
async def get_bridge_chains(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get available bridge source chains with balances."""
    from ..services.bridge import bridge_service, BridgeChain

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    # Get user's EVM wallet
    result = await session.execute(
        select(Wallet).where(
            Wallet.user_id == user.id,
            Wallet.chain_family == ChainFamily.EVM
        )
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        return {"chains": [], "wallet_address": None}

    # Get balances for all supported chains
    balances = bridge_service.get_all_usdc_balances(wallet.public_key)

    chains = []
    for chain, balance in balances.items():
        if chain != BridgeChain.POLYGON:  # Polygon is destination, not source
            chains.append({
                "id": chain.value,
                "name": chain.value.title(),
                "balance": str(balance),
                "has_balance": balance > Decimal("1"),  # Minimum $1 to bridge
            })

    return {
        "chains": chains,
        "wallet_address": wallet.public_key,
        "dest_chain": "polygon",
    }


@router.post("/bridge/quote", response_model=BridgeQuoteResponse)
async def get_bridge_quote(
    request: BridgeQuoteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get a quote for bridging USDC to Polygon."""
    from ..services.bridge import bridge_service, BridgeChain

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    try:
        source_chain = BridgeChain(request.source_chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid source chain: {request.source_chain}")

    amount = Decimal(str(request.amount))

    # Get user's EVM wallet
    result = await session.execute(
        select(Wallet).where(
            Wallet.user_id == user.id,
            Wallet.chain_family == ChainFamily.EVM
        )
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        raise HTTPException(status_code=400, detail="EVM wallet not found")

    # Check balance on source chain
    balance = bridge_service.get_usdc_balance(source_chain, wallet.public_key)
    if balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient USDC on {source_chain.value}. Have {balance}, need {amount}"
        )

    # Get fast bridge quote
    fast_quote = bridge_service.get_fast_bridge_quote(
        source_chain,
        BridgeChain.POLYGON,
        amount,
        wallet.public_key
    )

    return BridgeQuoteResponse(
        source_chain=source_chain.value,
        dest_chain="polygon",
        amount=str(amount),
        fast_bridge={
            "output_amount": str(fast_quote.output_amount),
            "fee_amount": str(fast_quote.fee_amount),
            "fee_percent": fast_quote.fee_percent,
            "estimated_time": "~30 seconds",
            "available": fast_quote.error is None,
            "error": fast_quote.error,
        } if fast_quote else None,
        standard_bridge={
            "output_amount": str(amount),  # No fee for standard
            "fee_amount": "0",
            "fee_percent": 0,
            "estimated_time": "~15 minutes",
            "available": True,
        },
    )


@router.post("/bridge/execute", response_model=BridgeExecuteResponse)
async def execute_bridge(
    request: BridgeExecuteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Execute a bridge transfer to Polygon."""
    import asyncio
    from ..services.bridge import bridge_service, BridgeChain
    from ..utils.encryption import decrypt

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    try:
        source_chain = BridgeChain(request.source_chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid source chain: {request.source_chain}")

    amount = Decimal(str(request.amount))

    # Get user's EVM wallet
    result = await session.execute(
        select(Wallet).where(
            Wallet.user_id == user.id,
            Wallet.chain_family == ChainFamily.EVM
        )
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        raise HTTPException(status_code=400, detail="EVM wallet not found")

    # Decrypt private key
    private_key = decrypt(
        wallet.encrypted_private_key,
        settings.encryption_key,
        user.telegram_id,
        "",  # No PIN required for bridging
    )

    # Execute bridge in thread pool (blocking operation)
    if request.mode == "fast":
        bridge_result = await asyncio.to_thread(
            bridge_service.bridge_usdc_fast,
            private_key,
            source_chain,
            BridgeChain.POLYGON,
            amount,
        )
    else:
        bridge_result = await asyncio.to_thread(
            bridge_service.bridge_usdc,
            private_key,
            source_chain,
            BridgeChain.POLYGON,
            amount,
        )

    if bridge_result.success:
        return BridgeExecuteResponse(
            success=True,
            source_chain=source_chain.value,
            dest_chain="polygon",
            amount=str(bridge_result.amount),
            tx_hash=bridge_result.burn_tx_hash,
            message=f"Bridge successful! USDC will arrive on Polygon shortly.",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=bridge_result.error_message or "Bridge failed"
        )


# ===================
# Position Endpoints
# ===================

@router.get("/positions")
async def get_positions(
    platform: Optional[str] = None,
    status: str = "open",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get user's positions."""
    query = select(Position).where(Position.user_id == user.id)

    if platform:
        try:
            plat_enum = Platform(platform.lower())
            query = query.where(Position.platform == plat_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    if status:
        try:
            status_enum = PositionStatus(status.lower())
            query = query.where(Position.status == status_enum)
        except ValueError:
            pass  # Ignore invalid status

    result = await session.execute(query)
    positions = result.scalars().all()

    return {
        "positions": [
            {
                "id": p.id,
                "platform": p.platform.value,
                "market_id": p.market_id,
                "market_title": p.market_title,
                "outcome": p.outcome.value,
                "token_amount": p.token_amount,
                "entry_price": float(p.entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "status": p.status.value,
                "pnl": calculate_pnl(p),
                "created_at": p.created_at.isoformat(),
            }
            for p in positions
        ]
    }


def calculate_pnl(position: Position) -> Optional[float]:
    """Calculate PnL for a position."""
    if not position.current_price:
        return None

    entry_value = float(position.entry_price) * float(position.token_amount)
    current_value = float(position.current_price) * float(position.token_amount)
    return current_value - entry_value


# ===================
# PnL Endpoints
# ===================

@router.get("/pnl/summary")
async def get_pnl_summary(
    platform: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get PnL summary across platforms."""
    query = select(Position).where(
        Position.user_id == user.id,
        Position.status == PositionStatus.CLOSED
    )

    if platform:
        try:
            plat_enum = Platform(platform.lower())
            query = query.where(Position.platform == plat_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    result = await session.execute(query)
    positions = result.scalars().all()

    # Calculate summary by platform
    summaries = {}
    for p in positions:
        plat = p.platform.value
        if plat not in summaries:
            summaries[plat] = {
                "platform": plat,
                "total_pnl": 0.0,
                "total_trades": 0,
                "total_invested": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
            }

        pnl = calculate_pnl(p) or 0
        invested = float(p.entry_price) * float(p.token_amount)

        summaries[plat]["total_pnl"] += pnl
        summaries[plat]["total_trades"] += 1
        summaries[plat]["total_invested"] += invested

        if pnl > 0:
            summaries[plat]["winning_trades"] += 1
        elif pnl < 0:
            summaries[plat]["losing_trades"] += 1

    # Calculate ROI
    for plat, s in summaries.items():
        if s["total_invested"] > 0:
            s["roi_percent"] = (s["total_pnl"] / s["total_invested"]) * 100
        else:
            s["roi_percent"] = 0.0

    return {"summaries": list(summaries.values())}


# ===================
# Referral Endpoints
# ===================

@router.get("/referral/stats")
async def get_referral_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get referral statistics."""
    # Get fee balances
    result = await session.execute(
        select(FeeBalance).where(FeeBalance.user_id == user.id)
    )
    fee_balances = result.scalars().all()

    # Count referrals
    result = await session.execute(
        select(User).where(User.referred_by_id == user.id)
    )
    referrals = result.scalars().all()

    return {
        "referral_code": user.referral_code,
        "total_referrals": len(referrals),
        "fee_balances": [
            {
                "chain_family": fb.chain_family.value,
                "claimable_usdc": fb.claimable_usdc,
                "total_earned_usdc": fb.total_earned_usdc,
                "total_withdrawn_usdc": fb.total_withdrawn_usdc,
            }
            for fb in fee_balances
        ]
    }


# ===================
# Geo Verification Endpoints
# ===================

@router.get("/geo/check")
async def check_geo_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Standalone geo verification page for Telegram Mini App.
    Detects IP, verifies user, and shows result.
    """
    from fastapi.responses import HTMLResponse
    from ..utils.geo_blocking import get_country_from_ip, is_country_blocked, get_country_name
    from .auth import get_user_from_init_data
    from datetime import datetime, timezone

    # Get initData from query param (Telegram passes it when opening Mini App)
    init_data = request.query_params.get("initData", "")

    # Also try getting from Telegram WebApp (will be handled by JS on frontend)
    # For now, return a page that handles auth via JavaScript
    bot_username = settings.telegram_bot_username

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Location Verification</title>
            <script src="https://telegram.org/js/telegram-web-app.js"></script>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0d0d0d;
                    color: white;
                    padding: 20px;
                    margin: 0;
                    min-height: 100vh;
                    box-sizing: border-box;
                }}
                .container {{ max-width: 400px; margin: 0 auto; text-align: center; }}
                h1 {{ margin-bottom: 10px; }}
                .subtitle {{ color: #888; margin-bottom: 30px; }}
                .status-box {{
                    border-radius: 12px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .blocked {{
                    background: #2d1f1f;
                    border: 1px solid #ff4757;
                }}
                .blocked h2 {{ color: #ff4757; }}
                .allowed {{
                    background: #1f2d1f;
                    border: 1px solid #00ff88;
                }}
                .allowed h2 {{ color: #00ff88; }}
                .status-box h2 {{ margin: 0 0 10px 0; }}
                .status-box p {{ color: #ccc; margin: 0; }}
                .note {{ color: #888; margin-top: 15px; }}
                .btn {{
                    display: inline-block;
                    margin-top: 20px;
                    padding: 14px 28px;
                    background: #0088cc;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: bold;
                    border: none;
                    cursor: pointer;
                }}
                .loading {{ color: #888; }}
                #error {{ color: #ff4757; display: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🌍 Location Verification</h1>
                <div id="loading" class="loading">
                    <p>Detecting your location...</p>
                </div>
                <div id="result" style="display: none;"></div>
                <div id="error">
                    <p>Failed to verify location. Please try again.</p>
                </div>
            </div>
            <script>
                const botUsername = "{bot_username}";

                async function verifyLocation() {{
                    try {{
                        // Get Telegram WebApp initData
                        if (!window.Telegram || !window.Telegram.WebApp) {{
                            throw new Error("Not in Telegram");
                        }}

                        Telegram.WebApp.ready();
                        const initData = Telegram.WebApp.initData;

                        if (!initData) {{
                            throw new Error("No auth data");
                        }}

                        // Call API to verify and get status
                        const response = await fetch("/api/v1/geo/verify-status?force_geo=1", {{
                            headers: {{
                                "X-Telegram-Init-Data": initData
                            }}
                        }});

                        if (!response.ok) {{
                            throw new Error("API error");
                        }}

                        const data = await response.json();
                        showResult(data);

                    }} catch (err) {{
                        console.error(err);
                        document.getElementById("loading").style.display = "none";
                        document.getElementById("error").style.display = "block";
                    }}
                }}

                function showResult(data) {{
                    document.getElementById("loading").style.display = "none";
                    const resultDiv = document.getElementById("result");

                    let html = '<p class="subtitle">Detected: <strong>' + data.country_name + '</strong></p>';

                    if (data.is_blocked) {{
                        html += '<div class="status-box blocked">';
                        html += '<h2>🚫 Access Restricted</h2>';
                        html += '<p>Your location is restricted from accessing Kalshi due to regulatory requirements.</p>';
                        html += '</div>';
                        html += '<p class="note">You can still use Polymarket, Opinion, and Limitless.</p>';
                    }} else {{
                        html += '<div class="status-box allowed">';
                        html += '<h2>✅ Access Granted</h2>';
                        html += '<p>Your location allows access to Kalshi.</p>';
                        html += '</div>';
                        html += '<p class="note">You can now trade on all platforms.</p>';
                    }}

                    html += '<button class="btn" onclick="closeApp()">Close</button>';

                    resultDiv.innerHTML = html;
                    resultDiv.style.display = "block";

                    // Setup main button
                    Telegram.WebApp.MainButton.setText("Close");
                    Telegram.WebApp.MainButton.show();
                    Telegram.WebApp.MainButton.onClick(closeApp);
                }}

                function closeApp() {{
                    if (window.Telegram && window.Telegram.WebApp) {{
                        Telegram.WebApp.close();
                    }} else if (botUsername) {{
                        window.location.href = "https://t.me/" + botUsername;
                    }}
                }}

                // Start verification on page load
                verifyLocation();
            </script>
        </body>
        </html>
        """
    )


@router.get("/geo/verify-status")
async def verify_geo_status_api(
    request: Request,
    user: User = Depends(get_current_user),
):
    """
    API endpoint to verify location and return JSON status.
    Called by the geo/check page via JavaScript.
    """
    from ..utils.geo_blocking import is_country_blocked, get_country_name

    country_code = user.country
    country_name = get_country_name(country_code) if country_code else "Unknown"
    is_blocked = is_country_blocked(Platform.KALSHI, country_code) if country_code else True

    return {
        "country_code": country_code,
        "country_name": country_name,
        "is_blocked": is_blocked,
        "platform": "kalshi",
    }


@router.get("/geo/verify/{token}")
async def verify_geo_location(
    token: str,
    request: Request,
):
    """
    Verify user's country from their IP address.
    This endpoint is accessed via a link from Telegram (legacy).
    """
    from fastapi.responses import RedirectResponse, HTMLResponse
    from ..db.database import get_user_by_geo_token, set_user_country_verified
    from ..utils.geo_blocking import get_country_from_ip, is_country_blocked, get_country_name

    # Get user by token
    user = await get_user_by_geo_token(token)
    if not user:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Verification Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Verification Failed</h1>
                <p>Invalid or expired verification link.</p>
                <p>Please request a new verification link from the bot.</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Get client IP - check common headers for proxied requests
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "")
    if not client_ip:
        client_ip = request.client.host if request.client else ""

    if not client_ip:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Verification Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Verification Failed</h1>
                <p>Could not determine your location.</p>
                <p>Please try again or contact support.</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Look up country from IP
    country_code = await get_country_from_ip(client_ip)

    if not country_code:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Verification Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Verification Failed</h1>
                <p>Could not determine your country from your IP address.</p>
                <p>Please disable any VPN and try again.</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Update user's country
    await set_user_country_verified(user.id, country_code)

    country_name = get_country_name(country_code)

    # Check if blocked for Kalshi
    is_blocked = is_country_blocked(Platform.KALSHI, country_code)
    blocked_msg = ""
    if is_blocked:
        blocked_msg = f"""
        <p style="color: #ff6b6b;">⚠️ Note: Access to Kalshi is restricted in {country_name}.</p>
        <p>You can still use other platforms like Polymarket, Opinion, and Limitless.</p>
        """

    # Build redirect URL back to Telegram
    bot_username = settings.telegram_bot_username
    if bot_username:
        redirect_url = f"https://t.me/{bot_username}?start=geo_verified"
        redirect_html = f'<p><a href="{redirect_url}" style="display: inline-block; margin-top: 20px; padding: 12px 24px; background: #0088cc; color: white; text-decoration: none; border-radius: 8px;">Return to Telegram Bot</a></p>'
    else:
        redirect_html = '<p>You can now return to the Telegram bot.</p>'

    return HTMLResponse(
        content=f"""
        <html>
        <head><title>Verification Complete</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>✅ Verification Complete</h1>
            <p>Your location has been verified as: <strong>{country_name}</strong></p>
            {blocked_msg}
            {redirect_html}
        </body>
        </html>
        """
    )


# ===================
# App Factory
# ===================

def create_api_app() -> FastAPI:
    """Create the FastAPI application for the Mini App."""
    import os
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app = FastAPI(
        title="Spredd Mini App API",
        description="REST API for Spredd Telegram Mini App",
        version="1.0.0",
    )

    # Configure CORS for Mini App
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Telegram Mini App runs in iframe
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(router)

    # Include real-time streaming router
    from .realtime import router as realtime_router
    app.include_router(realtime_router, prefix="/api")

    # Real-time data lifecycle management
    @app.on_event("startup")
    async def startup_realtime():
        """Start real-time data services on app startup."""
        from src.services.polymarket_ws import polymarket_ws_manager
        from src.services.price_poller import price_poller

        # Start Polymarket WebSocket
        try:
            await polymarket_ws_manager.start()
            print("[API] Polymarket WebSocket connected")
        except Exception as e:
            print(f"[API] Failed to start Polymarket WebSocket: {e}")

        # Start price poller for other platforms
        try:
            await price_poller.start()
            print("[API] Price poller started")
        except Exception as e:
            print(f"[API] Failed to start price poller: {e}")

    @app.on_event("shutdown")
    async def shutdown_realtime():
        """Stop real-time data services on app shutdown."""
        from src.services.polymarket_ws import polymarket_ws_manager
        from src.services.price_poller import price_poller

        await polymarket_ws_manager.stop()
        await price_poller.stop()
        print("[API] Real-time services stopped")

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "spredd-miniapp-api"}

    # =========================================
    # Direct routes for webapp (no /api/v1 prefix)
    # =========================================

    @app.get("/markets")
    async def get_webapp_markets(
        platform: Optional[str] = Query(default="all"),
        limit: int = Query(default=100, le=300),
        active: bool = Query(default=True),
    ):
        """Get markets for webapp - direct route without /api/v1 prefix."""
        from ..platforms import platform_registry

        results = []

        # Determine which platforms to fetch
        if platform and platform.lower() != "all":
            platforms_to_fetch = [platform.lower()]
        else:
            platforms_to_fetch = ["kalshi", "polymarket", "limitless"]

        for plat in platforms_to_fetch:
            try:
                platform_instance = platform_registry.get(Platform(plat))
                if not platform_instance:
                    continue

                markets = await platform_instance.get_markets(limit=limit, active_only=active)
                for m in markets:
                    # Extract image from raw_data if available
                    image = None
                    if m.raw_data:
                        if "event" in m.raw_data:
                            image = m.raw_data["event"].get("image")
                        elif "image" in m.raw_data:
                            image = m.raw_data["image"]

                    slug = m.event_id or m.market_id

                    results.append({
                        "id": m.market_id,
                        "platform": plat,
                        "question": m.title,
                        "description": m.description,
                        "image": image,
                        "category": m.category or "OTHER",
                        "outcomes": ["Yes", "No"],
                        "outcomePrices": [
                            str(float(m.yes_price)) if m.yes_price else "0.5",
                            str(float(m.no_price)) if m.no_price else "0.5",
                        ],
                        "volume": float(m.volume_24h) if m.volume_24h else 0,
                        "volume24hr": float(m.volume_24h) if m.volume_24h else 0,
                        "liquidity": float(m.liquidity) if m.liquidity else 0,
                        "endDate": m.close_time,
                        "slug": slug,
                        "active": m.is_active,
                    })
            except Exception as e:
                print(f"Error fetching {plat} markets: {e}")

        results.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)
        return results[:limit]

    @app.get("/markets/{market_id}")
    async def get_webapp_market_details(market_id: str):
        """Get single market details for webapp - tries all platforms."""
        from ..platforms import platform_registry
        from ..platforms.base import Outcome

        # Try to find the market across all platforms
        for plat_name in ["polymarket", "kalshi", "limitless"]:
            try:
                platform_instance = platform_registry.get(Platform(plat_name))
                if not platform_instance:
                    continue

                market = await platform_instance.get_market(market_id)
                if market:
                    # Extract image from raw_data
                    image = None
                    if market.raw_data:
                        if "event" in market.raw_data:
                            image = market.raw_data["event"].get("image")
                        elif "image" in market.raw_data:
                            image = market.raw_data["image"]

                    # Get orderbook prices for accuracy (Polymarket)
                    yes_price = float(market.yes_price) if market.yes_price else 0.5
                    no_price = float(market.no_price) if market.no_price else 0.5

                    if plat_name == "polymarket" and hasattr(platform_instance, 'get_orderbook'):
                        try:
                            yes_orderbook = await platform_instance.get_orderbook(market_id, Outcome.YES)
                            no_orderbook = await platform_instance.get_orderbook(market_id, Outcome.NO)

                            # Use mid price from orderbook if available
                            if yes_orderbook.best_bid and yes_orderbook.best_ask:
                                yes_price = float((yes_orderbook.best_bid + yes_orderbook.best_ask) / 2)
                            elif yes_orderbook.best_ask:
                                yes_price = float(yes_orderbook.best_ask)
                            elif yes_orderbook.best_bid:
                                yes_price = float(yes_orderbook.best_bid)

                            if no_orderbook.best_bid and no_orderbook.best_ask:
                                no_price = float((no_orderbook.best_bid + no_orderbook.best_ask) / 2)
                            elif no_orderbook.best_ask:
                                no_price = float(no_orderbook.best_ask)
                            elif no_orderbook.best_bid:
                                no_price = float(no_orderbook.best_bid)
                        except Exception as e:
                            print(f"Error fetching orderbook for {market_id}: {e}")
                            # Fall back to market prices

                    return {
                        "market": {
                            "market_id": market.market_id,
                            "platform": plat_name,
                            "title": market.title,
                            "description": market.description,
                            "image": image,
                            "category": market.category,
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "volume_24h": str(market.volume_24h) if market.volume_24h else "0",
                            "liquidity": str(market.liquidity) if market.liquidity else "0",
                            "is_active": market.is_active,
                            "close_time": market.close_time,
                            "slug": market.event_id or market.market_id,
                            "outcomes": ["Yes", "No"],
                        }
                    }
            except Exception as e:
                print(f"Error fetching {plat_name} market {market_id}: {e}")
                continue

        raise HTTPException(status_code=404, detail=f"Market not found: {market_id}")

    # Serve static webapp files if they exist
    webapp_dist = Path(__file__).parent.parent.parent / "webapp" / "dist"
    print(f"[API] Webapp dist path: {webapp_dist}")
    print(f"[API] Webapp dist exists: {webapp_dist.exists()}")
    if webapp_dist.exists():
        # Serve static assets
        app.mount("/assets", StaticFiles(directory=webapp_dist / "assets"), name="assets")

        # Serve index.html for all non-API routes (SPA fallback)
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # Don't serve SPA for API routes
            if full_path.startswith("api/") or full_path == "health":
                return {"detail": "Not found"}

            # Serve static files if they exist
            file_path = webapp_dist / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)

            # Fallback to index.html for SPA routing
            return FileResponse(webapp_dist / "index.html")

    return app
