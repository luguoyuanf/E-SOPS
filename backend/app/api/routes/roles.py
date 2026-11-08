import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import col, delete, func, select

from app.api.deps import (
    CurrentTenant,
    CurrentUser,
    PlatformReadTenant,
    SessionDep,
    grantable_tenant_menus,
    normalize_pagination,
    require_permission,
    user_has_permission,
)
from app.core.cache import CacheNamespace, redis_cache
from app.core.clock import get_datetime_utc
from app.platform.core.authorization_models import (
    Department,
    Menu,
    Role,
    RoleCreate,
    RoleDataScopeDepartment,
    RoleMenu,
    RoleMenuUpdate,
    RolePublic,
    RolesPublic,
    RoleUpdate,
    UserRole,
)

router = APIRouter(prefix="/roles", tags=["roles"])


def build_role_public(*, session: SessionDep, role: Role) -> RolePublic:
    department_ids = session.exec(
        select(RoleDataScopeDepartment.department_id).where(
            RoleDataScopeDepartment.role_id == role.id,
            RoleDataScopeDepartment.tenant_id == role.tenant_id,
        )
    ).all()
    return RolePublic.model_validate(
        role,
        update={"custom_department_ids": list(department_ids)},
    )


def sync_role_custom_departments(
    *,
    session: SessionDep,
    role: Role,
    department_ids: list[uuid.UUID],
) -> None:
    unique_ids = set(department_ids)
    if unique_ids:
        departments = session.exec(
            select(Department.id).where(
                Department.tenant_id == role.tenant_id,
                col(Department.id).in_(unique_ids),
            )
        ).all()
        if set(departments) != unique_ids:
            raise HTTPException(
                status_code=400,
                detail="Some custom data-scope departments do not exist",
            )

    session.exec(
        delete(RoleDataScopeDepartment).where(
            RoleDataScopeDepartment.role_id == role.id,
            RoleDataScopeDepartment.tenant_id == role.tenant_id,
        )
    )
    if role.data_scope == "custom":
        for department_id in unique_ids:
            session.add(
                RoleDataScopeDepartment(
                    role_id=role.id,
                    department_id=department_id,
                    tenant_id=role.tenant_id,
                )
            )


