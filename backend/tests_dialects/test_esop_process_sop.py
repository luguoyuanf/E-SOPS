"""ESOP draft/review and tenant isolation on a disposable SQLite database."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.modules.esop.infrastructure.models import Operation, ProcessRoute, SopDocument
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    TenantScopeError,
)
from app.modules.esop.public_api.dto import (
    OperationInput,
    RouteInput,
    SopCreate,
    SopPage,
    SopReject,
    SopUpdate,
)
from app.modules.esop.routes import (
    approve_sop,
    create_operation,
    create_route,
    create_sop,
    list_sop_versions,
    list_sops,
    new_sop_version,
    reject_sop,
    rollback_sop_version,
    submit_sop,
    update_sop,
)
from app.platform.public_api.files import FileAssetSummary
from app.platform.web_api import Principal


class Products:
    def __init__(self, product_id: uuid.UUID) -> None:
        self.product_id = product_id

    def exists(self, product_id: uuid.UUID) -> bool:
        return product_id == self.product_id


class Files:
    def __init__(self, file_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.file_id = file_id
        self.tenant_id = tenant_id

    def get_accessible_file(
        self, *, tenant_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileAssetSummary | None:
        if tenant_id != self.tenant_id or file_id != self.file_id:
            return None
        return FileAssetSummary(id=file_id, original_name="work.png", content_type="image/png", size=24, sha256="0" * 64)


def test_sop_review_locks_version_and_tenant_reads():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"esop": None}},
    )
    SQLModel.metadata.create_all(
        engine, tables=[Operation.__table__, ProcessRoute.__table__, SopDocument.__table__]
    )
    tenant_a, tenant_b, product_id, file_id = (uuid.uuid4() for _ in range(4))
    principal = Principal(id=uuid.uuid4(), is_superuser=False)
    products = Products(product_id)
    files = Files(file_id, tenant_a)

    with Session(engine) as session:
        with EsopTenantUnitOfWork(session, tenant_a) as uow:
            operation = create_operation(uow, OperationInput(code="ASSY", name="装配"), None, None)
            route = create_route(
                uow, RouteInput(code="MAIN", name="主流程", operation_ids=[operation.id])
            )
            assert route.operation_ids == [operation.id]
            with pytest.raises(HTTPException) as duplicate_step:
                create_route(
                    uow, RouteInput(
                        code="BAD", name="重复步骤", operation_ids=[operation.id, operation.id]
                    ),
                )
            assert duplicate_step.value.status_code == 422
            sop = create_sop(
                uow, principal, products, files,
                SopCreate(
                    product_id=product_id, operation_id=operation.id, title="装配图",
                    pages=[SopPage(file_id=file_id, sort=0)],
                ),
            )
            with pytest.raises(HTTPException) as premature:
                approve_sop(uow, principal, sop.id)
            assert premature.value.status_code == 409
            submitted = submit_sop(uow, sop.id)
            assert submitted.status == "pending"
            approved = approve_sop(uow, principal, sop.id)
            assert approved.status == "approved"
            with pytest.raises(HTTPException) as immutable:
                update_sop(uow, files, sop.id, SopUpdate(title="改动", pages=[]))
            assert immutable.value.status_code == 409
            draft = new_sop_version(uow, principal, sop.id)
            assert draft.version == 2 and draft.status == "draft"
            with pytest.raises(HTTPException) as duplicate_version:
                new_sop_version(uow, principal, sop.id)
            assert duplicate_version.value.status_code == 409
            update_sop(uow, files, draft.id, SopUpdate(title="新版", pages=[]))
            with pytest.raises(HTTPException) as empty_draft:
                submit_sop(uow, draft.id)
            assert empty_draft.value.status_code == 422
            update_sop(
                uow, files, draft.id,
                SopUpdate(title="新版", pages=[SopPage(file_id=file_id, sort=0)]),
            )
            submit_sop(uow, draft.id)
            assert reject_sop(uow, principal, draft.id, SopReject(reason="内容不完整")).status == "rejected"
            assert update_sop(
                uow, files, draft.id,
                SopUpdate(title="已修订", pages=[SopPage(file_id=file_id, sort=0)]),
            ).status == "draft"
            assert session.get(SopDocument, sop.id).title == "装配图"
            with pytest.raises(HTTPException) as foreign_file:
                update_sop(
                    uow, files, draft.id,
                    SopUpdate(title="新版", pages=[SopPage(file_id=uuid.uuid4(), sort=0)]),
                )
            assert foreign_file.value.status_code == 422

            submit_sop(uow, draft.id)
            approve_sop(uow, principal, draft.id)
            restored = rollback_sop_version(uow, principal, sop.id)
            assert restored.version == 3 and restored.status == "draft"
            assert restored.pages == sop.pages and restored.title == sop.title
            assert [item.version for item in list_sop_versions(uow, sop.id).items] == [3, 2, 1]
            assert [item.version for item in list_sops(
                uow, product_id=product_id, status="approved", latest_only=True,
            ).items] == [2]
            with pytest.raises(HTTPException) as duplicate_rollback:
                rollback_sop_version(uow, principal, sop.id)
            assert duplicate_rollback.value.status_code == 409
            assert session.get(SopDocument, sop.id).status == "approved"

        with EsopTenantUnitOfWork(session, tenant_b) as uow:
            assert session.exec(select(SopDocument)).all() == []
            assert session.exec(select(Operation)).all() == []
            assert session.exec(select(ProcessRoute)).all() == []
            with pytest.raises(HTTPException) as cross_tenant:
                update_sop(uow, files, draft.id, SopUpdate(title="越权", pages=[]))
            assert cross_tenant.value.status_code == 404
        with pytest.raises(TenantScopeError):
            session.exec(select(SopDocument)).all()
