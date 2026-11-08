"""Tenant isolation, commit invalidation and stale-generation publishing boundaries."""
import uuid
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core import transaction_cache
from app.core.cache import CacheNamespace, redis_cache
from app.core.transaction_cache import GENERATION_TTL_SECONDS, tenant_generation_key
from app.modules.erp.infrastructure.models import Product, ProductCategory
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork
from app.modules.esop import catalog_cache, terminal_routes
from app.modules.esop.infrastructure.device_auth import DeviceIdentity
from app.modules.esop.infrastructure.models import (
    Operation,
    OperationFileRendition,
    ProductSopVersion,
    SopDocument,
)
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.platform.infra.file_models import FileAsset
from app.platform.tenant_uow import PlatformTenantUnitOfWork


class MemoryRedis:
    """Model the two small Lua contracts without requiring a separate Redis service."""
    def __init__(self):
        self.values = {}
        self.expires = {}
        self.down = False
        self.time = 0
        self.calls = []

    def get(self, key):
        self.calls.append("get")
        if self.down:
            raise RedisConnectionError("test outage")
        if self.expires.get(key, float("inf")) <= self.time:
            self.values.pop(key, None)
        return self.values.get(key)

    def setex(self, key, ttl, value):
        if self.down:
            raise RedisConnectionError("test outage")
        self.values[key] = value
        self.expires[key] = self.time + int(ttl)
        return True

    def eval(self, script, count, *args):
        self.calls.append("eval")
        if self.down:
            raise RedisConnectionError("test outage")
        keys, argv = args[:count], args[count:]
        if "local result = {}" in script:
            result = []
            for index, key in enumerate(keys):
                token = self.get(key)
                if token is None:
                    self.setex(key, argv[len(keys)], argv[index])
                    token = self.get(key)
                result.append(token)
            return result
        assert "if redis.call('GET', KEYS[i]) ~= ARGV[i]" in script
        if any(self.get(key) != argv[index] for index, key in enumerate(keys[:-1])):
            return 0
        return int(self.setex(keys[-1], argv[len(keys)], argv[len(keys) - 1]))


@pytest.fixture
def memory_redis(monkeypatch):
    client = MemoryRedis()
    monkeypatch.setattr(redis_cache, "_get_client", lambda: client)
    return client


def database():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           execution_options={"schema_translate_map": {"esop": None, "erp": None}})
    # The ERP UoW uses PostgreSQL set_config on non-MySQL test connections.
    event.listen(engine, "connect", lambda connection, _record:
                 connection.create_function("set_config", 3, lambda *_: None))
    return engine


def generation(namespace, tenant):
    return redis_cache.get_or_create_generations([tenant_generation_key(namespace, tenant)],
                                               ttl_seconds=GENERATION_TTL_SECONDS)[0]


@pytest.mark.usefixtures("memory_redis")
def test_missing_generations_are_random_stable_and_first_invalidation_changes_them():
    tenant = uuid.uuid4()
    key = tenant_generation_key(CacheNamespace.SOP_GUIDANCE, tenant)
    first = generation(CacheNamespace.SOP_GUIDANCE, tenant)
    assert len(first) == 32 and first != "1"
    assert generation(CacheNamespace.SOP_GUIDANCE, tenant) == first
    redis_cache.set(key, uuid.uuid4().hex, ttl_seconds=GENERATION_TTL_SECONDS)
    assert generation(CacheNamespace.SOP_GUIDANCE, tenant) != first


@pytest.mark.usefixtures("memory_redis")
def test_cache_is_tenant_scoped_and_caches_empty_results():
    a, b = uuid.uuid4(), uuid.uuid4()
    empty, other = Mock(return_value={"list": []}), Mock(return_value={"list": [{"title": "B"}]})
    assert catalog_cache.cached_catalog(a, empty) == {"list": []}
    assert catalog_cache.cached_catalog(a, empty) == {"list": []}
    assert catalog_cache.cached_catalog(b, other)["list"][0]["title"] == "B"
    assert empty.call_count == other.call_count == 1


def test_invalidated_inflight_builder_cannot_publish(memory_redis):
    tenant = uuid.uuid4()
    def stale():
        redis_cache.set(tenant_generation_key(CacheNamespace.SOP_GUIDANCE, tenant), uuid.uuid4().hex,
                        ttl_seconds=GENERATION_TTL_SECONDS)
        return {"list": [{"title": "old"}]}
    catalog_cache.cached_catalog(tenant, stale)
    assert not any("esop-sop-catalog" in key for key in memory_redis.values)
    fresh = Mock(return_value={"list": [{"title": "new"}]})
    assert catalog_cache.cached_catalog(tenant, fresh)["list"][0]["title"] == "new"
    catalog_cache.cached_catalog(tenant, fresh)
    assert fresh.call_count == 1


def test_redis_outage_falls_back_and_missed_invalidation_is_bounded_by_payload_ttl(memory_redis):
    tenant = uuid.uuid4()
    catalog_cache.cached_catalog(tenant, lambda: {"list": [{"title": "old"}]})
    memory_redis.down = True
    fresh = Mock(return_value={"list": [{"title": "new"}]})
    assert catalog_cache.cached_catalog(tenant, fresh)["list"][0]["title"] == "new"
    assert not redis_cache.set(tenant_generation_key(CacheNamespace.SOP_GUIDANCE, tenant), uuid.uuid4().hex)
    memory_redis.down = False
    # Redis missed the write invalidation: an old entry can remain only until its original TTL expires.
    memory_redis.time += catalog_cache.CATALOG_TTL_SECONDS + 1
    assert catalog_cache.cached_catalog(tenant, fresh)["list"][0]["title"] == "new"
    assert fresh.call_count == 2


