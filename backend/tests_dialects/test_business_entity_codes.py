"""Code input and route regressions without database-wide fixtures."""

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.modules.erp.public_api.dto import (
    ProductCategoryCreate,
    ProductCategoryUpdate,
    ProductCreate,
    ProductUnitCreate,
    WarehouseCreate,
)
from app.modules.esop.public_api.channel_dto import CustomerInput
from app.modules.esop.public_api.dto import OperationInput, OperationPublic, RouteInput
from app.modules.esop.public_api.ota_dto import ChannelInput, HardwareInput
from app.modules.esop.public_api.production_dto import (
    LineInput,
    OrderInput,
    WorkshopInput,
)

INPUTS = [
    (ProductUnitCreate, {"name": "unit"}),
    (ProductCategoryCreate, {"name": "category"}),
    (ProductCreate, {"name": "product", "unit_id": uuid.uuid4(), "category_id": uuid.uuid4()}),
    (WarehouseCreate, {"name": "warehouse"}),
    (OperationInput, {"name": "operation"}),
    (RouteInput, {"name": "route", "operation_ids": [uuid.uuid4()]}),
    (WorkshopInput, {"name": "workshop"}),
    (LineInput, {"name": "line", "workshop_id": uuid.uuid4(), "layout": "single", "station_count": 1}),
    (OrderInput, {"product_id": uuid.uuid4(), "quantity": 1, "due_date": "2026-10-26"}),
    (ChannelInput, {"name": "channel"}),
    (HardwareInput, {"name": "hardware", "channel_id": uuid.uuid4(), "abi": "arm64-v8a"}),
    (CustomerInput, {"name": "customer"}),
]


@pytest.mark.parametrize(("model", "payload"), INPUTS)
def test_entity_code_input_accepts_missing_null_and_blank_but_preserves_manual(model, payload):
    assert model(**payload).code is None
    for value in (None, "", " \t "):
        assert model(**payload, code=value).code is None
    assert model(**payload, code="  MANUAL-001  ").code == "MANUAL-001"
    with pytest.raises(ValidationError):
        model(**payload, code="X" * 101)


def test_public_code_remains_required_and_patch_keeps_absent_input_distinct():
    assert "code" in OperationPublic.model_json_schema()["required"]
    assert ProductCategoryUpdate().model_dump(exclude_unset=True) == {}
    assert ProductCategoryUpdate(code=" ").code is None


@pytest.mark.parametrize(("route_name", "input_name", "model", "payload", "prefix"), [
    ("create_product_unit", "unit_in", ProductUnitCreate, {"name": "unit"}, "UNT"),
    ("create_product_category", "category_in", ProductCategoryCreate, {"name": "category"}, "CAT"),
    ("create_product", "product_in", ProductCreate,
     {"name": "product", "unit_id": uuid.uuid4(), "category_id": uuid.uuid4()}, "PRD"),
    ("create_warehouse", "warehouse_in", WarehouseCreate, {"name": "warehouse"}, "WH"),
])
def test_erp_blank_code_generation_and_idempotent_replay(monkeypatch, route_name, input_name, model, payload, prefix):
    from app.modules.erp import routes

    uow = SimpleNamespace(session=Mock())
    tenant = SimpleNamespace(tenant_id=uuid.uuid4())
    claim = Mock(return_value=SimpleNamespace(receipt=Mock()))
    replay = Mock(return_value=None)
    generate = Mock(return_value=prefix + "-GENERATED")
    monkeypatch.setattr(routes, "claim_create_command", claim)
    monkeypatch.setattr(routes, "replay_created_resource", replay)
    monkeypatch.setattr(routes, "generate_entity_code", generate)
    monkeypatch.setattr(routes, "get_repository", Mock(return_value=Mock()))
    for name in ("ensure_unique_code", "ensure_unique_name", "ensure_custom_unit_available",
                 "ensure_category_parent", "ensure_unique_product_barcode", "ensure_product_references", "complete_command"):
        monkeypatch.setattr(routes, name, Mock())
    call = getattr(routes, route_name)
    kwargs = {"uow": uow, "tenant_context": tenant, "principal": Mock(), "idempotency_key": "repeat-key"}
    created = call(**kwargs, **{input_name: model(**payload, code=" ")})
    assert created.code == prefix + "-GENERATED"
    assert claim.call_args.kwargs["payload"]["code"] is None
    replay.return_value = created
    repeated = call(**kwargs, **{input_name: model(**payload, code=" ")})
    assert repeated is created
    assert generate.call_count == 1
    assert claim.call_args.kwargs["payload"]["code"] is None


def test_esop_operation_blank_create_and_blank_update_preserve_code():
    from app.modules.esop.routes import create_operation, update_operation

    session = Mock()
    session.exec.return_value.one.return_value = -1
    session.exec.return_value.first.return_value = None
    uow = SimpleNamespace(session=session, tenant_id=uuid.uuid4())
    created = create_operation(uow, OperationInput(name="operation", code=" "), None, None)
    assert created.code.startswith("PROC")
    entity = session.add.call_args.args[0]
    session.get.return_value = entity
    updated = update_operation(uow, entity.id, OperationInput(name="renamed", code=" "), None, None)
    assert updated.code == created.code and updated.name == "renamed"


def test_channel_customer_blank_code_is_generated_before_platform_port(monkeypatch):
    from app.modules.esop import channel_routes

    session = Mock()
    principal = SimpleNamespace(id=uuid.uuid4())
    binding = SimpleNamespace(channel_id=uuid.uuid4())
    monkeypatch.setattr(channel_routes, "_channel_admin", Mock(return_value=binding))
    create = Mock(side_effect=lambda **kw: SimpleNamespace(
        id=uuid.uuid4(), code=kw["customer_code"], name=kw["customer_name"]
    ))
    monkeypatch.setattr(channel_routes, "create_channel_customer_tenant", create)
    result = channel_routes.create_channel_customer(session, principal, CustomerInput(name="customer", code=" "))
    assert result.tenant_code.startswith("TEN")
    assert create.call_args.kwargs["customer_code"] == result.tenant_code
