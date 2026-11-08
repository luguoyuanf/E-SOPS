import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api import deps as _deps
from app.core.data_permissions import build_owner_data_scope_filter_for_principal
from app.platform.alarm_type_directory import SqlAlarmTypeDirectory
from app.platform.channel_customer import (
    TenantSummary as ChannelCustomerTenantSummary,
)
from app.platform.channel_customer import (
    create_channel_customer_tenant,
    get_channel_customer_tenants,
    resolve_channel_customer_code,
)
from app.platform.infra.file_directory import SqlFileAssetDirectory, store_tenant_file
from app.platform.public_api.alarm_types import AlarmTypeDirectory
from app.platform.public_api.files import FileAssetDirectory, FileAssetSummary
from app.platform.public_api.tenants import TenantDirectory
from app.platform.public_api.users import UserDirectory
from app.platform.storage_provisioning import (
    ensure_esop_storage_account,
    ensure_paid_activation_storage,
)
from app.platform.tenant_directory import SqlTenantDirectory
from app.platform.user_directory import SqlUserDirectory
from app.platform.view_access import issue_view_key, resolve_view_key


@dataclass(frozen=True)
class Principal:
    """Stable request identity exposed to business module routes."""

    id: uuid.UUID
    is_superuser: bool


@dataclass(frozen=True)
class TenantContext:
    """Stable tenant selection exposed to business module routes."""

    tenant_id: uuid.UUID
    tenant_code: str
    user_id: uuid.UUID


def get_current_principal(current_user: _deps.CurrentUser) -> Principal:
    return Principal(id=current_user.id, is_superuser=current_user.is_superuser)


def get_current_tenant_context(tenant_context: _deps.CurrentTenant) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_context.tenant_id,
        tenant_code=tenant_context.tenant_code,
        user_id=tenant_context.user_id,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
CurrentTenant = Annotated[TenantContext, Depends(get_current_tenant_context)]
SessionDep = _deps.SessionDep


def get_file_asset_directory(session: SessionDep) -> FileAssetDirectory:
    return SqlFileAssetDirectory(session)


FileAssetDirectoryDep = Annotated[FileAssetDirectory, Depends(get_file_asset_directory)]


def get_alarm_type_directory(session: SessionDep) -> AlarmTypeDirectory:
    return SqlAlarmTypeDirectory(session)


AlarmTypeDirectoryDep = Annotated[AlarmTypeDirectory, Depends(get_alarm_type_directory)]


def preview_authorized_file(
    *, session: SessionDep, tenant_id: uuid.UUID, file_id: uuid.UUID
) -> FileResponse | StreamingResponse:
    """Use only after a module has checked access to the file reference."""
    return SqlFileAssetDirectory(session).preview_response(
        tenant_id=tenant_id, file_id=file_id
    )


def get_authorized_file(
    *, session: SessionDep, tenant_id: uuid.UUID, file_id: uuid.UUID,
) -> FileAssetSummary | None:
    """Caller must authorize the persisted business reference before switching file scope."""
    from app.platform.tenant_uow import PlatformTenantUnitOfWork

    with PlatformTenantUnitOfWork(session, tenant_id, privileged=True):
        return SqlFileAssetDirectory(session).get_accessible_file(
            tenant_id=tenant_id, file_id=file_id
        )


def download_authorized_file(
    *, session: SessionDep, tenant_id: uuid.UUID, file_id: uuid.UUID,
) -> FileResponse | StreamingResponse:
    """Caller must authorize the persisted business reference before switching file scope."""
    from urllib.parse import quote

    from app.platform.tenant_uow import PlatformTenantUnitOfWork

    with PlatformTenantUnitOfWork(session, tenant_id, privileged=True):
        directory = SqlFileAssetDirectory(session)
        asset = directory.get_accessible_file(tenant_id=tenant_id, file_id=file_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="File not found")
        response = directory.preview_response(tenant_id=tenant_id, file_id=file_id)
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(asset.original_name, safe='')}"
        return response


def upload_authorized_file(
    *,
    session: SessionDep,
    tenant_id: uuid.UUID,
    uploader_id: uuid.UUID,
    file: UploadFile,
    allowed_extensions: set[str] | None = None,
    max_size_mb: int | None = None,
) -> uuid.UUID:
    """Store a private file after a business module has checked upload permission."""
    asset = store_tenant_file(
        session=session,
        tenant_id=tenant_id,
        uploader_id=uploader_id,
        file=file,
        is_public=False,
        allowed_extensions=allowed_extensions,
        max_size_mb=max_size_mb,
    )
    return asset.id


def get_user_directory(session: SessionDep) -> UserDirectory:
    return SqlUserDirectory(session)


UserDirectoryDep = Annotated[UserDirectory, Depends(get_user_directory)]


