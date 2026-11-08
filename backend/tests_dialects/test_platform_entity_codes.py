"""Schema checks for optional business codes; no database fixtures or writes."""

import pytest
from pydantic import ValidationError

from app.platform.core.authorization_models import (
    DepartmentCreate,
    DepartmentUpdate,
    PostCreate,
    PostUpdate,
    RoleCreate,
    RoleUpdate,
)
from app.platform.core.configuration_models import (
    DictionaryTypeCreate,
    DictionaryTypeUpdate,
    SiteMessageTemplateCreate,
    SiteMessageTemplateUpdate,
)
from app.platform.core.entity_codes import generate_entity_code
from app.platform.core.identity_models import SmsLoginRequest
from app.platform.core.tenancy_models import (
    TenantCreate,
    TenantInitializationTemplateCreate,
    TenantInitializationTemplateUpdate,
    TenantPlanCreate,
    TenantPlanUpdate,
    TenantRegistrationRequest,
    TenantUpdate,
)
from app.platform.infra.file_models import (
    FileStorageChannelCreate,
    FileStorageChannelUpdate,
)
from app.platform.infra.mail_models import (
    MailAccountCreate,
    MailAccountUpdate,
    MailTemplateCreate,
    MailTemplateUpdate,
)
from app.platform.infra.sms_models import (
    SmsChannelCreate,
    SmsChannelUpdate,
    SmsTemplateCreate,
    SmsTemplateUpdate,
)

CASES = [
    (DepartmentCreate, DepartmentUpdate, "DEPT", {"name": "Example"}),
    (PostCreate, PostUpdate, "POST", {"name": "Example"}),
    (RoleCreate, RoleUpdate, "ROLE", {"name": "Example"}),
    (DictionaryTypeCreate, DictionaryTypeUpdate, "DICT", {"name": "Example"}),
    (SiteMessageTemplateCreate, SiteMessageTemplateUpdate, "MSG", {"name": "Example", "content": "Example"}),
    (TenantPlanCreate, TenantPlanUpdate, "PLAN", {"name": "Example"}),
    (TenantInitializationTemplateCreate, TenantInitializationTemplateUpdate, "TPL", {"name": "Example"}),
    (TenantCreate, TenantUpdate, "TEN", {"name": "Example"}),
    (FileStorageChannelCreate, FileStorageChannelUpdate, "FILECH", {"name": "Example"}),
    (SmsChannelCreate, SmsChannelUpdate, "SMSCH", {"name": "Example", "signature": "Example"}),
    (SmsTemplateCreate, SmsTemplateUpdate, "SMSTPL", {"name": "Example", "content": "Example"}),
    (MailAccountCreate, MailAccountUpdate, "MAIL", {"name": "Example", "email": "example@example.com", "host": "smtp.example.com"}),
    (MailTemplateCreate, MailTemplateUpdate, "MAILTPL", {"name": "Example", "title": "Example", "content": "Example"}),
]


@pytest.mark.parametrize("create,prefix,payload", [(create, prefix, payload) for create, _, prefix, payload in CASES])
def test_platform_create_codes_are_optional_and_manual_values_are_preserved(create, prefix, payload):
    generated = [create(**payload).code]
    for value in (None, "", "   "):
        generated.append(create(**payload, code=value).code)
    assert len(set(generated)) == len(generated)
    assert all(value.startswith(prefix) and len(value) <= 32 for value in generated)
    assert create(**payload, code="MANUAL-001").code == "MANUAL-001"
    assert "code" not in create.model_json_schema().get("required", [])
    with pytest.raises(ValidationError):
        create(**payload, code="x" * 101)


@pytest.mark.parametrize("update", [update for _, update, _, _ in CASES])
def test_platform_update_blank_code_preserves_existing_value(update):
    for value in (None, "", "   "):
        assert "code" not in update(code=value).model_dump(exclude_unset=True)
    assert update(code="MANUAL-002").model_dump(exclude_unset=True)["code"] == "MANUAL-002"


def test_root_department_code_optional_and_login_verification_code_stays_required():
    template = TenantInitializationTemplateCreate(name="Example", root_department_code=" ")
    assert template.root_department_code.startswith("DEPT")
    assert "root_department_code" not in TenantInitializationTemplateUpdate(root_department_code=" ").model_dump(exclude_unset=True)
    with pytest.raises(ValidationError):
        SmsLoginRequest(tenant_code="example", mobile="13800000000", code="")


def test_registration_can_generate_tenant_code_without_weakening_login_fields():
    payload = {"tenant_name": "Example", "email": "example@example.com", "mobile": "13800000000", "full_name": "Example", "password": "long-password", "sms_code": "123456"}
    for extras in ({}, {"tenant_code": None}, {"tenant_code": ""}, {"tenant_code": "  "}):
        registration = TenantRegistrationRequest(**payload, **extras)
        assert registration.tenant_code.startswith("TEN") and len(registration.tenant_code) <= 32
    assert TenantRegistrationRequest(**payload, tenant_code="my-tenant").tenant_code == "my-tenant"
    with pytest.raises(ValidationError):
        SmsLoginRequest(tenant_code="", mobile="13800000000", code="123456")


def test_generated_code_uses_prefix_and_eight_random_digits(monkeypatch):
    monkeypatch.setattr("app.platform.core.entity_codes.secrets.randbelow", lambda limit: 42 if limit == 100_000_000 else -1)
    assert generate_entity_code("PRD") == "PRD00000042"
