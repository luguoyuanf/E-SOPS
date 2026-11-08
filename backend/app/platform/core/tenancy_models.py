import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BeforeValidator, EmailStr, StringConstraints, model_validator
from sqlalchemy import BigInteger, ForeignKeyConstraint, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.clock import get_datetime_utc
from app.core.database_types import UTCDateTime as DateTime
from app.core.tenancy_constants import (
    DEFAULT_TENANT_PLAN_ID,
    DEFAULT_TENANT_TEMPLATE_ID,
)
from app.platform.core.entity_codes import EntityCodeUpdateMixin, generate_entity_code
from app.platform.core.identity_fields import LoginUsername


class TenantLifecycleStatus(StrEnum):
    TRIAL = "trial"
    FORMAL = "formal"
    FROZEN = "frozen"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class TenantLifecycleAction(StrEnum):
    CONVERT_TO_FORMAL = "convert_to_formal"
    RENEW = "renew"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    ARCHIVE = "archive"


class TenantPlanBase(SQLModel):
    code: str = Field(min_length=1, max_length=100, unique=True, index=True)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    max_members: int | None = Field(default=None, ge=1)
    max_file_assets: int | None = Field(default=None, ge=1)
    max_storage_bytes: int | None = Field(default=None, ge=1, sa_type=BigInteger)  # type: ignore
    is_default: bool = False
    is_active: bool = True


