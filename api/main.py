"""
Spredd Markets API - FastAPI backend for web/mini app frontend.

Reuses the bot's platform code to provide REST endpoints.
Run with: uvicorn api.main:app --reload --port 8000
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    MarketResponse,
    EventResponse,
    PricePointResponse,
    OrderBookResponse,
    OrderBookEntryResponse,
    MarketStatsResponse,
    TradeResponse,
    CategoryResponse,
    TagResponse,
    TrendingTagResponse,
    HealthResponse,
)

# Import platform code from bot
from src.platforms import (
    get_platform,
    polymarket_platform,
    kalshi_platform,
    opinion_platform,
    limitless_platform,
)
from src.db.models import Platform, Outcome
from src.config import settings


# Platform instances
platforms_initialized = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize platforms on startup."""
    global platforms_initialized

    # Initialize all platforms
    try:
        await polymarket_platform.initialize()
        print("[OK] Polymarket initialized")
    except Exception as e:
        print(f"[WARN] Polymarket init failed: {e}")

    try:
        await kalshi_platform.initialize()
        print("[OK] Kalshi initialized")
    except Exception as e:
        print(f"[WARN] Kalshi init failed: {e}")

    try:
        await opinion_platform.initialize()
        print("[OK] Opinion Labs initialized")
    except Exception as e:
        print(f"[WARN] Opinion Labs init failed: {e}")

    try:
        await limitless_platform.initialize()
        print("[OK] Limitless initialized")
    except Exception as e:
        print(f"[WARN] Limitless init failed: {e}")

    platforms_initialized = True
    print("API ready")

    yield

    # Cleanup
    await polymarket_platform.close()
    await kalshi_platform.close()
    await opinion_platform.close()
    await limitless_platform.close()


app = FastAPI(
    title="Spredd Markets API",
    description="Multi-platform prediction markets API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "https://spredd.markets",  # Production domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def market_to_response(market, platform_name: str = "polymarket") -> MarketResponse:
    """Convert platform Market to API response."""
    # Get outcomes and prices
    outcomes = ["Yes", "No"]
    prices = []
    token_ids = []

    if market.yes_price is not None:
        prices.append(str(float(market.yes_price)))
    else:
        prices.append("0")

    if market.no_price is not None:
        prices.append(str(float(market.no_price)))
    else:
        prices.append("0")

    if market.yes_token:
        token_ids.append(market.yes_token)
    if market.no_token:
        token_ids.append(market.no_token)

    return MarketResponse(
        id=market.market_id,
        question=market.title,
        description=market.description,
        image=getattr(market, 'image', None),
        icon=getattr(market, 'icon', None),
        category=market.category,
        outcomes=outcomes,
        outcomePrices=prices,
        clobTokenIds=token_ids,
        volume=float(market.volume_24h) if market.volume_24h else None,
        volume24hr=float(market.volume_24h) if market.volume_24h else None,
        liquidity=float(market.liquidity) if market.liquidity else None,
        endDate=market.close_time,
        active=market.is_active,
        closed=not market.is_active,
        slug=market.market_id,
        platform=platform_name,
        subtitle=market.description[:100] if market.description else None,
    )


# ===================
# Health Check
# ===================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check API and platform health."""
    return HealthResponse(
        healthy=platforms_initialized,
        platforms={
            "polymarket": True,
            "kalshi": True,
            "opinion": True,
            "limitless": True,
        }
    )


# ===================
# Polymarket Routes (for frontend compatibility)
# ===================

@app.get("/polymarket/health")
async def polymarket_health():
    """Polymarket health check."""
    return {"healthy": True}


@app.get("/polymarket/markets", response_model=list[MarketResponse])
async def get_polymarket_markets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    active: bool = Query(True),
    order: str = Query("volume"),
    ascending: bool = Query(False),
):
    """Get Polymarket markets."""
    import httpx
    import json as json_lib

    try:
        # Fetch directly from Gamma API for accurate prices
        async with httpx.AsyncClient(timeout=15.0) as client:
            gamma_url = "https://gamma-api.polymarket.com/events"

            resp = await client.get(gamma_url, params={
                "active": "true" if active else "false",
                "limit": 500,
                "order": "volume24hr",
                "ascending": "false",
            })

            if resp.status_code != 200:
                return []

            all_events = resp.json()
            markets = []

            for event in all_events:
                for m in event.get("markets", []):
                    # Parse outcome prices
                    outcome_prices_raw = m.get("outcomePrices", [])
                    if isinstance(outcome_prices_raw, str):
                        try:
                            outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                        except:
                            outcome_prices_raw = []

                    prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

                    # Parse token IDs
                    tokens_raw = m.get("clobTokenIds", [])
                    if isinstance(tokens_raw, str):
                        try:
                            tokens_raw = json_lib.loads(tokens_raw)
                        except:
                            tokens_raw = []

                    # Parse outcomes
                    outcomes_raw = m.get("outcomes", ["Yes", "No"])
                    if isinstance(outcomes_raw, str):
                        try:
                            outcomes_raw = json_lib.loads(outcomes_raw)
                        except:
                            outcomes_raw = ["Yes", "No"]

                    markets.append(MarketResponse(
                        id=m.get("conditionId") or str(m.get("id", "")),
                        question=m.get("question") or m.get("groupItemTitle") or event.get("title", ""),
                        description=m.get("description") or event.get("description"),
                        image=event.get("image"),
                        icon=event.get("icon"),
                        category=event.get("category"),
                        outcomes=outcomes_raw,
                        outcomePrices=prices,
                        clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                        volume=float(m.get("volume", 0)) if m.get("volume") else None,
                        volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                        liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                        endDate=m.get("endDate") or event.get("endDate"),
                        active=m.get("active", True),
                        closed=m.get("closed", False),
                        slug=m.get("conditionId") or str(m.get("id", "")),
                        platform="polymarket",
                    ))

            # Sort by volume and apply pagination
            markets.sort(key=lambda x: x.volume24hr or 0, reverse=not ascending)
            return markets[offset:offset + limit]

    except Exception as e:
        print(f"Error fetching markets: {e}")
        return []


@app.get("/polymarket/markets/search", response_model=list[MarketResponse])
async def search_polymarket_markets(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
):
    """Search Polymarket markets."""
    try:
        markets = await polymarket_platform.search_markets(q, limit=limit)
        return [market_to_response(m, "polymarket") for m in markets]
    except Exception as e:
        print(f"Error searching markets: {e}")
        return []


