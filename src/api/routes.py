"""
FastAPI routes for Spredd Mini App.
Exposes bot functionality via REST API.
"""

import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.database import get_session
from ..db.models import (
    Chain,
    ChainFamily,
    FeeBalance,
    Order,
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
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session)
) -> User:
    """
    Validate Telegram initData and get/create user.
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

    user.active_platform = platform_enum
    await session.commit()

    return {"status": "success", "active_platform": platform}


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

    wallet_service = WalletService(session)
    await wallet_service.initialize()

    balances = []

    # Get user's wallets
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user.id)
    )
    wallets = result.scalars().all()

    for wallet in wallets:
        if wallet.chain_family == ChainFamily.EVM:
            # Get EVM balances (Polygon, Base, etc.)
            evm_balances = await wallet_service.get_evm_balances(wallet.public_key)
            balances.append({
                "chain_family": "evm",
                "public_key": wallet.public_key,
                "balances": [
                    {"token": b.token, "amount": b.amount, "chain": b.chain}
                    for b in evm_balances
                ]
            })
        elif wallet.chain_family == ChainFamily.SOLANA:
            # Get Solana balances
            sol_balances = await wallet_service.get_solana_balances(wallet.public_key)
            balances.append({
                "chain_family": "solana",
                "public_key": wallet.public_key,
                "balances": [
                    {"token": b.token, "amount": b.amount, "chain": b.chain}
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

@router.get("/markets/search")
async def search_markets(
    q: str = Query(..., min_length=1),
    platform: Optional[str] = None,
    limit: int = Query(default=20, le=100),
):
    """Search markets across platforms."""
    from ..platforms.kalshi import KalshiPlatform
    from ..platforms.polymarket import PolymarketPlatform

    results = []

    # Determine which platforms to search
    platforms_to_search = []
    if platform:
        platforms_to_search = [platform.lower()]
    else:
        platforms_to_search = ["kalshi", "polymarket"]

    for plat in platforms_to_search:
        try:
            if plat == "kalshi":
                kalshi = KalshiPlatform()
                markets = await kalshi.search_markets(q, limit=limit)
                for m in markets:
                    results.append({
                        "platform": "kalshi",
                        "id": m.get("id") or m.get("market_id"),
                        "title": m.get("title") or m.get("question"),
                        "yes_price": m.get("yes_price"),
                        "no_price": m.get("no_price"),
                        "volume": m.get("volume"),
                        "is_active": m.get("is_active", True),
                    })
            elif plat == "polymarket":
                poly = PolymarketPlatform()
                markets = await poly.search_markets(q, limit=limit)
                for m in markets:
                    results.append({
                        "platform": "polymarket",
                        "id": m.get("condition_id") or m.get("id"),
                        "title": m.get("question") or m.get("title"),
                        "yes_price": m.get("yes_price"),
                        "no_price": m.get("no_price"),
                        "volume": m.get("volume"),
                        "is_active": m.get("active", True),
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
    from ..platforms.kalshi import KalshiPlatform
    from ..platforms.polymarket import PolymarketPlatform

    results = []

    if not platform or platform.lower() == "kalshi":
        try:
            kalshi = KalshiPlatform()
            markets = await kalshi.get_trending_markets(limit=limit)
            for m in markets:
                results.append({
                    "platform": "kalshi",
                    "id": m.get("id") or m.get("market_id"),
                    "title": m.get("title") or m.get("question"),
                    "yes_price": m.get("yes_price"),
                    "no_price": m.get("no_price"),
                    "volume": m.get("volume"),
                })
        except Exception as e:
            print(f"Error getting Kalshi trending: {e}")

    if not platform or platform.lower() == "polymarket":
        try:
            poly = PolymarketPlatform()
            markets = await poly.get_trending_markets(limit=limit)
            for m in markets:
                results.append({
                    "platform": "polymarket",
                    "id": m.get("condition_id") or m.get("id"),
                    "title": m.get("question") or m.get("title"),
                    "yes_price": m.get("yes_price"),
                    "no_price": m.get("no_price"),
                    "volume": m.get("volume"),
                })
        except Exception as e:
            print(f"Error getting Polymarket trending: {e}")

    return {"markets": results[:limit]}


@router.get("/markets/{platform}/{market_id}")
async def get_market_details(
    platform: str,
    market_id: str,
):
    """Get detailed market information."""
    from ..platforms.kalshi import KalshiPlatform
    from ..platforms.polymarket import PolymarketPlatform

    try:
        if platform.lower() == "kalshi":
            kalshi = KalshiPlatform()
            market = await kalshi.get_market(market_id)
        elif platform.lower() == "polymarket":
            poly = PolymarketPlatform()
            market = await poly.get_market(market_id)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        return {"market": market}

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
    from ..platforms.kalshi import KalshiPlatform
    from ..platforms.polymarket import PolymarketPlatform

    try:
        platform = request.platform.lower()

        if platform == "kalshi":
            plat = KalshiPlatform()
        elif platform == "polymarket":
            plat = PolymarketPlatform()
        else:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        quote = await plat.get_quote(
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            amount=request.amount,
        )

        return QuoteResponse(
            platform=platform,
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            input_amount=quote.get("input_amount", request.amount),
            expected_output=quote.get("expected_output", "0"),
            price=float(quote.get("price", 0)),
            price_impact=quote.get("price_impact"),
            fees=quote.get("fees", {}),
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trading/execute", response_model=OrderResponse)
async def execute_order(
    request: OrderRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Execute a trade order."""
    from ..services.wallet import WalletService
    from ..platforms.kalshi import KalshiPlatform
    from ..platforms.polymarket import PolymarketPlatform

    try:
        platform = request.platform.lower()

        # Get user's wallet
        if platform == "kalshi":
            chain_family = ChainFamily.SOLANA
            plat = KalshiPlatform()
        elif platform == "polymarket":
            chain_family = ChainFamily.EVM
            plat = PolymarketPlatform()
        else:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

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

        # Decrypt private key
        wallet_service = WalletService(session)
        private_key = wallet_service.decrypt_private_key(wallet.encrypted_private_key)

        # Execute order
        tx_result = await plat.execute_order(
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            amount=request.amount,
            private_key=private_key,
            slippage_bps=request.slippage_bps,
        )

        # Create order record
        order = Order(
            id=str(uuid.uuid4()),
            user_id=user.id,
            platform=Platform(platform),
            chain=Chain.SOLANA if platform == "kalshi" else Chain.POLYGON,
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            input_token="USDC",
            input_amount=request.amount,
            output_token=f"{request.outcome.upper()} shares",
            expected_output=tx_result.get("expected_output", "0"),
            actual_output=tx_result.get("actual_output"),
            status=tx_result.get("status", "submitted"),
            tx_hash=tx_result.get("tx_hash"),
        )
        session.add(order)
        await session.commit()

        return OrderResponse(
            order_id=order.id,
            status=order.status,
            tx_hash=order.tx_hash,
            message=tx_result.get("message", "Order submitted"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "spredd-miniapp-api"}

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
