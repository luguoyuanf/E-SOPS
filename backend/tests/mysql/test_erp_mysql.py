"""ERP MySQL checks. Live cases require MYSQL_ERP_TEST=1 in an isolated schema.

Run with --confcutdir=tests/mysql to avoid PostgreSQL suite fixtures.
"""
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import delete, insert, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.database import engine
from app.modules.erp.application.document_numbers import allocate_document_no
from app.modules.erp.infrastructure.models import (
    ERP_OWNED_MODELS,
    ERP_TENANT_SCOPED_MODELS,
    Product,
    ProductCategory,
    ProductUnit,
    Warehouse,
)
from app.modules.erp.infrastructure.tenant_uow import (
    ErpTenantUnitOfWork,
    TenantScopeError,
)
from app.modules.manifest import build_manifest
from app.modules.migrations import module_alembic_config

live = pytest.mark.skipif(os.environ.get("MYSQL_ERP_TEST") != "1", reason="isolated ERP test schema required")


def test_frozen_mysql_erp_chain_and_offline_sql():
    assert settings.DATABASE_TYPE == "mysql"
    config = module_alembic_config("erp")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["mysql_erp_0002_platform_units"]
    source = Path(script.get_revision("mysql_erp_0001").path).read_text()
    assert "create_all" not in source and "infrastructure.models" not in source
    assert source.count("op.create_table(") == len(ERP_TENANT_SCOPED_MODELS) == 40
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, "mysql_erp_0001", sql=True)
    sql = output.getvalue()
    assert "CREATE SCHEMA" not in sql and "ROW LEVEL SECURITY" not in sql
    assert "JSON" in sql and "DATETIME(6)" in sql and "GENERATED ALWAYS" in sql
    assert sql.count("CREATE TRIGGER ") == 77
    assert "NEW.`quantity` >= 0" in sql
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    latest_sql = output.getvalue()
    assert "CREATE TABLE erp_platform_product_unit" in latest_sql
    assert "platform_unit_id" in latest_sql
    assert len(ERP_OWNED_MODELS) == 41
    assert latest_sql.count("CREATE TABLE ") == len(ERP_OWNED_MODELS) + 1  # Alembic version table
    manifest = build_manifest(edition="erp")
    assert [m.code for m in manifest.modules] == ["platform", "erp"]
    assert manifest.modules[1].migration_heads == ["mysql_erp_0002_platform_units"]
    with pytest.raises(ValueError, match="Platform and ERP"):
        build_manifest(edition="suite")


@pytest.fixture
def tenant():
    assert settings.MYSQL_DB.startswith("esop_fva_test_erp_")
    from app.platform.core.tenancy_models import (
        Tenant,
        TenantInitializationTemplate,
        TenantPlan,
    )
    tenant_id = uuid.uuid4()
    with Session(engine) as session:
        plan_id = session.exec(select(TenantPlan.id).where(TenantPlan.code == "standard")).one()
        template_id = session.exec(select(TenantInitializationTemplate.id).where(TenantInitializationTemplate.code == "standard")).one()
        session.add(Tenant(id=tenant_id, code="erp-test-" + tenant_id.hex, name="ERP MySQL isolated fixture", plan_id=plan_id, initialization_template_id=template_id))
        session.commit()
    return tenant_id


@live
def test_scope_reads_alias_aggregate_nested_and_identity_map(tenant):
    other = uuid.uuid4()
    ids = []
    with Session(engine) as session:
        for owner in (tenant, other):
            with ErpTenantUnitOfWork(session, owner):
                unit = ProductUnit(tenant_id=owner, code="unit", name="单位")
                session.add(unit)
                session.commit()
                ids.append(unit.id)
        with ErpTenantUnitOfWork(session, tenant):
            assert session.get(ProductUnit, ids[1]) is None
            assert session.get(ProductUnit, ids[0]) is not None
            alias = aliased(ProductUnit)
            assert session.exec(select(func.count()).select_from(alias)).one() == 1
            with ErpTenantUnitOfWork(session, tenant):
                assert session.exec(select(ProductUnit)).one().id == ids[0]
            assert session.info["erp_tenant_id"] == tenant
        assert not session.info.get("erp_tenant_id")
        assert not any(isinstance(obj, ProductUnit) for obj in session.identity_map.values())
        with pytest.raises(TenantScopeError):
            session.get(ProductUnit, ids[0])


