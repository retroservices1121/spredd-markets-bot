"""
Redis caching layer for Spredd Markets Bot.

Provides typed get/set methods for market data with graceful degradation —
if Redis is unavailable, all methods return None and the bot works normally.
"""

import hashlib
import json
from decimal import Decimal
from typing import Any, Optional

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _serialize_decimal(obj):
    """JSON serializer for Decimal and Enum types."""
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "value"):  # Enum
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _market_to_dict(market) -> dict:
    """Convert a Market dataclass to a JSON-serializable dict."""
    return {
        "platform": market.platform.value,
        "chain": market.chain.value,
        "market_id": market.market_id,
        "event_id": market.event_id,
        "title": market.title,
        "description": market.description,
        "category": market.category,
        "yes_price": str(market.yes_price) if market.yes_price is not None else None,
        "no_price": str(market.no_price) if market.no_price is not None else None,
        "volume_24h": str(market.volume_24h) if market.volume_24h is not None else None,
        "liquidity": str(market.liquidity) if market.liquidity is not None else None,
        "is_active": market.is_active,
        "close_time": market.close_time,
        "yes_token": market.yes_token,
        "no_token": market.no_token,
        "raw_data": market.raw_data,
        "image_url": market.image_url,
        "outcome_name": market.outcome_name,
        "is_multi_outcome": market.is_multi_outcome,
        "related_market_count": market.related_market_count,
        "yes_outcome_name": market.yes_outcome_name,
        "no_outcome_name": market.no_outcome_name,
        "resolution_criteria": market.resolution_criteria,
    }


def _dict_to_market(d: dict):
    """Convert a dict back to a Market dataclass."""
    from src.db.models import Chain, Platform
    from src.platforms.base import Market

    return Market(
        platform=Platform(d["platform"]),
        chain=Chain(d["chain"]),
        market_id=d["market_id"],
        event_id=d.get("event_id"),
        title=d["title"],
        description=d.get("description"),
        category=d.get("category"),
        yes_price=Decimal(d["yes_price"]) if d.get("yes_price") is not None else None,
        no_price=Decimal(d["no_price"]) if d.get("no_price") is not None else None,
        volume_24h=Decimal(d["volume_24h"]) if d.get("volume_24h") is not None else None,
        liquidity=Decimal(d["liquidity"]) if d.get("liquidity") is not None else None,
        is_active=d.get("is_active", True),
        close_time=d.get("close_time"),
        yes_token=d.get("yes_token"),
        no_token=d.get("no_token"),
        raw_data=d.get("raw_data"),
        image_url=d.get("image_url"),
        outcome_name=d.get("outcome_name"),
        is_multi_outcome=d.get("is_multi_outcome", False),
        related_market_count=d.get("related_market_count", 0),
        yes_outcome_name=d.get("yes_outcome_name"),
        no_outcome_name=d.get("no_outcome_name"),
        resolution_criteria=d.get("resolution_criteria"),
    )


def _orderbook_to_dict(ob) -> dict:
    """Convert an OrderBook dataclass to a JSON-serializable dict."""
    return {
        "market_id": ob.market_id,
        "outcome": ob.outcome.value,
        "bids": [[str(p), str(s)] for p, s in ob.bids],
        "asks": [[str(p), str(s)] for p, s in ob.asks],
    }


def _dict_to_orderbook(d: dict):
    """Convert a dict back to an OrderBook dataclass."""
    from src.db.models import Outcome
    from src.platforms.base import OrderBook

    return OrderBook(
        market_id=d["market_id"],
        outcome=Outcome(d["outcome"]),
        bids=[(Decimal(p), Decimal(s)) for p, s in d["bids"]],
        asks=[(Decimal(p), Decimal(s)) for p, s in d["asks"]],
    )


