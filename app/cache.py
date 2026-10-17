"""Redis cache for product reads, using the cache-aside pattern.

Read:  look in Redis -> on a miss, read the database -> save the result in Redis with a TTL.
Write: after any change to a tenant's products or stock is committed, bump that tenant's
       cache version. Every key contains the version, so old entries are simply never read
       again (they expire on their own). A reader that loaded old data just before a write
       saves it under the old version, so stale data is never served after a write.

If Redis is not configured or not reachable, every read goes to the database.
"""

import json
import logging
from collections.abc import Callable
from typing import Any, cast

import redis
from flask import Flask, current_app

_EXTENSION_KEY = "stockroom_redis"
_log = logging.getLogger("stockroom.cache")


def init_redis(app: Flask) -> None:
    """Create the Redis client (or none, if REDIS_URL is not set)."""
    url = app.config.get("REDIS_URL")
    app.extensions[_EXTENSION_KEY] = (
        # Short timeouts: a broken Redis must not make every request slow
        redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5
        )
        if url
        else None
    )


def redis_client() -> redis.Redis | None:
    return cast(redis.Redis | None, current_app.extensions.get(_EXTENSION_KEY))


def _version_key(tenant_id: int) -> str:
    return f"stockroom:tenant:{tenant_id}:products:version"


def cached_product_data(tenant_id: int, name: str, load: Callable[[], Any]) -> tuple[Any, bool]:
    """Return (data, came_from_cache) for one of the tenant's product reads.

    `name` identifies the read, e.g. "list" or "product:42". `load` builds the data from the
    database; it must return something JSON can store (already-serialised dicts and lists).
    """
    client = redis_client()
    if client is None:
        return load(), False

    try:
        version = cast(str | None, client.get(_version_key(tenant_id))) or "0"
        key = f"stockroom:tenant:{tenant_id}:products:v{version}:{name}"
        cached = cast(str | None, client.get(key))
    except redis.RedisError:
        _log.warning("cache unavailable, reading from the database", exc_info=True)
        return load(), False

    if cached is not None:
        return json.loads(cached), True

    data = load()
    try:
        client.set(key, json.dumps(data), ex=current_app.config["CACHE_TTL_SECONDS"])
    except redis.RedisError:
        _log.warning("could not save to the cache", exc_info=True)
    return data, False


def invalidate_products(tenant_id: int) -> None:
    """Make every cached product read of this tenant stale. Call it after committing."""
    client = redis_client()
    if client is None:
        return
    try:
        client.incr(_version_key(tenant_id))
    except redis.RedisError:
        # Entries then live until their TTL runs out; log loudly so it gets noticed
        _log.error("could not invalidate the product cache of tenant %s", tenant_id, exc_info=True)


def redis_status() -> str:
    """Redis state for the readiness check: up, down or not configured."""
    client = redis_client()
    if client is None:
        return "not configured"
    try:
        client.ping()
    except redis.RedisError:
        return "down"
    return "up"
