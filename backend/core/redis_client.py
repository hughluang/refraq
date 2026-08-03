"""Redis client factory for persistent Session store."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from backend.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for persistent Store Backend")
    return Redis.from_url(settings.redis_url, decode_responses=True)


def ping_redis() -> None:
    if get_redis().ping() is not True:
        raise RuntimeError("Redis PING failed")


def reset_redis_singleton() -> None:
    try:
        client = get_redis()
        client.close()
    except Exception:
        pass
    get_redis.cache_clear()
