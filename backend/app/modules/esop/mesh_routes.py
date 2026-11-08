"""Activated native terminals may request limited maintenance enrollment."""

from fastapi import APIRouter, HTTPException, Response

from app.modules.esop.application.mesh_enrollment import issue_enrollment
from app.modules.esop.infrastructure.models import Terminal
from app.modules.esop.infrastructure.tenant_uow import EsopTenantUnitOfWork
from app.modules.esop.public_api.mesh_dto import (
    MeshEnrollmentPublic,
    MeshEnrollmentRequest,
)
from app.modules.esop.terminal_routes import DeviceDep
from app.platform.web_api import SessionDep, require_resolved_tenant_module_access

router = APIRouter(prefix="/esop", tags=["esop-terminal"])


@router.post("/terminal/mesh-enrollment", response_model=MeshEnrollmentPublic)
def enroll_terminal_mesh(
    session: SessionDep,
    device: DeviceDep,
    response: Response,
    body: MeshEnrollmentRequest | None = None,  # noqa: ARG001 - schema rejects injected authority
) -> MeshEnrollmentPublic:
    response.headers["Cache-Control"] = "no-store"
    with EsopTenantUnitOfWork(session, device.tenant_id):
        terminal = session.get(Terminal, device.terminal_id)
        if terminal is None or not terminal.is_active or terminal.tenant_id != device.tenant_id:
            raise HTTPException(status_code=401, detail="Invalid device credential")
        if terminal.device_code == "WEB" or terminal.device_code.startswith("web:"):
            raise HTTPException(status_code=403, detail="Web terminals cannot request mesh enrollment")
    require_resolved_tenant_module_access(
        session=session, tenant_id=device.tenant_id, module_code="esop",
    )
    return issue_enrollment(device.tenant_id, device.terminal_id)
