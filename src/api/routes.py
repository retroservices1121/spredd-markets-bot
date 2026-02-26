"""
FastAPI routes for Spredd Mini App.
Exposes bot functionality via REST API.
"""

import asyncio
import hashlib
import random
import time
import uuid
from decimal import Decimal
from typing import Any, Optional

import jwt

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware

from .coalesce import coalesce
from .rate_limit import limiter, rate_limit_handler, get_user_key
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
from .auth import TelegramUser, get_user_from_init_data, validate_telegram_login, validate_wallet_signature

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
# Pagination Helper
# ===================

def paginate_results(items: list, page: int, limit: int) -> tuple[dict, list]:
    """Slice a list and return pagination metadata + page items."""
    total = len(items)
    offset = (page - 1) * limit
    page_items = items[offset:offset + limit]
    return {
        "pagination": {"page": page, "limit": limit, "total": total, "has_more": (offset + limit) < total}
    }, page_items


# ===================
# Dependencies
# ===================

async def get_current_user(
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_wallet_address: Optional[str] = Header(None, alias="X-Wallet-Address"),
    x_wallet_signature: Optional[str] = Header(None, alias="X-Wallet-Signature"),
    x_wallet_timestamp: Optional[str] = Header(None, alias="X-Wallet-Timestamp"),
    session: AsyncSession = Depends(get_session)
) -> User:
    """
    Authenticate via Telegram initData, wallet signature, or JWT Bearer token.
    Also automatically captures user's country from IP for geo-blocking.

    Auth methods (checked in order):
    1. Telegram initData (X-Telegram-Init-Data header)
    2. Wallet signature (X-Wallet-Address + X-Wallet-Signature + X-Wallet-Timestamp)
    3. JWT Bearer token (Authorization header, for PWA)
    """
    user: Optional[User] = None

    # Method 1: Telegram initData
    if x_telegram_init_data:
        tg_user = get_user_from_init_data(x_telegram_init_data, settings.telegram_bot_token)
        if tg_user:
            result = await session.execute(
                select(User).where(User.telegram_id == tg_user.id)
            )
            user = result.scalar_one_or_none()

            if not user:
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

    # Method 2: Wallet signature (for Chrome extension)
    if not user and x_wallet_address and x_wallet_signature and x_wallet_timestamp:
        verified_address = validate_wallet_signature(
            x_wallet_address, x_wallet_signature, x_wallet_timestamp
        )
        if verified_address:
            # Find user by wallet public_key
            result = await session.execute(
                select(User).join(Wallet).where(
                    Wallet.public_key.ilike(verified_address)
                )
            )
            user = result.scalar_one_or_none()

    # Method 3: JWT Bearer token (for PWA)
    if not user:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, settings.telegram_bot_token, algorithms=["HS256"])
                telegram_id = int(payload["sub"])
                result = await session.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
                user = result.scalar_one_or_none()
            except Exception:
                pass

    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication")

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
# Auth Endpoints (PWA)
# ===================

