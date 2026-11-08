"""Export filters and tenant isolation on the fixed test MySQL."""
import asyncio
import uuid

from sqlmodel import Session

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.core.database import engine
from app.modules.esop import activation_routes as routes
from app.modules.esop.infrastructure.device_auth import issue_key
from app.platform.web_api import Principal, TenantContext


def test_unused_export_is_scoped_to_current_tenant():
    assert settings.MYSQL_DB == "esop_fva_test_20261024"
    tenant_id = uuid.uuid4()
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    tenant = TenantContext(tenant_id=tenant_id, tenant_code="test", user_id=principal.id)
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                unused, unused_text = issue_key(session, tenant_id)
                used, used_text = issue_key(session, tenant_id)
                used.used_at = get_datetime_utc()
                session.add(used)
                _, foreign_text = issue_key(session, uuid.uuid4())
                session.flush()
                response = routes.export_activation_keys(session, principal, tenant, is_used=False)

                async def body():
                    return "".join([part if isinstance(part, str) else part.decode() async for part in response.body_iterator])

                text = asyncio.run(body())
                assert unused_text in text
                assert used_text not in text
                assert foreign_text not in text
                response = routes.export_activation_keys(session, principal, tenant, is_used=False, tenant_id=uuid.uuid4())
                assert unused_text not in asyncio.run(body())
        finally:
            outer.rollback()
