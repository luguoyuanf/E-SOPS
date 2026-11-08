"""Username uniqueness and authentication must follow tenant membership."""
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.platform.core.identity_models import User, UserCreate
from app.platform.core.tenancy_models import Tenant, TenantMembership
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import PlatformGlobalUnitOfWork


def test_same_username_across_tenants_and_login_isolation():
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(engine, tables=[SQLModel.metadata.tables[name] for name in names])
    with Session(engine, expire_on_commit=False) as session:
        with PlatformGlobalUnitOfWork(session):
            a, b = Tenant(code="tenant-a", name="A"), Tenant(code="tenant-b", name="B")
            session.add_all([a, b])
            session.commit()
            first = crud.create_user(session=session, tenant_id=a.id, user_create=UserCreate(username="same", password="password-a"))
            second = crud.create_user(session=session, tenant_id=b.id, user_create=UserCreate(username="same", password="password-b"))
            assert crud.authenticate(session=session, email="same", password="password-a", tenant_id=a.id).id == first.id
            assert crud.authenticate(session=session, email="same", password="password-b", tenant_id=b.id).id == second.id
            assert crud.authenticate(session=session, email="same", password="password-a", tenant_id=b.id) is None
            assert crud.authenticate(session=session, email="same", password="password-a") is None
            with pytest.raises(HTTPException) as conflict:
                crud.create_user(session=session, tenant_id=a.id, user_create=UserCreate(username="same", password="password-c"))
            assert conflict.value.status_code == 409
            third = User(username="same", hashed_password="unused")
            session.add(third)
            session.flush()
            session.add(TenantMembership(user_id=third.id, tenant_id=a.id, username="same"))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