@router.post("/auth/telegram-login")
async def telegram_login(payload: dict, session: AsyncSession = Depends(get_session)):
    """Exchange Telegram Login Widget data for a JWT token.

    The PWA uses Telegram Login Widget (different from Mini App initData).
    Returns a long-lived JWT for subsequent API calls.
    """
    user_data = validate_telegram_login(payload, settings.telegram_bot_token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram login")

    # Find or create user (same as existing initData flow)
    result = await session.execute(
        select(User).where(User.telegram_id == user_data.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            telegram_id=user_data.id,
            username=user_data.username,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Issue JWT (30-day expiry)
    token = jwt.encode(
        {"sub": str(user.telegram_id), "exp": int(time.time()) + 86400 * 30},
        settings.telegram_bot_token,
        algorithm="HS256",
    )
    return {
        "token": token,
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
        },
    }


# ===================
# Feed Endpoint (PWA)
# ===================

@router.get("/markets/feed")
@limiter.limit(settings.rate_limit_heavy)
async def get_market_feed(
    request: Request,
    cursor: Optional[int] = Query(default=None),
    limit: int = Query(default=20, le=50),
):
    """Get shuffled markets for the TikTok-style feed.

    Returns markets with images, randomized but deterministic per cursor position.
    Pulls from the cached trending markets across all platforms.
    """
    from ..platforms import platform_registry

    all_markets: list[dict] = []

    # Gather markets from trending cache — try Redis first, then in-memory
    cache_key = "all"
    rc = _get_redis_cache()
    if rc and rc.is_available:
        redis_hit = await rc.get_api_trending(cache_key)
        if redis_hit is not None:
            all_markets = list(redis_hit)
    if not all_markets:
        now = time.time()
        cached = _trending_cache.get(cache_key)
        if cached and (now - cached[0]) < _TRENDING_CACHE_TTL:
            all_markets = list(cached[1])
    if not all_markets:
        # Coalesce concurrent cache misses — only one coroutine fetches
        async def _fetch_feed():
            _all = []
            for plat_name in ["polymarket", "kalshi", "limitless"]:
                try:
                    plat_instance = platform_registry.get(Platform(plat_name))
                    if plat_instance:
                        markets = await plat_instance.get_trending_markets(limit=50)
                        for m in markets:
                            image = m.image_url
                            if not image and m.raw_data:
                                if "event" in m.raw_data:
                                    image = m.raw_data["event"].get("image")
                                elif "image" in m.raw_data:
                                    image = m.raw_data["image"]
                            _all.append({
                                "id": m.market_id,
                                "platform": plat_name,
                                "title": m.title,
                                "image": image,
                                "yes_price": float(m.yes_price) if m.yes_price else 0.5,
                                "no_price": float(m.no_price) if m.no_price else 0.5,
                                "volume": float(m.volume_24h) if m.volume_24h else 0,
                                "category": getattr(m, "category", None),
                                "end_date": getattr(m, "end_date", None),
                            })
                except Exception as e:
                    print(f"[Feed] Error fetching {plat_name}: {e}")
            return _all

        async def _recheck_feed():
            _rc = _get_redis_cache()
            if _rc and _rc.is_available:
                hit = await _rc.get_api_trending("all")
                if hit is not None:
                    return list(hit)
            _now = time.time()
            _cached = _trending_cache.get("all")
            if _cached and (_now - _cached[0]) < _TRENDING_CACHE_TTL:
                return list(_cached[1])
            return None

        all_markets = await coalesce("feed:all", _fetch_feed, _recheck_feed)

    # Filter to markets with images for the visual feed
    feed_markets = [m for m in all_markets if m.get("image")]
    # Fall back to all markets if not enough have images
    if len(feed_markets) < 5:
        feed_markets = all_markets

    # Shuffle deterministically by day so feed changes daily but is stable per session
    day_seed = int(time.time() // 86400)
    rng = random.Random(day_seed)
    rng.shuffle(feed_markets)

    # Pagination
    start = cursor or 0
    end = start + limit
    page = feed_markets[start:end]
    next_cursor = end if end < len(feed_markets) else None

    return {
        "markets": page,
        "next_cursor": next_cursor,
    }


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


@router.get("/config/platform-keys")
async def get_platform_keys(user: User = Depends(get_current_user)):
    """Return platform API keys for direct market data fetching.

    Keys are served to authenticated users so the extension can fetch
    market data directly from each platform's API (faster than proxying
    through the bot API).  Keys never appear in extension source code.
    """
    keys: dict[str, dict[str, str]] = {}
    if settings.dflow_api_key:
        keys["kalshi"] = {
            "base_url": "https://c.prediction-markets-api.dflow.net",
            "header": "x-api-key",
            "key": settings.dflow_api_key,
        }
    if settings.opinion_api_key:
        keys["opinion"] = {
            "base_url": settings.opinion_api_url,
            "header": "apikey",
            "key": settings.opinion_api_key.strip(),
        }
    if settings.limitless_api_key:
        keys["limitless"] = {
            "base_url": settings.limitless_api_url,
            "header": "X-API-Key",
            "key": settings.limitless_api_key,
        }
    if settings.myriad_api_key:
        keys["myriad"] = {
            "base_url": settings.myriad_api_url,
            "header": "x-api-key",
            "key": settings.myriad_api_key,
        }
    if settings.jupiter_api_key:
        keys["jupiter"] = {
            "base_url": settings.jupiter_api_url,
            "header": "x-api-key",
            "key": settings.jupiter_api_key,
        }
    return {"keys": keys}


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
@limiter.limit(settings.rate_limit_heavy)
async def get_all_markets(
    request: Request,
    platform: Optional[str] = Query(default="all", description="Platform filter: all, polymarket, kalshi, opinion, limitless, myriad"),
    limit: int = Query(default=25, le=25),
    page: int = Query(default=1, ge=1),
    active: bool = Query(default=True),
):
    """Get markets from all platforms for the webapp."""
    from ..platforms import platform_registry

    # Check Redis cache first, then in-memory fallback
    plat_key = (platform or "all").lower()
    cache_key = (plat_key, active)
    rc = _get_redis_cache()
    if rc and rc.is_available:
        redis_hit = await rc.get_api_markets(plat_key, active)
        if redis_hit is not None:
            meta, page_items = paginate_results(redis_hit, page, limit)
            return {"markets": page_items, **meta}
    now = time.time()
    cached = _markets_cache.get(cache_key)
    if cached and (now - cached[0]) < _MARKETS_CACHE_TTL:
        meta, page_items = paginate_results(cached[1], page, limit)
        return {"markets": page_items, **meta}

    # Coalesce concurrent cache misses for the same platform/active combo
    coalesce_key = f"markets:{plat_key}:{active}"

    async def _fetch_markets():
        results = []
        if platform and platform.lower() != "all":
            platforms_to_fetch = [platform.lower()]
        else:
            platforms_to_fetch = ["kalshi", "polymarket", "opinion", "limitless", "myriad"]

        per_platform_limit = limit if len(platforms_to_fetch) == 1 else max(limit, 200)

        for plat in platforms_to_fetch:
            try:
                platform_instance = platform_registry.get(Platform(plat))
                if not platform_instance:
                    continue

                markets = await platform_instance.get_markets(limit=per_platform_limit, active_only=active)
                for m in markets:
                    image = m.image_url
                    if not image and plat == "polymarket" and m.raw_data:
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
                        "event_id": m.event_id,
                        "is_multi_outcome": m.is_multi_outcome,
                        "outcome_name": m.outcome_name,
                        "related_market_count": m.related_market_count,
                    })
            except Exception as e:
                print(f"Error fetching {plat} markets: {e}")

        # Sort
        if platform and platform.lower() == "kalshi":
            rapid = [r for r in results if _is_rapid_market(r["id"])]
            regular = [r for r in results if not _is_rapid_market(r["id"])]
            rapid.sort(key=lambda x: x.get("endDate") or "9999", reverse=False)
            regular.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)
            results = rapid + regular
        else:
            results.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)

        # Update cache
        _now = time.time()
        _markets_cache[cache_key] = (_now, results)
        _evict_cache(_markets_cache, _MARKETS_CACHE_TTL)
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            await _rc.set_api_markets(plat_key, active, results)

        return results

    async def _recheck_markets():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            hit = await _rc.get_api_markets(plat_key, active)
            if hit is not None:
                return hit
        _now = time.time()
        _cached = _markets_cache.get(cache_key)
        if _cached and (_now - _cached[0]) < _MARKETS_CACHE_TTL:
            return _cached[1]
        return None

    results = await coalesce(coalesce_key, _fetch_markets, _recheck_markets)
    meta, page_items = paginate_results(results, page, limit)
    return {"markets": page_items, **meta}


# API response caches: in-memory fallback when Redis is unavailable
# key -> (timestamp, results)
_search_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_markets_cache: dict[tuple[str, bool], tuple[float, list[dict]]] = {}
_trending_cache: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 120  # 2 minutes
_MARKETS_CACHE_TTL = 120  # 2 minutes
_TRENDING_CACHE_TTL = 120  # 2 minutes

