"""Database-backed ERP document number allocation."""


from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.core.clock import get_datetime_utc
from app.modules.erp.infrastructure.models import DocumentSequence
from app.modules.erp.infrastructure.tenant_uow import ErpTenantUnitOfWork


def allocate_document_no(*, uow: ErpTenantUnitOfWork, prefix: str) -> str:
    """Allocate a tenant-scoped daily sequence in the current transaction."""

    sequence_date = get_datetime_utc().date()
    if uow.session.get_bind().dialect.name == "mysql":
        uow.session.exec(mysql_insert(DocumentSequence).values(
            tenant_id=uow.tenant_id, prefix=prefix, sequence_date=sequence_date, next_value=2,
        ).on_duplicate_key_update(next_value=DocumentSequence.next_value + 1)
          .execution_options(erp_upsert_tenant=uow.tenant_id))
        sequence = uow.session.exec(select(DocumentSequence).where(
            DocumentSequence.prefix == prefix,
            DocumentSequence.sequence_date == sequence_date,
        ).with_for_update().execution_options(populate_existing=True)).one()
        allocated = sequence.next_value - 1
        return f"{prefix}{sequence_date:%Y%m%d}{allocated:06d}"
    next_value = uow.session.exec(
        insert(DocumentSequence)
        .values(
            tenant_id=uow.tenant_id,
            prefix=prefix,
            sequence_date=sequence_date,
            next_value=2,
        )
        .on_conflict_do_update(
            index_elements=("tenant_id", "prefix", "sequence_date"),
            set_={"next_value": DocumentSequence.next_value + 1},
        )
        .returning(DocumentSequence.next_value)
    ).scalar_one()
    allocated = int(next_value) - 1
    return f"{prefix}{sequence_date:%Y%m%d}{allocated:06d}"
