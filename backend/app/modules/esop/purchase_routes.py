"""Authenticated shared purchase content, editable only by platform root."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.clock import get_datetime_utc
from app.modules.esop.infrastructure.models import PurchaseContent
from app.modules.esop.public_api.purchase_dto import PurchasePageContent
from app.platform.web_api import CurrentPrincipal, SessionDep, require_module_access

router = APIRouter(prefix="/esop", tags=["esop-purchase"], dependencies=[Depends(require_module_access("esop", "esop:purchase:list"))])


@router.get("/purchase-content", response_model=PurchasePageContent)
def read_purchase_content(session: SessionDep) -> PurchasePageContent:
    row = session.get(PurchaseContent, 1)
    return PurchasePageContent.model_validate(row.content) if row else PurchasePageContent()


@router.put("/purchase-content", response_model=PurchasePageContent)
def save_purchase_content(session: SessionDep, principal: CurrentPrincipal, body: PurchasePageContent) -> PurchasePageContent:
    if not principal.is_superuser:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    row = session.get(PurchaseContent, 1)
    if row is None:
        row = PurchaseContent(content=body.model_dump(), updated_by=principal.id)
    else:
        row.content = body.model_dump()
        row.updated_by = principal.id
        row.updated_at = get_datetime_utc()
    session.add(row)
    session.commit()
    return body
