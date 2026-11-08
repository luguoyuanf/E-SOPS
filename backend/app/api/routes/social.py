import unicodedata
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, or_, select

from app.api.deps import (
    CurrentTenant,
    CurrentUser,
    PlatformReadTenant,
    SessionDep,
    normalize_pagination,
    require_permission,
)
from app.core.cache import redis_cache
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.mfa import decrypt_totp_secret, encrypt_secret, verify_totp_code
from app.core.security import verify_password
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.identity_models import (
    EnterpriseOidcIdentity,
    SocialClient,
    SocialClientCreate,
    SocialClientPublic,
    SocialClientsPublic,
    SocialClientUpdate,
    SocialUser,
    SocialUserBind,
    SocialUserPublic,
    SocialUsersPublic,
    User,
)
from app.platform.core.tenancy_models import TenantMembership

router = APIRouter(prefix="/social", tags=["social"])


class GoogleConfigUpdate(BaseModel):
    enabled: bool
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str | None = Field(default=None, max_length=255)
    current_password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, max_length=32)


def require_google_platform_admin(current_user: CurrentUser, tenant: CurrentTenant) -> None:
    if settings.APP_EDITION != "esop":
        raise HTTPException(status_code=404, detail="Google configuration unavailable")
    if not current_user.is_superuser or tenant.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(status_code=403, detail="Google configuration requires platform administrator")


def google_config_row(session: SessionDep) -> SocialClient | None:
    return session.exec(select(SocialClient).where(
        SocialClient.tenant_id == DEFAULT_TENANT_ID,
        SocialClient.social_type == "google",
        SocialClient.user_type == "platform",
    )).first()


@router.get("/google/config")
def read_google_config(session: SessionDep, current_user: CurrentUser, tenant: CurrentTenant) -> dict[str, Any]:
    require_google_platform_admin(current_user, tenant)
    row = google_config_row(session)
    return {
        "enabled": row.is_active if row else settings.ENTERPRISE_OIDC_ENABLED,
        "client_id": row.client_id if row else settings.ENTERPRISE_OIDC_CLIENT_ID or "",
        "client_secret_configured": bool(row.client_secret if row else settings.ENTERPRISE_OIDC_CLIENT_SECRET),
        "redirect_uri": (row.agent_id if row else settings.ENTERPRISE_OIDC_REDIRECT_URI) or "",
    }


@router.put("/google/config")
def update_google_config(session: SessionDep, current_user: CurrentUser, tenant: CurrentTenant, body: GoogleConfigUpdate) -> dict[str, Any]:
    require_google_platform_admin(current_user, tenant)
    attempts = redis_cache.incr(redis_cache.build_key("google-config", "reauth", str(current_user.id)), ttl_seconds=300)
    if attempts is None:
        raise HTTPException(status_code=503, detail="Google configuration verification unavailable")
    if attempts > 5:
        raise HTTPException(status_code=429, detail="Too many verification attempts")
    valid, _ = verify_password(body.current_password, current_user.hashed_password)
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid current password")
    if current_user.mfa_enabled:
        try:
            secret = decrypt_totp_secret(current_user.mfa_secret_encrypted or "")
        except ValueError:
            raise HTTPException(status_code=403, detail="MFA verification required") from None
        if not body.mfa_code or not verify_totp_code(secret=secret, code=body.mfa_code):
            raise HTTPException(status_code=403, detail="MFA verification required")
    client_id = body.client_id.strip()
    if not client_id.endswith(".apps.googleusercontent.com") or not client_id[:-len(".apps.googleusercontent.com")]:
        raise HTTPException(status_code=400, detail="Invalid Google client ID")
    from app.platform.infra.google_oauth_config import lock_google_config_anchor

    lock_google_config_anchor(session)
    row = google_config_row(session)
    replacement = (body.client_secret or "").strip()
    if replacement == "******":
        replacement = ""
    if row is None:
        if not replacement:
            replacement = settings.ENTERPRISE_OIDC_CLIENT_SECRET or ""
        if not replacement:
            raise HTTPException(status_code=400, detail="Google client secret required")
        redirect = settings.ENTERPRISE_OIDC_REDIRECT_URI or f"{settings.FRONTEND_HOST.rstrip('/')}{settings.API_V1_STR}/login/enterprise-oidc/callback"
        row = SocialClient(tenant_id=DEFAULT_TENANT_ID, name="Google", social_type="google", user_type="platform", client_id=client_id, client_secret=encrypt_secret(replacement), agent_id=redirect, is_active=body.enabled, remark=uuid.uuid4().hex)
    else:
        row.client_id = client_id
        row.is_active = body.enabled
        row.remark = uuid.uuid4().hex
        if replacement:
            row.client_secret = encrypt_secret(replacement)
        row.updated_at = get_datetime_utc()
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Google configuration changed concurrently") from exc
    return read_google_config(session=session, current_user=current_user, tenant=tenant)


