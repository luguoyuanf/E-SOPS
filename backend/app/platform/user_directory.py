import uuid
from collections.abc import Collection

from sqlmodel import Session, select

from app.platform.core.authorization_models import Post, Role, UserPost, UserRole
from app.platform.core.identity_models import User
from app.platform.core.tenancy_models import TenantMembership
from app.platform.public_api.users import UserOption, UserSummary


class SqlUserDirectory:
    """Platform-owned adapter for the narrow user lookup contract."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def is_tenant_administrator(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        return self._session.exec(
            select(Role.id).join(UserRole, UserRole.role_id == Role.id)
            .join(TenantMembership, TenantMembership.user_id == UserRole.user_id)
            .where(
                UserRole.user_id == user_id, UserRole.tenant_id == tenant_id,
                Role.tenant_id == tenant_id, Role.is_system, Role.is_active,
                Role.code.in_(["super_admin", "admin"]),
                TenantMembership.tenant_id == tenant_id, TenantMembership.is_active,
            )
        ).first() is not None

    def can_correct_production_reports(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        if self.is_tenant_administrator(user_id, tenant_id):
            return True
        return self._session.exec(
            select(Post.id).join(UserPost, UserPost.post_id == Post.id)
            .join(TenantMembership, TenantMembership.user_id == UserPost.user_id)
            .where(
                UserPost.user_id == user_id, UserPost.tenant_id == tenant_id,
                Post.tenant_id == tenant_id,
                Post.code.in_(["manager", "director", "general_manager", "chairman"]), Post.is_active,
                TenantMembership.tenant_id == tenant_id, TenantMembership.is_active,
            )
        ).first() is not None

    def list_tenant_options(self, tenant_id: uuid.UUID) -> list[UserOption]:
        rows = self._session.exec(
            select(User.id, User.full_name, User.username)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == tenant_id, TenantMembership.is_active)
            .order_by(User.full_name, User.username)
        ).all()
        return [UserOption(id=id, label=name or username or str(id)) for id, name, username in rows]

    def get_users(self, user_ids: Collection[uuid.UUID]) -> list[UserSummary]:
        if not user_ids:
            return []
        users = self._session.exec(select(User).where(User.id.in_(user_ids))).all()
        return [
            UserSummary(
                id=user.id,
                full_name=user.full_name,
                email=user.email,
                is_active=user.is_active,
            )
            for user in users
        ]

    def validate_active_users(self, user_ids: Collection[uuid.UUID]) -> None:
        requested = set(user_ids)
        users = self.get_users(requested)
        active_ids = {user.id for user in users if user.is_active}
        if requested != active_ids:
            raise ValueError("One or more users are missing or inactive")
