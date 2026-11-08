import uuid
from collections.abc import Generator
from datetime import timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core import security
from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.database import engine
from app.core.tenancy import (
    DEFAULT_TENANT_ID,
    TenantContext,
    get_active_tenant_membership,
    get_default_tenant,
)
from app.models import TokenPayload
from app.modules.access import evaluate_module_access, filter_module_scoped_permissions
from app.platform.core.authorization_models import Menu, Role, RoleMenu, UserRole
from app.platform.core.identity_models import User, UserSession
from app.platform.core.tenancy_models import Tenant, TenantPlan, TenantPlanMenu
from app.platform.core.tenant_menu_access import (
    tenant_permission_allowed,
    tenant_plan_menu_ids,
)
from app.platform.tenant_uow import (
    PlatformGlobalUnitOfWork,
    PlatformTenantUnitOfWork,
    activate_platform_tenant_scope,
)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)
optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]
OptionalTokenDep = Annotated[str | None, Depends(optional_oauth2)]


def get_token_payload(token: TokenDep) -> TokenPayload:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        return TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )


CurrentTokenPayload = Annotated[TokenPayload, Depends(get_token_payload)]


def grantable_tenant_menus(session: Session, tenant_id: uuid.UUID) -> list[Menu]:
    ids = tenant_plan_menu_ids(session, tenant_id)
    if not ids:
        return []
    menus = session.exec(select(Menu).where(Menu.id.in_(ids)).order_by(Menu.sort)).all()
    allowed_codes = set(filter_module_scoped_permissions(
        session=session,
        tenant_id=tenant_id,
        permission_codes=[menu.permission_code for menu in menus if menu.permission_code],
    ))
    menus = [menu for menu in menus if menu.permission_code is None or menu.permission_code in allowed_codes]
    while True:
        parents = {menu.parent_id for menu in menus}
        filtered = [menu for menu in menus if menu.type != "directory" or menu.id in parents]
        if len(filtered) == len(menus):
            return filtered
        menus = filtered