# Redis cache import (lazy — module may not be loaded yet during import)
_redis_cache = None

def _get_redis_cache():
    """Get Redis cache singleton (lazy import)."""
    global _redis_cache
    if _redis_cache is None:
        try:
            from src.services.cache import cache
            _redis_cache = cache
        except Exception:
            pass
    return _redis_cache


def _evict_cache(cache_dict: dict, ttl: float) -> None:
    """Remove stale entries from a cache dict."""
    now = time.time()
    stale = [k for k, v in cache_dict.items() if (now - v[0]) > ttl * 5]
    for k in stale:
        del cache_dict[k]


# ---------------------------------------------------------------------------
# Background cache warmer — pre-fetches markets every 60s so every request
# is an instant cache hit. Populates the same _markets_cache / _trending_cache
# dicts that the endpoints already read from.
# ---------------------------------------------------------------------------
_WARM_INTERVAL = 60  # seconds between background refreshes
_cache_warmer_task: asyncio.Task | None = None

_ALL_PLATFORMS = ["kalshi", "polymarket", "opinion", "limitless", "myriad"]


_RAPID_PREFIXES = (
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",
    "KXBTC5M", "KXETH5M", "KXSOL5M", "KXXRP5M", "KXDOGE5M",
    "KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED",
)


def _is_rapid_market(market_id: str) -> bool:
    """Check if a Kalshi market is a rapid (5-min, 15-min, hourly) market."""
    t = (market_id or "").upper()
    return any(t.startswith(p) for p in _RAPID_PREFIXES)


async def _warm_markets_cache() -> None:
    """Fetch markets for each platform + 'all' and store in _markets_cache."""
    from ..platforms import platform_registry

    # Warm per-platform caches
    for plat in _ALL_PLATFORMS:
        try:
            platform_instance = platform_registry.get(Platform(plat))
            if not platform_instance:
                continue

            markets = await platform_instance.get_markets(limit=1000, active_only=True)
            results = []
            for m in markets:
                image = m.image_url
                if not image and plat == "polymarket" and m.raw_data:
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
                    "event_id": m.event_id,
                    "is_multi_outcome": m.is_multi_outcome,
                    "outcome_name": m.outcome_name,
                    "related_market_count": m.related_market_count,
                })

            # For Kalshi: boost rapid markets (5-min, 15-min, hourly) to the
            # top so they survive any limit truncation. They're sorted by
            # soonest ending first, then the rest by volume.
            if plat == "kalshi":
                rapid = [r for r in results if _is_rapid_market(r["id"])]
                regular = [r for r in results if not _is_rapid_market(r["id"])]
                rapid.sort(key=lambda x: x.get("endDate") or "9999", reverse=False)
                regular.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)
                results = rapid + regular
                print(f"[CacheWarmer] Kalshi: {len(rapid)} rapid + {len(regular)} regular markets")
            else:
                results.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)

            now = time.time()
            _markets_cache[(plat, True)] = (now, results)
            # Also write to Redis
            rc = _get_redis_cache()
            if rc and rc.is_available:
                await rc.set_api_markets(plat, True, results)
        except Exception as e:
            print(f"[CacheWarmer] Error warming {plat}: {e}")

    # Build the combined "all" cache from per-platform caches
    all_results = []
    for plat in _ALL_PLATFORMS:
        cached = _markets_cache.get((plat, True))
        if cached:
            all_results.extend(cached[1])
    all_results.sort(key=lambda x: x.get("volume24hr", 0), reverse=True)
    _markets_cache[("all", True)] = (time.time(), all_results)
    rc = _get_redis_cache()
    if rc and rc.is_available:
        await rc.set_api_markets("all", True, all_results)


async def _warm_trending_cache() -> None:
    """Pre-warm the trending markets cache."""
    from ..platforms import platform_registry

    results = []
    for plat in _ALL_PLATFORMS:
        try:
            platform_instance = platform_registry.get(Platform(plat))
            if not platform_instance or not hasattr(platform_instance, "get_trending_markets"):
                continue
            markets = await platform_instance.get_trending_markets(limit=50)
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
            print(f"[CacheWarmer] Error warming trending {plat}: {e}")

    now = time.time()
    _trending_cache["all"] = (now, results)

    # Also cache per-platform trending
    for plat in _ALL_PLATFORMS:
        plat_results = [r for r in results if r["platform"] == plat]
        if plat_results:
            _trending_cache[plat] = (now, plat_results)

    # Write to Redis
    rc = _get_redis_cache()
    if rc and rc.is_available:
        await rc.set_api_trending("all", results)
        for plat in _ALL_PLATFORMS:
            plat_results = [r for r in results if r["platform"] == plat]
            if plat_results:
                await rc.set_api_trending(plat, plat_results)


async def _cache_warmer_loop() -> None:
    """Background loop that refreshes market caches every _WARM_INTERVAL seconds."""
    # Initial warm — run immediately on startup
    print("[CacheWarmer] Initial cache warm starting...")
    try:
        await _warm_markets_cache()
        await _warm_trending_cache()
        print("[CacheWarmer] Initial cache warm complete")
    except Exception as e:
        print(f"[CacheWarmer] Initial warm failed: {e}")

    while True:
        await asyncio.sleep(_WARM_INTERVAL)
        try:
            await _warm_markets_cache()
            await _warm_trending_cache()
        except Exception as e:
            print(f"[CacheWarmer] Refresh failed: {e}")


def start_cache_warmer() -> None:
    """Start the background cache warmer task."""
    global _cache_warmer_task
    if _cache_warmer_task is None or _cache_warmer_task.done():
        _cache_warmer_task = asyncio.create_task(_cache_warmer_loop())
        print("[CacheWarmer] Background cache warmer started (60s interval)")


def stop_cache_warmer() -> None:
    """Stop the background cache warmer task."""
    global _cache_warmer_task
    if _cache_warmer_task and not _cache_warmer_task.done():
        _cache_warmer_task.cancel()
        _cache_warmer_task = None
        print("[CacheWarmer] Background cache warmer stopped")


