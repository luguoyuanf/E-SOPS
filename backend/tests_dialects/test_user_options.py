import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import deps
from app.api.routes import departments, posts, users
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
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import activate_platform_tenant_scope


@pytest.mark.parametrize(
    "permission",
    ["system:user:list", "system:user:create", "system:user:update", "none", "root"],
)
def test_user_options_are_readonly_current_tenant_and_require_user_administration(
    permission,
):
    import_platform_model_groups()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="options", name="Options")
        own, foreign = (
            Tenant(code="own", name="Own", plan_id=plan.id),
            Tenant(code="foreign", name="Foreign"),
        )
        user = User(
            email="options@example.com",
            hashed_password="unused",
            is_superuser=permission == "root",
        )
        role = Role(tenant_id=own.id, code="options", name="Options")
        session.add_all([plan, own, foreign, user, role])
        session.flush()
        if permission not in ("none", "root"):
            menu = Menu(title="User administration", permission_code=permission)
            session.add(menu)
            session.flush()
            session.add_all(
                [
                    TenantPlanMenu(plan_id=plan.id, menu_id=menu.id),
                    RoleMenu(role_id=role.id, menu_id=menu.id),
                    UserRole(user_id=user.id, role_id=role.id, tenant_id=own.id),
                ]
            )
        for tenant in (own, foreign):
            session.add_all(
                [
                    Department(
                        tenant_id=tenant.id, name=tenant.name, code="department"
                    ),
                    Post(tenant_id=tenant.id, name=tenant.name, code="post"),
                ]
            )
        session.commit()
        app = FastAPI()
        app.include_router(users.router)
        app.include_router(departments.router)
        app.include_router(posts.router)

        def context():
            activate_platform_tenant_scope(session, own.id)
            return TenantContext(
                tenant_id=own.id, tenant_code=own.code, user_id=user.id
            )

        app.dependency_overrides[deps.get_db] = lambda: session
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_current_tenant_context] = context
        with TestClient(app) as client:
            for path in ("/users/department-options", "/users/post-options"):
                response = client.get(path)
                if permission == "none":
                    assert response.status_code == 403
                else:
                    assert response.status_code == 200
                    assert response.json()[0]["tenant_id"] == str(own.id)
                response = client.get(path, params={"tenant_id": str(foreign.id)})
                if permission == "root":
                    assert response.status_code == 200
                    assert response.json()[0]["tenant_id"] == str(foreign.id)
                else:
                    assert response.status_code == 403
            if permission != "root":
                assert client.get("/departments").status_code == 403
                assert client.get("/posts").status_code == 403
            assert client.post("/users/department-options").status_code == 405
            assert client.post("/users/post-options").status_code == 405
