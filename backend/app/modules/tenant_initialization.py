"""Dispatch module-owned defaults only from explicit tenant provisioning."""

import uuid

from sqlmodel import Session


def prepare_tenant_creation(*, session: Session) -> None:
    """Acquire module catalog locks before the new tenant row is inserted."""
    from app.modules.access import get_runtime_manifest
    from app.modules.registry import get_module_definitions

    definitions = get_module_definitions()
    for module in get_runtime_manifest().modules:
        hook = definitions[module.code].lifecycle.prepare_tenant_creation
        if hook is not None:
            hook(session)


def initialize_tenant_modules(*, session: Session, tenant_id: uuid.UUID) -> None:
    # Resolve lazily: Platform routes are imported while the registry is assembled.
    from app.modules.access import get_runtime_manifest
    from app.modules.registry import get_module_definitions

    definitions = get_module_definitions()
    for module in get_runtime_manifest().modules:
        hook = definitions[module.code].lifecycle.initialize_tenant
        if hook is not None:
            hook(session, tenant_id)