@live
@pytest.mark.parametrize("operation", ["select", "insert", "update", "delete", "raw", "driver", "core"])
def test_unscoped_and_direct_sql_denied(tenant, operation):
    from app.platform.tenant_uow import PlatformTenantScopeError
    with Session(engine) as session:
        with pytest.raises((TenantScopeError, PlatformTenantScopeError)):
            if operation == "select":
                session.exec(select(ProductUnit)).all()
            elif operation == "insert":
                session.add(ProductUnit(tenant_id=tenant, code="bad", name="bad"))
                session.flush()
            elif operation == "update":
                session.exec(update(ProductUnit).values(name="bad"))
            elif operation == "delete":
                session.exec(delete(ProductUnit))
            elif operation == "raw":
                session.execute(text("SELECT * FROM erp_product_unit"))
            elif operation == "driver":
                session.connection().exec_driver_sql("SELECT * FROM erp_product_unit")
            else:
                session.connection().execute(ProductUnit.__table__.select())
        session.rollback()


@live
def test_cross_tenant_writes_bulk_and_connection_bypass_denied(tenant):
    other = uuid.uuid4()
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        session.add(ProductUnit(tenant_id=other, code="bad", name="bad"))
        with pytest.raises(TenantScopeError, match="does not match"):
            session.flush()
        session.rollback()
        for statement in (update(ProductUnit).values(name="bad"), delete(ProductUnit),
                          insert(ProductUnit).values(tenant_id=tenant, code="bad", name="bad")):
            with pytest.raises(TenantScopeError):
                session.execute(statement)
        with pytest.raises(TenantScopeError):
            session.connection().execute(ProductUnit.__table__.select())
        unit = ProductUnit(tenant_id=tenant, code="valid", name="valid")
        session.add(unit)
        session.commit()
        unit.tenant_id = other
        with pytest.raises(TenantScopeError):
            session.flush()
        session.rollback()


@live
def test_generated_default_and_barcode_unique_slots(tenant):
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        warehouses = [Warehouse(tenant_id=tenant, code=str(i), name=str(i), is_default=i == 0) for i in range(3)]
        session.add_all(warehouses)
        session.commit()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(Warehouse(tenant_id=tenant, code="other", name="other", is_default=True))
                session.flush()
        unit = ProductUnit(tenant_id=tenant, code="u", name="u")
        category = ProductCategory(tenant_id=tenant, code="c", name="c")
        session.add_all([unit, category])
        session.flush()
        for i in range(2):
            session.add(Product(tenant_id=tenant, code=str(i), name=str(i), category_id=category.id, unit_id=unit.id, barcode=""))
        session.flush()
        session.add(Product(tenant_id=tenant, code="bar1", name="bar1", category_id=category.id, unit_id=unit.id, barcode="123"))
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(Product(tenant_id=tenant, code="bar2", name="bar2", category_id=category.id, unit_id=unit.id, barcode="123"))
                session.flush()
        session.commit()


@live
def test_mysql57_checks_and_cross_tenant_foreign_keys(tenant):
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        with pytest.raises(DBAPIError, match="ck_erp_supplier_tax_rate"):
            with session.begin_nested():
                from app.modules.erp.infrastructure.models import Supplier
                session.add(Supplier(tenant_id=tenant, code="bad", name="bad", tax_rate=-1))
                session.flush()
        unit = ProductUnit(tenant_id=tenant, code="u", name="u")
        category = ProductCategory(tenant_id=tenant, code="c", name="c")
        session.add_all([unit, category])
        session.commit()
        unit_id, category_id = unit.id, category.id
    with Session(engine) as session, ErpTenantUnitOfWork(session, uuid.uuid4()) as uow:
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(Product(tenant_id=uow.tenant_id, code="bad", name="bad", category_id=category_id, unit_id=unit_id))
                session.flush()


