"""Platform-owned dictionary storage for ESOP alarm categories."""

import uuid
from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.tenancy_constants import DEFAULT_TENANT_ID
from app.platform.core.configuration_models import DictionaryItem, DictionaryType
from app.platform.public_api.alarm_types import AlarmDictionaryEntry
from app.platform.tenant_uow import PlatformTenantUnitOfWork

TYPE_CODE = "esop_alarm_type"
T = TypeVar("T")


class SqlAlarmTypeDirectory:
    def __init__(self, session: Session) -> None:
        self._bind = session.get_bind()

    def _scoped(self, tenant_id: uuid.UUID, operation: Callable[[Session], T], *, write: bool = False) -> T:
        # A dedicated Platform session preserves the caller's ESOP tenant/RLS scope.
        with Session(self._bind) as session:
            with PlatformTenantUnitOfWork(session, tenant_id):
                result = operation(session)
                if write:
                    session.commit()
                return result

    @staticmethod
    def _type(session: Session, tenant_id: uuid.UUID, *, create: bool = False) -> DictionaryType | None:
        row = session.exec(select(DictionaryType).where(
            DictionaryType.tenant_id == tenant_id, DictionaryType.code == TYPE_CODE,
        )).first()
        if row is None and create:
            row = DictionaryType(tenant_id=tenant_id, code=TYPE_CODE, name="ESOP 报警类型")
            session.add(row)
            session.flush()
        return row

    @staticmethod
    def _entry(item: DictionaryItem) -> AlarmDictionaryEntry:
        return AlarmDictionaryEntry(code=item.value, name=item.label, sort=item.sort, active=item.is_active)

    def _list(self, session: Session, tenant_id: uuid.UUID) -> list[AlarmDictionaryEntry]:
        type_ = self._type(session, tenant_id)
        if type_ is None:
            return []
        rows = session.exec(select(DictionaryItem).where(
            DictionaryItem.tenant_id == tenant_id, DictionaryItem.type_id == type_.id,
        ).order_by(DictionaryItem.sort, DictionaryItem.created_at)).all()
        return [self._entry(row) for row in rows]

    def list_global(self) -> list[AlarmDictionaryEntry]:
        return self._scoped(DEFAULT_TENANT_ID, lambda session: self._list(session, DEFAULT_TENANT_ID))

    def list_tenant(self, tenant_id: uuid.UUID) -> list[AlarmDictionaryEntry]:
        return self._scoped(tenant_id, lambda session: self._list(session, tenant_id))

    def _create(self, session: Session, tenant_id: uuid.UUID, name: str) -> AlarmDictionaryEntry:
        type_ = self._type(session, tenant_id, create=True)
        assert type_ is not None
        code = f"alarm_{uuid.uuid4().hex[:16]}"
        item = DictionaryItem(tenant_id=tenant_id, type_id=type_.id, value=code,
                              label=name, sort=1000, is_active=True)
        session.add(item)
        session.flush()
        return self._entry(item)

    def create_global(self, name: str) -> AlarmDictionaryEntry:
        return self._scoped(DEFAULT_TENANT_ID,
                            lambda session: self._create(session, DEFAULT_TENANT_ID, name), write=True)

    def create_tenant(self, tenant_id: uuid.UUID, name: str) -> AlarmDictionaryEntry:
        return self._scoped(tenant_id, lambda session: self._create(session, tenant_id, name), write=True)

    def _rename(self, session: Session, tenant_id: uuid.UUID, code: str, name: str) -> AlarmDictionaryEntry:
        type_ = self._type(session, tenant_id)
        if type_ is None:
            raise HTTPException(status_code=404, detail="报警类型不存在")
        item = session.exec(select(DictionaryItem).where(
            DictionaryItem.tenant_id == tenant_id, DictionaryItem.type_id == type_.id,
            DictionaryItem.value == code,
        )).first()
        if item is None:
            raise HTTPException(status_code=404, detail="报警类型不存在")
        item.label = name
        item.updated_at = get_datetime_utc()
        session.add(item)
        session.flush()
        return self._entry(item)

    def rename_global(self, code: str, name: str) -> AlarmDictionaryEntry:
        return self._scoped(DEFAULT_TENANT_ID,
                            lambda session: self._rename(session, DEFAULT_TENANT_ID, code, name), write=True)

    def rename_tenant(self, tenant_id: uuid.UUID, code: str, name: str) -> AlarmDictionaryEntry:
        return self._scoped(tenant_id, lambda session: self._rename(session, tenant_id, code, name), write=True)
