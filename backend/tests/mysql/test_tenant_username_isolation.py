"""The fixed test MySQL database rolls back all test records."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import crud
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.identity_models import User, UserCreate
from app.platform.core.tenancy_models import Tenant, TenantMembership
from app.platform.tenant_uow import PlatformGlobalUnitOfWork
from tests.mysql.test_official_channel import session as database_session

session = database_session


def test_username_isolation_and_unique_constraint(session):
    suffix = uuid.uuid4().hex
    with PlatformGlobalUnitOfWork(session):
        baseline = session.get(Tenant, DEFAULT_TENANT_ID)
        a = Tenant(code="ua-" + suffix[:12], name="Username A", plan_id=baseline.plan_id, initialization_template_id=baseline.initialization_template_id)
        b = Tenant(code="ub-" + suffix[:12], name="Username B", plan_id=baseline.plan_id, initialization_template_id=baseline.initialization_template_id)
        session.add_all([a, b])
        session.flush()
        first = crud.create_user(session=session, tenant_id=a.id, user_create=UserCreate(username=suffix, password="password-a"))
        second = crud.create_user(session=session, tenant_id=b.id, user_create=UserCreate(username=suffix, password="password-b"))
        assert crud.authenticate(session=session, email=suffix, password="password-a", tenant_id=a.id).id == first.id
        assert crud.authenticate(session=session, email=suffix, password="password-b", tenant_id=b.id).id == second.id
        assert crud.authenticate(session=session, email=suffix, password="password-a", tenant_id=b.id) is None
        assert crud.authenticate(session=session, email=suffix, password="password-a") is None
        with pytest.raises(HTTPException) as conflict:
            crud.create_user(session=session, tenant_id=a.id, user_create=UserCreate(username=suffix, password="password-c"))
        assert conflict.value.status_code == 409
        with session.begin_nested():
            third = User(username=suffix, hashed_password="unused")
            session.add(third)
            session.flush()
            session.add(TenantMembership(user_id=third.id, tenant_id=a.id, username=suffix))
            with pytest.raises(IntegrityError):
                session.flush()
