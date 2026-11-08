"""Application-layer MySQL isolation. These tests do not claim database RLS."""

import uuid

import pytest
from sqlalchemy import delete, insert, literal_column, text, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.core.database import engine
from app.platform.core.authorization_models import Role
from app.platform.core.tenancy_models import (
    Tenant,
    TenantInitializationTemplate,
    TenantPlan,
)
from app.platform.tenant_uow import (
    PlatformGlobalUnitOfWork,
    PlatformTenantScopeError,
    PlatformTenantUnitOfWork,
)


@pytest.fixture
def realms():
    if engine.dialect.name != "mysql":
        pytest.skip("requires MySQL")
    assert engine.url.database and "_test_" in engine.url.database
    with Session(engine) as session:
        plan = TenantPlan(code=f"uow-{uuid.uuid4().hex[:12]}", name="UoW plan")
        template = TenantInitializationTemplate(
            code=f"uow-{uuid.uuid4().hex[:12]}", name="UoW template"
        )
        session.add_all([plan, template])
        session.flush()
        plan_id, template_id = plan.id, template.id
        tenants = [
            Tenant(
                code=f"uow-{uuid.uuid4().hex[:12]}",
                name="UoW test",
                plan_id=plan_id,
                initialization_template_id=template_id,
            )
            for _ in range(2)
        ]
        session.add_all(tenants)
        session.flush()
        ids = [row.id for row in tenants]
        role_ids = []
        for tenant_id in ids:
            with PlatformTenantUnitOfWork(session, tenant_id, privileged=True):
                role = Role(tenant_id=tenant_id, code="reader", name="Reader")
                role_ids.append(role.id)
                session.add(role)
                session.flush()
        session.commit()
    try:
        yield ids, role_ids
    finally:
        with Session(engine) as session:
            with PlatformGlobalUnitOfWork(session):
                session.exec(delete(Role).where(Role.tenant_id.in_(ids)))
                session.exec(delete(Tenant).where(Tenant.id.in_(ids)))
                session.exec(delete(TenantPlan).where(TenantPlan.id == plan_id))
                session.exec(
                    delete(TenantInitializationTemplate).where(
                        TenantInitializationTemplate.id == template_id
                    )
                )
                session.commit()


def test_scope_reads_aliases_bulk_writes_and_root_global(realms):
    ids, roles = realms
    with Session(engine) as session:
        with pytest.raises(PlatformTenantScopeError, match="explicit UnitOfWork"):
            session.exec(select(Role)).all()
        session.add(Role(tenant_id=ids[0], code="no-scope", name="No scope"))
        with pytest.raises(PlatformTenantScopeError, match="explicit UnitOfWork"):
            session.flush()
        session.rollback()
        with PlatformGlobalUnitOfWork(session):
            assert len(session.exec(select(Role).where(Role.id.in_(roles))).all()) == 2
        with PlatformTenantUnitOfWork(session, ids[0]):
            assert session.get(Role, roles[1]) is None
            alias = aliased(Role)
            assert (
                session.exec(select(alias).where(alias.id.in_(roles))).one().id
                == roles[0]
            )
            result = session.exec(
                update(Role).where(Role.id == roles[1]).values(name="Stolen")
            )
            assert result.rowcount == 0
            result = session.exec(delete(Role).where(Role.id == roles[1]))
            assert result.rowcount == 0
            with pytest.raises(PlatformTenantScopeError, match="immutable"):
                session.exec(
                    update(Role).where(Role.id == roles[0]).values(tenant_id=ids[1])
                )
            with pytest.raises(PlatformTenantScopeError, match="ORM operations"):
                session.exec(
                    insert(Role).values(
                        id=uuid.uuid4(), tenant_id=ids[1], code="bulk", name="Bad"
                    )
                )
            with pytest.raises(PlatformTenantScopeError, match="ORM operations"):
                session.exec(select(Role.__table__))
            with pytest.raises(PlatformTenantScopeError, match="checked ORM"):
                session.bulk_update_mappings(Role, [{"id": roles[1], "name": "Bypass"}])
            session.rollback()
            session.commit()
        with PlatformTenantUnitOfWork(session, ids[1]):
            assert session.get(Role, roles[1]).name == "Reader"


def test_raw_connection_sql_cannot_bypass_scope(realms):
    ids, _roles = realms
    with Session(engine) as session:
        with PlatformTenantUnitOfWork(session, ids[0]):
            for statement in (
                "SELECT * FROM role",
                "DELETE FROM role",
                "WITH x AS (SELECT * FROM role) SELECT * FROM x",
            ):
                with pytest.raises(PlatformTenantScopeError, match="Raw SQL"):
                    session.execute(text(statement))
            with pytest.raises(PlatformTenantScopeError, match="Raw SQL"):
                session.connection().execute(text("SELECT * FROM role"))
            with pytest.raises(PlatformTenantScopeError, match="Driver SQL"):
                session.connection().exec_driver_sql("SELECT * FROM role")
            with pytest.raises(PlatformTenantScopeError, match="checked ORM"):
                session.connection().execute(select(Role.__table__))
            with pytest.raises(PlatformTenantScopeError, match="Raw SQL fragments"):
                session.exec(select(Role).from_statement(text("SELECT * FROM role")))
            with pytest.raises(PlatformTenantScopeError, match="Raw SQL fragments"):
                session.exec(select(literal_column("(SELECT COUNT(*) FROM role)")))
            assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_cross_tenant_flush_delete_and_owner_changes_fail(realms):
    ids, roles = realms
    with Session(engine) as session:
        with PlatformGlobalUnitOfWork(session):
            foreign = session.get(Role, roles[1])
        with PlatformTenantUnitOfWork(session, ids[0]):
            session.add(Role(tenant_id=ids[1], code="bad", name="Bad"))
            with pytest.raises(PlatformTenantScopeError, match="does not match"):
                session.flush()
            session.rollback()
            session.add(foreign)
            session.delete(foreign)
            with pytest.raises(PlatformTenantScopeError, match="does not match"):
                session.flush()
            session.rollback()
            own = session.get(Role, roles[0])
            own.tenant_id = ids[1]
            with pytest.raises(PlatformTenantScopeError):
                session.flush()
            session.rollback()


def test_nested_scope_restoration_identity_map_and_failure(realms):
    ids, roles = realms
    with Session(engine) as session:
        with PlatformTenantUnitOfWork(session, ids[0]):
            assert session.get(Role, roles[0]) is not None
            with pytest.raises(PlatformTenantScopeError, match="multiple tenants"):
                with PlatformTenantUnitOfWork(session, ids[1]):
                    pass
            with PlatformTenantUnitOfWork(session, ids[1], privileged=True):
                assert session.get(Role, roles[0]) is None
                assert session.get(Role, roles[1]) is not None
            assert session.info["platform_tenant_id"] == ids[0]
            assert session.get(Role, roles[1]) is None
            with pytest.raises(ValueError):
                with PlatformGlobalUnitOfWork(session):
                    assert session.get(Role, roles[1]) is not None
                    raise ValueError("test")
            assert session.info["platform_tenant_id"] == ids[0]
            assert not session.info.get("platform_global_scope")
        assert "platform_tenant_id" not in session.info
        with pytest.raises(PlatformTenantScopeError, match="explicit UnitOfWork"):
            session.exec(select(Role)).all()