@router.get(
    "",
    dependencies=[Depends(require_permission("system:role:list"))],
    response_model=RolesPublic,
)
def read_roles(
    session: SessionDep,
    read_tenant: PlatformReadTenant,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Any:
    page, page_size = normalize_pagination(page=page, page_size=page_size)
    filters = [Role.tenant_id == read_tenant] if read_tenant else []
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            (col(Role.name).ilike(pattern)) | (col(Role.code).ilike(pattern))
        )
    if created_from is not None:
        filters.append(Role.created_at >= created_from)
    if created_to is not None:
        filters.append(Role.created_at <= created_to)

    count_statement = select(func.count()).select_from(Role)
    if filters:
        count_statement = count_statement.where(*filters)
    count = session.exec(count_statement).one()

    statement = select(Role)
    if filters:
        statement = statement.where(*filters)
    statement = (
        statement.order_by(col(Role.sort), col(Role.created_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    roles = session.exec(statement).all()
    return RolesPublic(
        items=[build_role_public(session=session, role=role) for role in roles],
        total=count,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    dependencies=[Depends(require_permission("system:role:create"))],
    response_model=RolePublic,
)
def create_role(
    *, session: SessionDep, tenant_context: CurrentTenant, role_in: RoleCreate
) -> Any:
    existing_role = session.exec(
        select(Role).where(
            Role.tenant_id == tenant_context.tenant_id,
            Role.code == role_in.code,
        )
    ).first()
    if existing_role:
        raise HTTPException(status_code=409, detail="Role code already exists")

    role = Role.model_validate(
        role_in.model_dump(exclude={"custom_department_ids"}),
        update={"tenant_id": tenant_context.tenant_id},
    )
    session.add(role)
    session.flush()
    sync_role_custom_departments(
        session=session,
        role=role,
        department_ids=role_in.custom_department_ids,
    )
    session.commit()
    session.refresh(role)
    redis_cache.bump_namespace(CacheNamespace.RBAC)
    return build_role_public(session=session, role=role)


@router.get(
    "/{role_id}",
    dependencies=[Depends(require_permission("system:role:list"))],
    response_model=RolePublic,
)
def read_role(
    *, session: SessionDep, tenant_context: CurrentTenant, role_id: uuid.UUID
) -> Any:
    role = session.get(Role, role_id)
    if not role or role.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")
    return build_role_public(session=session, role=role)


@router.patch(
    "/{role_id}",
    dependencies=[Depends(require_permission("system:role:update"))],
    response_model=RolePublic,
)
def update_role(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    role_id: uuid.UUID,
    role_in: RoleUpdate,
) -> Any:
    role = session.get(Role, role_id)
    if not role or role.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system and role_in.is_system is False:
        raise HTTPException(status_code=400, detail="System role cannot be unmarked")
    if role.is_system and role_in.code and role_in.code != role.code:
        raise HTTPException(
            status_code=400, detail="System role code cannot be changed"
        )
    if role_in.code and role_in.code != role.code:
        existing_role = session.exec(
            select(Role).where(
                Role.tenant_id == tenant_context.tenant_id,
                Role.code == role_in.code,
            )
        ).first()
        if existing_role:
            raise HTTPException(status_code=409, detail="Role code already exists")

    update_data = role_in.model_dump(
        exclude={"custom_department_ids"}, exclude_unset=True
    )
    role.sqlmodel_update(update_data)
    if role.data_scope != "custom":
        sync_role_custom_departments(session=session, role=role, department_ids=[])
    elif role_in.custom_department_ids is not None:
        sync_role_custom_departments(
            session=session,
            role=role,
            department_ids=role_in.custom_department_ids,
        )
    role.updated_at = get_datetime_utc()
    session.add(role)
    session.commit()
    session.refresh(role)
    redis_cache.bump_namespace(CacheNamespace.RBAC)
    return build_role_public(session=session, role=role)


@router.delete(
    "/{role_id}",
    dependencies=[Depends(require_permission("system:role:delete"))],
    status_code=204,
)
def delete_role(
    *, session: SessionDep, tenant_context: CurrentTenant, role_id: uuid.UUID
) -> Response:
    role = session.get(Role, role_id)
    if not role or role.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System role cannot be deleted")

    bound_user = session.exec(
        select(UserRole).where(UserRole.role_id == role_id)
    ).first()
    if bound_user:
        raise HTTPException(status_code=400, detail="Role is assigned to users")

    session.exec(delete(RoleMenu).where(RoleMenu.role_id == role_id))
    session.delete(role)
    session.commit()
    redis_cache.bump_namespace(CacheNamespace.RBAC)
    return Response(status_code=204)


@router.get(
    "/{role_id}/menus",
    dependencies=[Depends(require_permission("system:role:list"))],
    response_model=list[uuid.UUID],
)
def read_role_menus(
    *, session: SessionDep, tenant_context: CurrentTenant, role_id: uuid.UUID
) -> Any:
    role = session.get(Role, role_id)
    if not role or role.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")

    role_menus = session.exec(select(RoleMenu).where(RoleMenu.role_id == role_id)).all()
    allowed_ids = {menu.id for menu in grantable_tenant_menus(session, role.tenant_id)}
    return [role_menu.menu_id for role_menu in role_menus if role_menu.menu_id in allowed_ids]


@router.put(
    "/{role_id}/menus",
    dependencies=[Depends(require_permission("system:role:update"))],
    response_model=list[uuid.UUID],
)
def update_role_menus(
    *,
    session: SessionDep,
    tenant_context: CurrentTenant,
    current_user: CurrentUser,
    role_id: uuid.UUID,
    body: RoleMenuUpdate,
) -> Any:
    role = session.get(Role, role_id)
    if not role or role.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found")

    allowed_ids = {menu.id for menu in grantable_tenant_menus(session, role.tenant_id)}
    if not set(body.menu_ids) <= allowed_ids:
        raise HTTPException(
            status_code=403,
            detail="Menus exceed tenant plan or platform administration boundary",
        )
    if not current_user.is_superuser:
        for menu in session.exec(select(Menu).where(Menu.id.in_(body.menu_ids))).all():
            if menu.permission_code and not user_has_permission(
                session=session,
                current_user=current_user,
                tenant_id=role.tenant_id,
                permission_code=menu.permission_code,
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Cannot grant permissions beyond own authority",
                )
    if body.menu_ids:
        menus_count = session.exec(
            select(func.count())
            .select_from(Menu)
            .where(col(Menu.id).in_(body.menu_ids))
        ).one()
        if menus_count != len(set(body.menu_ids)):
            raise HTTPException(status_code=400, detail="Some menus do not exist")

    session.exec(delete(RoleMenu).where(RoleMenu.role_id == role_id))
    for menu_id in set(body.menu_ids):
        session.add(RoleMenu(role_id=role_id, menu_id=menu_id))
    role.updated_at = get_datetime_utc()
    session.add(role)
    session.commit()
    redis_cache.bump_namespace(CacheNamespace.RBAC)
    return body.menu_ids
