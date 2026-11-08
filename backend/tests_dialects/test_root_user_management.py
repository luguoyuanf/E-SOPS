"""Explicit root user-management scope; tenant actors retain isolation."""

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import deps
from app.api.routes import users
from app.core.config import settings
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
from app.platform.core.tenancy_models import (
    Tenant,
    TenantMembership,
    TenantPlan,
    TenantPlanMenu,
    TenantProfile,
)
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)
from app.platform.tenant_uow import (
    PlatformGlobalUnitOfWork,
    activate_platform_tenant_scope,
)


@pytest.fixture
def management(monkeypatch):
    from app.modules.esop.infrastructure.models import ChannelAdmin
    import_platform_model_groups()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(engine, tables=[SQLModel.metadata.tables[name] for name in names] + [ChannelAdmin.__table__])
    events = []
    monkeypatch.setattr(users, 'enqueue_event', lambda **kwargs: events.append(kwargs))
    with Session(engine, expire_on_commit=False) as session:
        plan = TenantPlan(code='management', name='Management')
        a, b = [Tenant(code=x, name=x, plan_id=plan.id) for x in ('a', 'b')]
        root = User(email='root@example.com', hashed_password='unused', is_superuser=True)
        tenant_actor = User(email='tenant@example.com', hashed_password='unused')
        target = User(username='target', email='target@example.com', hashed_password='unused')
        builtin = User(email=str(settings.FIRST_SUPERUSER), hashed_password='unused', is_superuser=True)
        shared = User(email='shared@example.com', hashed_password='unused')
        session.add_all([plan, a, b, root, tenant_actor, target, builtin, shared])
        roles, posts, departments = [], [], []
        for tenant in (a, b):
            roles.append(Role(tenant_id=tenant.id, code='admin', name=tenant.name, data_scope='all'))
            posts.append(Post(tenant_id=tenant.id, code='post', name=tenant.name))
            departments.append(Department(tenant_id=tenant.id, code='dept', name=tenant.name))
        session.add_all([*roles, *posts, *departments])
        session.flush()
        for actor, tenant, default in [(root,a,True),(tenant_actor,a,True),(target,b,True),(builtin,b,True),(shared,a,True),(shared,b,False)]:
            session.add(TenantMembership(user_id=actor.id, tenant_id=tenant.id, is_active=True, is_default=default))
        session.add(UserRole(user_id=tenant_actor.id, role_id=roles[0].id, tenant_id=a.id))
        for action in ('list','update','delete'):
            menu = Menu(title=action, permission_code=f'system:user:{action}')
            session.add(menu)
            session.flush()
            session.add_all([TenantPlanMenu(plan_id=plan.id, menu_id=menu.id), RoleMenu(role_id=roles[0].id, menu_id=menu.id)])
        session.add(TenantProfile(tenant_id=b.id, contact_user_id=target.id))
        session.commit()
        actor = [root]
        def context():
            activate_platform_tenant_scope(session, a.id)
            return TenantContext(tenant_id=a.id, tenant_code=a.code, user_id=actor[0].id)
        app = FastAPI()
        app.include_router(users.router)
        app.dependency_overrides[deps.get_db] = lambda: session
        app.dependency_overrides[deps.get_current_user] = lambda: actor[0]
        app.dependency_overrides[deps.get_current_tenant_context] = context
        ids = {name: str(obj.id) for name,obj in [('a',a),('b',b),('root',root),('target',target),('builtin',builtin),('shared',shared)]}
        with TestClient(app) as client:
            yield client, session, ids, actor, tenant_actor, roles, posts, departments, events


def test_root_edits_foreign_user_and_uses_foreign_options(management):
    client, session, ids, *_rest = management
    roles, posts, departments = management[5:8]
    params = {'tenant_id': ids['b']}
    response = client.patch('/users/'+ids['target'], params=params, json={'full_name':'Updated', 'department_id':str(departments[1].id)})
    assert response.status_code == 200, response.text
    assert response.json()['full_name'] == 'Updated'
    assert response.json()['tenant_id'] == ids['b']
    assert {x['id'] for x in client.get('/users/department-options',params=params).json()} == {str(departments[1].id)}
    assert {x['id'] for x in client.get('/users/post-options',params=params).json()} == {str(posts[1].id)}
    for kind, entity in [('roles', roles[1]),('posts',posts[1])]:
        key = 'role_ids' if kind == 'roles' else 'post_ids'
        response=client.put(f'/users/{ids["target"]}/{kind}',params=params,json={key:[str(entity.id)]})
        assert response.status_code == 200,response.text
        assert client.get(f'/users/{ids["target"]}/{kind}',params=params).json()[0]['id'] == str(entity.id)
    assert session.info.get('platform_tenant_id') is not None
    assert not session.info.get('platform_global_scope')


@pytest.mark.parametrize('path,body', [('roles',{'role_ids':None}),('posts',{'post_ids':None}),('',{'department_id':None})])
def test_root_cannot_assign_relationships_from_wrong_tenant(management,path,body):
    client, _, ids, *_ = management
    entity = management[5][0] if path=='roles' else management[6][0] if path=='posts' else management[7][0]
    key=next(iter(body))
    body={key:[str(entity.id)] if path else str(entity.id)}
    response=client.request('PUT' if path else 'PATCH',f'/users/{ids["target"]}'+('/'+path if path else ''),params={'tenant_id':ids['b']},json=body)
    assert response.status_code == 400,response.text


