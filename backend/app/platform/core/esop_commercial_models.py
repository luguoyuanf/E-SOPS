"""Platform control-plane entitlements for ESOP tenants."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from pydantic import Field as PydanticField
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel

from app.core.clock import get_datetime_utc
from app.core.database_types import UTCDateTime


class EsopTenantStorage(SQLModel, table=True):
    __tablename__ = "esoptenantstorage"

    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", primary_key=True, ondelete="CASCADE")
    base_bytes: int = Field(default=100 * 1024 * 1024, ge=0, sa_type=BigInteger)  # type: ignore
    certified_at: datetime | None = Field(default=None, sa_type=UTCDateTime)  # type: ignore


class EsopStorageGrant(SQLModel, table=True):
    __tablename__ = "esopstoragegrant"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True, ondelete="CASCADE")
    capacity_bytes: int = Field(ge=0, sa_type=BigInteger)  # type: ignore
    starts_at: datetime = Field(sa_type=UTCDateTime)  # type: ignore
    expires_at: datetime | None = Field(default=None, sa_type=UTCDateTime)  # type: ignore
    source: str = Field(default="expansion", max_length=32)
    note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=UTCDateTime)  # type: ignore


class EsopStorageGrantCreate(BaseModel):
    tenant_id: uuid.UUID
    capacity_bytes: int = PydanticField(gt=0)
    starts_at: datetime
    expires_at: datetime
    note: str | None = PydanticField(default=None, max_length=500)


class EsopStorageGrantPublic(BaseModel):
    source: str
    id: uuid.UUID
    tenant_id: uuid.UUID
    capacity_bytes: int
    starts_at: datetime
    expires_at: datetime | None
    note: str | None
    created_at: datetime


class EsopStorageGrantsPublic(BaseModel):
    items: list[EsopStorageGrantPublic]
    total: int


class EsopStorageUsagePublic(BaseModel):
    tenant_id: uuid.UUID
    base_bytes: int
    active_grant_bytes: int
    limit_bytes: int
    used_bytes: int


class EsopStorageDefault(BaseModel):
    capacity_mib: int = PydanticField(ge=0, le=8589934591)