@router.get("/markets/kalshi/event/{event_id}")
@limiter.limit(settings.rate_limit_heavy)
async def get_kalshi_event(request: Request, event_id: str):
    """Get Kalshi event with nested markets and image."""
    from ..platforms import platform_registry

    kalshi = platform_registry.get(Platform.KALSHI)
    if not kalshi:
        raise HTTPException(status_code=503, detail="Kalshi platform not available")

    # Check Redis cache
    rc = _get_redis_cache()
    cache_key = f"spredd:api:kalshi:event:{event_id}"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            return cached

    async def _fetch():
        data = await kalshi.get_event(event_id)
        if not data:
            raise HTTPException(status_code=404, detail="Event not found")
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            from src.config import settings as _s
            await _rc.set_json(cache_key, data, _s.cache_ttl_market_detail)
        return data

    async def _recheck():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            return await _rc.get_json(cache_key)
        return None

    return await coalesce(f"kalshi_event:{event_id}", _fetch, _recheck)


@router.get("/markets/kalshi/{market_id}/candlesticks")
@limiter.limit(settings.rate_limit_heavy)
async def get_kalshi_candlesticks(
    request: Request,
    market_id: str,
    start_ts: int = Query(..., description="Start timestamp (unix seconds)"),
    end_ts: int = Query(..., description="End timestamp (unix seconds)"),
    interval: int = Query(default=60, description="1, 60, or 1440 minutes"),
):
    """Get price candlestick data for a Kalshi market."""
    from ..platforms import platform_registry

    kalshi = platform_registry.get(Platform.KALSHI)
    if not kalshi:
        raise HTTPException(status_code=503, detail="Kalshi platform not available")

    # Check Redis cache (candlestick data is semi-static for completed intervals)
    rc = _get_redis_cache()
    cache_key = f"spredd:api:kalshi:candles:{market_id}:{start_ts}:{end_ts}:{interval}"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            return cached

    async def _fetch():
        data = await kalshi.get_market_candlesticks(market_id, start_ts, end_ts, interval)
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            from src.config import settings as _s
            await _rc.set_json(cache_key, data, _s.cache_ttl_markets)
        return data

    async def _recheck():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            return await _rc.get_json(cache_key)
        return None

    return await coalesce(f"kalshi_candles:{market_id}:{start_ts}:{end_ts}:{interval}", _fetch, _recheck)


@router.get("/markets/kalshi/{market_id}/trades")
@limiter.limit(settings.rate_limit_heavy)
async def get_kalshi_trades(
    request: Request,
    market_id: str,
    limit: int = Query(default=100, le=1000),
):
    """Get recent trades for a Kalshi market."""
    from ..platforms import platform_registry

    kalshi = platform_registry.get(Platform.KALSHI)
    if not kalshi:
        raise HTTPException(status_code=503, detail="Kalshi platform not available")

    # Check Redis cache
    rc = _get_redis_cache()
    cache_key = f"spredd:api:kalshi:trades:{market_id}:{limit}"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            return cached

    async def _fetch():
        trades = await kalshi.get_trades(market_id=market_id, limit=limit)
        result = {"trades": trades}
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            from src.config import settings as _s
            await _rc.set_json(cache_key, result, _s.cache_ttl_market_detail)
        return result

    async def _recheck():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            return await _rc.get_json(cache_key)
        return None

    return await coalesce(f"kalshi_trades:{market_id}:{limit}", _fetch, _recheck)


@router.get("/markets/search")
@limiter.limit(settings.rate_limit_heavy)
async def search_markets(
    request: Request,
    q: str = Query(..., min_length=1),
    platform: Optional[str] = None,
    limit: int = Query(default=20, le=25),
    page: int = Query(default=1, ge=1),
):
    """Search markets across platforms."""
    from ..platforms import platform_registry

    # Check Redis cache first, then in-memory fallback
    plat_str = (platform or "all").lower()
    cache_key = (q.lower().strip(), plat_str)
    rc = _get_redis_cache()
    if rc and rc.is_available:
        redis_hit = await rc.get_api_search(q, plat_str)
        if redis_hit is not None:
            meta, page_items = paginate_results(redis_hit, page, limit)
            return {"markets": page_items, **meta}
    now = time.time()
    cached = _search_cache.get(cache_key)
    if cached and (now - cached[0]) < _SEARCH_CACHE_TTL:
        meta, page_items = paginate_results(cached[1], page, limit)
        return {"markets": page_items, **meta}

    q_hash = hashlib.md5(q.lower().strip().encode()).hexdigest()[:8]

    async def _fetch_search():
        results = []
        platforms_to_search = [platform.lower()] if platform else ["kalshi", "polymarket", "opinion", "limitless", "myriad"]
        per_platform_limit = limit if len(platforms_to_search) == 1 else max(limit, 50)

        for plat in platforms_to_search:
            try:
                platform_instance = platform_registry.get(Platform(plat))
                if not platform_instance:
                    continue

                markets = await platform_instance.search_markets(q, limit=per_platform_limit)
                for m in markets:
                    image = m.image_url
                    if not image and plat == "polymarket" and m.raw_data:
                        if "event" in m.raw_data:
                            image = m.raw_data["event"].get("image")
                        elif "image" in m.raw_data:
                            image = m.raw_data["image"]
                    results.append({
                        "platform": plat,
                        "id": m.market_id,
                        "title": m.title,
                        "image": image,
                        "yes_price": float(m.yes_price) if m.yes_price else None,
                        "no_price": float(m.no_price) if m.no_price else None,
                        "volume": str(m.volume_24h) if m.volume_24h else None,
                        "is_active": m.is_active,
                        "event_id": m.event_id,
                    })
            except Exception as e:
                print(f"Error searching {plat}: {e}")

        _now = time.time()
        _search_cache[cache_key] = (_now, results)
        _evict_cache(_search_cache, _SEARCH_CACHE_TTL)
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            await _rc.set_api_search(q, plat_str, results)
        return results

    async def _recheck_search():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            hit = await _rc.get_api_search(q, plat_str)
            if hit is not None:
                return hit
        _now = time.time()
        _cached = _search_cache.get(cache_key)
        if _cached and (_now - _cached[0]) < _SEARCH_CACHE_TTL:
            return _cached[1]
        return None

    results = await coalesce(f"search:{q_hash}:{plat_str}", _fetch_search, _recheck_search)
    meta, page_items = paginate_results(results, page, limit)
    return {"markets": page_items, **meta}


