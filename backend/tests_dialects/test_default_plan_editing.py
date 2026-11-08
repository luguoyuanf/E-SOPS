"""Default plans use the same editing rules as other plans."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes.tenants import (
    delete_tenant_plan,
    update_tenant_plan,
    update_tenant_plan_menus,
)
from app.platform.core.authorization_models import Menu
from app.platform.core.tenancy_models import (
    Tenant,
    TenantPlan,
    TenantPlanMenuUpdate,
    TenantPlanUpdate,
)
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


def test_default_plan_edit_menus_and_delete():
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        plan = TenantPlan(code="standard", name="Standard", is_default=True)
        menu = Menu(title="Users", permission_code="system:user:list")
        session.add_all([plan, menu])
        session.commit()
        result = update_tenant_plan(
            session=session, plan_id=plan.id, plan_in=TenantPlanUpdate(name="Updated")
        )
        assert result.name == "Updated"
        assert update_tenant_plan_menus(
            session=session,
            plan_id=plan.id,
            body=TenantPlanMenuUpdate(menu_ids=[menu.id]),
        ) == [menu.id]
        tenant = Tenant(code="bound", name="Bound", plan_id=plan.id)
        session.add(tenant)
        session.commit()
        with pytest.raises(HTTPException, match="Tenant plan is in use"):
            delete_tenant_plan(session=session, plan_id=plan.id)
        session.delete(tenant)
        session.commit()
        assert delete_tenant_plan(session=session, plan_id=plan.id).status_code == 204
