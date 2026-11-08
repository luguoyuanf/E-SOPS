"""Every platform management list must include both fixture tenants for root."""

import importlib
from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_platform_read_tenant
from app.core.clock import get_datetime_utc
from app.core.tenancy import TenantContext
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import Tenant
from app.platform.migration_metadata import (
    PLATFORM_MODEL_GROUPS,
    import_platform_model_groups,
)

CASES = [
    (
        "app.api.routes.departments",
        "read_departments",
        "app.platform.core.authorization_models",
        "Department",
    ),
    (
        "app.api.routes.posts",
        "read_posts",
        "app.platform.core.authorization_models",
        "Post",
    ),
    (
        "app.api.routes.notices",
        "read_notices",
        "app.platform.core.configuration_models",
        "Notice",
    ),
    (
        "app.api.routes.site_messages",
        "read_site_message_templates",
        "app.platform.core.configuration_models",
        "SiteMessageTemplate",
    ),
    (
        "app.api.routes.site_messages",
        "read_site_messages",
        "app.platform.core.configuration_models",
        "UserMessage",
    ),
    (
        "app.api.routes.social",
        "read_social_clients",
        "app.platform.core.identity_models",
        "SocialClient",
    ),
    (
        "app.api.routes.social",
        "read_social_users",
        "app.platform.core.identity_models",
        "SocialUser",
    ),
    (
        "app.api.routes.oauth2",
        "read_oauth2_clients",
        "app.platform.core.identity_models",
        "OAuth2Client",
    ),
    (
        "app.api.routes.oauth2",
        "read_oauth2_tokens",
        "app.platform.core.identity_models",
        "OAuth2AccessToken",
    ),
    (
        "app.platform.infra.files_router",
        "read_files",
        "app.platform.infra.file_models",
        "FileAsset",
    ),
    (
        "app.platform.infra.logs_router",
        "read_login_logs",
        "app.platform.infra.audit_models",
        "LoginLog",
    ),
    (
        "app.platform.infra.logs_router",
        "read_operation_logs",
        "app.platform.infra.audit_models",
        "OperationLog",
    ),
    (
        "app.platform.infra.mail_router",
        "read_mail_accounts",
        "app.platform.infra.mail_models",
        "MailAccount",
    ),
    (
        "app.platform.infra.mail_router",
        "read_mail_templates",
        "app.platform.infra.mail_models",
        "MailTemplate",
    ),
    (
        "app.platform.infra.mail_router",
        "read_mail_logs",
        "app.platform.infra.mail_models",
        "MailLog",
    ),
    (
        "app.platform.infra.sms_router",
        "read_sms_channels",
        "app.platform.infra.sms_models",
        "SmsChannel",
    ),
    (
        "app.platform.infra.sms_router",
        "read_sms_templates",
        "app.platform.infra.sms_models",
        "SmsTemplate",
    ),
    (
        "app.platform.infra.sms_router",
        "read_sms_logs",
        "app.platform.infra.sms_models",
        "SmsLog",
    ),
]


@pytest.mark.parametrize("route_module,function_name,model_module,model_name", CASES)
def test_root_management_lists_are_global_with_explicit_tenant_filter(
    route_module, function_name, model_module, model_name
):
    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    model = getattr(importlib.import_module(model_module), model_name)
    function = getattr(importlib.import_module(route_module), function_name)
    with Session(engine) as session:
        tenants = [
            Tenant(code=f"T{index}", name=f"Tenant {index}") for index in range(2)
        ]
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        session.add_all([*tenants, root])
        session.flush()
        rows = []
        for index, tenant in enumerate(tenants):
            values = {
                name: f"test{index}"
                for name, field in model.model_fields.items()
                if field.is_required()
            }
            values.update(tenant_id=tenant.id)
            for name in ("size", "status_code", "duration_ms"):
                if name in values:
                    values[name] = 1
            if "expires_at" in values:
                values["expires_at"] = get_datetime_utc() + timedelta(hours=1)
            if "user_id" in values:
                values["user_id"] = root.id
            for name in ("email", "from_email", "to_email"):
                if name in values:
                    values[name] = "fixture@example.com"
            if model_name == "FileAsset":
                values["sha256"] = "a" * 64
            if model_name == "LoginLog":
                values["status"] = "success"
            if model_name == "OperationLog":
                values.update(method="GET", path="/fixture")
            row = model(**values)
            rows.append(row)
            session.add(row)
        session.commit()
        context = TenantContext(
            tenant_id=tenants[0].id, tenant_code=tenants[0].code, user_id=root.id
        )
        scope = get_platform_read_tenant(session, root, context, None)
        next(scope)
        result = function(session=session, read_tenant=None)
        assert {item.tenant_id for item in result.items} == {
            tenant.id for tenant in tenants
        }
        with pytest.raises(StopIteration):
            next(scope)
        scope = get_platform_read_tenant(session, root, context, tenants[1].id)
        next(scope)
        result = function(session=session, read_tenant=tenants[1].id)
        assert len(result.items) == 1 and result.items[0].tenant_id == tenants[1].id
        with pytest.raises(StopIteration):
            next(scope)


def test_global_private_file_download_requires_verified_root(monkeypatch):
    from fastapi import HTTPException

    from app.platform.infra import files_router
    from app.platform.infra.file_models import FileAsset

    import_platform_model_groups()
    engine = create_engine("sqlite://")
    names = {name for group in PLATFORM_MODEL_GROUPS for name in group.tables}
    SQLModel.metadata.create_all(
        engine, tables=[SQLModel.metadata.tables[name] for name in names]
    )
    with Session(engine) as session:
        a, b = Tenant(code="a", name="A"), Tenant(code="b", name="B")
        root = User(
            email="root@example.com", hashed_password="unused", is_superuser=True
        )
        ordinary = User(email="ordinary@example.com", hashed_password="unused")
        file = FileAsset(
            tenant_id=b.id,
            original_name="fixture.txt",
            stored_name="fixture.txt",
            size=1,
            sha256="a" * 64,
            storage_path="fixture",
            is_public=False,
        )
        session.add_all([a, b, root, ordinary, file])
        session.commit()
        monkeypatch.setattr(
            files_router,
            "get_file_download_response",
            lambda **kwargs: kwargs["tenant_id"],
        )
        assert files_router.download_file(session, root, a.id, file.id) == b.id
        with pytest.raises(HTTPException) as error:
            files_router.download_file(session, ordinary, a.id, file.id)
        assert error.value.status_code == 403