@live
def test_concurrent_document_number_allocation_and_rollback(tenant):
    def allocate(_):
        with Session(engine) as session, ErpTenantUnitOfWork(session, tenant) as uow:
            number = allocate_document_no(uow=uow, prefix="TEST")
            session.commit()
            return number
    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers = list(pool.map(allocate, range(12)))
    assert len(set(numbers)) == 12
    assert sorted(int(number[-6:]) for number in numbers) == list(range(1, 13))
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant) as uow:
        rolled_back = allocate_document_no(uow=uow, prefix="TEST")
        session.rollback()
    assert allocate(0) == rolled_back


@live
def test_concurrent_stock_posting_and_append_only_triggers(tenant):
    from decimal import Decimal

    from app.modules.erp.application.inventory_posting import (
        InventoryEffect,
        InventoryPostingService,
    )
    from app.modules.erp.infrastructure.models import (
        StockBalance,
        StockLedger,
        StockLedgerType,
    )
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        unit = ProductUnit(tenant_id=tenant, code="u", name="u")
        category = ProductCategory(tenant_id=tenant, code="c", name="c")
        warehouse = Warehouse(tenant_id=tenant, code="w", name="w")
        session.add_all([unit, category, warehouse])
        session.flush()
        product = Product(tenant_id=tenant, code="p", name="p", unit_id=unit.id, category_id=category.id)
        session.add(product)
        session.commit()
        product_id, warehouse_id = product.id, warehouse.id
    def post(_):
        with Session(engine) as session, ErpTenantUnitOfWork(session, tenant) as uow:
            InventoryPostingService(uow).post(effects=(InventoryEffect(
                product_id=product_id, warehouse_id=warehouse_id, delta_quantity=Decimal("1"),
                ledger_type=StockLedgerType.OTHER_IN, source_document_type="stock_in",
                source_document_id=uuid.uuid4(), source_item_id=uuid.uuid4(),
                source_document_no="TEST", source_version=1,
            ),), operator_id=uuid.uuid4())
            session.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(post, range(8)))
    with Session(engine) as session, ErpTenantUnitOfWork(session, tenant):
        assert session.exec(select(StockBalance.quantity)).one() == 8
        ledger_id = session.exec(select(StockLedger.id)).first()
    # Direct independent DML connection verifies database triggers, beyond ORM guards.
    with engine.connect() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(update(StockLedger.__table__).where(StockLedger.id == ledger_id).values(balance_after=999))
        connection.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(delete(StockLedger.__table__).where(StockLedger.id == ledger_id))
        connection.rollback()


@live
def test_module_entitlement_override_is_tenant_scoped(tenant):
    from app.modules.access import evaluate_module_access
    from app.platform.core.runtime_models import (
        ModuleEntitlementEffect,
        TenantModuleEntitlementOverride,
    )
    from app.platform.tenant_uow import PlatformTenantUnitOfWork
    with Session(engine) as session, PlatformTenantUnitOfWork(session, tenant):
        session.add(TenantModuleEntitlementOverride(
            tenant_id=tenant, module_code="erp", effect=ModuleEntitlementEffect.REVOKE, reason="isolated negative check",
        ))
        session.commit()
        assert not evaluate_module_access(session=session, tenant_id=tenant, module_code="erp").allowed
        assert evaluate_module_access(session=session, tenant_id=tenant, module_code="erp").error_code == "TENANT_MODULE_ENTITLEMENT_REQUIRED"
