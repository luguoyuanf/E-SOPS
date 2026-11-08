import importlib.util
import secrets
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app import crud
from app.api.routes.tenants import create_tenant
from app.core.security import get_password_hash
from app.platform.core.identity_models import User, UserCreate, UserUpdate
from app.platform.core.tenancy_models import (
    Tenant,
    TenantCreate,
    TenantInitializationTemplate,
    TenantMembership,
    TenantPlan,
)
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)


def fixture_engine():
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    return engine


def test_username_normalization_and_validation():
    assert (
        UserCreate(
            email="valid@example.com", password="test-password", username=" TangYun "
        ).username
        == "tangyun"
    )
    assert UserUpdate(username="").username is None
    assert UserUpdate().model_dump(exclude_unset=True) == {}
    for username in ["email@example.com", "has space", "-invalid", "a" * 65, "中文"]:
        with pytest.raises(ValidationError):
            UserUpdate(username=username)


@pytest.mark.parametrize("username", ["has space", "-invalid", "a" * 65, "中文"])
def test_tenant_account_rejects_invalid_usernames(username):
    with pytest.raises(ValidationError):
        TenantCreate(code="invalid", name="Invalid", username=username)


def test_username_and_email_auth_share_identity_and_ignore_full_name():
    password = secrets.token_urlsafe(18)
    with Session(fixture_engine()) as session:
        user = crud.create_user(
            session=session,
            user_create=UserCreate(
                email="actual@example.com",
                password=password,
                username=" TangYun ",
                full_name="another-alias",
            ),
        )
        assert user.username == "tangyun"
        for identifier in ["tangyun", " TangYun ", "actual@example.com"]:
            assert (
                crud.authenticate(
                    session=session, email=identifier, password=password
                ).id
                == user.id
            )
        assert (
            crud.authenticate(session=session, email="another-alias", password=password)
            is None
        )
        assert (
            crud.authenticate(
                session=session, email="tangyun", password="wrong-password"
            )
            is None
        )
        legacy = crud.create_user(
            session=session,
            user_create=UserCreate(email="legacy@example.com", password=password),
        )
        assert legacy.username is None
        assert (
            crud.authenticate(
                session=session, email="legacy@example.com", password=password
            ).id
            == legacy.id
        )
        with pytest.raises(HTTPException) as error:
            crud.create_user(
                session=session,
                user_create=UserCreate(
                    email="duplicate@example.com", password=password, username="TANGYUN"
                ),
            )
        assert error.value.status_code == 409
        with pytest.raises(HTTPException) as error:
            crud.update_user(
                session=session, db_user=legacy, user_in=UserUpdate(username="tangyun")
            )
        assert error.value.status_code == 409
        crud.update_user(
            session=session, db_user=user, user_in=UserUpdate(username=None)
        )
        assert (
            crud.authenticate(session=session, email="tangyun", password=password)
            is None
        )
        assert (
            crud.authenticate(
                session=session, email="actual@example.com", password=password
            ).id
            == user.id
        )


def test_database_unique_constraint_and_controlled_conflict_response():
    with Session(fixture_engine()) as session:
        session.add(
            User(email="a@example.com", hashed_password="unused", username="same")
        )
        session.commit()
        session.add(
            User(email="b@example.com", hashed_password="unused", username="same")
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    import asyncio

    from app.main import integrity_exception_handler

    response = asyncio.run(integrity_exception_handler(None, None))
    assert response.status_code == 409 and b"CONFLICT" in response.body


@pytest.mark.parametrize("account_only", [False, True])
def test_initial_tenant_admin_username_preserves_membership_and_global_uniqueness(account_only, monkeypatch):
    # The SQLite fixture contains Platform tables only, so tenant provisioning
    # must use the Base Edition rather than the caller's ERP environment.
    from app.modules.manifest import build_manifest

    manifest = build_manifest(edition="base")
    monkeypatch.setattr("app.modules.access.get_runtime_manifest", lambda: manifest)
    password = secrets.token_urlsafe(18)
    with Session(fixture_engine()) as session:
        plan = TenantPlan(code="fixture", name="Fixture")
        template = TenantInitializationTemplate(code="fixture", name="Fixture")
        parent = Tenant(code="parent", name="Parent")
        root = User(
            email="root@example.com",
            hashed_password=get_password_hash(password),
            is_superuser=True,
        )
        session.add_all([plan, template, parent, root])
        session.commit()
        session.info["platform_tenant_id"] = parent.id
        created = create_tenant(
            session=session,
            current_user=root,
            tenant_in=TenantCreate(
                code="test",
                name="Test",
                plan_id=plan.id,
                initialization_template_id=template.id,
                username=" TangYun " if account_only else "tangyun@test.example.com",
                password=password,
                admin_username=None if account_only else " TangYun ",
            ),
        )
        admin = crud.authenticate(session=session, email="tangyun", password=password)
        assert (
            admin
            and (admin.email.endswith("@accounts.example.com") if account_only
                 else admin.email == "tangyun@test.example.com")
            and not admin.is_superuser
        )
        membership = session.exec(
            select(TenantMembership).where(
                TenantMembership.user_id == admin.id,
                TenantMembership.tenant_id == created.id,
            )
        ).one()
        assert not session.exec(
            select(TenantMembership).where(
                TenantMembership.user_id == root.id,
                TenantMembership.tenant_id == created.id,
            )
        ).first()
        assert created.admin_username == "tangyun"
        assert membership.is_active
        from starlette.requests import Request

        from app.api.routes.login import create_login_token

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/fixture",
                "headers": [],
                "client": ("127.0.0.1", 1),
            }
        )
        with Session(session.get_bind()) as login_session:
            authenticated = crud.authenticate(
                session=login_session, email="tangyun", password=password
            )
            with pytest.raises(HTTPException) as wrong_tenant:
                create_login_token(
                    session=login_session,
                    request=request,
                    user=authenticated,
                    tenant_id=parent.id,
                )
            assert wrong_tenant.value.status_code == 403
            token = create_login_token(
                session=login_session,
                request=request,
                user=authenticated,
                tenant_id=created.id,
            )
            assert token.tenant_id == created.id
        with pytest.raises(HTTPException) as error:
            create_tenant(
                session=session,
                current_user=root,
                tenant_in=TenantCreate(
                    code="other",
                    name="Other",
                    plan_id=plan.id,
                    initialization_template_id=template.id,
                    username="other@test.example.com",
                    password=password,
                    admin_username="TANGYUN",
                ),
            )
        assert error.value.status_code == 409
        with pytest.raises(HTTPException) as error:
            create_tenant(
                session=session,
                current_user=root,
                tenant_in=TenantCreate(
                    code="noadmin", name="No admin", admin_username="unused"
                ),
            )
        assert error.value.status_code == 400


@pytest.mark.parametrize(
    "filename",
    [
        "mysql_versions/mysql_platform_0002_username.py",
        "versions/d8f2b6a0c4e8_optional_login_username.py",
    ],
)
def test_new_revision_preserves_existing_email_accounts_and_roundtrips(filename):
    path = Path(__file__).resolve().parents[1] / "app/alembic" / filename
    spec = importlib.util.spec_from_file_location("username_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE user(id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO user(email) VALUES ('existing@example.com')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert connection.execute(
                text("SELECT email, username FROM user")
            ).one() == ("existing@example.com", None)
            connection.execute(
                text("INSERT INTO user(email) VALUES ('another@example.com')")
            )
            module.downgrade()
            assert connection.scalar(text("SELECT COUNT(*) FROM user")) == 2