@pytest.mark.parametrize('method,path,body', [('PATCH','',{'full_name':'Forbidden'}),('DELETE','',None),('GET','/roles',None),('PUT','/posts',{'post_ids':[]}),('POST','/mfa/reset',None)])
def test_non_root_cannot_select_another_tenant(management,method,path,body):
    client, _, ids, actor, tenant_actor, *_ = management
    actor[0]=tenant_actor
    response=client.request(method,'/users/'+ids['target']+path,params={'tenant_id':ids['b']},json=body)
    assert response.status_code == 403,response.text


def test_root_must_select_actual_membership_and_cannot_rename(management):
    client, _, ids, *_=management
    assert client.patch('/users/'+ids['target'],params={'tenant_id':ids['a']},json={'full_name':'Wrong'}).status_code == 404
    assert client.patch('/users/'+ids['target'],params={'tenant_id':ids['b']},json={'username':'renamed'}).status_code == 422


def test_root_edits_builtin_and_retains_self_and_last_root_protection(management):
    client, _, ids, *_=management
    params={'tenant_id':ids['b']}
    response=client.patch('/users/'+ids['builtin'],params=params,json={'full_name':'Builtin updated'})
    assert response.status_code == 200,response.text
    assert client.delete('/users/'+ids['root']).status_code == 403
    assert client.patch('/users/'+ids['builtin'],params=params,json={'is_superuser':False}).status_code==200
    assert client.patch('/users/'+ids['root'],json={'is_active':False}).status_code==400


def test_root_archives_foreign_user_and_preserves_other_memberships(management):
    client, session, ids, *_=management
    assert client.delete('/users/'+ids['target'],params={'tenant_id':ids['b']}).status_code==403
    assert session.get(User,UUID(ids['target'])).archived_at is None
    assert client.delete('/users/'+ids['shared'],params={'tenant_id':ids['b']}).status_code==204
    assert session.get(User,UUID(ids['shared'])).is_active
    with PlatformGlobalUnitOfWork(session):
        from sqlmodel import select
        rows=session.exec(select(TenantMembership).where(TenantMembership.user_id==UUID(ids['shared']))).all()
        assert {str(row.tenant_id): row.is_active for row in rows}=={ids['a']:True,ids['b']:False}
    assert [event['tenant_id'] for event in management[-1]]==[UUID(ids['b'])]


def test_root_can_reset_mfa_in_selected_tenant(management):
    client, _, ids, *_ = management
    response = client.post('/users/'+ids['target']+'/mfa/reset', params={'tenant_id':ids['b']})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("kind", ["root", "channel", "tenant_role", "disabled_tenant_role"])
def test_administrators_cannot_be_deleted_even_by_root(management, kind):
    from app.api.routes.users import protected_administrator_ids
    from app.modules.esop.infrastructure.models import ChannelAdmin
    client, session, ids, *_ = management
    target_id = UUID(ids['shared'])
    user = session.get(User, target_id)
    if kind == "root":
        user.is_superuser = True
        session.add(user)
    elif kind == "channel":
        from uuid import uuid4
        session.add(ChannelAdmin(channel_id=uuid4(), user_id=target_id))
    else:
        role = management[5][1]
        role.code = "super_admin"
        role.is_system = True
        role.is_active = kind != "disabled_tenant_role"
        session.add(role)
        session.add(UserRole(user_id=target_id, tenant_id=UUID(ids['b']), role_id=role.id))
    session.commit()
    with PlatformGlobalUnitOfWork(session):
        assert target_id in protected_administrator_ids(session=session, user_ids={target_id})
    response = client.delete('/users/'+str(target_id), params={'tenant_id':ids['b']})
    assert response.status_code == 403, response.text
    assert '不允许删除' in response.json()['detail']
    assert session.get(User, target_id).archived_at is None
    assert not management[-1]


def test_user_list_marks_protected_accounts_and_leaves_regular_user_deletable(management):
    client, _, ids, *_ = management
    response = client.get('/users')
    assert response.status_code == 200, response.text
    rows = response.json()['items']
    assert all(row['deletion_protected'] for row in rows if row['id'] in {ids['root'], ids['builtin'], ids['target']})
    assert all(not row['deletion_protected'] for row in rows if row['id'] == ids['shared'])


def test_protected_user_cannot_be_anonymized(management):
    client, session, ids, *_ = management
    response = client.post('/users/'+ids['root']+'/anonymize', json={'reason':'test'})
    assert response.status_code == 403, response.text
    assert session.get(User, UUID(ids['root'])).anonymized_at is None


def test_unbundled_module_is_not_queried(management, monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.users import protected_administrator_ids
    from app.modules import access, registry
    _, session, ids, *_ = management
    monkeypatch.setattr(access, 'get_runtime_manifest', lambda: SimpleNamespace(modules=[SimpleNamespace(code='platform')]))
    def forbidden(*_args):
        raise AssertionError('unbundled provider queried')
    monkeypatch.setattr(registry, 'get_module_definitions', lambda: {'esop':SimpleNamespace(code='esop', protected_user_ids=forbidden)})
    assert not protected_administrator_ids(session=session, user_ids={UUID(ids['shared'])})
