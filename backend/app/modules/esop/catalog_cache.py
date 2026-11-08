"""Tenant-specific approved guidance payloads; authentication is never cached."""
import uuid
from collections.abc import Callable
from typing import Any

from app.core.cache import CacheNamespace, redis_cache
from app.core.transaction_cache import GENERATION_TTL_SECONDS, tenant_generation_key

CATALOG_TTL_SECONDS = 60
_DEPENDENCIES = (CacheNamespace.PRODUCT_DIRECTORY, CacheNamespace.SOP_GUIDANCE, CacheNamespace.FILE_ASSETS)


def cached_catalog(tenant_id: uuid.UUID, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    generation_keys = [tenant_generation_key(namespace, tenant_id) for namespace in _DEPENDENCIES]
    generations = redis_cache.get_or_create_generations(generation_keys, ttl_seconds=GENERATION_TTL_SECONDS)
    if generations is None:
        return build()
    key = redis_cache.build_key("esop-sop-catalog", "v1", tenant_id, *generations)
    cached = redis_cache.get_json(key)
    if isinstance(cached, dict) and isinstance(cached.get("list"), list):
        return cached
    result = build()
    redis_cache.publish_json_if_generations(key, generation_keys=generation_keys, expected=generations,
                                            value=result, ttl_seconds=CATALOG_TTL_SECONDS)
    return result