def test_each_owner_registers_only_its_catalog_dependencies():
    assert transaction_cache._NAMESPACES[Product] == CacheNamespace.PRODUCT_DIRECTORY
    assert transaction_cache._NAMESPACES[ProductCategory] == CacheNamespace.PRODUCT_DIRECTORY
    for model in (Operation, ProductSopVersion, SopDocument, OperationFileRendition):
        assert transaction_cache._NAMESPACES[model] == CacheNamespace.SOP_GUIDANCE
    assert transaction_cache._NAMESPACES[FileAsset] == CacheNamespace.FILE_ASSETS


@pytest.mark.parametrize("model,uow_type,namespace,values,field", [
    (ProductCategory, ErpTenantUnitOfWork, CacheNamespace.PRODUCT_DIRECTORY, {"code": "CACHE", "name": "before"}, "name"),
    (Operation, EsopTenantUnitOfWork, CacheNamespace.SOP_GUIDANCE,
     {"code": "CACHE", "name": "before", "product_id": uuid.uuid4()}, "name"),
    (OperationFileRendition, EsopTenantUnitOfWork, CacheNamespace.SOP_GUIDANCE,
     {"original_file_id": uuid.uuid4(), "display_file_id": uuid.uuid4()}, "display_file_id"),
    (FileAsset, PlatformTenantUnitOfWork, CacheNamespace.FILE_ASSETS,
     {"original_name": "before.mp4", "stored_name": "stored", "storage_path": "unused", "size": 10, "sha256": "0" * 64}, "original_name"),
])
@pytest.mark.usefixtures("memory_redis")
def test_owner_create_update_delete_commit_invalidates_only_its_tenant(model, uow_type, namespace, values, field):
    engine = database()
    SQLModel.metadata.create_all(engine, tables=[model.__table__])
    tenant, other = uuid.uuid4(), uuid.uuid4()
    before, other_before = generation(namespace, tenant), generation(namespace, other)
    with Session(engine) as session, uow_type(session, tenant):
        entity = model(tenant_id=tenant, **values)
        session.add(entity)
        session.flush()
        assert generation(namespace, tenant) == before
        session.commit()
        created = generation(namespace, tenant)
        assert created != before and generation(namespace, other) == other_before
        setattr(entity, field, uuid.uuid4() if field == "display_file_id" else "after")
        session.add(entity)
        session.commit()
        updated = generation(namespace, tenant)
        assert updated != created
        session.delete(entity)
        session.commit()
        assert generation(namespace, tenant) != updated
        assert generation(namespace, other) == other_before


@pytest.mark.parametrize("nested_commit,root_commit", [(False, True), (True, False), (True, True)])
@pytest.mark.usefixtures("memory_redis")
def test_savepoint_does_not_lose_outer_changes_or_invalidate_before_root_commit(nested_commit, root_commit):
    engine = database()
    SQLModel.metadata.create_all(engine, tables=[ProductCategory.__table__])
    tenant = uuid.uuid4()
    before = generation(CacheNamespace.PRODUCT_DIRECTORY, tenant)
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        session.add(ProductCategory(tenant_id=tenant, code="OUTER", name="outer"))
        session.flush()
        nested = session.begin_nested()
        session.add(ProductCategory(tenant_id=tenant, code="INNER", name="inner"))
        session.flush()
        nested.commit() if nested_commit else nested.rollback()
        assert generation(CacheNamespace.PRODUCT_DIRECTORY, tenant) == before
        session.commit() if root_commit else session.rollback()
        assert (generation(CacheNamespace.PRODUCT_DIRECTORY, tenant) != before) == root_commit


def test_hit_still_authenticates_and_miss_builds_after_generation_in_new_session(memory_redis, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    tenant = uuid.uuid4()
    device = DeviceIdentity(tenant, uuid.uuid4())
    authorized = Mock()
    monkeypatch.setattr(terminal_routes, "_terminal", authorized)
    with Session(engine) as request_session:
        request_session.exec(text("SELECT 1"))  # DeviceDep has already opened the request snapshot.
        def build(read_session, _device):
            assert read_session is not request_session
            assert not read_session.in_transaction()
            assert any("tenant-generation" in key for key in memory_redis.values)
            return {"list": []}
        builder = Mock(side_effect=build)
        monkeypatch.setattr(terminal_routes, "_build_terminal_sop_catalog", builder)
        assert terminal_routes.terminal_sop_catalog(request_session, device) == {"list": []}
        assert terminal_routes.terminal_sop_catalog(request_session, device) == {"list": []}
        assert builder.call_count == 1 and authorized.call_count == 2
        authorized.side_effect = HTTPException(401, "disabled device")
        with pytest.raises(HTTPException) as error:
            terminal_routes.terminal_sop_catalog(request_session, device)
        assert error.value.status_code == 401 and builder.call_count == 1