def authenticate_terminal_staff(
    *,
    session: SessionDep,
    request: Request,
    tenant_id: uuid.UUID,
    username: str,
    password: str,
) -> dict[str, str]:
    """Issue a tenant-scoped platform session after device authentication.

    The caller must first validate its device credential and resolve tenant_id.
    """
    from app import crud
    from app.api.routes.login import (
        clear_failed_login_attempts,
        create_login_token,
        is_login_rate_limited,
        record_failed_login_attempt,
    )
    from app.core.tenancy import get_active_tenant_membership

    identifier = username.strip().lower()
    if is_login_rate_limited(request, identifier):
        raise HTTPException(status_code=429, detail="Too many login attempts")
    account = (
        crud.get_user_by_email(session=session, email=identifier)
        if "@" in identifier
        else crud.get_user_by_username(session=session, username=identifier, tenant_id=tenant_id)
    )
    user = crud.authenticate(session=session, email=identifier, password=password, tenant_id=tenant_id)
    membership = (
        get_active_tenant_membership(
            session=session, user_id=account.id, tenant_id=tenant_id,
        )
        if account is not None
        else None
    )
    failure = None
    if account is None or membership is None:
        failure = "当前租户下不存在该账号，或账号未获租户访问授权"
    elif not account.is_active:
        failure = "账号已停用，请联系管理员"
    elif user is None:
        failure = "账号或密码错误，请重新输入"
    elif user.mfa_enabled:
        failure = "该账号已启用多重验证，暂不支持终端密码登录，请联系管理员"
    if failure:
        if record_failed_login_attempt(request, identifier):
            raise HTTPException(status_code=429, detail="Too many login attempts")
        raise HTTPException(status_code=401, detail=failure)
    assert user is not None
    clear_failed_login_attempts(request, identifier)
    token = create_login_token(
        session=session,
        request=request,
        user=user,
        tenant_id=tenant_id,
        client_kind="terminal",
    )
    return {
        **get_terminal_staff_profile(session=session, tenant_id=tenant_id, user_id=user.id),
        "accessToken": token.access_token,
    }


def get_terminal_staff_profile(*, session: SessionDep, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    """Read the current tenant membership and posts for a terminal staff badge."""
    from sqlmodel import select

    from app.core.tenancy import get_active_tenant_membership
    from app.platform.core.authorization_models import Post, UserPost
    from app.platform.core.identity_models import User
    from app.platform.tenant_uow import PlatformTenantUnitOfWork

    with PlatformTenantUnitOfWork(session, tenant_id):
        user = session.get(User, user_id)
        membership = get_active_tenant_membership(session=session, user_id=user_id, tenant_id=tenant_id)
        if user is None or membership is None or not user.is_active:
            raise HTTPException(status_code=403, detail="Staff is not active in this tenant")
        post_names = session.exec(
            select(Post.name).join(UserPost, UserPost.post_id == Post.id)
            .where(UserPost.user_id == user_id, UserPost.tenant_id == tenant_id,
                   Post.tenant_id == tenant_id)
            .order_by(Post.sort, Post.name)
        ).all()
        return {
            "post": "、".join(post_names),
            "phoneNumber": user.mobile or "",
            "hiredate": membership[0].hire_date.isoformat() if membership[0].hire_date else "",
            "avatar": user.avatar_url or "",
            "userId": str(user.id),
            "username": user.username or user.email or "",
            "name": user.full_name or user.username or user.email or "",
        }


def get_tenant_directory(session: SessionDep) -> TenantDirectory:
    return SqlTenantDirectory(session)


TenantDirectoryDep = Annotated[TenantDirectory, Depends(get_tenant_directory)]


def build_owner_data_scope_filter(
    *,
    session: SessionDep,
    current_principal: Principal,
    tenant_id: uuid.UUID,
    owner_id_column: Any,
) -> Any:
    return build_owner_data_scope_filter_for_principal(
        session=session,
        principal_id=current_principal.id,
        is_superuser=current_principal.is_superuser,
        tenant_id=tenant_id,
        owner_id_column=owner_id_column,
    )


def normalize_pagination(
    *, page: int, page_size: int, max_page_size: int = 100
) -> tuple[int, int]:
    return _deps.normalize_pagination(
        page=page,
        page_size=page_size,
        max_page_size=max_page_size,
    )


def require_any_module_access(module_code: str, permission_codes: tuple[str, ...]):
    return _deps.require_any_module_access(module_code, permission_codes)


def require_module_access(module_code: str, permission_code: str):
    return _deps.require_module_access(module_code, permission_code)


def require_resolved_tenant_module_access(*, session: SessionDep, tenant_id: uuid.UUID, module_code: str) -> None:
    """Check a module after a trusted client/device resolver has identified its tenant."""
    from app.modules.access import evaluate_module_access
    from app.platform.tenant_uow import PlatformTenantUnitOfWork

    existing = session.info.get("platform_tenant_id")
    if existing is not None and existing != tenant_id:
        raise HTTPException(status_code=403, detail="Client and session tenant differ")
    with PlatformTenantUnitOfWork(session, tenant_id):
        decision = evaluate_module_access(session=session, tenant_id=tenant_id, module_code=module_code)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.error_code)


__all__ = [
    "issue_view_key",
    "resolve_view_key",
    "require_resolved_tenant_module_access",
    "CurrentTenant",
    "CurrentPrincipal",
    "SessionDep",
    "FileAssetDirectoryDep",
    "AlarmTypeDirectoryDep",
    "preview_authorized_file",
    "download_authorized_file",
    "get_authorized_file",
    "upload_authorized_file",
    "UserDirectoryDep",
    "TenantDirectoryDep",
    "Principal",
    "TenantContext",
    "build_owner_data_scope_filter",
    "normalize_pagination",
    "require_module_access",
    "require_any_module_access",
    "ensure_esop_storage_account",
    "ensure_paid_activation_storage",
    "ChannelCustomerTenantSummary",
    "create_channel_customer_tenant",
    "get_channel_customer_tenants",
    "resolve_channel_customer_code",
]
