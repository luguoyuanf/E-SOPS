import uuid

from sqlmodel import Session, select

from app.platform.core.tenancy_models import Tenant


class SqlTenantDirectory:
    """Enumerate identities without exposing Platform ORM to business modules."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_tenant_ids(self) -> tuple[uuid.UUID, ...]:
        # Catalog writers call this after the catalog lock. A locking read sees
        # tenants committed while waiting, including under MySQL REPEATABLE READ.
        return tuple(self._session.exec(
            select(Tenant.id).order_by(Tenant.id).with_for_update()
        ).all())
