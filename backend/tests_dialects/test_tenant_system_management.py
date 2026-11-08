"""Tenant system pages expose only their own records; messaging stays root-only."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import deps
from app.api.routes import departments, posts
from app.core.tenancy import TenantContext
from app.platform.core.authorization_models import (
    Department,
    Menu,
    Post,
    Role,
    RoleMenu,
    UserRole,
)
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.infra import logs_router
from app.platform.infra.audit_models import LoginLog, OperationLog
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import activate_platform_tenant_scope


def test_tenant_system_lists_and_cross_tenant_access():
    import_platform_model_groups()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="system", name="System")
        tenants = [
            Tenant(code=code, name=code, plan_id=plan.id) for code in ("own", "other")
        ]
        user = User(email="system@example.com", hashed_password="unused")
        role = Role(tenant_id=tenants[0].id, code="admin", name="Admin")
        session.add_all([plan, *tenants, user, role])
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=tenants[0].id))
        for code in ("department", "post", "login-log", "operation-log"):
            menu = Menu(title=code, permission_code=f"system:{code}:list")
            session.add(menu)
            session.flush()
            session.add_all(
                [
                    TenantPlanMenu(plan_id=plan.id, menu_id=menu.id),
                    RoleMenu(role_id=role.id, menu_id=menu.id),
                ]
            )
        for tenant in tenants:
            session.add_all(
                [
                    Department(tenant_id=tenant.id, code="same-code", name=tenant.name),
                    Post(tenant_id=tenant.id, code="same-code", name=tenant.name),
                    LoginLog(tenant_id=tenant.id, status="success"),
                    OperationLog(
                        tenant_id=tenant.id,
                        module="system",
                        action="test",
                        method="GET",
                        path="/test",
                        status_code=200,
                        duration_ms=1,
                    ),
                ]
            )
        colleague = User(email="colleague@example.com", hashed_password="unused")
        session.add(colleague)
        session.add(
            OperationLog(
                tenant_id=tenants[0].id,
                user_id=colleague.id,
                email=colleague.email,
                module="system",
                action="update",
                method="PATCH",
                path="/colleague-operation",
                status_code=200,
                duration_ms=1,
            )
        )
        session.commit()
        app = FastAPI()
        for router in (departments.router, posts.router, logs_router.router):
            app.include_router(router)

        def context():
            activate_platform_tenant_scope(session, tenants[0].id)
            return TenantContext(
                tenant_id=tenants[0].id, tenant_code="own", user_id=user.id
            )

        app.dependency_overrides[deps.get_db] = lambda: session
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_current_tenant_context] = context
        with TestClient(app) as client:
            for path in ("/departments", "/posts", "/logs/login", "/logs/operation"):
                response = client.get(path)
                assert response.status_code == 200, response.text
                assert response.json()["total"] == (2 if path == "/logs/operation" else 1)
                assert {row["tenant_id"] for row in response.json()["items"]} == {
                    str(tenants[0].id)
                }
                assert (
                    client.get(
                        path, params={"tenant_id": str(tenants[1].id)}
                    ).status_code
                    == 403
                )

            # A tenant administrator sees colleagues' operations, not only their own.
            own_logs = client.get("/logs/operation").json()
            assert str(colleague.id) in {row["user_id"] for row in own_logs["items"]}
            filtered = client.get(
                "/logs/operation", params={"keyword": "colleague", "page_size": 1}
            ).json()
            assert filtered["total"] == 1
            assert filtered["items"][0]["user_id"] == str(colleague.id)

            # The same HTTP dependency grants global reads only to platform root.
            user.is_superuser = True
            session.add(user)
            session.commit()
            response = client.get("/logs/operation", params={"page_size": 1})
            assert response.status_code == 200, response.text
            assert response.json()["total"] == 3
            assert len(response.json()["items"]) == 1
            all_logs = client.get("/logs/operation").json()
            assert {row["tenant_id"] for row in all_logs["items"]} == {
                str(tenant.id) for tenant in tenants
            }
            other_logs = client.get(
                "/logs/operation", params={"tenant_id": str(tenants[1].id)}
            ).json()
            assert other_logs["total"] == 1
            assert other_logs["items"][0]["tenant_id"] == str(tenants[1].id)