class TenantPlan(TenantPlanBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantPlanCreate(TenantPlanBase):
    code: Annotated[str, BeforeValidator(lambda value: value if value is not None and str(value).strip() else generate_entity_code("PLAN"))] = Field(
        default_factory=lambda: generate_entity_code("PLAN"), min_length=1, max_length=100
    )
    type: int = 0
    logo: str | None = Field(default=None, max_length=500)
    price: float = Field(default=0, ge=0)
    published: int = 0
    order_num: int = Field(default=1, ge=0)
    remark: str | None = Field(default=None, max_length=500)


class TenantPlanUpdate(EntityCodeUpdateMixin, SQLModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    max_members: int | None = Field(default=None, ge=1)
    max_file_assets: int | None = Field(default=None, ge=1)
    max_storage_bytes: int | None = Field(default=None, ge=1)
    is_default: bool | None = None
    is_active: bool | None = None
    type: int | None = None
    logo: str | None = Field(default=None, max_length=500)
    price: float | None = Field(default=None, ge=0)
    published: int | None = None
    order_num: int | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=500)


class TenantPlanPublic(TenantPlanBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    type: int = 0
    logo: str | None = None
    price: float = 0
    published: int = 0
    order_num: int = 1
    subscription_num: int = 0
    subscription_total_amount: float = 0
    remark: str | None = None
    menu_count: int = 0


class TenantPlansPublic(SQLModel):
    items: list[TenantPlanPublic]
    total: int
    page: int
    page_size: int


class TenantInitializationTemplateBase(SQLModel):
    code: str = Field(min_length=1, max_length=100, unique=True, index=True)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    root_department_code: str = Field(
        default="headquarters", min_length=1, max_length=100
    )
    root_department_name: str = Field(default="总部", min_length=1, max_length=100)
    seed_posts: bool = True
    seed_dictionaries: bool = True
    seed_settings: bool = True
    seed_storage_channels: bool = True
    seed_message_templates: bool = True
    seed_sms_channels: bool = True
    seed_mail_accounts: bool = True
    is_default: bool = False
    is_active: bool = True


class TenantInitializationTemplate(TenantInitializationTemplateBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantInitializationTemplateCreate(TenantInitializationTemplateBase):
    code: Annotated[str, BeforeValidator(lambda value: value if value is not None and str(value).strip() else generate_entity_code("TPL"))] = Field(
        default_factory=lambda: generate_entity_code("TPL"), min_length=1, max_length=100
    )
    root_department_code: Annotated[str, BeforeValidator(lambda value: value if value is not None and str(value).strip() else generate_entity_code("DEPT"))] = Field(
        default_factory=lambda: generate_entity_code("DEPT"), min_length=1, max_length=100
    )


class TenantInitializationTemplateUpdate(EntityCodeUpdateMixin, SQLModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    root_department_code: str | None = Field(default=None, min_length=1, max_length=100)
    root_department_name: str | None = Field(default=None, min_length=1, max_length=100)
    seed_posts: bool | None = None
    seed_dictionaries: bool | None = None
    seed_settings: bool | None = None
    seed_storage_channels: bool | None = None
    seed_message_templates: bool | None = None
    seed_sms_channels: bool | None = None
    seed_mail_accounts: bool | None = None
    is_default: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def preserve_blank_root_department_code(cls, data):
        if isinstance(data, dict) and (data.get("root_department_code") is None or not str(data.get("root_department_code")).strip()):
            data = dict(data)
            data.pop("root_department_code", None)
        return data


class TenantInitializationTemplatePublic(TenantInitializationTemplateBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantInitializationTemplatesPublic(SQLModel):
    items: list[TenantInitializationTemplatePublic]
    total: int
    page: int
    page_size: int


class TenantBase(SQLModel):
    code: str = Field(min_length=1, max_length=100, unique=True, index=True)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class Tenant(TenantBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    plan_id: uuid.UUID = Field(
        default=DEFAULT_TENANT_PLAN_ID,
        foreign_key="tenantplan.id",
        index=True,
        ondelete="RESTRICT",
    )
    initialization_template_id: uuid.UUID = Field(
        default=DEFAULT_TENANT_TEMPLATE_ID,
        foreign_key="tenantinitializationtemplate.id",
        index=True,
        ondelete="RESTRICT",
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantPublic(TenantBase):
    admin_username: str | None = None
    id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str | None = None
    initialization_template_id: uuid.UUID
    initialization_template_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    contact_user_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_mobile: str | None = None
    industry: int | None = None
    type: int | None = None
    address_code: str | None = None
    address_detail: str | None = None
    qualifications: str | None = None
    website: str | None = None
    recharge_amount: float = 0
    payment_amount: float = 0
    balance_amount: float = 0
    account_count: int | None = None
    current_account_count: int = 0
    lifecycle_status: TenantLifecycleStatus = TenantLifecycleStatus.FORMAL
    effective_at: datetime | None = None
    trial_ends_at: datetime | None = None
    service_expires_at: datetime | None = None
    frozen_at: datetime | None = None
    frozen_reason: str | None = None
    owner_name: str | None = None
    customer_source: str | None = None
    follow_up_notes: str | None = None


class TenantCreate(TenantBase):
    code: Annotated[str, BeforeValidator(lambda value: value if value is not None and str(value).strip() else generate_entity_code("TEN"))] = Field(
        default_factory=lambda: generate_entity_code("TEN"), min_length=1, max_length=100
    )
    admin_username: LoginUsername = Field(default=None, max_length=64)
    plan_id: uuid.UUID | None = None
    initialization_template_id: uuid.UUID | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    contact_mobile: str | None = Field(default=None, max_length=32)
    industry: int | None = None
    type: int | None = None
    address_code: str | None = Field(default=None, max_length=100)
    address_detail: str | None = Field(default=None, max_length=255)
    qualifications: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=255)
    account_count: int | None = Field(default=None, ge=0)
    username: Annotated[EmailStr, Field(max_length=255)] | LoginUsername = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    lifecycle_status: TenantLifecycleStatus = TenantLifecycleStatus.FORMAL
    effective_at: datetime | None = None
    trial_ends_at: datetime | None = None
    service_expires_at: datetime | None = None
    owner_name: str | None = Field(default=None, max_length=100)
    customer_source: str | None = Field(default=None, max_length=100)
    follow_up_notes: str | None = Field(default=None, max_length=1000)


class TenantUpdate(EntityCodeUpdateMixin, SQLModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    plan_id: uuid.UUID | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    contact_mobile: str | None = Field(default=None, max_length=32)
    industry: int | None = None
    type: int | None = None
    address_code: str | None = Field(default=None, max_length=100)
    address_detail: str | None = Field(default=None, max_length=255)
    qualifications: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=255)
    account_count: int | None = Field(default=None, ge=0)
    lifecycle_status: TenantLifecycleStatus | None = None
    effective_at: datetime | None = None
    trial_ends_at: datetime | None = None
    service_expires_at: datetime | None = None
    frozen_reason: str | None = Field(default=None, max_length=500)
    owner_name: str | None = Field(default=None, max_length=100)
    customer_source: str | None = Field(default=None, max_length=100)
    follow_up_notes: str | None = Field(default=None, max_length=1000)


class TenantsPublic(SQLModel):
    items: list[TenantPublic]
    total: int
    page: int
    page_size: int


class TenantMembershipPublic(SQLModel):
    tenant: TenantPublic
    is_active: bool
    is_default: bool
    is_current: bool
    created_at: datetime | None = None


class TenantSwitchRequest(SQLModel):
    tenant_id: uuid.UUID


class TenantUsagePublic(SQLModel):
    tenant_id: uuid.UUID
    plan: TenantPlanPublic
    members: int
    file_assets: int
    storage_bytes: int


class TenantLifecycleActionRequest(SQLModel):
    action: TenantLifecycleAction
    service_expires_at: datetime | None = None
    frozen_reason: str | None = Field(default=None, max_length=500)


class TenantMenuSyncResult(SQLModel):
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


class TenantProfile(SQLModel, table=True):
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id", primary_key=True, ondelete="CASCADE"
    )
    contact_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
    )
    contact_name: str | None = Field(default=None, max_length=100)
    contact_mobile: str | None = Field(default=None, max_length=32)
    industry: int | None = None
    tenant_type: int | None = None
    address_code: str | None = Field(default=None, max_length=100)
    address_detail: str | None = Field(default=None, max_length=255)
    qualifications: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=255)
    recharge_amount: float = 0
    payment_amount: float = 0
    balance_amount: float = 0
    account_count: int | None = Field(default=None, ge=0)
    lifecycle_status: TenantLifecycleStatus = Field(
        default=TenantLifecycleStatus.FORMAL,
        sa_type=String(32),
        index=True,
    )
    lifecycle_status_before_freeze: TenantLifecycleStatus | None = Field(
        default=None,
        sa_type=String(32),
    )
    effective_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    trial_ends_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    service_expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    frozen_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    frozen_reason: str | None = Field(default=None, max_length=500)
    owner_name: str | None = Field(default=None, max_length=100, index=True)
    customer_source: str | None = Field(default=None, max_length=100, index=True)
    follow_up_notes: str | None = Field(default=None, max_length=1000)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantPlanProfile(SQLModel, table=True):
    plan_id: uuid.UUID = Field(
        foreign_key="tenantplan.id", primary_key=True, ondelete="CASCADE"
    )
    package_type: int = 0
    logo: str | None = Field(default=None, max_length=500)
    price: float = Field(default=0, ge=0)
    published: int = 0
    order_num: int = Field(default=1, ge=0)
    subscription_num: int = Field(default=0, ge=0)
    subscription_total_amount: float = Field(default=0, ge=0)
    remark: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantPlanMenu(SQLModel, table=True):
    plan_id: uuid.UUID = Field(
        foreign_key="tenantplan.id", primary_key=True, ondelete="CASCADE"
    )
    menu_id: uuid.UUID = Field(
        foreign_key="menu.id", primary_key=True, ondelete="CASCADE"
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class TenantPlanMenuUpdate(SQLModel):
    menu_ids: list[uuid.UUID]


class TenantRegistrationRequest(SQLModel):
    tenant_code: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=5,
            max_length=32,
            pattern=r"^[a-z][a-z0-9-]{4,31}$",
        ),
    ]
    tenant_name: str = Field(min_length=2, max_length=100)
    email: EmailStr = Field(max_length=255)
    mobile: str | None = Field(default=None, min_length=8, max_length=32)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    sms_code: str | None = Field(default=None, min_length=6, max_length=6)
    email_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")] | None = None

    @model_validator(mode="after")
    def require_verification(self) -> Self:
        if not self.email_code and not (self.mobile and self.sms_code):
            raise ValueError("Email verification code is required")
        return self


class TenantMembership(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_tenantmembership_tenant_username"),
        ForeignKeyConstraint(
            ["department_id", "tenant_id"],
            ["department.id", "department.tenant_id"],
            ondelete="RESTRICT",
        ),
    )

    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE"
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id", primary_key=True, index=True, ondelete="CASCADE"
    )
    username: LoginUsername = Field(default=None, max_length=64)
    department_id: uuid.UUID | None = Field(default=None, index=True)
    hire_date: date | None = None
    is_active: bool = True
    is_default: bool = False
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