@router.get("/markets/trending")
@limiter.limit(settings.rate_limit_heavy)
async def get_trending_markets(
    request: Request,
    platform: Optional[str] = None,
    limit: int = Query(default=10, le=25),
    page: int = Query(default=1, ge=1),
):
    """Get trending markets."""
    from ..platforms import platform_registry

    # Check Redis cache first, then in-memory fallback
    plat_key = (platform or "all").lower()
    rc = _get_redis_cache()
    if rc and rc.is_available:
        redis_hit = await rc.get_api_trending(plat_key)
        if redis_hit is not None:
            meta, page_items = paginate_results(redis_hit, page, limit)
            return {"markets": page_items, **meta}
    now = time.time()
    cached = _trending_cache.get(plat_key)
    if cached and (now - cached[0]) < _TRENDING_CACHE_TTL:
        meta, page_items = paginate_results(cached[1], page, limit)
        return {"markets": page_items, **meta}

    async def _fetch_trending():
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
                            "image": m.image_url,
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
                        image = m.image_url
                        if not image and m.raw_data:
                            if "event" in m.raw_data:
                                image = m.raw_data["event"].get("image")
                            elif "image" in m.raw_data:
                                image = m.raw_data["image"]
                        results.append({
                            "platform": "polymarket",
                            "id": m.market_id,
                            "title": m.title,
                            "image": image,
                            "yes_price": float(m.yes_price) if m.yes_price else None,
                            "no_price": float(m.no_price) if m.no_price else None,
                            "volume": str(m.volume_24h) if m.volume_24h else None,
                            "is_active": m.is_active,
                        })
            except Exception as e:
                print(f"Error getting Polymarket trending: {e}")

        for plat_name in ["opinion", "limitless", "myriad"]:
            if not platform or platform.lower() == plat_name:
                try:
                    plat_instance = platform_registry.get(Platform(plat_name))
                    if plat_instance and hasattr(plat_instance, 'get_trending_markets'):
                        markets = await plat_instance.get_trending_markets(limit=limit)
                        for m in markets:
                            results.append({
                                "platform": plat_name,
                                "id": m.market_id,
                                "title": m.title,
                                "image": m.image_url,
                                "yes_price": float(m.yes_price) if m.yes_price else None,
                                "no_price": float(m.no_price) if m.no_price else None,
                                "volume": str(m.volume_24h) if m.volume_24h else None,
                                "is_active": m.is_active,
                            })
                except Exception as e:
                    print(f"Error getting {plat_name} trending: {e}")

        _now = time.time()
        _trending_cache[plat_key] = (_now, results)
        _evict_cache(_trending_cache, _TRENDING_CACHE_TTL)
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            await _rc.set_api_trending(plat_key, results)
        return results

    async def _recheck_trending():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            hit = await _rc.get_api_trending(plat_key)
            if hit is not None:
                return hit
        _now = time.time()
        _cached = _trending_cache.get(plat_key)
        if _cached and (_now - _cached[0]) < _TRENDING_CACHE_TTL:
            return _cached[1]
        return None

    results = await coalesce(f"trending:{plat_key}", _fetch_trending, _recheck_trending)
    meta, page_items = paginate_results(results, page, limit)
    return {"markets": page_items, **meta}


@router.get("/markets/categories")
@limiter.limit(settings.rate_limit_heavy)
async def get_market_categories(request: Request):
    """Get available market categories for Polymarket."""
    from ..platforms import platform_registry

    # Check Redis cache (categories are fairly static)
    rc = _get_redis_cache()
    cache_key = "spredd:api:categories"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            return cached

    _default_categories = {
        "categories": [
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
            {"id": "business", "label": "Business", "emoji": "💼"},
            {"id": "science", "label": "Science", "emoji": "🔬"},
        ]
    }

    async def _fetch_categories():
        try:
            poly = platform_registry.get(Platform.POLYMARKET)
            if poly and hasattr(poly, 'get_available_categories'):
                categories = poly.get_available_categories()
                result = {"categories": categories}
                _rc = _get_redis_cache()
                if _rc and _rc.is_available:
                    await _rc.set_json(cache_key, result, 300)
                return result
        except Exception as e:
            print(f"Error getting categories: {e}")
        return _default_categories

    async def _recheck_categories():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            return await _rc.get_json(cache_key)
        return None

    return await coalesce("categories", _fetch_categories, _recheck_categories)


@router.get("/markets/category/{category}")
@limiter.limit(settings.rate_limit_heavy)
async def get_markets_by_category(
    request: Request,
    category: str,
    limit: int = Query(default=20, le=25),
    page: int = Query(default=1, ge=1),
):
    """Get markets by category (Polymarket only)."""
    from ..platforms import platform_registry

    # Check Redis cache
    rc = _get_redis_cache()
    cache_key = f"spredd:api:category:{category}"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            # Handle both old {"markets": [...]} and new [...] cache format
            items = cached.get("markets", cached) if isinstance(cached, dict) else cached
            meta, page_items = paginate_results(items, page, limit)
            return {"markets": page_items, **meta}

    async def _fetch_category():
        poly = platform_registry.get(Platform.POLYMARKET)
        if not poly:
            raise HTTPException(status_code=400, detail="Polymarket not available")

        markets = await poly.get_markets_by_category(category, limit=100)
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
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            from src.config import settings as _s
            await _rc.set_json(cache_key, results, _s.cache_ttl_markets)
        return results

    async def _recheck_category():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            hit = await _rc.get_json(cache_key)
            if hit is not None:
                return hit.get("markets", hit) if isinstance(hit, dict) else hit
        return None

    try:
        results = await coalesce(f"category:{category}", _fetch_category, _recheck_category)
        meta, page_items = paginate_results(results, page, limit)
        return {"markets": page_items, **meta}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching markets: {e}")