def has_backoffice_menu(session: Session, user: User, tenant_id: uuid.UUID) -> bool:
    if user.is_superuser:
        return True
    terminal_only_role = session.exec(
        select(Role.id).join(UserRole, UserRole.role_id == Role.id).where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
            Role.is_active,
            Role.code.in_(["esop_team_leader", "esop_member"]),
        )
    ).first()
    if terminal_only_role is not None:
        return False
    codes = session.exec(
        select(Menu.permission_code)
        .join(RoleMenu, RoleMenu.menu_id == Menu.id)
        .join(Role, Role.id == RoleMenu.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .join(Tenant, Tenant.id == UserRole.tenant_id)
        .join(TenantPlan, TenantPlan.id == Tenant.plan_id)
        .join(TenantPlanMenu, TenantPlanMenu.menu_id == Menu.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
            Role.is_active,
            Tenant.id == tenant_id,
            Tenant.is_active,
            TenantPlan.is_active,
            TenantPlanMenu.plan_id == Tenant.plan_id,
            Menu.type == "menu",
            Menu.is_active,
            Menu.is_visible,
        )
        .distinct()
    ).all()
    allowed = [code for code in codes if tenant_permission_allowed(code)]
    return None in allowed or bool(filter_module_scoped_permissions(
        session=session, tenant_id=tenant_id,
        permission_codes=[code for code in allowed if code],
    ))


def get_current_user(
    request: Request, session: SessionDep, token_data: CurrentTokenPayload,
) -> User:
    return get_user_from_token_payload(
        session=session, token_data=token_data,
        allow_terminal=request.url.path.startswith(f"{settings.API_V1_STR}/esop/terminal/"),
    )


def get_user_from_token_payload(
    *, session: Session, token_data: TokenPayload, allow_terminal: bool = False,
) -> User:
    if not token_data.sub or not token_data.jti or token_data.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    try:
        user_id = uuid.UUID(token_data.sub)
    except ValueError, TypeError, AttributeError:
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    activate_platform_tenant_scope(session, token_data.tenant_id)
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    now = get_datetime_utc()
    user_session = session.exec(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.token_jti == token_data.jti,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).first()
    if not user_session:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if token_data.tenant_id != user_session.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is invalid",
        )
    if token_data.client_kind == "terminal":
        if not allow_terminal:
            raise HTTPException(status_code=403, detail="Terminal session cannot access the back office")
    elif not has_backoffice_menu(session, user, token_data.tenant_id):
        raise HTTPException(status_code=403, detail="Back-office menu permission required")

    # Identity, revocation and expiry are still read on every request.
    # Only the informational heartbeat write is throttled.
    if user_session.last_active_at is None or now - user_session.last_active_at >= timedelta(seconds=60):
        user_session.last_active_at = now
        session.add(user_session)
        session.commit()
    session.info["verified_request_session"] = (user.id, token_data.jti, token_data.tenant_id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_tenant_context(
    session: SessionDep,
    current_user: CurrentUser,
    token_data: CurrentTokenPayload,
) -> TenantContext:
    if not token_data.jti:
        raise HTTPException(status_code=403, detail="Tenant context is invalid")
    tenant_id = token_data.tenant_id
    verified = session.info.get("verified_request_session")
    if verified != (current_user.id, token_data.jti, tenant_id):
        user_session = session.exec(
            select(UserSession).where(UserSession.user_id == current_user.id,
                UserSession.token_jti == token_data.jti, UserSession.revoked_at.is_(None))
        ).first()
        if user_session is None or tenant_id != user_session.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant context is invalid")
    membership = get_active_tenant_membership(
        session=session,
        user_id=current_user.id,
        tenant_id=tenant_id,
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Tenant context is invalid")
    _, tenant = membership
    activate_platform_tenant_scope(session, tenant.id)
    return TenantContext(
        tenant_id=tenant.id,
        tenant_code=tenant.code,
        user_id=current_user.id,
    )


CurrentTenant = Annotated[TenantContext, Depends(get_current_tenant_context)]


def get_public_tenant_id(session: SessionDep, token: OptionalTokenDep) -> uuid.UUID:
    if token is None:
        tenant = get_default_tenant(session)
        tenant_id = tenant.id if tenant is not None else DEFAULT_TENANT_ID
        activate_platform_tenant_scope(session, tenant_id)
        return tenant_id
    try:
        token_data = TokenPayload(
            **jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        )
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    current_user = get_user_from_token_payload(
        session=session,
        token_data=token_data,
    )
    return get_current_tenant_context(
        session=session,
        current_user=current_user,
        token_data=token_data,
    ).tenant_id


PublicTenantId = Annotated[uuid.UUID, Depends(get_public_tenant_id)]


def get_optional_tenant_id(
    session: SessionDep, token: OptionalTokenDep
) -> uuid.UUID | None:
    return get_public_tenant_id(session=session, token=token)


OptionalTenantId = Annotated[uuid.UUID | None, Depends(get_optional_tenant_id)]


def get_optional_current_user(
    session: SessionDep, token: OptionalTokenDep
) -> User | None:
    if not token:
        return None
    try:
        token_data = TokenPayload(
            **jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        )
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    return get_user_from_token_payload(session=session, token_data=token_data)


OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]


def normalize_pagination(
    *, page: int, page_size: int, max_page_size: int = 100
) -> tuple[int, int]:
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be greater than 0")
    if page_size < 1:
        raise HTTPException(status_code=422, detail="page_size must be greater than 0")
    return page, min(page_size, max_page_size)


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def user_has_permission(
    *,
    session: Session,
    current_user: User,
    tenant_id: uuid.UUID,
    permission_code: str,
) -> bool:
    if current_user.is_superuser:
        return True

    if not tenant_permission_allowed(permission_code):
        return False
    allowed_menu_ids = tenant_plan_menu_ids(session, tenant_id)
    if not allowed_menu_ids:
        return False
    statement = (
        select(Menu)
        .join(RoleMenu, RoleMenu.menu_id == Menu.id)
        .join(Role, Role.id == RoleMenu.role_id)
        .join(UserRole, UserRole.role_id == RoleMenu.role_id)
        .where(
            UserRole.user_id == current_user.id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
            Menu.permission_code == permission_code,
            Menu.id.in_(allowed_menu_ids),
            Menu.is_active,
            Role.is_active,
        )
    )
    return session.exec(statement).first() is not None


def require_permission(permission_code: str):
    def dependency(
        session: SessionDep,
        current_user: CurrentUser,
        tenant_context: CurrentTenant,
    ) -> User:
        if user_has_permission(
            session=session,
            current_user=current_user,
            tenant_id=tenant_context.tenant_id,
            permission_code=permission_code,
        ):
            return current_user

        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )

    return dependency


