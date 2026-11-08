"""ESOP module contract."""

from app.modules.contracts import (
    LifecycleHooks,
    MigrationSpec,
    ModuleDefinition,
    ScheduleHandler,
)
from app.modules.esop.activation_routes import router as activation_router
from app.modules.esop.alarm_type_routes import router as alarm_type_router
from app.modules.esop.broadcast_routes import router as broadcast_router
from app.modules.esop.channel_routes import router as channel_router
from app.modules.esop.dashboard_routes import router as dashboard_router
from app.modules.esop.menu_access import menu_permission_visible, protected_user_ids
from app.modules.esop.mesh_routes import router as mesh_router
from app.modules.esop.operation_media import run_media_conversion
from app.modules.esop.ota_routes import router as ota_router
from app.modules.esop.plan_scheduler import run_plan_schedule
from app.modules.esop.product_sop_routes import router as product_sop_router
from app.modules.esop.production_routes import router as production_router
from app.modules.esop.purchase_routes import router as purchase_router
from app.modules.esop.report_change_routes import router as report_change_router
from app.modules.esop.report_routes import router as report_router
from app.modules.esop.routes import router
from app.modules.esop.sip_routes import router as sip_router
from app.modules.esop.terminal_routes import router as terminal_router
from app.modules.esop.web_terminal import initialize_web_terminal
from app.modules.esop.web_terminal import router as web_terminal_router

definition = ModuleDefinition(
    code="esop",
    version="0.1.0",
    dependencies=("platform", "erp"),
    lifecycle=LifecycleHooks(initialize_tenant=initialize_web_terminal),
    routers=(web_terminal_router, dashboard_router, purchase_router, activation_router, router, product_sop_router, production_router, terminal_router, mesh_router, report_router, sip_router, report_change_router, alarm_type_router, ota_router, channel_router, broadcast_router),
    api_prefix="/api/v1/esop",
    permission_prefix="esop",
    migration=MigrationSpec(
        namespace="esop",
        schema="esop",
        owned_tables=(
            "operation", "process_route", "sop_document", "product_sop_lock", "product_sop_version",
            "operation_file_rendition", "operation_media_job", "workshop",
            "production_line", "station", "production_order", "production_plan", "production_plan_group",
            "work_release", "work_release_assignment", "activation_key", "activation_unbind_log", "device_credential", "terminal_installation", "terminal",
            "production_report", "production_report_revision", "production_report_change", "sip_inspection", "alarm_event", "alarm_type_preference", "channel", "hardware_model", "ota_package",
            "channel_admin", "channel_customer_tenant", "broadcast", "broadcast_record", "advertisement", "purchase_content",
        ),
    ),
    schedules=("esop.plan.advance", "esop.media.convert"),
    schedule_handlers=(ScheduleHandler(code="esop.plan.advance", interval_seconds=30, handler=run_plan_schedule),
                       ScheduleHandler(code="esop.media.convert", interval_seconds=5, handler=run_media_conversion)),
    menu_permission_visible=menu_permission_visible,
    protected_user_ids=protected_user_ids,
    menus=(
        "esop:purchase:list",
        "esop:product:list", "esop:staff:list",
        "esop:operation:list", "esop:operation:create", "esop:operation:update", "esop:operation:delete",
        "esop:route:list", "esop:route:create", "esop:route:update",
        "esop:sop:list", "esop:sop:create", "esop:sop:update",
        "esop:sop:submit", "esop:sop:review", "esop:sop:upload",
        "esop:workshop:list", "esop:workshop:create", "esop:workshop:update", "esop:workshop:delete",
        "esop:line:list", "esop:line:create", "esop:line:update", "esop:line:delete",
        "esop:order:list", "esop:order:create", "esop:order:update",
        "esop:plan:list", "esop:plan:create", "esop:plan:update", "esop:plan:publish",
        "esop:device:issue", "esop:device:list", "esop:device:bind",
        "esop:report:create", "esop:report:list", "esop:report:export",
        "esop:sip:list",
        "esop:alarm:list",
        "esop:alarm:resolve",
        "esop:alarm:type:manage",
        "esop:ota:list", "esop:ota:manage", "esop:ota:publish",
        "esop:channel:portal", "esop:channel:admin", "esop:channel:issue",
        "esop:broadcast:list", "esop:broadcast:manage",
    ),
)
