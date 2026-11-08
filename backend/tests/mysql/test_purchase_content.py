"""Purchase-page API guards and persistence on the fixed online test MySQL."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api import deps
from app.core.config import settings
from app.core.database import engine
from app.modules.esop.infrastructure.models import PurchaseContent
from app.modules.esop.public_api.purchase_dto import PurchasePageContent
from app.modules.esop.purchase_routes import router
from app.platform.web_api import Principal, get_current_principal


@pytest.fixture
def page_api():
    assert settings.DATABASE_TYPE == 'mysql' and settings.MYSQL_DB == 'esop_fva_test_20261024'
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode='create_savepoint', expire_on_commit=False) as session:
                existing = session.get(PurchaseContent, 1)
                if existing:
                    session.delete(existing)
                    session.flush()
                actor = [Principal(id=uuid.uuid4(), is_superuser=True)]
                app = FastAPI()
                app.include_router(router)
                app.dependency_overrides[deps.get_db] = lambda: session
                # Isolate the new content/write policy from existing module-entitlement tests.
                app.dependency_overrides[router.dependencies[0].dependency] = lambda: None
                app.dependency_overrides[get_current_principal] = lambda: actor[0]
                with TestClient(app) as client:
                    yield client, session, actor
        finally:
            transaction.rollback()


def test_defaults_are_read_only_and_authentication_is_required(page_api):
    client, session, _ = page_api
    assert client.get('/esop/purchase-content').json() == PurchasePageContent().model_dump()
    assert session.exec(select(PurchaseContent)).all() == []
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as anonymous:
        assert anonymous.get('/esop/purchase-content').status_code == 401


def test_root_save_is_shared_and_cancelled_local_edits_are_not_saved(page_api):
    client, session, actor = page_api
    payload = client.get('/esop/purchase-content').json()
    payload['contact_text'] = '联系客户经理：验收内容'
    payload['prices'] = [{'customer':'企业','quantity':'1 台','price':'60 元 / 台'}]
    assert client.put('/esop/purchase-content', json=payload).status_code == 200
    assert session.get(PurchaseContent, 1).updated_by == actor[0].id
    actor[0] = Principal(id=uuid.uuid4(), is_superuser=False)
    assert client.get('/esop/purchase-content').json() == payload
    payload['contact_text'] = '本地未保存编辑'
    assert client.get('/esop/purchase-content').json()['contact_text'] != payload['contact_text']


@pytest.mark.parametrize('role', ['tenant','channel'])
def test_non_root_cannot_change_shared_content(page_api, role):
    client, _, actor = page_api
    actor[0] = Principal(id=uuid.uuid4(), is_superuser=False)
    payload = PurchasePageContent().model_dump()
    payload['title'] = role
    assert client.put('/esop/purchase-content', json=payload).status_code == 403
    assert client.get('/esop/purchase-content').json()['title'] == '购买与扩容'


def test_invalid_content_is_rejected_without_writing(page_api):
    client, session, _ = page_api
    payload = PurchasePageContent().model_dump()
    payload['prices'][0]['price'] = '   '
    assert client.put('/esop/purchase-content', json=payload).status_code == 422
    payload = PurchasePageContent().model_dump()
    payload['tenant_id'] = str(uuid.uuid4())
    assert client.put('/esop/purchase-content', json=payload).status_code == 422
    assert session.get(PurchaseContent, 1) is None


def test_existing_menu_grants_read_but_does_not_grant_edit(page_api):
    from app.core.tenancy import TenantContext
    from app.core.tenancy_constants import DEFAULT_TENANT_ID
    from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
    from app.platform.core.identity_models import User
    from app.platform.core.tenancy_models import TenantMembership
    from app.platform.tenant_uow import (
        PlatformGlobalUnitOfWork,
        activate_platform_tenant_scope,
    )

    client, session, actor = page_api
    with PlatformGlobalUnitOfWork(session):
        menu = session.exec(select(Menu).where(Menu.route_name == 'EsopPurchase')).one()
        assert menu.permission_code == 'esop:purchase:list'
        user = User(username='purchase_' + uuid.uuid4().hex[:12], hashed_password='unused', is_active=True)
        role = Role(tenant_id=DEFAULT_TENANT_ID, code=uuid.uuid4().hex, name='Purchase reader')
        session.add_all([user, role])
        session.flush()
        session.add(TenantMembership(user_id=user.id, tenant_id=DEFAULT_TENANT_ID, is_active=True))
        session.flush()
        session.add_all([RoleMenu(role_id=role.id, menu_id=menu.id), UserRole(user_id=user.id, role_id=role.id, tenant_id=DEFAULT_TENANT_ID)])
        session.flush()
        role_id, user_id, menu_id = role.id, user.id, menu.id
    actor[0] = user
    app = client.app
    app.dependency_overrides.pop(router.dependencies[0].dependency)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    def tenant_context():
        activate_platform_tenant_scope(session, DEFAULT_TENANT_ID)
        return TenantContext(tenant_id=DEFAULT_TENANT_ID, tenant_code='default', user_id=user_id)
    app.dependency_overrides[deps.get_current_tenant_context] = tenant_context
    assert client.get('/esop/purchase-content').status_code == 200
    assert client.put('/esop/purchase-content', json=PurchasePageContent().model_dump()).status_code == 403
    with PlatformGlobalUnitOfWork(session):
        session.delete(session.get(RoleMenu, (role_id, menu_id)))
        session.flush()
    assert client.get('/esop/purchase-content').status_code == 403
