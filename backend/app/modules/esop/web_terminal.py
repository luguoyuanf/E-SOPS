"""One browser terminal per tenant, provisioned by the module lifecycle."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.modules.esop.infrastructure.device_auth import _digest, resolve_device
from app.modules.esop.infrastructure.device_installation import allocate_terminal_serial
from app.modules.esop.infrastructure.models import DeviceCredential, Terminal
from app.modules.esop.infrastructure.tenant_uow import (
    EsopTenantUnitOfWork,
    EsopTenantUowDep,
)
from app.modules.esop.public_api.terminal_dto import WebTerminalBootstrapPublic
from app.platform.web_api import (
    CurrentPrincipal,
    SessionDep,
    UserDirectoryDep,
    require_module_access,
)

WEB_DEVICE_CODE = "WEB"
router = APIRouter(prefix="/esop", tags=["esop-terminal"])


def web_device_token(terminal_id: uuid.UUID) -> str:
    return _digest(f"web-terminal:{terminal_id}")


def initialize_web_terminal(session: Session, tenant_id: uuid.UUID) -> None:
    """Called by explicit tenant provisioning, never by a list/read request."""
    with EsopTenantUnitOfWork(session, tenant_id):
        terminal = session.exec(select(Terminal).where(
            Terminal.device_code == WEB_DEVICE_CODE,
        )).first()
        if terminal is not None:
            return
        terminal = Terminal(
            tenant_id=tenant_id, device_code=WEB_DEVICE_CODE,
            serial_number=allocate_terminal_serial(session),
            device_name="Web终端", app_version="Web版",
        )
        session.add(terminal)
        session.flush()
        session.add(DeviceCredential(
            device_code=f"web:{tenant_id}", tenant_id=tenant_id, terminal_id=terminal.id,
            token_hash=_digest(f"token:{web_device_token(terminal.id)}"),
        ))
        session.flush()


@router.get("/terminals/web-access", response_model=dict[str, bool],
            dependencies=[Depends(require_module_access("esop", "esop:device:list"))])
def web_terminal_access(uow: EsopTenantUowDep, principal: CurrentPrincipal,
                        users: UserDirectoryDep) -> dict[str, bool]:
    return {"allowed": principal.is_superuser or users.is_tenant_administrator(principal.id, uow.tenant_id)}


@router.post("/terminals/{terminal_id}/open-web", response_model=dict[str, str],
             dependencies=[Depends(require_module_access("esop", "esop:device:list"))])
def open_web_terminal(terminal_id: uuid.UUID, uow: EsopTenantUowDep,
                      principal: CurrentPrincipal, users: UserDirectoryDep) -> dict[str, str]:
    if not (principal.is_superuser or users.is_tenant_administrator(principal.id, uow.tenant_id)):
        raise HTTPException(status_code=403, detail="仅管理员可以打开 Web 终端")
    terminal = uow.session.get(Terminal, terminal_id)
    if terminal is None or terminal.tenant_id != uow.tenant_id or terminal.device_code != WEB_DEVICE_CODE or not terminal.is_active:
        raise HTTPException(status_code=404, detail="Web终端不存在或已停用")
    return {"path": f"/web-terminal/{terminal.id}"}


@router.get("/web-terminal/{terminal_id}", response_model=WebTerminalBootstrapPublic)
def anonymous_web_terminal(terminal_id: uuid.UUID, session: SessionDep,
                           response: Response) -> WebTerminalBootstrapPublic:
    # Resolve the trusted global device directory first; never accept a caller's tenant ID.
    credential = session.exec(select(DeviceCredential).where(
        DeviceCredential.terminal_id == terminal_id,
    )).first()
    if credential is None or credential.device_code != f"web:{credential.tenant_id}":
        raise HTTPException(status_code=404, detail="Web终端不存在")
    token = web_device_token(terminal_id)
    identity = resolve_device(session, token)
    response.headers["Cache-Control"] = "no-store"
    from app.modules.esop.terminal_routes import terminal_profile

    return WebTerminalBootstrapPublic(
        deviceToken=token, tenantId=identity.tenant_id, deviceId=terminal_id,
        profile=terminal_profile(session, identity),
    )


if __name__ == "__main__":
    from app.core.database import engine
    from app.platform.web_api import get_tenant_directory

    with Session(engine) as session:
        for tenant_id in get_tenant_directory(session).list_tenant_ids():
            initialize_web_terminal(session, tenant_id)
        session.commit()
