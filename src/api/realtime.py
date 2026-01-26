"""
Real-time streaming API endpoints using Server-Sent Events (SSE).

Provides live price updates to the webapp without requiring WebSocket on the frontend.
The backend maintains WebSocket connections to exchanges and streams updates via SSE.
"""

import asyncio
import json
import time
from decimal import Decimal
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from src.services.websocket_manager import price_cache, PriceUpdate
from src.services.polymarket_ws import polymarket_ws_manager
from src.services.price_poller import price_poller
from src.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def serialize_price_update(update: PriceUpdate) -> dict:
    """Serialize a PriceUpdate for JSON transmission."""
    return {
        "platform": update.platform,
        "market_id": update.market_id,
        "token_id": update.token_id,
        "best_bid": str(update.best_bid) if update.best_bid else None,
        "best_ask": str(update.best_ask) if update.best_ask else None,
        "last_trade_price": str(update.last_trade_price) if update.last_trade_price else None,
        "last_trade_size": str(update.last_trade_size) if update.last_trade_size else None,
        "last_trade_side": update.last_trade_side,
        "timestamp": update.timestamp,
    }


async def price_event_generator(
    token_ids: list[str],
    platform: str = "polymarket",
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for price updates.

    Yields SSE-formatted events whenever prices change for subscribed tokens.
    """
    # Queue for receiving price updates
    update_queue: asyncio.Queue[PriceUpdate] = asyncio.Queue()

    async def on_price_update(update: PriceUpdate):
        await update_queue.put(update)

    # Subscribe to price updates for all tokens
    for token_id in token_ids:
        price_cache.subscribe(platform, token_id, on_price_update)

    try:
        # Send initial prices for all tokens
        for token_id in token_ids:
            cached = await price_cache.get_price(platform, token_id)
            if cached:
                data = json.dumps(serialize_price_update(cached), cls=DecimalEncoder)
                yield f"event: price\ndata: {data}\n\n"

        # Stream updates
        while True:
            try:
                # Wait for updates with timeout (for keepalive)
                update = await asyncio.wait_for(update_queue.get(), timeout=30.0)
                data = json.dumps(serialize_price_update(update), cls=DecimalEncoder)
                yield f"event: price\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield f": keepalive {time.time()}\n\n"

    finally:
        # Unsubscribe on disconnect
        for token_id in token_ids:
            price_cache.unsubscribe(platform, token_id, on_price_update)


async def multi_market_event_generator(
    markets: list[dict],  # [{"market_id": str, "yes_token": str, "no_token": str}]
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for multiple markets across platforms.

    Subscribes to all provided markets and streams combined updates.
    """
    update_queue: asyncio.Queue[PriceUpdate] = asyncio.Queue()

    async def on_price_update(update: PriceUpdate):
        await update_queue.put(update)

    # Track subscriptions for cleanup
    subscriptions: list[tuple[str, str]] = []

    try:
        # Subscribe to all markets
        for market in markets:
            platform = market.get("platform", "polymarket")
            market_id = market.get("market_id", "")
            yes_token = market.get("yes_token")
            no_token = market.get("no_token")

            if yes_token:
                price_cache.subscribe(platform, yes_token, on_price_update)
                subscriptions.append((platform, yes_token))

            if no_token:
                price_cache.subscribe(platform, no_token, on_price_update)
                subscriptions.append((platform, no_token))

            # Subscribe via appropriate service based on platform
            if platform == "polymarket":
                # Use WebSocket for Polymarket
                await polymarket_ws_manager.subscribe_market(
                    market_id=market_id,
                    yes_token=yes_token,
                    no_token=no_token,
                )
            else:
                # Use polling for other platforms (Kalshi, Limitless, Opinion)
                price_poller.subscribe(
                    platform=platform,
                    market_id=market_id,
                    yes_token=yes_token,
                    no_token=no_token,
                )

        # Send connection confirmation
        yield f"event: connected\ndata: {json.dumps({'markets': len(markets)})}\n\n"

        # Send initial prices
        for platform, token_id in subscriptions:
            cached = await price_cache.get_price(platform, token_id)
            if cached:
                data = json.dumps(serialize_price_update(cached), cls=DecimalEncoder)
                yield f"event: price\ndata: {data}\n\n"

        # Stream updates
        while True:
            try:
                update = await asyncio.wait_for(update_queue.get(), timeout=30.0)
                data = json.dumps(serialize_price_update(update), cls=DecimalEncoder)
                yield f"event: price\ndata: {data}\n\n"
            except asyncio.TimeoutError:
                yield f": keepalive {time.time()}\n\n"

    finally:
        # Cleanup subscriptions
        for platform, token_id in subscriptions:
            price_cache.unsubscribe(platform, token_id, on_price_update)


@router.get("/prices/stream")
async def stream_prices(
    request: Request,
    token_ids: str = Query(..., description="Comma-separated token IDs to subscribe to"),
    platform: str = Query(default="polymarket", description="Platform name"),
):
    """
    Stream real-time price updates via Server-Sent Events.

    Example usage in JavaScript:
    ```js
    const eventSource = new EventSource('/api/realtime/prices/stream?token_ids=abc,def&platform=polymarket');
    eventSource.addEventListener('price', (event) => {
        const data = JSON.parse(event.data);
        console.log('Price update:', data);
    });
    ```
    """
    tokens = [t.strip() for t in token_ids.split(",") if t.strip()]

    if not tokens:
        return {"error": "No token IDs provided"}

    # Ensure WebSocket is connected for Polymarket
    if platform == "polymarket" and not polymarket_ws_manager.is_connected:
        await polymarket_ws_manager.start()

    return StreamingResponse(
        price_event_generator(tokens, platform),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/prices/subscribe")
async def subscribe_markets(
    request: Request,
    markets: list[dict],
):
    """
    Subscribe to multiple markets and return SSE stream.

    Request body:
    ```json
    {
        "markets": [
            {
                "platform": "polymarket",
                "market_id": "...",
                "yes_token": "...",
                "no_token": "..."
            }
        ]
    }
    ```
    """
    if not markets:
        return {"error": "No markets provided"}

    # Ensure WebSocket connections are active
    has_polymarket = any(m.get("platform", "polymarket") == "polymarket" for m in markets)
    if has_polymarket and not polymarket_ws_manager.is_connected:
        await polymarket_ws_manager.start()

    return StreamingResponse(
        multi_market_event_generator(markets),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/prices/snapshot")
async def get_price_snapshot(
    platform: Optional[str] = Query(default=None, description="Filter by platform"),
):
    """
    Get current snapshot of all cached prices.

    Returns all live prices currently in cache, optionally filtered by platform.
    """
    prices = await price_cache.get_all_prices(platform)
    return {
        "count": len(prices),
        "prices": {
            key: serialize_price_update(update)
            for key, update in prices.items()
        },
    }


@router.get("/status")
async def get_realtime_status():
    """Get status of real-time connections."""
    return {
        "polymarket": {
            "type": "websocket",
            "connected": polymarket_ws_manager.is_connected,
            "state": polymarket_ws_manager._client.state.value if polymarket_ws_manager._client else "not_started",
        },
        "kalshi": {
            "type": "polling",
            "active": price_poller._running,
            "subscriptions": len([s for s in price_poller._subscriptions.values() if s.platform == "kalshi"]),
        },
        "limitless": {
            "type": "polling",
            "active": price_poller._running,
            "subscriptions": len([s for s in price_poller._subscriptions.values() if s.platform == "limitless"]),
        },
        "opinion": {
            "type": "polling",
            "active": price_poller._running,
            "subscriptions": len([s for s in price_poller._subscriptions.values() if s.platform == "opinion"]),
        },
    }


@router.post("/connect")
async def connect_realtime():
    """Manually trigger real-time data connections (useful for initialization)."""
    results = {}

    # Start Polymarket WebSocket
    try:
        await polymarket_ws_manager.start()
        results["polymarket"] = "websocket_connected"
    except Exception as e:
        results["polymarket"] = f"error: {str(e)}"

    # Start price poller for other platforms
    try:
        await price_poller.start()
        results["poller"] = "started"
    except Exception as e:
        results["poller"] = f"error: {str(e)}"

    return results


@router.post("/disconnect")
async def disconnect_realtime():
    """Manually disconnect real-time data services."""
    await polymarket_ws_manager.stop()
    await price_poller.stop()
    return {"status": "disconnected"}