def _hash_params(*args) -> str:
    """Create a short hash from parameters for cache key."""
    raw = ":".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class RedisCache:
    """Async Redis cache with typed methods for market data.

    All public methods gracefully degrade — if Redis is down or unconfigured,
    get methods return None and set methods silently no-op.
    """

    def __init__(self):
        self._redis = None
        self._available = False
        self._hits = 0
        self._misses = 0

    @property
    def is_available(self) -> bool:
        return self._available

    async def connect(self) -> None:
        """Connect to Redis. Logs warning and continues if unavailable."""
        if not settings.redis_url:
            logger.info("Redis cache disabled (REDIS_URL not set)")
            return

        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
                max_connections=settings.redis_pool_size,
            )
            # Verify connection
            await self._redis.ping()
            self._available = True
            logger.info("Redis cache connected", url=settings.redis_url.split("@")[-1])
        except Exception as e:
            logger.warning("Redis cache unavailable, running without cache", error=str(e))
            self._redis = None
            self._available = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
            self._available = False
            logger.info("Redis cache closed")

    def cache_stats(self) -> dict:
        """Return hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
            "total": total,
        }

    async def health_check(self) -> dict:
        """Return cache health status."""
        if not self._available or not self._redis:
            return {"status": "unavailable", "reason": "not connected", **self.cache_stats()}
        try:
            await self._redis.ping()
            info = await self._redis.info("memory")
            return {
                "status": "healthy",
                "used_memory": info.get("used_memory_human", "unknown"),
                **self.cache_stats(),
            }
        except Exception as e:
            return {"status": "unhealthy", "reason": str(e), **self.cache_stats()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, key: str) -> Optional[str]:
        if not self._available or not self._redis:
            self._misses += 1
            return None
        try:
            val = await self._redis.get(key)
            if val is not None:
                self._hits += 1
            else:
                self._misses += 1
            return val
        except Exception as e:
            self._misses += 1
            logger.debug("Redis GET failed", key=key, error=str(e))
            return None

    async def _set(self, key: str, value: str, ttl: int) -> None:
        if not self._available or not self._redis:
            return
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.debug("Redis SET failed", key=key, error=str(e))

    async def _delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern. Returns count deleted."""
        if not self._available or not self._redis:
            return 0
        try:
            count = 0
            async for key in self._redis.scan_iter(match=pattern, count=200):
                await self._redis.delete(key)
                count += 1
            return count
        except Exception as e:
            logger.warning("Redis pattern delete failed", pattern=pattern, error=str(e))
            return 0

    # ------------------------------------------------------------------
    # Market listings (trending / browse)
    # ------------------------------------------------------------------

    async def get_markets(self, platform: str, limit: int, offset: int, active_only: bool) -> Optional[list]:
        key = f"spredd:{platform}:markets:{_hash_params(limit, offset, active_only)}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return [_dict_to_market(d) for d in json.loads(raw)]
        except Exception as e:
            logger.debug("Cache deserialize failed", key=key, error=str(e))
            return None

    async def set_markets(self, platform: str, limit: int, offset: int, active_only: bool, markets: list) -> None:
        key = f"spredd:{platform}:markets:{_hash_params(limit, offset, active_only)}"
        try:
            data = json.dumps([_market_to_dict(m) for m in markets], default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_markets)
        except Exception as e:
            logger.debug("Cache serialize failed", key=key, error=str(e))

    # ------------------------------------------------------------------
    # Single market detail
    # ------------------------------------------------------------------

    async def get_market(self, platform: str, market_id: str) -> Optional[object]:
        key = f"spredd:{platform}:market:{market_id}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return _dict_to_market(json.loads(raw))
        except Exception:
            return None

    async def set_market(self, platform: str, market_id: str, market) -> None:
        key = f"spredd:{platform}:market:{market_id}"
        try:
            data = json.dumps(_market_to_dict(market), default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_market_detail)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Search results
    # ------------------------------------------------------------------

    async def get_search(self, platform: str, query: str, limit: int) -> Optional[list]:
        key = f"spredd:{platform}:search:{_hash_params(query.lower().strip(), limit)}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return [_dict_to_market(d) for d in json.loads(raw)]
        except Exception:
            return None

    async def set_search(self, platform: str, query: str, limit: int, markets: list) -> None:
        key = f"spredd:{platform}:search:{_hash_params(query.lower().strip(), limit)}"
        try:
            data = json.dumps([_market_to_dict(m) for m in markets], default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_search)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Category markets
    # ------------------------------------------------------------------

    async def get_category(self, platform: str, category_id: str) -> Optional[list]:
        key = f"spredd:{platform}:category:{category_id}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return [_dict_to_market(d) for d in json.loads(raw)]
        except Exception:
            return None

    async def set_category(self, platform: str, category_id: str, markets: list) -> None:
        key = f"spredd:{platform}:category:{category_id}"
        try:
            data = json.dumps([_market_to_dict(m) for m in markets], default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_markets)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Related markets (multi-outcome events)
    # ------------------------------------------------------------------

    async def get_related(self, platform: str, event_id: str) -> Optional[list]:
        key = f"spredd:{platform}:related:{event_id}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return [_dict_to_market(d) for d in json.loads(raw)]
        except Exception:
            return None

    async def set_related(self, platform: str, event_id: str, markets: list) -> None:
        key = f"spredd:{platform}:related:{event_id}"
        try:
            data = json.dumps([_market_to_dict(m) for m in markets], default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_market_detail)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Orderbook snapshots
    # ------------------------------------------------------------------

    async def get_orderbook(self, platform: str, market_id: str, outcome: str) -> Optional[object]:
        key = f"spredd:{platform}:orderbook:{market_id}:{outcome}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return _dict_to_orderbook(json.loads(raw))
        except Exception:
            return None

    async def set_orderbook(self, platform: str, market_id: str, outcome: str, orderbook) -> None:
        key = f"spredd:{platform}:orderbook:{market_id}:{outcome}"
        try:
            data = json.dumps(_orderbook_to_dict(orderbook), default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_market_detail)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # API routes caches (dict results for the extension/mini-app)
    # ------------------------------------------------------------------

    async def get_api_markets(self, platform: str, active: bool) -> Optional[list[dict]]:
        key = f"spredd:api:markets:{platform}:{active}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_api_markets(self, platform: str, active: bool, results: list[dict]) -> None:
        key = f"spredd:api:markets:{platform}:{active}"
        try:
            data = json.dumps(results, default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_markets)
        except Exception:
            pass

    async def get_api_search(self, query: str, platform: str) -> Optional[list[dict]]:
        key = f"spredd:api:search:{_hash_params(query.lower().strip(), platform)}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_api_search(self, query: str, platform: str, results: list[dict]) -> None:
        key = f"spredd:api:search:{_hash_params(query.lower().strip(), platform)}"
        try:
            data = json.dumps(results, default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_search)
        except Exception:
            pass

    async def get_api_trending(self, platform: str) -> Optional[list[dict]]:
        key = f"spredd:api:trending:{platform}"
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_api_trending(self, platform: str, results: list[dict]) -> None:
        key = f"spredd:api:trending:{platform}"
        try:
            data = json.dumps(results, default=_serialize_decimal)
            await self._set(key, data, settings.cache_ttl_markets)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Generic JSON cache (for API route dicts, events, candlesticks, etc.)
    # ------------------------------------------------------------------

    async def get_json(self, key: str) -> Optional[Any]:
        """Get an arbitrary JSON-serializable value by full key."""
        raw = await self._get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_json(self, key: str, value, ttl: int) -> None:
        """Set an arbitrary JSON-serializable value with explicit TTL."""
        try:
            data = json.dumps(value, default=_serialize_decimal)
            await self._set(key, data, ttl)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    async def flush_platform(self, platform: str) -> int:
        """Flush all cached data for a specific platform."""
        return await self._delete_pattern(f"spredd:*{platform}*")

    async def flush_all(self) -> int:
        """Flush all spredd cache keys."""
        return await self._delete_pattern("spredd:*")


# Module-level singleton
cache = RedisCache()