@router.get("/markets/{platform}/{market_id}")
async def get_market_details(
    request: Request,
    platform: str,
    market_id: str,
):
    """Get detailed market information."""
    from ..platforms import platform_registry

    # Check Redis cache
    rc = _get_redis_cache()
    plat_lower = platform.lower()
    cache_key = f"spredd:api:market:{plat_lower}:{market_id}"
    if rc and rc.is_available:
        cached = await rc.get_json(cache_key)
        if cached is not None:
            return cached

    async def _fetch_detail():
        platform_instance = platform_registry.get(Platform(plat_lower))
        if not platform_instance:
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        market = await platform_instance.get_market(market_id)
        result = {"market": market}
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            from src.config import settings as _s
            await _rc.set_json(cache_key, result, _s.cache_ttl_market_detail)
        return result

    async def _recheck_detail():
        _rc = _get_redis_cache()
        if _rc and _rc.is_available:
            return await _rc.get_json(cache_key)
        return None

    try:
        return await coalesce(f"detail:{plat_lower}:{market_id}", _fetch_detail, _recheck_detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Market not found: {e}")


# ===================
# Trading Endpoints
# ===================

@router.post("/trading/quote", response_model=QuoteResponse)
@limiter.limit(settings.rate_limit_trading, key_func=get_user_key)
async def get_quote(
    request: Request,
    body: QuoteRequest = ...,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get a quote for a trade."""
    from ..platforms import platform_registry

    try:
        platform = body.platform.lower()

        try:
            plat = platform_registry.get(Platform(platform))
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        if not plat:
            raise HTTPException(status_code=400, detail=f"Platform not initialized: {platform}")

        # Convert amount to Decimal for platform methods
        amount_decimal = Decimal(str(body.amount))

        # Convert outcome string to Outcome enum
        try:
            outcome_enum = Outcome(body.outcome.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid outcome: {body.outcome}")

        quote = await plat.get_quote(
            market_id=body.market_id,
            outcome=outcome_enum,
            side=body.side,
            amount=amount_decimal,
        )

        # Quote is a dataclass, access attributes directly
        return QuoteResponse(
            platform=platform,
            market_id=body.market_id,
            outcome=body.outcome,
            side=body.side,
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
@limiter.limit(settings.rate_limit_trading, key_func=get_user_key)
async def execute_order(
    request: Request,
    body: OrderRequest = ...,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Execute a trade order."""
    from ..platforms import platform_registry
    from ..utils.encryption import decrypt

    try:
        platform = body.platform.lower()

        # Get platform and determine chain family
        try:
            plat = platform_registry.get(Platform(platform))
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

        if not plat:
            raise HTTPException(status_code=400, detail=f"Platform not initialized: {platform}")

        # Determine chain family based on platform
        if platform in ("kalshi", "jupiter"):
            chain_family = ChainFamily.SOLANA
        elif platform in ("polymarket", "opinion", "limitless", "myriad"):
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
        amount_decimal = Decimal(str(body.amount))

        # Convert outcome string to Outcome enum
        try:
            outcome_enum = Outcome(body.outcome.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid outcome: {body.outcome}")

        # Convert private key to appropriate type based on platform
        # decrypt() returns raw bytes
        if platform in ("kalshi", "jupiter"):
            from solders.keypair import Keypair
            # Solana private key is raw bytes (64 bytes)
            signing_key = Keypair.from_bytes(private_key)
        else:
            from eth_account import Account
            # EVM private key is raw bytes (32 bytes)
            signing_key = Account.from_key(private_key)

        # First get a quote
        quote = await plat.get_quote(
            market_id=body.market_id,
            outcome=outcome_enum,
            side=body.side,
            amount=amount_decimal,
        )

        # Execute the trade using the quote
        tx_result = await plat.execute_trade(
            quote=quote,
            private_key=signing_key,
        )

        # Create order record
        platform_enum = Platform(platform)
        chain_map = {
            "kalshi": Chain.SOLANA,
            "polymarket": Chain.POLYGON,
            "opinion": Chain.BSC,
            "limitless": Chain.BASE,
            "myriad": Chain.ABSTRACT,
            "jupiter": Chain.SOLANA,
        }
        chain_enum = chain_map.get(platform, Chain.POLYGON)

        order = Order(
            id=str(uuid.uuid4()),
            user_id=user.id,
            platform=platform_enum,
            chain=chain_enum,
            market_id=body.market_id,
            outcome=body.outcome,
            side=body.side,
            input_token="USDC",
            input_amount=body.amount,
            output_token=f"{body.outcome.upper()} shares",
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
                market = await plat.get_market(body.market_id)
                market_title = market.title if market else f"Market {body.market_id[:16]}..."
            except Exception:
                market_title = f"Market {body.market_id[:16]}..."

            # Get token_id from quote_data
            token_id = quote.quote_data.get("token_id", "") if quote.quote_data else ""

            # Calculate amounts
            output_amount = str(tx_result.output_amount) if tx_result.output_amount else str(quote.expected_output)
            entry_price = float(quote.price_per_token)

            if body.side == "buy":
                # Check for existing open position to update
                existing_position = await session.execute(
                    select(Position).where(
                        Position.user_id == user.id,
                        Position.platform == platform_enum,
                        Position.market_id == body.market_id,
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
                        market_id=body.market_id,
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
                        Position.market_id == body.market_id,
                        Position.outcome == outcome_enum,
                        Position.status == PositionStatus.OPEN,
                    )
                )
                existing = existing_position.scalar_one_or_none()

                if existing:
                    # Reduce position or close it
                    sell_amount = Decimal(str(body.amount)) / Decimal(str(entry_price)) if entry_price > 0 else Decimal("0")
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
    dest_chain: str = "polygon"


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
    dest_chain: str = "polygon"


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
    """Get a quote for bridging USDC to another chain."""
    from ..services.bridge import bridge_service, BridgeChain

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    try:
        source_chain = BridgeChain(request.source_chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid source chain: {request.source_chain}")

    try:
        dest_chain = BridgeChain(request.dest_chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid dest chain: {request.dest_chain}")

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
        dest_chain,
        amount,
        wallet.public_key
    )

    return BridgeQuoteResponse(
        source_chain=source_chain.value,
        dest_chain=dest_chain.value,
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
    """Execute a bridge transfer."""
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

    try:
        dest_chain = BridgeChain(request.dest_chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid dest chain: {request.dest_chain}")

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
            dest_chain,
            amount,
        )
    else:
        bridge_result = await asyncio.to_thread(
            bridge_service.bridge_usdc,
            private_key,
            source_chain,
            dest_chain,
            amount,
        )

    if bridge_result.success:
        return BridgeExecuteResponse(
            success=True,
            source_chain=source_chain.value,
            dest_chain=dest_chain.value,
            amount=str(bridge_result.amount),
            tx_hash=bridge_result.burn_tx_hash,
            message=f"Bridge successful! USDC will arrive on {dest_chain.value.title()} shortly.",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=bridge_result.error_message or "Bridge failed"
        )


# ===================
# Swap Endpoints
# ===================

class SwapQuoteRequest(BaseModel):
    """Swap quote request."""
    chain: str
    from_token: str = "native"  # "native" or token contract address
    from_decimals: int = 18
    to_token: str = "native"  # "native" means default USDC, or token contract address
    to_decimals: int = 6
    amount: str  # Amount in whole units (e.g. "0.5" for 0.5 ETH)


class SwapQuoteResponse(BaseModel):
    """Swap quote response."""
    chain: str
    from_token: str
    to_token: str = ""
    amount: str
    output_amount: str
    fee_amount: str
    fee_percent: float
    estimated_time: str
    tool_name: str
    available: bool
    error: Optional[str] = None


class SwapExecuteRequest(BaseModel):
    """Swap execution request."""
    chain: str
    from_token: str = "native"
    from_decimals: int = 18
    to_token: str = "native"
    to_decimals: int = 6
    amount: str


class SwapExecuteResponse(BaseModel):
    """Swap execution response."""
    success: bool
    chain: str
    amount: str
    tx_hash: Optional[str] = None
    message: str


@router.post("/swap/quote", response_model=SwapQuoteResponse)
async def get_swap_quote(
    request: SwapQuoteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get a quote for swapping a token to USDC on the same chain."""
    from ..services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    try:
        chain = BridgeChain(request.chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain: {request.chain}")

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

    # Determine from_token address
    from_token = NATIVE_TOKEN if request.from_token == "native" else request.from_token

    # Determine to_token: "native" means default (USDC), otherwise use provided address
    to_token_addr = None if request.to_token == "native" else request.to_token

    # Get swap quote
    quote = bridge_service.get_swap_quote(
        chain,
        amount,
        wallet.public_key,
        from_token=from_token,
        from_decimals=request.from_decimals,
        to_token=to_token_addr,
        to_decimals=request.to_decimals,
    )

    return SwapQuoteResponse(
        chain=chain.value,
        from_token=request.from_token,
        to_token=request.to_token,
        amount=str(amount),
        output_amount=str(quote.output_amount),
        fee_amount=str(quote.fee_amount),
        fee_percent=quote.fee_percent,
        estimated_time=f"~{quote.estimated_time_seconds}s" if quote.estimated_time_seconds else "~30s",
        tool_name=quote.tool_name or "DEX",
        available=quote.error is None,
        error=quote.error,
    )


@router.post("/swap/execute", response_model=SwapExecuteResponse)
async def execute_swap(
    request: SwapExecuteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Execute a token swap to USDC on the same chain."""
    import asyncio
    from ..services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN
    from ..utils.encryption import decrypt

    # Initialize bridge service if needed
    if not bridge_service._initialized:
        bridge_service.initialize()

    try:
        chain = BridgeChain(request.chain.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chain: {request.chain}")

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
        "",  # No PIN required
    )

    # Determine from_token address
    from_token = NATIVE_TOKEN if request.from_token == "native" else request.from_token

    # Determine to_token: "native" means default (USDC), otherwise use provided address
    to_token_addr = None if request.to_token == "native" else request.to_token

    # Execute swap in thread pool (blocking operation)
    swap_result = await asyncio.to_thread(
        bridge_service.execute_swap,
        private_key,
        chain,
        amount,
        None,  # No progress callback
        from_token,
        request.from_decimals,
        to_token_addr,
        request.to_decimals,
    )

    if swap_result.success:
        return SwapExecuteResponse(
            success=True,
            chain=chain.value,
            amount=str(swap_result.amount),
            tx_hash=swap_result.burn_tx_hash,
            message="Swap successful!",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=swap_result.error_message or "Swap failed"
        )


# ===================
# Position Endpoints
# ===================

@router.get("/positions")
async def get_positions(
    platform: Optional[str] = None,
    status: str = "open",
    limit: int = Query(default=25, le=25),
    page: int = Query(default=1, ge=1),
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

    all_items = [
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

    meta, page_items = paginate_results(all_items, page, limit)
    return {"positions": page_items, **meta}


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
                        html += '<p class="note">You can still use Polymarket, Opinion, Limitless, and Myriad.</p>';
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
        <p>You can still use other platforms like Polymarket, Opinion, Limitless, and Myriad.</p>
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
    import traceback
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from slowapi.errors import RateLimitExceeded
    from ..utils.logging import get_logger

    _log = get_logger("api")

    app = FastAPI(
        title="Spredd Mini App API",
        description="REST API for Spredd Telegram Mini App",
        version="1.0.0",
    )

    # GZip compression — compresses responses >1KB (cuts bandwidth 5-10x for market lists)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Configure CORS for Mini App
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Telegram Mini App runs in iframe
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiter — middleware applies global default; decorators override per-route
    from slowapi.middleware import SlowAPIMiddleware
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # Timing middleware — logs duration and adds X-Response-Time header
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        _log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 1),
        )
        return response

    # Global exception handler — catches unhandled errors, returns clean JSON
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            raise exc
        _log.error(
            "unhandled_exception",
            path=str(request.url.path),
            method=request.method,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred. Please try again.",
            },
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

        # Start background cache warmer for instant market responses
        start_cache_warmer()

    @app.on_event("shutdown")
    async def shutdown_realtime():
        """Stop real-time data services on app shutdown."""
        from src.services.polymarket_ws import polymarket_ws_manager
        from src.services.price_poller import price_poller

        stop_cache_warmer()
        await polymarket_ws_manager.stop()
        await price_poller.stop()
        print("[API] Real-time services stopped")

    # Health check (exempt from rate limiting)
    @app.get("/health")
    @limiter.exempt
    async def health_check():
        return {"status": "healthy", "service": "spredd-miniapp-api"}

    @app.get("/health/cache")
    @limiter.exempt
    async def cache_health_check():
        """Check Redis cache health."""
        rc = _get_redis_cache()
        if not rc:
            return {"status": "unavailable", "reason": "cache module not loaded"}
        return await rc.health_check()

    # =========================================
    # Direct routes for webapp (no /api/v1 prefix)
    # =========================================

    @app.get("/markets")
    async def get_webapp_markets(
        request: Request,
        platform: Optional[str] = Query(default="all"),
        limit: int = Query(default=100, le=1000),
        active: bool = Query(default=True),
    ):
        """Get markets for webapp - direct route without /api/v1 prefix."""
        # Delegate to the /api/v1/markets endpoint (shares cache)
        return await get_all_markets(request=request, platform=platform, limit=limit, active=active)

    @app.get("/markets/{market_id}")
    async def get_webapp_market_details(market_id: str):
        """Get single market details for webapp - tries all platforms."""
        from ..platforms import platform_registry
        from ..platforms.base import Outcome

        # Check Redis cache first (this is the most expensive endpoint)
        rc = _get_redis_cache()
        cache_key = f"spredd:api:webapp:market:{market_id}"
        if rc and rc.is_available:
            cached = await rc.get_json(cache_key)
            if cached is not None:
                return cached

        async def _fetch_webapp_market():
            # Try to find the market across all platforms
            for plat_name in ["polymarket", "kalshi", "limitless", "myriad"]:
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

                        result = {
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

                        _rc = _get_redis_cache()
                        if _rc and _rc.is_available:
                            from src.config import settings as _s
                            await _rc.set_json(cache_key, result, _s.cache_ttl_market_detail)
                        return result
                except Exception as e:
                    print(f"Error fetching {plat_name} market {market_id}: {e}")
                    continue

            raise HTTPException(status_code=404, detail=f"Market not found: {market_id}")

        async def _recheck_webapp_market():
            _rc = _get_redis_cache()
            if _rc and _rc.is_available:
                return await _rc.get_json(cache_key)
            return None

        return await coalesce(f"webapp:{market_id}", _fetch_webapp_market, _recheck_webapp_market)

    # Serve static webapp files if they exist
    webapp_dist = Path(__file__).parent.parent.parent / "webapp" / "dist"
    print(f"[API] Webapp dist path: {webapp_dist}")
    print(f"[API] Webapp dist exists: {webapp_dist.exists()}")
    if webapp_dist.exists():
        # Serve static assets
        app.mount("/assets", StaticFiles(directory=webapp_dist / "assets"), name="assets")

    # Serve PWA static files if they exist
    pwa_dist = Path(__file__).parent.parent.parent / "pwa" / "dist"
    print(f"[API] PWA dist path: {pwa_dist} (resolved: {pwa_dist.resolve()})")
    print(f"[API] PWA dist exists: {pwa_dist.exists()}")
    # Fallback: check /app/pwa/dist (Railway's working directory)
    if not pwa_dist.exists():
        pwa_alt = Path("/app/pwa/dist")
        print(f"[API] Trying alt PWA path: {pwa_alt}, exists: {pwa_alt.exists()}")
        if pwa_alt.exists():
            pwa_dist = pwa_alt
    if pwa_dist.exists() and (pwa_dist / "assets").exists():
        print(f"[API] Mounting PWA assets from: {pwa_dist}")
        app.mount("/pwa/assets", StaticFiles(directory=pwa_dist / "assets"), name="pwa-assets")
    else:
        print(f"[API] PWA dist NOT found — /pwa/ routes will not work")

    # Debug endpoint to check PWA dist status
    @app.get("/debug/pwa-status")
    async def debug_pwa_status():
        import os
        return {
            "pwa_dist": str(pwa_dist),
            "pwa_dist_resolved": str(pwa_dist.resolve()),
            "pwa_dist_exists": pwa_dist.exists(),
            "webapp_dist": str(webapp_dist),
            "webapp_dist_exists": webapp_dist.exists(),
            "cwd": os.getcwd(),
            "__file__": __file__,
            "pwa_contents": os.listdir(str(pwa_dist)) if pwa_dist.exists() else [],
            "pwa_parent_contents": os.listdir(str(pwa_dist.parent)) if pwa_dist.parent.exists() else [],
        }

    # SPA fallback for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Don't serve SPA for API routes
        if full_path.startswith("api/") or full_path == "health":
            return {"detail": "Not found"}

        # PWA routes: /pwa, /pwa/portfolio, /pwa/profile, etc.
        if full_path.startswith("pwa") and pwa_dist.exists():
            # Serve static files (sw.js, manifest, etc.)
            sub_path = full_path[4:].lstrip("/")  # strip "pwa/" prefix
            if sub_path:
                file_path = pwa_dist / sub_path
                if file_path.exists() and file_path.is_file():
                    return FileResponse(file_path)
            # SPA fallback
            return FileResponse(pwa_dist / "index.html")

        # Existing webapp serving
        if webapp_dist.exists():
            file_path = webapp_dist / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(webapp_dist / "index.html")

        return {"detail": "Not found"}

    return app