MODULE_ACCESS_ERRORS = {
    "MODULE_NOT_INSTALLED": (404, "Module is not installed"),
    "MODULE_UNAVAILABLE": (503, "Module is unavailable"),
    "TENANT_MODULE_ENTITLEMENT_REQUIRED": (
        403,
        "Tenant module entitlement is required",
    ),
    "TENANT_MODULE_DISABLED": (403, "Tenant module is disabled"),
}


def require_module_access(module_code: str, permission_code: str):
    """Apply module availability and tenant entitlement before RBAC."""

    def dependency(
        session: SessionDep,
        current_user: CurrentUser,
        tenant_context: CurrentTenant,
    ) -> User:
        decision = evaluate_module_access(
            session=session,
            tenant_id=tenant_context.tenant_id,
            module_code=module_code,
        )
        if not decision.allowed:
            status_code, detail = MODULE_ACCESS_ERRORS[
                decision.error_code or "MODULE_UNAVAILABLE"
            ]
            raise HTTPException(status_code=status_code, detail=detail)
        if user_has_permission(
            session=session,
            current_user=current_user,
            tenant_id=tenant_context.tenant_id,
            permission_code=permission_code,
        ):
            return current_user
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )

    return dependency


def require_any_module_access(module_code: str, permission_codes: tuple[str, ...]):
    """Check module entitlement once, then allow any explicitly listed permission."""
    if not permission_codes:
        raise ValueError("At least one permission is required")

    def dependency(
        session: SessionDep,
        current_user: CurrentUser,
        tenant_context: CurrentTenant,
    ) -> User:
        decision = evaluate_module_access(
            session=session, tenant_id=tenant_context.tenant_id, module_code=module_code,
        )
        if not decision.allowed:
            status_code, detail = MODULE_ACCESS_ERRORS[decision.error_code or "MODULE_UNAVAILABLE"]
            raise HTTPException(status_code=status_code, detail=detail)
        if any(user_has_permission(
            session=session, current_user=current_user, tenant_id=tenant_context.tenant_id,
            permission_code=code,
        ) for code in permission_codes):
            return current_user
        raise HTTPException(status_code=403, detail="没有执行此操作的权限")

    return dependency


def get_platform_read_tenant(
    session: SessionDep,
    current_user: CurrentUser,
    tenant_context: CurrentTenant,
    tenant_id: uuid.UUID | None = Query(default=None),
) -> Generator[uuid.UUID | None]:
    """Only verified platform root may request an unfiltered control-plane read."""
    if current_user.is_superuser:
        scope = (
            PlatformGlobalUnitOfWork(session)
            if tenant_id is None
            else PlatformTenantUnitOfWork(session, tenant_id, privileged=True)
        )
        with scope:
            yield tenant_id
    else:
        if tenant_id is not None and tenant_id != tenant_context.tenant_id:
            raise HTTPException(status_code=403, detail="Cannot access another tenant")
        yield tenant_context.tenant_id


PlatformReadTenant = Annotated[uuid.UUID | None, Depends(get_platform_read_tenant)]


def get_platform_configuration_tenant(
    session: SessionDep,
    current_user: CurrentUser,
    tenant_context: CurrentTenant,
) -> Generator[TenantContext]:
    """Authorize platform configuration writes, independent of selected tenant."""
    get_current_active_superuser(current_user)
    with PlatformTenantUnitOfWork(session, DEFAULT_TENANT_ID, privileged=True):
        yield TenantContext(
            tenant_id=DEFAULT_TENANT_ID,
            tenant_code="default",
            user_id=tenant_context.user_id,
        )


PlatformConfigurationTenant = Annotated[
    TenantContext, Depends(get_platform_configuration_tenant)
]
