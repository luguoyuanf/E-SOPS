"""Commit-scoped invalidation; each data owner registers only its own ORM models."""
import uuid

from sqlalchemy import event
from sqlmodel import Session

from app.core.cache import redis_cache

GENERATION_TTL_SECONDS = 86400
_NAMESPACES: dict[type, str] = {}
_PENDING_KEY = "tenant_cache_invalidations"


def register_tenant_cache_models(namespace: str, models: tuple[type, ...]) -> None:
    for model in models:
        _NAMESPACES[model] = namespace


def tenant_generation_key(namespace: str, tenant_id: uuid.UUID) -> str:
    return redis_cache.build_key("tenant-generation", namespace, tenant_id)


@event.listens_for(Session, "before_flush")
def _collect_invalidations(session: Session, _flush_context, _instances) -> None:
    for entity in session.new | session.dirty | session.deleted:
        namespace = _NAMESPACES.get(type(entity))
        if namespace is None or (entity in session.dirty and not session.is_modified(entity, include_collections=True)):
            continue
        tenant_id = getattr(entity, "tenant_id", None)
        if tenant_id is not None:
            session.info.setdefault(_PENDING_KEY, set()).add((namespace, tenant_id))


@event.listens_for(Session, "after_commit")
def _invalidate_committed(session: Session) -> None:
    # SAVEPOINT release is not a durable commit: preserve outer + inner changes until root commit.
    if session.in_nested_transaction():
        return
    for namespace, tenant_id in session.info.pop(_PENDING_KEY, set()):
        redis_cache.set(tenant_generation_key(namespace, tenant_id), uuid.uuid4().hex,
                        ttl_seconds=GENERATION_TTL_SECONDS)


@event.listens_for(Session, "after_rollback")
def _discard_rolled_back(session: Session) -> None:
    # A nested rollback must not erase already-flushed outer changes. A conservative later eviction is safe.
    if not session.in_nested_transaction():
        session.info.pop(_PENDING_KEY, None)