@router.get("/google/bindings", dependencies=[Depends(require_permission("system:social-user:list"))])
def read_google_bindings(session: SessionDep, read_tenant: PlatformReadTenant, current_user: CurrentUser, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    if settings.APP_EDITION != "esop":
        raise HTTPException(status_code=404, detail="Google bindings unavailable")
    if read_tenant is None and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Forbidden")
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    filters = [EnterpriseOidcIdentity.provider == "google"]
    if read_tenant is not None:
        filters.append(EnterpriseOidcIdentity.tenant_id == read_tenant)
    total = session.exec(select(func.count()).select_from(EnterpriseOidcIdentity).where(*filters)).one()
    rows = session.exec(select(EnterpriseOidcIdentity).where(*filters).order_by(col(EnterpriseOidcIdentity.created_at).desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": r.id, "tenant_id": r.tenant_id, "user_id": r.user_id, "created_at": r.created_at} for r in rows], "total": total, "page": page, "page_size": page_size}


def mask_social_client(client: SocialClient) -> SocialClientPublic:
    data = SocialClientPublic.model_validate(client)
    if data.client_secret:
        data.client_secret = "******"
    return data


def is_google_type(value: str | None) -> bool:
    return unicodedata.normalize("NFKC", value or "").strip().casefold() == "google"


def reject_google_type(value: str | None) -> None:
    if is_google_type(value):
        raise HTTPException(status_code=403, detail="Google configuration uses the platform-only endpoint")


def ensure_social_client_unique(
    *,
    session: SessionDep,
    tenant_id: uuid.UUID,
    social_type: str,
    user_type: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(SocialClient).where(
        SocialClient.tenant_id == tenant_id,
        SocialClient.social_type == social_type,
        SocialClient.user_type == user_type,
    )
    if exclude_id:
        statement = statement.where(SocialClient.id != exclude_id)
    if session.exec(statement).first():
        raise HTTPException(
            status_code=409,
            detail="Social client for this platform and user type already exists",
        )


def get_social_client_or_404(
    *, session: SessionDep, tenant_id: uuid.UUID | None, client_id: uuid.UUID
) -> SocialClient:
    client = session.exec(
        select(SocialClient).where(
            SocialClient.id == client_id,
            (SocialClient.tenant_id == tenant_id) if tenant_id else True,
        )
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Social client not found")
    return client


def get_social_user_or_404(
    *, session: SessionDep, tenant_id: uuid.UUID | None, social_user_id: uuid.UUID
) -> SocialUser:
    social_user = session.exec(
        select(SocialUser).where(
            SocialUser.id == social_user_id,
            (SocialUser.tenant_id == tenant_id) if tenant_id else True,
        )
    ).first()
    if not social_user:
        raise HTTPException(status_code=404, detail="Social user not found")
    if is_google_type(social_user.type):
        raise HTTPException(status_code=404, detail="Social user not found")
    return social_user


def to_social_user_public(
    *, session: SessionDep, social_user: SocialUser
) -> SocialUserPublic:
    data = SocialUserPublic.model_validate(social_user)
    if social_user.user_id:
        user = session.get(User, social_user.user_id)
        if user:
            data.user_email = user.email
            data.user_full_name = user.full_name
    return data


@router.get(
    "/clients",
    dependencies=[Depends(require_permission("system:social-client:list"))],
    response_model=SocialClientsPublic,
)
def read_social_clients(
    session: SessionDep,
    read_tenant: PlatformReadTenant,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    social_type: str | None = None,
    user_type: str | None = None,
    is_active: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    filters = [SocialClient.tenant_id == read_tenant] if read_tenant else []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                col(SocialClient.name).ilike(pattern),
                col(SocialClient.client_id).ilike(pattern),
                col(SocialClient.remark).ilike(pattern),
            )
        )
    if social_type:
        filters.append(SocialClient.social_type == social_type)
    if user_type:
        filters.append(SocialClient.user_type == user_type)
    if is_active is not None:
        filters.append(SocialClient.is_active == is_active)

    if created_from is not None:
        filters.append(SocialClient.created_at >= created_from)
    if created_to is not None:
        filters.append(SocialClient.created_at <= created_to)
    count_statement = select(func.count()).select_from(SocialClient)
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(SocialClient)
    if filters:
        statement = statement.where(*filters)
    clients = session.exec(
        statement.order_by(col(SocialClient.updated_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SocialClientsPublic(
        items=[mask_social_client(client) for client in clients],
        total=count,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/clients",
    dependencies=[Depends(require_permission("system:social-client:create"))],
    response_model=SocialClientPublic,
)
def create_social_client(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    client_in: SocialClientCreate,
) -> SocialClientPublic:
    reject_google_type(client_in.social_type)
    ensure_social_client_unique(
        session=session,
        tenant_id=tenant_context.tenant_id,
        social_type=client_in.social_type,
        user_type=client_in.user_type,
    )
    client = SocialClient.model_validate(
        client_in,
        update={"tenant_id": tenant_context.tenant_id},
    )
    if client.client_secret:
        client.client_secret = encrypt_secret(client.client_secret)
    session.add(client)
    session.commit()
    session.refresh(client)
    return mask_social_client(client)


@router.get(
    "/clients/{client_id}",
    dependencies=[Depends(require_permission("system:social-client:list"))],
    response_model=SocialClientPublic,
)
def read_social_client(
    read_tenant: PlatformReadTenant,
    session: SessionDep,
    client_id: uuid.UUID,
) -> SocialClientPublic:
    client = get_social_client_or_404(
        session=session,
        tenant_id=read_tenant,
        client_id=client_id,
    )
    return mask_social_client(client)


@router.patch(
    "/clients/{client_id}",
    dependencies=[Depends(require_permission("system:social-client:update"))],
    response_model=SocialClientPublic,
)
def update_social_client(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    current_user: CurrentUser,
    client_id: uuid.UUID,
    client_in: SocialClientUpdate,
) -> SocialClientPublic:
    client = get_social_client_or_404(
        session=session,
        tenant_id=tenant_context.tenant_id,
        client_id=client_id,
    )
    reject_google_type(client.social_type)
    reject_google_type(client_in.social_type)

    update_data = client_in.model_dump(exclude_unset=True)
    current_password = update_data.pop("current_password", None)
    if update_data.get("client_secret") == "******":
        update_data.pop("client_secret")
    elif update_data.get("client_secret"):
        if not current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        verified, _ = verify_password(current_password, current_user.hashed_password)
        if not verified:
            raise HTTPException(status_code=400, detail="Incorrect password")
        update_data["client_secret"] = encrypt_secret(update_data["client_secret"])
    next_social_type = update_data.get("social_type", client.social_type)
    next_user_type = update_data.get("user_type", client.user_type)
    if next_social_type != client.social_type or next_user_type != client.user_type:
        ensure_social_client_unique(
            session=session,
            tenant_id=tenant_context.tenant_id,
            social_type=next_social_type,
            user_type=next_user_type,
            exclude_id=client.id,
        )
    client.sqlmodel_update(update_data)
    client.updated_at = get_datetime_utc()
    session.add(client)
    session.commit()
    session.refresh(client)
    return mask_social_client(client)


@router.delete(
    "/clients/{client_id}",
    dependencies=[Depends(require_permission("system:social-client:delete"))],
    status_code=204,
)
def delete_social_client(
    tenant_context: CurrentTenant,
    session: SessionDep,
    client_id: uuid.UUID,
) -> None:
    client = get_social_client_or_404(
        session=session,
        tenant_id=tenant_context.tenant_id,
        client_id=client_id,
    )
    reject_google_type(client.social_type)
    if session.exec(
        select(SocialUser).where(
            SocialUser.tenant_id == tenant_context.tenant_id,
            SocialUser.social_client_id == client_id,
        )
    ).first():
        raise HTTPException(status_code=400, detail="Social client is used by users")
    session.delete(client)
    session.commit()
    return None


@router.get(
    "/users",
    dependencies=[Depends(require_permission("system:social-user:list"))],
    response_model=SocialUsersPublic,
)
def read_social_users(
    session: SessionDep,
    read_tenant: PlatformReadTenant,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    type: str | None = None,
    openid: str | None = None,
    user_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    # Google bindings use EnterpriseOidcIdentity as their sole source of truth.
    filters = [func.lower(func.trim(SocialUser.type)) != "google"]
    if read_tenant:
        filters.append(SocialUser.tenant_id == read_tenant)
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                col(SocialUser.nickname).ilike(pattern),
                col(SocialUser.openid).ilike(pattern),
                col(SocialUser.unionid).ilike(pattern),
            )
        )
    if type:
        filters.append(SocialUser.type == type)
    if openid:
        filters.append(col(SocialUser.openid).ilike(f"%{openid}%"))
    if user_id:
        filters.append(SocialUser.user_id == user_id)

    if created_from is not None:
        filters.append(SocialUser.created_at >= created_from)
    if created_to is not None:
        filters.append(SocialUser.created_at <= created_to)
    count_statement = select(func.count()).select_from(SocialUser)
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(SocialUser)
    if filters:
        statement = statement.where(*filters)
    users = session.exec(
        statement.order_by(col(SocialUser.updated_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SocialUsersPublic(
        items=[
            to_social_user_public(session=session, social_user=user) for user in users
            if not is_google_type(user.type)
        ],
        total=count,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/users/{social_user_id}",
    dependencies=[Depends(require_permission("system:social-user:list"))],
    response_model=SocialUserPublic,
)
def read_social_user(
    read_tenant: PlatformReadTenant,
    session: SessionDep,
    social_user_id: uuid.UUID,
) -> SocialUserPublic:
    social_user = get_social_user_or_404(
        session=session,
        tenant_id=read_tenant,
        social_user_id=social_user_id,
    )
    return to_social_user_public(session=session, social_user=social_user)


@router.post(
    "/users/{social_user_id}/bind",
    dependencies=[Depends(require_permission("system:social-user:list"))],
    response_model=SocialUserPublic,
)
def bind_social_user(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    social_user_id: uuid.UUID,
    body: SocialUserBind,
) -> SocialUserPublic:
    social_user = get_social_user_or_404(
        session=session,
        tenant_id=tenant_context.tenant_id,
        social_user_id=social_user_id,
    )
    reject_google_type(social_user.type)
    membership = session.exec(
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.user_id == body.user_id,
            TenantMembership.tenant_id == tenant_context.tenant_id,
            TenantMembership.is_active,
            User.is_active,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=400, detail="Target user is invalid")
    user = session.get(User, body.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Target user is invalid")
    conflict = session.exec(
        select(SocialUser).where(
            SocialUser.tenant_id == tenant_context.tenant_id,
            SocialUser.type == social_user.type,
            SocialUser.user_id == body.user_id,
            SocialUser.id != social_user.id,
        )
    ).first()
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="Target user already has a social account for this platform",
        )
    social_user.user_id = user.id
    social_user.updated_at = get_datetime_utc()
    session.add(social_user)
    session.commit()
    session.refresh(social_user)
    return to_social_user_public(session=session, social_user=social_user)


@router.post(
    "/users/{social_user_id}/unbind",
    dependencies=[Depends(require_permission("system:social-user:list"))],
    response_model=SocialUserPublic,
)
def unbind_social_user(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    social_user_id: uuid.UUID,
) -> SocialUserPublic:
    social_user = get_social_user_or_404(
        session=session,
        tenant_id=tenant_context.tenant_id,
        social_user_id=social_user_id,
    )
    reject_google_type(social_user.type)
    social_user.user_id = None
    social_user.updated_at = get_datetime_utc()
    session.add(social_user)
    session.commit()
    session.refresh(social_user)
    return to_social_user_public(session=session, social_user=social_user)