@app.get("/polymarket/markets/category/{category}", response_model=list[MarketResponse])
async def get_polymarket_markets_by_category(
    category: str = Path(...),
    limit: int = Query(50, ge=1, le=100),
):
    """Get Polymarket markets by category."""
    try:
        markets = await polymarket_platform.get_markets_by_category(category, limit=limit)
        return [market_to_response(m, "polymarket") for m in markets]
    except Exception as e:
        print(f"Error fetching category markets: {e}")
        return []


@app.get("/polymarket/markets/{market_id}", response_model=MarketResponse)
async def get_polymarket_market(market_id: str = Path(...)):
    """Get a specific Polymarket market."""
    import httpx
    import json as json_lib

    try:
        # Fetch directly from Gamma API for accurate prices
        async with httpx.AsyncClient(timeout=15.0) as client:
            gamma_url = "https://gamma-api.polymarket.com/events"
            markets_url = "https://gamma-api.polymarket.com/markets"

            found_market = None
            found_event = None

            # First try direct market lookup by condition ID
            resp = await client.get(markets_url, params={"condition_id": market_id})
            if resp.status_code == 200:
                markets_data = resp.json()
                if markets_data and len(markets_data) > 0:
                    found_market = markets_data[0]
                    # Fetch parent event for additional data
                    event_slug = found_market.get("eventSlug")
                    if event_slug:
                        event_resp = await client.get(gamma_url, params={"slug": event_slug})
                        if event_resp.status_code == 200:
                            events = event_resp.json()
                            if events:
                                found_event = events[0]

            # Fallback: Search through events with proper ordering
            if not found_market:
                for search_params in [
                    {"active": "true", "limit": 500, "order": "volume24hr", "ascending": "false"},
                    {"closed": "true", "limit": 200, "order": "volume24hr", "ascending": "false"},
                ]:
                    resp = await client.get(gamma_url, params=search_params)
                    if resp.status_code == 200:
                        all_events = resp.json()
                        for event in all_events:
                            for m in event.get("markets", []):
                                if m.get("conditionId") == market_id:
                                    found_market = m
                                    found_event = event
                                    break
                            if found_market:
                                break
                    if found_market:
                        break

            if not found_market:
                raise HTTPException(status_code=404, detail="Market not found")

            m = found_market
            event = found_event

            # Parse outcome prices
            outcome_prices_raw = m.get("outcomePrices", [])
            if isinstance(outcome_prices_raw, str):
                try:
                    outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                except:
                    outcome_prices_raw = []

            prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

            # Parse token IDs
            tokens_raw = m.get("clobTokenIds", [])
            if isinstance(tokens_raw, str):
                try:
                    tokens_raw = json_lib.loads(tokens_raw)
                except:
                    tokens_raw = []

            # Parse outcomes
            outcomes_raw = m.get("outcomes", ["Yes", "No"])
            if isinstance(outcomes_raw, str):
                try:
                    outcomes_raw = json_lib.loads(outcomes_raw)
                except:
                    outcomes_raw = ["Yes", "No"]

            return MarketResponse(
                id=m.get("conditionId") or str(m.get("id", "")),
                question=m.get("question") or m.get("groupItemTitle") or (event.get("title", "") if event else ""),
                description=m.get("description") or (event.get("description") if event else None),
                image=event.get("image") if event else None,
                icon=event.get("icon") if event else None,
                category=event.get("category") if event else None,
                outcomes=outcomes_raw,
                outcomePrices=prices,
                clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                volume=float(m.get("volume", 0)) if m.get("volume") else None,
                volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                endDate=m.get("endDate") or (event.get("endDate") if event else None),
                active=m.get("active", True),
                closed=m.get("closed", False),
                slug=m.get("conditionId") or str(m.get("id", "")),
                platform="polymarket",
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching market: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/polymarket/markets/{market_id}/price-history", response_model=list[PricePointResponse])
async def get_price_history(
    market_id: str = Path(...),
    outcome: str = Query("YES"),
    interval: str = Query("1d"),
):
    """Get price history for a market."""
    try:
        # Get market to find token ID
        market = await polymarket_platform.get_market(market_id)
        if not market:
            return []

        token_id = market.yes_token if outcome.upper() == "YES" else market.no_token
        if not token_id:
            return []

        # Fetch from Polymarket CLOB API
        from datetime import datetime, timedelta
        import httpx

        # Map interval to fidelity (minutes)
        fidelity_map = {"1h": 1, "6h": 5, "1d": 15, "1w": 60, "max": 1440}
        fidelity = fidelity_map.get(interval, 15)

        # Calculate time range
        now = int(datetime.now().timestamp())
        ranges = {"1h": 3600, "6h": 21600, "1d": 86400, "1w": 604800, "max": 31536000}
        start_ts = now - ranges.get(interval, 86400)

        url = f"https://clob.polymarket.com/prices-history"
        params = {
            "market": token_id,
            "startTs": start_ts,
            "endTs": now,
            "fidelity": fidelity,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                history = data.get("history", [])
                return [PricePointResponse(t=int(p["t"]), p=float(p["p"])) for p in history]

        return []
    except Exception as e:
        print(f"Error fetching price history: {e}")
        return []


@app.get("/polymarket/price-history/{token_id}", response_model=list[PricePointResponse])
async def get_price_history_by_token(
    token_id: str = Path(...),
    interval: str = Query("1d"),
    startTs: Optional[int] = Query(None),
    endTs: Optional[int] = Query(None),
    fidelity: Optional[int] = Query(None),
):
    """Get price history by token ID."""
    try:
        from datetime import datetime
        import httpx

        now = int(datetime.now().timestamp())
        fidelity_map = {"1h": 1, "6h": 5, "1d": 15, "1w": 60, "max": 1440}
        actual_fidelity = fidelity or fidelity_map.get(interval, 15)

        ranges = {"1h": 3600, "6h": 21600, "1d": 86400, "1w": 604800, "max": 31536000}
        actual_start = startTs or (now - ranges.get(interval, 86400))
        actual_end = endTs or now

        url = f"https://clob.polymarket.com/prices-history"
        params = {
            "market": token_id,
            "startTs": actual_start,
            "endTs": actual_end,
            "fidelity": actual_fidelity,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                history = data.get("history", [])
                return [PricePointResponse(t=int(p["t"]), p=float(p["p"])) for p in history]

        return []
    except Exception as e:
        print(f"Error fetching price history: {e}")
        return []


@app.get("/polymarket/price/orderbook/{token_id}")
async def get_orderbook_by_token(token_id: str = Path(...)):
    """Get order book by token ID."""
    try:
        import httpx

        url = f"https://clob.polymarket.com/book"
        params = {"token_id": token_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()

        return {"bids": [], "asks": []}
    except Exception as e:
        print(f"Error fetching orderbook: {e}")
        return {"bids": [], "asks": []}


@app.get("/polymarket/clob/market-depth/{token_id}")
async def get_market_depth(
    token_id: str = Path(...),
    levels: int = Query(10),
):
    """Get market depth by token ID."""
    try:
        import httpx

        url = f"https://clob.polymarket.com/book"
        params = {"token_id": token_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                bids = [{"price": float(b["price"]), "size": float(b["size"]), "total": 0} for b in data.get("bids", [])[:levels]]
                asks = [{"price": float(a["price"]), "size": float(a["size"]), "total": 0} for a in data.get("asks", [])[:levels]]

                # Calculate totals
                bid_total = 0
                for b in bids:
                    bid_total += b["size"]
                    b["total"] = bid_total

                ask_total = 0
                for a in asks:
                    ask_total += a["size"]
                    a["total"] = ask_total

                return {
                    "bids": bids,
                    "asks": asks,
                    "bidDepth": bid_total,
                    "askDepth": ask_total,
                    "totalDepth": bid_total + ask_total,
                }

        return {"bids": [], "asks": [], "bidDepth": 0, "askDepth": 0, "totalDepth": 0}
    except Exception as e:
        print(f"Error fetching market depth: {e}")
        return {"bids": [], "asks": [], "bidDepth": 0, "askDepth": 0, "totalDepth": 0}


@app.get("/polymarket/clob/trades/{token_id}", response_model=list[TradeResponse])
async def get_recent_trades(
    token_id: str = Path(...),
    limit: int = Query(50, ge=1, le=100),
):
    """Get recent trades by token ID."""
    try:
        import httpx

        url = f"https://clob.polymarket.com/trades"
        params = {"asset_id": token_id, "limit": limit}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                trades = resp.json()
                return [
                    TradeResponse(
                        id=str(t.get("id", "")),
                        timestamp=int(t.get("timestamp", 0)),
                        price=float(t.get("price", 0)),
                        size=float(t.get("size", 0)),
                        side=t.get("side", "BUY").upper(),
                    )
                    for t in trades
                ]

        return []
    except Exception as e:
        print(f"Error fetching trades: {e}")
        return []


@app.get("/polymarket/clob/midpoint/{token_id}")
async def get_midpoint(token_id: str = Path(...)):
    """Get midpoint price for a token."""
    try:
        import httpx

        url = f"https://clob.polymarket.com/midpoint"
        params = {"token_id": token_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return {"midpoint": float(data.get("mid", 0))}

        return {"midpoint": 0}
    except Exception as e:
        print(f"Error fetching midpoint: {e}")
        return {"midpoint": 0}


@app.get("/polymarket/clob/spread/{token_id}")
async def get_spread(token_id: str = Path(...)):
    """Get bid-ask spread for a token."""
    try:
        import httpx

        url = f"https://clob.polymarket.com/book"
        params = {"token_id": token_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])

                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0
                spread = best_ask - best_bid if best_ask and best_bid else 0
                spread_pct = (spread / best_bid * 100) if best_bid else 0

                return {
                    "spread": spread,
                    "spreadPercent": spread_pct,
                    "bid": best_bid,
                    "ask": best_ask,
                }

        return {"spread": 0, "spreadPercent": 0, "bid": 0, "ask": 0}
    except Exception as e:
        print(f"Error fetching spread: {e}")
        return {"spread": 0, "spreadPercent": 0, "bid": 0, "ask": 0}


@app.get("/polymarket/events", response_model=list[EventResponse])
async def get_polymarket_events(
    limit: int = Query(30, ge=1, le=100),
    active: bool = Query(True),
    order: str = Query("volume"),
    ascending: bool = Query(False),
):
    """Get Polymarket events (grouped markets)."""
    import httpx
    import json as json_lib

    try:
        # Fetch directly from Gamma API for accurate prices
        async with httpx.AsyncClient(timeout=15.0) as client:
            gamma_url = "https://gamma-api.polymarket.com/events"

            resp = await client.get(gamma_url, params={
                "active": "true" if active else "false",
                "limit": 500,  # Fetch more to ensure we have all markets
                "order": "volume24hr",
                "ascending": "false",
            })

            if resp.status_code != 200:
                return []

            all_events = resp.json()
            events = []

            for event in all_events:
                market_responses = []
                for m in event.get("markets", []):
                    # Parse outcome prices
                    outcome_prices_raw = m.get("outcomePrices", [])
                    if isinstance(outcome_prices_raw, str):
                        try:
                            outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                        except:
                            outcome_prices_raw = []

                    prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

                    # Parse token IDs
                    tokens_raw = m.get("clobTokenIds", [])
                    if isinstance(tokens_raw, str):
                        try:
                            tokens_raw = json_lib.loads(tokens_raw)
                        except:
                            tokens_raw = []

                    # Parse outcomes
                    outcomes_raw = m.get("outcomes", ["Yes", "No"])
                    if isinstance(outcomes_raw, str):
                        try:
                            outcomes_raw = json_lib.loads(outcomes_raw)
                        except:
                            outcomes_raw = ["Yes", "No"]

                    market_responses.append(MarketResponse(
                        id=m.get("conditionId") or str(m.get("id", "")),
                        question=m.get("question") or m.get("groupItemTitle") or event.get("title", ""),
                        description=m.get("description") or event.get("description"),
                        image=event.get("image"),
                        icon=event.get("icon"),
                        category=event.get("category"),
                        outcomes=outcomes_raw,
                        outcomePrices=prices,
                        clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                        volume=float(m.get("volume", 0)) if m.get("volume") else None,
                        volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                        liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                        endDate=m.get("endDate") or event.get("endDate"),
                        active=m.get("active", True),
                        closed=m.get("closed", False),
                        slug=m.get("conditionId") or str(m.get("id", "")),
                        platform="polymarket",
                    ))

                events.append(EventResponse(
                    id=event.get("id") or event.get("conditionId", ""),
                    title=event.get("title", ""),
                    description=event.get("description"),
                    image=event.get("image"),
                    icon=event.get("icon"),
                    slug=event.get("slug") or str(event.get("id", "")),
                    markets=market_responses,
                    endDate=event.get("endDate"),
                    category=event.get("category"),
                    volume=float(event.get("volume", 0)) if event.get("volume") else None,
                    volume24hr=float(event.get("volume24hr", 0)) if event.get("volume24hr") else None,
                    liquidity=float(event.get("liquidity", 0)) if event.get("liquidity") else None,
                    platform="polymarket",
                ))

            return events

    except Exception as e:
        print(f"Error fetching events: {e}")
        return []


@app.get("/polymarket/events/{event_id}", response_model=EventResponse)
async def get_polymarket_event(event_id: str = Path(...)):
    """Get a specific Polymarket event by ID, slug, or conditionId."""
    import httpx
    import json as json_lib

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            gamma_url = "https://gamma-api.polymarket.com/events"
            markets_url = "https://gamma-api.polymarket.com/markets"

            found_event = None
            target_market = None

            print(f"Looking up event/market: {event_id}")

            # Strategy 1: Try to find market by conditionId (different param names)
            for param_name in ["conditionId", "condition_id", "id"]:
                resp = await client.get(markets_url, params={param_name: event_id})
                if resp.status_code == 200:
                    markets_data = resp.json()
                    if markets_data and len(markets_data) > 0:
                        target_market = markets_data[0]
                        print(f"Found market via {param_name}: {target_market.get('question', '')[:50]}")
                        # Get parent event
                        event_slug = target_market.get("eventSlug")
                        if event_slug:
                            event_resp = await client.get(gamma_url, params={"slug": event_slug})
                            if event_resp.status_code == 200:
                                events = event_resp.json()
                                if events:
                                    found_event = events[0]
                                    break
                if found_event:
                    break

            # Strategy 2: Try by event slug
            if not found_event:
                resp = await client.get(gamma_url, params={"slug": event_id})
                if resp.status_code == 200:
                    events = resp.json()
                    if events:
                        found_event = events[0]
                        print(f"Found event via slug: {found_event.get('title', '')[:50]}")

            # Strategy 3: Try by event ID
            if not found_event:
                resp = await client.get(gamma_url, params={"id": event_id})
                if resp.status_code == 200:
                    events = resp.json()
                    if events:
                        found_event = events[0]
                        print(f"Found event via id: {found_event.get('title', '')[:50]}")

            # Strategy 4: Search through active events looking for conditionId match
            # Use same ordering as markets list endpoint for consistency
            if not found_event:
                print("Searching through active events...")
                resp = await client.get(gamma_url, params={
                    "active": "true",
                    "limit": 500,
                    "order": "volume24hr",
                    "ascending": "false"
                })
                if resp.status_code == 200:
                    all_events = resp.json()
                    for e in all_events:
                        # Check if event ID matches
                        if str(e.get("id")) == event_id or e.get("slug") == event_id:
                            found_event = e
                            break
                        # Check markets within event
                        for m in e.get("markets", []):
                            if m.get("conditionId") == event_id:
                                found_event = e
                                target_market = m
                                print(f"Found market in event: {e.get('title', '')[:50]}")
                                break
                        if found_event:
                            break

            # Strategy 5: Search closed events
            if not found_event:
                print("Searching through closed events...")
                resp = await client.get(gamma_url, params={
                    "closed": "true",
                    "limit": 200,
                    "order": "volume24hr",
                    "ascending": "false"
                })
                if resp.status_code == 200:
                    all_events = resp.json()
                    for e in all_events:
                        if str(e.get("id")) == event_id or e.get("slug") == event_id:
                            found_event = e
                            break
                        for m in e.get("markets", []):
                            if m.get("conditionId") == event_id:
                                found_event = e
                                target_market = m
                                break
                        if found_event:
                            break

            if not found_event:
                print(f"Event not found for: {event_id}")
                raise HTTPException(status_code=404, detail="Event not found")

            event = found_event
            markets_data = event.get("markets", [])

            # Build market responses
            market_responses = []
            for m in markets_data:
                # Parse outcome prices
                outcome_prices_raw = m.get("outcomePrices", [])
                if isinstance(outcome_prices_raw, str):
                    try:
                        outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                    except:
                        outcome_prices_raw = []

                prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

                # Parse token IDs
                tokens_raw = m.get("clobTokenIds", [])
                if isinstance(tokens_raw, str):
                    try:
                        tokens_raw = json_lib.loads(tokens_raw)
                    except:
                        tokens_raw = []

                # Parse outcomes
                outcomes_raw = m.get("outcomes", ["Yes", "No"])
                if isinstance(outcomes_raw, str):
                    try:
                        outcomes_raw = json_lib.loads(outcomes_raw)
                    except:
                        outcomes_raw = ["Yes", "No"]

                market_responses.append(MarketResponse(
                    id=m.get("conditionId") or str(m.get("id", "")),
                    question=m.get("question") or m.get("groupItemTitle") or event.get("title", ""),
                    description=m.get("description") or event.get("description"),
                    image=event.get("image"),
                    icon=event.get("icon"),
                    category=event.get("category"),
                    outcomes=outcomes_raw,
                    outcomePrices=prices,
                    clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                    volume=float(m.get("volume", 0)) if m.get("volume") else None,
                    volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                    liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                    endDate=m.get("endDate") or event.get("endDate"),
                    active=m.get("active", True),
                    closed=m.get("closed", False),
                    slug=m.get("conditionId") or str(m.get("id", "")),
                    platform="polymarket",
                ))

            return EventResponse(
                id=str(event.get("id", "")) or event.get("conditionId", ""),
                title=event.get("title", ""),
                description=event.get("description"),
                image=event.get("image"),
                icon=event.get("icon"),
                slug=event.get("slug") or str(event.get("id", "")),
                markets=market_responses,
                endDate=event.get("endDate"),
                category=event.get("category"),
                volume=float(event.get("volume", 0)) if event.get("volume") else None,
                volume24hr=float(event.get("volume24hr", 0)) if event.get("volume24hr") else None,
                liquidity=float(event.get("liquidity", 0)) if event.get("liquidity") else None,
                platform="polymarket",
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/polymarket/tags", response_model=list[TagResponse])
async def get_polymarket_tags():
    """Get available tags."""
    # Return predefined categories as tags
    categories = polymarket_platform.get_available_categories()
    return [
        TagResponse(id=c["id"], label=c["label"], slug=c["id"])
        for c in categories
    ]


@app.get("/polymarket/tags/trending", response_model=list[TrendingTagResponse])
async def get_trending_tags(limit: int = Query(20, ge=1, le=50)):
    """Get trending tags."""
    categories = polymarket_platform.get_available_categories()
    return [
        TrendingTagResponse(
            tag=c["label"],
            slug=c["id"],
            eventCount=10,  # Placeholder
            totalVolume=100000,  # Placeholder
            score=1.0,
        )
        for c in categories[:limit]
    ]


@app.get("/polymarket/sports/categories")
async def get_sports_categories():
    """Get sports categories."""
    return [
        {"name": "NFL", "emoji": "🏈", "count": 50},
        {"name": "NBA", "emoji": "🏀", "count": 30},
        {"name": "NHL", "emoji": "🏒", "count": 20},
        {"name": "MLB", "emoji": "⚾", "count": 15},
        {"name": "Soccer", "emoji": "⚽", "count": 40},
        {"name": "UFC/MMA", "emoji": "🥊", "count": 10},
    ]


# ===================
# Kalshi Routes
# ===================

@app.get("/kalshi/markets", response_model=list[MarketResponse])
async def get_kalshi_markets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    active: bool = Query(True),
):
    """Get Kalshi markets."""
    try:
        markets = await kalshi_platform.get_markets(
            limit=limit,
            offset=offset,
            active_only=active,
        )
        return [market_to_response(m, "kalshi") for m in markets]
    except Exception as e:
        print(f"Error fetching Kalshi markets: {e}")
        return []


@app.get("/kalshi/markets/search", response_model=list[MarketResponse])
async def search_kalshi_markets(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
):
    """Search Kalshi markets."""
    try:
        markets = await kalshi_platform.search_markets(q, limit=limit)
        return [market_to_response(m, "kalshi") for m in markets]
    except Exception as e:
        print(f"Error searching Kalshi markets: {e}")
        return []


@app.get("/kalshi/markets/category/{category}", response_model=list[MarketResponse])
async def get_kalshi_markets_by_category(
    category: str = Path(...),
    limit: int = Query(50, ge=1, le=100),
):
    """Get Kalshi markets by category."""
    try:
        markets = await kalshi_platform.get_markets_by_category(category, limit=limit)
        return [market_to_response(m, "kalshi") for m in markets]
    except Exception as e:
        print(f"Error fetching Kalshi category markets: {e}")
        return []


@app.get("/kalshi/markets/{market_id}", response_model=MarketResponse)
async def get_kalshi_market(market_id: str = Path(...)):
    """Get a specific Kalshi market."""
    try:
        market = await kalshi_platform.get_market(market_id)
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")
        return market_to_response(market, "kalshi")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/kalshi/categories", response_model=list[CategoryResponse])
async def get_kalshi_categories():
    """Get Kalshi categories."""
    categories = kalshi_platform.get_available_categories()
    return [
        CategoryResponse(id=c["id"], label=c["label"], emoji=c["emoji"], count=0)
        for c in categories
    ]


# ===================
# Multi-Platform Routes
# ===================

@app.get("/platforms")
async def get_platforms():
    """Get available platforms."""
    return [
        {"id": "polymarket", "name": "Polymarket", "emoji": "🔮", "chain": "polygon"},
        {"id": "kalshi", "name": "Kalshi", "emoji": "📊", "chain": "solana"},
        {"id": "limitless", "name": "Limitless", "emoji": "♾️", "chain": "base"},
        {"id": "opinion", "name": "Opinion Labs", "emoji": "💭", "chain": "bsc"},
    ]


@app.get("/markets", response_model=list[MarketResponse])
async def get_all_markets(
    platform: Optional[str] = Query(None, description="Filter by platform: polymarket, kalshi, all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    active: bool = Query(True),
):
    """Get markets from all platforms or a specific one. Returns combined results sorted by volume."""
    import httpx
    import json as json_lib

    results = []
    platforms_to_fetch = []

    if platform and platform != "all":
        platforms_to_fetch = [platform]
    else:
        platforms_to_fetch = ["polymarket", "kalshi", "opinion", "limitless"]

    async with httpx.AsyncClient(timeout=20.0) as client:
        # Fetch Polymarket markets
        if "polymarket" in platforms_to_fetch:
            try:
                gamma_url = "https://gamma-api.polymarket.com/events"
                resp = await client.get(gamma_url, params={
                    "active": "true" if active else "false",
                    "limit": 200,
                    "order": "volume24hr",
                    "ascending": "false",
                })

                if resp.status_code == 200:
                    all_events = resp.json()
                    for event in all_events:
                        for m in event.get("markets", []):
                            # Parse outcome prices
                            outcome_prices_raw = m.get("outcomePrices", [])
                            if isinstance(outcome_prices_raw, str):
                                try:
                                    outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                                except:
                                    outcome_prices_raw = []

                            prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

                            # Parse token IDs
                            tokens_raw = m.get("clobTokenIds", [])
                            if isinstance(tokens_raw, str):
                                try:
                                    tokens_raw = json_lib.loads(tokens_raw)
                                except:
                                    tokens_raw = []

                            # Parse outcomes
                            outcomes_raw = m.get("outcomes", ["Yes", "No"])
                            if isinstance(outcomes_raw, str):
                                try:
                                    outcomes_raw = json_lib.loads(outcomes_raw)
                                except:
                                    outcomes_raw = ["Yes", "No"]

                            results.append(MarketResponse(
                                id=m.get("conditionId") or str(m.get("id", "")),
                                question=m.get("question") or m.get("groupItemTitle") or event.get("title", ""),
                                description=m.get("description") or event.get("description"),
                                image=event.get("image"),
                                icon=event.get("icon"),
                                category=event.get("category"),
                                outcomes=outcomes_raw,
                                outcomePrices=prices,
                                clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                                volume=float(m.get("volume", 0)) if m.get("volume") else None,
                                volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                                liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                                endDate=m.get("endDate") or event.get("endDate"),
                                active=m.get("active", True),
                                closed=m.get("closed", False),
                                slug=m.get("conditionId") or str(m.get("id", "")),
                                platform="polymarket",
                            ))
            except Exception as e:
                print(f"Error fetching Polymarket markets: {e}")

        # Fetch Kalshi markets via DFlow API
        if "kalshi" in platforms_to_fetch:
            try:
                # Use correct DFlow metadata API URL
                dflow_url = "https://c.prediction-markets-api.dflow.net/api/v1/markets"
                headers = {"x-api-key": settings.dflow_api_key} if settings.dflow_api_key else {}

                params = {"limit": 200}
                if active:
                    params["status"] = "active"

                resp = await client.get(dflow_url, headers=headers, params=params, timeout=15.0)

                print(f"Kalshi API response status: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    kalshi_markets = data.get("markets", data.get("data", []))
                    print(f"Got {len(kalshi_markets)} Kalshi markets from API")

                    for m in kalshi_markets:
                        # Skip inactive markets if active filter is on
                        status = m.get("status", "").lower()
                        if active and status not in ["open", "active", ""]:
                            continue

                        # Parse prices (DFlow uses camelCase: yesAsk, noAsk, yesBid, noBid)
                        # Prices are already in decimal format (0.26 = 26%)
                        yes_price = m.get("yesAsk") or m.get("yesBid") or 0
                        no_price = m.get("noAsk") or m.get("noBid") or 0

                        # Infer category from ticker
                        ticker = m.get("ticker", "")
                        category = "Other"
                        if any(x in ticker.upper() for x in ["TRUMP", "BIDEN", "DEM", "REP", "ELECT", "PRES", "GOV", "SENATE", "CONGRESS"]):
                            category = "Politics"
                        elif any(x in ticker.upper() for x in ["BTC", "ETH", "CRYPTO", "COIN"]):
                            category = "Crypto"
                        elif any(x in ticker.upper() for x in ["NBA", "NFL", "MLB", "NHL", "FIFA", "CFP", "SPORT"]):
                            category = "Sports"
                        elif any(x in ticker.upper() for x in ["FED", "CPI", "GDP", "RATE", "ECON"]):
                            category = "Economics"
                        elif any(x in ticker.upper() for x in ["WEATHER", "TEMP", "HURRICANE"]):
                            category = "Weather"

                        # Convert timestamp to ISO string if needed
                        end_date = m.get("closeTime") or m.get("expirationTime")
                        if end_date and isinstance(end_date, (int, float)):
                            from datetime import datetime
                            end_date = datetime.fromtimestamp(end_date).isoformat()
                        elif end_date:
                            end_date = str(end_date)

                        results.append(MarketResponse(
                            id=m.get("ticker") or str(m.get("id", "")),
                            question=m.get("title") or m.get("question", ""),
                            description=m.get("subtitle") or m.get("description"),
                            image=None,
                            icon=None,
                            category=category,
                            outcomes=["Yes", "No"],
                            outcomePrices=[str(yes_price or 0), str(no_price or 0)],
                            clobTokenIds=[],
                            volume=float(m.get("volume", 0)) if m.get("volume") else None,
                            volume24hr=float(m.get("openInterest", 0)) if m.get("openInterest") else None,  # Use openInterest as proxy
                            liquidity=float(m.get("openInterest", 0)) if m.get("openInterest") else None,
                            endDate=end_date,
                            active=status in ["open", "active", ""],
                            closed=status in ["closed", "settled"],
                            slug=m.get("ticker") or str(m.get("id", "")),
                            platform="kalshi",
                        ))
            except Exception as e:
                print(f"Error fetching Kalshi markets: {e}")

        # Fetch Opinion Labs markets
        if "opinion" in platforms_to_fetch:
            try:
                opinion_url = "https://proxy.opinion.trade:8443/openapi/market"
                headers = {"apikey": settings.opinion_api_key} if settings.opinion_api_key else {}

                params = {"limit": 100, "sortBy": 5}  # sortBy 5 = volume
                if active:
                    params["status"] = "activated"

                resp = await client.get(opinion_url, headers=headers, params=params, timeout=15.0)

                print(f"Opinion API response status: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    opinion_markets = data.get("result", {}).get("list", [])
                    print(f"Got {len(opinion_markets)} Opinion markets from API")

                    for m in opinion_markets:
                        # Status check
                        status_enum = m.get("statusEnum", "").lower()
                        if active and status_enum not in ["activated", "active"]:
                            continue

                        # Convert timestamp to ISO string
                        end_date = m.get("cutoffAt") or m.get("closeTime")
                        if end_date and isinstance(end_date, (int, float)):
                            from datetime import datetime
                            end_date = datetime.fromtimestamp(end_date).isoformat()
                        elif end_date:
                            end_date = str(end_date)

                        # Default prices (Opinion doesn't include prices in market list)
                        yes_price = "0.5"
                        no_price = "0.5"

                        results.append(MarketResponse(
                            id=str(m.get("marketId") or m.get("id", "")),
                            question=m.get("marketTitle") or m.get("title") or "",
                            description=m.get("rules") or m.get("description"),
                            image=m.get("thumbnailUrl") or m.get("coverUrl"),
                            icon=None,
                            category=m.get("category") or "Prediction",
                            outcomes=[m.get("yesLabel", "Yes"), m.get("noLabel", "No")],
                            outcomePrices=[yes_price, no_price],
                            clobTokenIds=[m.get("yesTokenId", ""), m.get("noTokenId", "")],
                            volume=float(m.get("volume", 0)) if m.get("volume") else None,
                            volume24hr=float(m.get("volume24h", 0)) if m.get("volume24h") else None,
                            liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                            endDate=end_date,
                            active=status_enum in ["activated", "active"],
                            closed=status_enum in ["resolved", "settled"],
                            slug=str(m.get("marketId") or m.get("id", "")),
                            platform="opinion",
                        ))
            except Exception as e:
                print(f"Error fetching Opinion markets: {e}")

        # Fetch Limitless markets
        if "limitless" in platforms_to_fetch:
            try:
                markets = await limitless_platform.get_markets(limit=100, active_only=True)
                print(f"Got {len(markets)} Limitless markets from platform")

                for m in markets:
                    results.append(MarketResponse(
                        id=m.market_id,
                        question=m.title or "",
                        description=m.description,
                        image=getattr(m, 'image', None),
                        icon=None,
                        category=m.category or "Prediction",
                        outcomes=["Yes", "No"],
                        outcomePrices=[str(float(m.yes_price or 0)), str(float(m.no_price or 0))],
                        clobTokenIds=[m.yes_token or "", m.no_token or ""],
                        volume=float(m.volume_24h) if m.volume_24h else None,
                        volume24hr=float(m.volume_24h) if m.volume_24h else None,
                        liquidity=float(m.liquidity) if m.liquidity else None,
                        endDate=m.close_time,
                        active=m.is_active,
                        closed=not m.is_active,
                        slug=m.market_id,
                        platform="limitless",
                    ))
            except Exception as e:
                print(f"Error fetching Limitless markets: {e}")

    # Sort by volume24hr descending
    results.sort(key=lambda x: x.volume24hr or 0, reverse=True)

    # Apply search filter if provided
    if search:
        search_lower = search.lower()
        results = [r for r in results if search_lower in (r.question or "").lower() or search_lower in (r.description or "").lower()]

    # Apply pagination
    return results[offset:offset + limit]


@app.get("/markets/{market_id}", response_model=MarketResponse)
async def get_market_by_id(market_id: str = Path(...)):
    """Get a specific market by ID from any platform."""
    import httpx
    import json as json_lib
    from datetime import datetime

    # Detect platform by ID format
    # Kalshi tickers are like: KXSB-26-LAR, KXBTC-25JAN14-B55000
    # Polymarket conditionIds are like: 0x17815081230e3b9c78b098162c33b1ffa68c4ec29c123d3d14989599e0c2e113
    # Opinion market IDs are numeric like: 3975
    is_kalshi = not market_id.startswith("0x") and "-" in market_id
    is_opinion = market_id.isdigit()
    is_polymarket = market_id.startswith("0x")

    async with httpx.AsyncClient(timeout=15.0) as client:
        if is_opinion:
            # Fetch from Opinion API
            try:
                opinion_url = f"https://proxy.opinion.trade:8443/openapi/market/{market_id}"
                headers = {"apikey": settings.opinion_api_key} if settings.opinion_api_key else {}

                resp = await client.get(opinion_url, headers=headers, timeout=15.0)

                if resp.status_code == 200:
                    data = resp.json()
                    m = data.get("result", {}).get("data", data.get("result", data))

                    if m and isinstance(m, dict):
                        # Convert timestamp
                        end_date = m.get("cutoffAt") or m.get("closeTime")
                        if end_date and isinstance(end_date, (int, float)):
                            end_date = datetime.fromtimestamp(end_date).isoformat()
                        elif end_date:
                            end_date = str(end_date)

                        return MarketResponse(
                            id=str(m.get("marketId") or market_id),
                            question=m.get("marketTitle") or m.get("title") or "",
                            description=m.get("rules") or m.get("description"),
                            image=m.get("thumbnailUrl") or m.get("coverUrl"),
                            icon=None,
                            category=m.get("category") or "Prediction",
                            outcomes=[m.get("yesLabel", "Yes"), m.get("noLabel", "No")],
                            outcomePrices=["0.5", "0.5"],
                            clobTokenIds=[m.get("yesTokenId", ""), m.get("noTokenId", "")],
                            volume=float(m.get("volume", 0)) if m.get("volume") else None,
                            volume24hr=float(m.get("volume24h", 0)) if m.get("volume24h") else None,
                            liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                            endDate=end_date,
                            active=m.get("statusEnum", "").lower() in ["activated", "active"],
                            closed=m.get("statusEnum", "").lower() in ["resolved", "settled"],
                            slug=str(m.get("marketId") or market_id),
                            platform="opinion",
                        )

                # Try fetching from market list if direct endpoint fails
                list_url = "https://proxy.opinion.trade:8443/openapi/market"
                resp = await client.get(list_url, headers=headers, params={"marketId": market_id}, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    markets = data.get("result", {}).get("list", [])
                    if markets:
                        m = markets[0]
                        end_date = m.get("cutoffAt") or m.get("closeTime")
                        if end_date and isinstance(end_date, (int, float)):
                            end_date = datetime.fromtimestamp(end_date).isoformat()

                        return MarketResponse(
                            id=str(m.get("marketId") or market_id),
                            question=m.get("marketTitle") or m.get("title") or "",
                            description=m.get("rules") or m.get("description"),
                            image=m.get("thumbnailUrl"),
                            icon=None,
                            category=m.get("category") or "Prediction",
                            outcomes=[m.get("yesLabel", "Yes"), m.get("noLabel", "No")],
                            outcomePrices=["0.5", "0.5"],
                            clobTokenIds=[m.get("yesTokenId", ""), m.get("noTokenId", "")],
                            volume=float(m.get("volume", 0)) if m.get("volume") else None,
                            volume24hr=float(m.get("volume24h", 0)) if m.get("volume24h") else None,
                            liquidity=None,
                            endDate=end_date,
                            active=True,
                            closed=False,
                            slug=str(m.get("marketId") or market_id),
                            platform="opinion",
                        )

                raise HTTPException(status_code=404, detail="Opinion market not found")
            except HTTPException:
                raise
            except Exception as e:
                print(f"Error fetching Opinion market: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        elif is_kalshi:
            # Fetch from DFlow API
            try:
                dflow_url = "https://c.prediction-markets-api.dflow.net/api/v1/markets"
                headers = {"x-api-key": settings.dflow_api_key} if settings.dflow_api_key else {}

                resp = await client.get(dflow_url, headers=headers, params={"limit": 200, "status": "active"})

                if resp.status_code == 200:
                    data = resp.json()
                    kalshi_markets = data.get("markets", data.get("data", []))

                    for m in kalshi_markets:
                        if m.get("ticker") == market_id:
                            # Found the market
                            yes_price = m.get("yesAsk") or m.get("yesBid") or 0
                            no_price = m.get("noAsk") or m.get("noBid") or 0

                            # Infer category
                            ticker = m.get("ticker", "")
                            category = "Other"
                            if any(x in ticker.upper() for x in ["TRUMP", "BIDEN", "DEM", "REP", "ELECT", "PRES", "GOV"]):
                                category = "Politics"
                            elif any(x in ticker.upper() for x in ["BTC", "ETH", "CRYPTO"]):
                                category = "Crypto"
                            elif any(x in ticker.upper() for x in ["NBA", "NFL", "MLB", "NHL", "CFP"]):
                                category = "Sports"
                            elif any(x in ticker.upper() for x in ["FED", "CPI", "GDP"]):
                                category = "Economics"

                            # Convert timestamp
                            end_date = m.get("closeTime") or m.get("expirationTime")
                            if end_date and isinstance(end_date, (int, float)):
                                end_date = datetime.fromtimestamp(end_date).isoformat()
                            elif end_date:
                                end_date = str(end_date)

                            return MarketResponse(
                                id=m.get("ticker"),
                                question=m.get("title") or "",
                                description=m.get("subtitle"),
                                image=None,
                                icon=None,
                                category=category,
                                outcomes=["Yes", "No"],
                                outcomePrices=[str(yes_price or 0), str(no_price or 0)],
                                clobTokenIds=[],
                                volume=float(m.get("volume", 0)) if m.get("volume") else None,
                                volume24hr=float(m.get("openInterest", 0)) if m.get("openInterest") else None,
                                liquidity=float(m.get("openInterest", 0)) if m.get("openInterest") else None,
                                endDate=end_date,
                                active=m.get("status", "").lower() in ["open", "active", ""],
                                closed=m.get("status", "").lower() in ["closed", "settled"],
                                slug=m.get("ticker"),
                                platform="kalshi",
                            )

                raise HTTPException(status_code=404, detail="Kalshi market not found")
            except HTTPException:
                raise
            except Exception as e:
                print(f"Error fetching Kalshi market: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        else:
            # Polymarket - delegate to existing endpoint
            try:
                gamma_url = "https://gamma-api.polymarket.com/events"
                markets_url = "https://gamma-api.polymarket.com/markets"

                found_market = None
                found_event = None

                # Try direct market lookup
                resp = await client.get(markets_url, params={"condition_id": market_id})
                if resp.status_code == 200:
                    markets_data = resp.json()
                    if markets_data and len(markets_data) > 0:
                        found_market = markets_data[0]
                        event_slug = found_market.get("eventSlug")
                        if event_slug:
                            event_resp = await client.get(gamma_url, params={"slug": event_slug})
                            if event_resp.status_code == 200:
                                events = event_resp.json()
                                if events:
                                    found_event = events[0]

                # Fallback: Search through events
                if not found_market:
                    for search_params in [
                        {"active": "true", "limit": 500, "order": "volume24hr", "ascending": "false"},
                        {"closed": "true", "limit": 200},
                    ]:
                        resp = await client.get(gamma_url, params=search_params)
                        if resp.status_code == 200:
                            all_events = resp.json()
                            for event in all_events:
                                for m in event.get("markets", []):
                                    if m.get("conditionId") == market_id:
                                        found_market = m
                                        found_event = event
                                        break
                                if found_market:
                                    break
                        if found_market:
                            break

                if not found_market:
                    raise HTTPException(status_code=404, detail="Market not found")

                m = found_market
                event = found_event

                # Parse fields
                outcome_prices_raw = m.get("outcomePrices", [])
                if isinstance(outcome_prices_raw, str):
                    try:
                        outcome_prices_raw = json_lib.loads(outcome_prices_raw)
                    except:
                        outcome_prices_raw = []
                prices = [str(p) for p in outcome_prices_raw] if outcome_prices_raw else ["0", "0"]

                tokens_raw = m.get("clobTokenIds", [])
                if isinstance(tokens_raw, str):
                    try:
                        tokens_raw = json_lib.loads(tokens_raw)
                    except:
                        tokens_raw = []

                outcomes_raw = m.get("outcomes", ["Yes", "No"])
                if isinstance(outcomes_raw, str):
                    try:
                        outcomes_raw = json_lib.loads(outcomes_raw)
                    except:
                        outcomes_raw = ["Yes", "No"]

                return MarketResponse(
                    id=m.get("conditionId") or str(m.get("id", "")),
                    question=m.get("question") or m.get("groupItemTitle") or (event.get("title", "") if event else ""),
                    description=m.get("description") or (event.get("description") if event else None),
                    image=event.get("image") if event else None,
                    icon=event.get("icon") if event else None,
                    category=event.get("category") if event else None,
                    outcomes=outcomes_raw,
                    outcomePrices=prices,
                    clobTokenIds=tokens_raw if isinstance(tokens_raw, list) else [],
                    volume=float(m.get("volume", 0)) if m.get("volume") else None,
                    volume24hr=float(m.get("volume24hr", 0)) if m.get("volume24hr") else None,
                    liquidity=float(m.get("liquidity", 0)) if m.get("liquidity") else None,
                    endDate=m.get("endDate") or (event.get("endDate") if event else None),
                    active=m.get("active", True),
                    closed=m.get("closed", False),
                    slug=m.get("conditionId") or str(m.get("id", "")),
                    platform="polymarket",
                )
            except HTTPException:
                raise
            except Exception as e:
                print(f"Error fetching Polymarket market: {e}")
                raise HTTPException(status_code=500, detail=str(e))


# ===================
# Trading Routes
# ===================

from pydantic import BaseModel
from typing import Literal

class QuoteRequest(BaseModel):
    platform: str
    market_id: str
    outcome: Literal["yes", "no"]
    side: Literal["buy", "sell"]
    amount: str


class QuoteResponse(BaseModel):
    platform: str
    market_id: str
    outcome: str
    side: str
    input_amount: str
    expected_output: str
    price_per_token: float
    price_impact: Optional[float] = None
    platform_fee: Optional[str] = None
    network_fee_estimate: Optional[str] = None


@app.post("/api/v1/trading/quote", response_model=QuoteResponse)
async def get_trading_quote(request: QuoteRequest):
    """Get a quote for buying/selling outcome tokens."""
    from decimal import Decimal

    try:
        # Get the appropriate platform
        platform_map = {
            "polymarket": polymarket_platform,
            "kalshi": kalshi_platform,
            "opinion": opinion_platform,
            "limitless": limitless_platform,
        }

        platform = platform_map.get(request.platform)
        if not platform:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {request.platform}")

        # Get quote from platform
        amount = Decimal(request.amount)
        outcome = Outcome.YES if request.outcome.lower() == "yes" else Outcome.NO

        quote = await platform.get_quote(
            market_id=request.market_id,
            outcome=outcome,
            side=request.side,
            amount=amount,
        )

        if not quote:
            raise HTTPException(status_code=400, detail="Could not get quote for this market")

        return QuoteResponse(
            platform=request.platform,
            market_id=request.market_id,
            outcome=request.outcome,
            side=request.side,
            input_amount=request.amount,
            expected_output=str(quote.expected_output),
            price_per_token=float(quote.price_per_token),
            price_impact=float(quote.price_impact) if quote.price_impact else None,
            platform_fee=str(quote.platform_fee) if quote.platform_fee else None,
            network_fee_estimate=str(quote.network_fee_estimate) if quote.network_fee_estimate else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Quote error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class TradeRequest(BaseModel):
    platform: str
    market_id: str
    outcome: Literal["yes", "no"]
    side: Literal["buy", "sell"]
    amount: str
    slippage_bps: int = 100


class TradeResponse(BaseModel):
    success: bool
    tx_hash: Optional[str] = None
    input_amount: str
    output_amount: Optional[str] = None
    error_message: Optional[str] = None


@app.post("/api/v1/trading/execute", response_model=TradeResponse)
async def execute_trade(request: TradeRequest):
    """Execute a trade. Note: This requires wallet setup and authentication."""
    # For now, return a mock response since trading requires wallet infrastructure
    return TradeResponse(
        success=False,
        input_amount=request.amount,
        error_message="Trading requires wallet setup. Please use the Telegram bot for trading.",
    )


# ===================
# Run directly
# ===================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
