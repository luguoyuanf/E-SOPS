"""Platform navigation seed and legacy menu migration service."""

from sqlmodel import Session, select

from app.core.clock import get_datetime_utc
from app.core.config import settings
from app.platform.core.authorization_models import Menu, RoleMenu


def ensure_menu(
    *,
    session: Session,
    title: str,
    type: str,
    sort: int,
    parent_id=None,
    route_path: str | None = None,
    route_name: str | None = None,
    component: str | None = None,
    icon: str | None = None,
    permission_code: str | None = None,
    is_visible: bool = True,
    is_active: bool = True,
) -> Menu:
    menu = None
    if permission_code:
        menu = session.exec(
            select(Menu).where(Menu.permission_code == permission_code)
        ).first()
    elif route_path:
        menu = session.exec(select(Menu).where(Menu.route_path == route_path)).first()

    if menu:
        changed = False
        for field, value in {
            "title": title,
            "type": type,
            "parent_id": parent_id,
            "route_path": route_path,
            "route_name": route_name,
            "component": component,
            "icon": icon,
            "is_visible": is_visible,
            "is_active": is_active,
        }.items():
            if value is not None and getattr(menu, field) != value:
                setattr(menu, field, value)
                changed = True
        if changed:
            session.add(menu)
            session.flush()
        return menu

    menu = Menu(
        title=title,
        type=type,
        parent_id=parent_id,
        route_path=route_path,
        route_name=route_name,
        component=component,
        icon=icon,
        permission_code=permission_code,
        sort=sort,
        is_visible=is_visible,
        is_active=is_active,
    )
    session.add(menu)
    session.flush()
    return menu


def seed_menus(*, session: Session) -> list[Menu]:
    remove_obsolete_menus(session=session)
    dashboard = ensure_menu(
        session=session,
        title="menu.dashboard",
        type="menu",
        route_path="/dashboard",
        route_name="Dashboard",
        component="#/views/dashboard/analytics/index.vue",
        icon="lucide:layout-dashboard",
        permission_code="dashboard:view",
        sort=0,
    )
    system = ensure_menu(
        session=session,
        title="menu.system",
        type="directory",
        route_path="/system",
        route_name="System",
        icon="lucide:settings",
        sort=10,
    )
    tenant_center = ensure_menu(
        session=session,
        title="menu.systemTenantCenter",
        type="directory",
        parent_id=system.id,
        route_path="/system/tenant-center",
        route_name="SystemTenantCenter",
        icon="lucide:building",
        sort=5,
    )
    basic_settings = ensure_menu(
        session=session,
        title="menu.infrastructure",
        type="directory",
        route_path="/basic-settings",
        route_name="BasicSettings",
        icon="lucide:settings-2",
        sort=15,
    )
    tenants = ensure_menu(
        session=session,
        title="menu.systemTenants",
        type="menu",
        parent_id=tenant_center.id,
        route_path="/system/tenants",
        route_name="SystemTenants",
        component="#/views/system/tenants/index.vue",
        icon="lucide:building-2",
        permission_code="platform:tenant:list",
        sort=10,
    )
    tenant_plans = ensure_menu(
        session=session,
        title="menu.systemTenantPlans",
        type="menu",
        parent_id=tenant_center.id,
        route_path="/system/tenant-plans",
        route_name="SystemTenantPlans",
        component="#/views/system/tenant-plans/index.vue",
        icon="lucide:package",
        permission_code="platform:plan:list",
        sort=20,
    )
    tenant_templates = ensure_menu(
        session=session,
        title="menu.systemTenantTemplates",
        type="menu",
        parent_id=tenant_center.id,
        route_path="/system/tenant-templates",
        route_name="SystemTenantTemplates",
        component="#/views/system/tenant-templates/index.vue",
        icon="lucide:layout-template",
        permission_code="platform:template:list",
        sort=30,
    )
    users = ensure_menu(
        session=session,
        title="menu.systemUsers",
        type="menu",
        parent_id=system.id,
        route_path="/system/users",
        route_name="SystemUsers",
        component="#/views/system/users/index.vue",
        icon="lucide:users",
        permission_code="system:user:list",
        sort=10,
    )
    roles = ensure_menu(
        session=session,
        title="menu.systemRoles",
        type="menu",
        parent_id=system.id,
        route_path="/system/roles",
        route_name="SystemRoles",
        component="#/views/system/roles/index.vue",
        icon="lucide:shield-check",
        permission_code="system:role:list",
        sort=20,
    )
    menus = ensure_menu(
        session=session,
        title="menu.systemMenus",
        type="menu",
        parent_id=system.id,
        route_path="/system/menus",
        route_name="SystemMenus",
        component="#/views/system/menus/index.vue",
        icon="lucide:menu",
        permission_code="system:menu:list",
        sort=30,
    )
    departments = ensure_menu(
        session=session,
        title="menu.systemDepartments",
        type="menu",
        parent_id=system.id,
        route_path="/system/departments",
        route_name="SystemDepartments",
        component="#/views/system/departments/index.vue",
        icon="lucide:building-2",
        permission_code="system:department:list",
        sort=40,
    )
    posts = ensure_menu(
        session=session,
        title="menu.systemPosts",
        type="menu",
        parent_id=system.id,
        route_path="/system/posts",
        route_name="SystemPosts",
        component="#/views/system/posts/index.vue",
        icon="lucide:briefcase-business",
        permission_code="system:post:list",
        sort=50,
    )
    dictionaries = ensure_menu(
        session=session,
        title="menu.systemDictionaries",
        type="menu",
        parent_id=system.id,
        route_path="/system/dictionaries",
        route_name="SystemDictionaries",
        component="#/views/system/dictionaries/index.vue",
        icon="lucide:book-open",
        permission_code="system:dict:list",
        sort=60,
    )
    system_settings = ensure_menu(
        session=session,
        title="menu.systemSettings",
        type="menu",
        parent_id=basic_settings.id,
        route_path="/basic-settings/settings",
        route_name="SystemSettings",
        component="#/views/system/settings/index.vue",
        icon="lucide:sliders-horizontal",
        permission_code="system:setting:list",
        sort=10,
    )
    oauth2 = ensure_menu(
        session=session,
        title="menu.oauth2",
        type="directory",
        parent_id=system.id,
        route_path="/system/oauth2",
        route_name="OAuth2",
        icon="lucide:shield",
        sort=85,
    )
    oauth2_clients = ensure_menu(
        session=session,
        title="menu.oauth2Clients",
        type="menu",
        parent_id=oauth2.id,
        route_path="/system/oauth2/clients",
        route_name="OAuth2Clients",
        component="#/views/oauth2/clients/index.vue",
        icon="lucide:hard-drive",
        permission_code="system:oauth2-client:list",
        sort=10,
    )
    oauth2_tokens = ensure_menu(
        session=session,
        title="menu.oauth2Tokens",
        type="menu",
        parent_id=oauth2.id,
        route_path="/system/oauth2/tokens",
        route_name="OAuth2Tokens",
        component="#/views/oauth2/tokens/index.vue",
        icon="lucide:key-round",
        permission_code="system:oauth2-token:list",
        sort=20,
    )
    social = ensure_menu(
        session=session,
        title="menu.socialLogin",
        type="directory",
        parent_id=system.id,
        route_path="/system/social",
        route_name="SocialLogin",
        icon="lucide:rocket",
        sort=86,
    )
    social_clients = ensure_menu(
        session=session,
        title="menu.socialClients",
        type="menu",
        parent_id=social.id,
        route_path="/system/social/clients",
        route_name="SocialClients",
        component="#/views/social/clients/index.vue",
        icon="lucide:settings-2",
        permission_code="system:social-client:list",
        sort=10,
    )
    social_users = ensure_menu(
        session=session,
        title="menu.socialUsers",
        type="menu",
        parent_id=social.id,
        route_path="/system/social/users",
        route_name="SocialUsers",
        component="#/views/social/users/index.vue",
        icon="lucide:users-round",
        permission_code="system:social-user:list",
        sort=20,
    )
    migrate_directory_menu(
        session=session,
        parent=system,
        route_name="Logs",
        legacy_paths=("/logs",),
        target_path="/system/logs",
        sort=90,
    )
    logs = ensure_menu(
        session=session,
        title="menu.logs",
        type="directory",
        parent_id=system.id,
        route_path="/system/logs",
        route_name="Logs",
        icon="lucide:clipboard-list",
        sort=90,
    )
    login_logs = ensure_menu(
        session=session,
        title="menu.loginLogs",
        type="menu",
        parent_id=logs.id,
        route_path="/system/logs/login",
        route_name="LoginLogs",
        component="#/views/logs/login/index.vue",
        icon="lucide:log-in",
        permission_code="system:login-log:list",
        sort=10,
    )
    operation_logs = ensure_menu(
        session=session,
        title="menu.operationLogs",
        type="menu",
        parent_id=logs.id,
        route_path="/system/logs/operation",
        route_name="OperationLogs",
        component="#/views/logs/operation/index.vue",
        icon="lucide:history",
        permission_code="system:operation-log:list",
        sort=20,
    )
    migrate_directory_menu(
        session=session,
        parent=basic_settings,
        route_name="Files",
        legacy_paths=("/files", "/system/files"),
        target_path="/basic-settings/files",
        sort=20,
    )
    files = ensure_menu(
        session=session,
        title="menu.files",
        type="directory",
        parent_id=basic_settings.id,
        route_path="/basic-settings/files",
        route_name="Files",
        icon="lucide:folder",
        sort=20,
    )
    if files.component is not None or files.permission_code is not None:
        files.component = None
        files.permission_code = None
        session.add(files)
        session.flush()
    file_channels = ensure_menu(
        session=session,
        title="menu.fileChannels",
        type="menu",
        parent_id=files.id,
        route_path="/basic-settings/files/channels",
        route_name="FileChannels",
        component="#/views/files/channels/index.vue",
        icon="lucide:database",
        permission_code="system:file:channel:list",
        sort=10,
    )
    file_config = ensure_menu(
        session=session,
        title="menu.fileConfig",
        type="menu",
        parent_id=files.id,
        route_path="/basic-settings/files/config",
        route_name="FileConfig",
        component="#/views/files/config/index.vue",
        icon="lucide:settings-2",
        permission_code="system:file:config:list",
        sort=20,
    )
    file_list = ensure_menu(
        session=session,
        title="menu.fileList",
        type="menu",
        parent_id=files.id,
        route_path="/basic-settings/files/list",
        route_name="FileList",
        component="#/views/files/index.vue",
        icon="lucide:files",
        permission_code="system:file:list",
        sort=30,
    )
    message_center = ensure_menu(
        session=session,
        title="menu.messageCenter",
        type="directory",
        parent_id=system.id,
        route_path="/system/message-center",
        route_name="MessageCenter",
        icon="lucide:messages-square",
        sort=110,
    )
    notices = ensure_menu(
        session=session,
        title="menu.notices",
        type="menu",
        parent_id=message_center.id,
        route_path="/system/message-center/notices",
        route_name="Notices",
        component="#/views/notices/index.vue",
        icon="lucide:megaphone",
        permission_code="system:notice:list",
        sort=10,
    )
    messages = ensure_menu(
        session=session,
        title="menu.messages",
        type="menu",
        parent_id=message_center.id,
        route_path="/system/message-center/messages",
        route_name="Messages",
        component="#/views/messages/index.vue",
        icon="lucide:mail",
        permission_code="personal:message:list",
        sort=20,
    )
    site_messages = ensure_menu(
        session=session,
        title="menu.siteMessages",
        type="directory",
        parent_id=message_center.id,
        route_path="/system/message-center/site-messages",
        route_name="SiteMessages",
        component="#/views/_core/router-view.vue",
        icon="lucide:inbox",
        sort=30,
    )
    site_message_templates = ensure_menu(
        session=session,
        title="menu.siteMessageTemplates",
        type="menu",
        parent_id=site_messages.id,
        route_path="/system/message-center/site-messages/templates",
        route_name="SiteMessageTemplates",
        component="#/views/site-messages/templates/index.vue",
        icon="lucide:archive",
        permission_code="system:site-message-template:list",
        sort=10,
    )
    site_message_list = ensure_menu(
        session=session,
        title="menu.siteMessageList",
        type="menu",
        parent_id=site_messages.id,
        route_path="/system/message-center/site-messages/list",
        route_name="SiteMessageList",
        component="#/views/site-messages/messages/index.vue",
        icon="lucide:edit-3",
        permission_code="system:site-message:list",
        sort=20,
    )
    sms = ensure_menu(
        session=session,
        title="menu.sms",
        type="directory",
        parent_id=message_center.id,
        route_path="/system/message-center/sms",
        route_name="Sms",
        component="#/views/_core/router-view.vue",
        icon="lucide:message-square-more",
        sort=40,
    )
    sms_channels = ensure_menu(
        session=session,
        title="menu.smsChannels",
        type="menu",
        parent_id=sms.id,
        route_path="/system/message-center/sms/channels",
        route_name="SmsChannels",
        component="#/views/sms/channels/index.vue",
        icon="lucide:messages-square",
        permission_code="system:sms-channel:list",
        sort=10,
    )
    sms_templates = ensure_menu(
        session=session,
        title="menu.smsTemplates",
        type="menu",
        parent_id=sms.id,
        route_path="/system/message-center/sms/templates",
        route_name="SmsTemplates",
        component="#/views/sms/templates/index.vue",
        icon="lucide:scroll-text",
        permission_code="system:sms-template:list",
        sort=20,
    )
    sms_logs = ensure_menu(
        session=session,
        title="menu.smsLogs",
        type="menu",
        parent_id=sms.id,
        route_path="/system/message-center/sms/logs",
        route_name="SmsLogs",
        component="#/views/sms/logs/index.vue",
        icon="lucide:send",
        permission_code="system:sms-log:list",
        sort=30,
    )
    mail = ensure_menu(
        session=session,
        title="menu.mail",
        type="directory",
        parent_id=message_center.id,
        route_path="/system/message-center/mail",
        route_name="Mail",
        component="#/views/_core/router-view.vue",
        icon="lucide:mail",
        sort=50,
    )
    mail_accounts = ensure_menu(
        session=session,
        title="menu.mailAccounts",
        type="menu",
        parent_id=mail.id,
        route_path="/system/message-center/mail/accounts",
        route_name="MailAccounts",
        component="#/views/mail/accounts/index.vue",
        icon="lucide:mail-check",
        permission_code="system:mail-account:list",
        sort=10,
    )
    mail_templates = ensure_menu(
        session=session,
        title="menu.mailTemplates",
        type="menu",
        parent_id=mail.id,
        route_path="/system/message-center/mail/templates",
        route_name="MailTemplates",
        component="#/views/mail/templates/index.vue",
        icon="lucide:scroll-text",
        permission_code="system:mail-template:list",
        sort=20,
    )
    mail_logs = ensure_menu(
        session=session,
        title="menu.mailLogs",
        type="menu",
        parent_id=mail.id,
        route_path="/system/message-center/mail/logs",
        route_name="MailLogs",
        component="#/views/mail/logs/index.vue",
        icon="lucide:send",
        permission_code="system:mail-log:list",
        sort=30,
    )
    items = ensure_menu(
        session=session,
        title="menu.items",
        type="menu",
        route_path="/items",
        route_name="Items",
        component="#/modules/items/views/index.vue",
        icon="lucide:list-todo",
        permission_code="business:item:list",
        sort=20,
    )
    erp = ensure_menu(
        session=session,
        title="ERP 系统",
        type="directory",
        route_path="/erp",
        route_name="Erp",
        icon="lucide:boxes",
        sort=21,
    )
    esop = ensure_menu(
        session=session,
        title="ESOP 作业指导",
        type="directory",
        route_path="/esop",
        route_name="Esop",
        icon="lucide:factory",
        sort=22,
    )
    esop_basic = ensure_menu(
        session=session, title="基础资料", type="directory",
        route_path="/esop/basic", route_name="EsopBasic", sort=24,
        icon="lucide:database",
    )
    # ensure_menu preserves None fields on existing records; explicitly promote this group.
    if esop_basic.parent_id is not None:
        esop_basic.parent_id = None
        session.add(esop_basic)
        session.flush()
    esop_resources = ensure_menu(
        session=session, title="产线与终端", type="directory",
        route_path="/esop/resources", route_name="EsopResources", sort=25,
        icon="lucide:network",
    )
    if esop_resources.parent_id is not None:
        esop_resources.parent_id = None
        esop_resources.sort = esop_basic.sort + 1
        session.add(esop_resources)
        session.flush()
    esop_sop_center = ensure_menu(
        session=session, title="SOP 管理", type="directory", parent_id=esop.id,
        route_path="/esop/sop-center", route_name="EsopSopCenter", sort=30,
        icon="lucide:book-open", is_visible=False,
    )
    esop_publish_center = ensure_menu(
        session=session, title="工单&发布", type="directory",
        route_path="/esop/publish-center", route_name="EsopPublishCenter", sort=23,
        icon="lucide:send",
    )
    if esop_publish_center.parent_id is not None:
        esop_publish_center.parent_id = None
        session.add(esop_publish_center)
        session.flush()
    esop_order_center = ensure_menu(
        session=session, title="生产订单", type="directory", parent_id=esop_publish_center.id,
        route_path="/esop/order-center", route_name="EsopOrderCenter", sort=40,
        icon="lucide:clipboard-list", is_visible=False,
    )
    esop_records = ensure_menu(
        session=session, title="生产记录", type="directory", parent_id=esop_publish_center.id,
        route_path="/esop/records", route_name="EsopRecords", sort=60,
        icon="lucide:history", is_visible=False,
    )
    esop_services = ensure_menu(
        session=session, title="授权与服务", type="directory", parent_id=esop_resources.id,
        route_path="/esop/services", route_name="EsopServices", sort=70,
        icon="lucide:shield-check",
    )
    esop_products = ensure_menu(
        session=session, title="产品", type="menu", parent_id=esop_basic.id,
        route_path="/esop/basic/products", route_name="EsopProducts",
        component="#/modules/erp/views/products/index.vue",
        permission_code="esop:product:list", sort=10,
        icon="lucide:package",
        is_visible=False,
    )
    esop_operations = ensure_menu(
        session=session,
        title="SOP列表",
        type="menu",
        parent_id=esop.id,
        route_path="/esop/basic/operations",
        route_name="EsopOperations",
        component="#/modules/esop/views/sops/index.vue",
        permission_code="esop:operation:list",
        sort=10,
        icon="lucide:settings-2",
    )
    esop_routes = ensure_menu(
        session=session,
        title="工艺流程",
        type="menu",
        parent_id=esop_basic.id,
        route_path="/esop/basic/routes",
        route_name="EsopRoutes",
        component="#/modules/esop/views/routes/index.vue",
        permission_code="esop:route:list",
        sort=20,
        icon="lucide:route",
        is_visible=False,
    )
    esop_sops = ensure_menu(
        session=session,
        title="SOP 管理",
        type="menu",
        parent_id=esop_sop_center.id,
        route_path="/esop/sop-center/sops",
        route_name="EsopSops",
        component="#/modules/esop/views/sops/index.vue",
        permission_code="esop:sop:list",
        sort=30,
        icon="lucide:file-text",
        is_visible=False,
    )
    esop_review = ensure_menu(
        session=session,
        title="SOP 审核",
        type="menu",
        parent_id=esop.id,
        route_path="/esop/sop-center/review",
        route_name="EsopReview",
        component="#/modules/esop/views/review/index.vue",
        permission_code="esop:sop:review",
        sort=40,
        icon="lucide:clipboard-check",
    )
    esop_workshops = ensure_menu(
        session=session, title="车间", type="menu", parent_id=esop_basic.id,
        route_path="/esop/basic/workshops", route_name="EsopWorkshops",
        component="#/modules/esop/views/lines/index.vue",
        permission_code="esop:workshop:list", sort=40,
        icon="lucide:warehouse",
    )
    esop_staff = ensure_menu(
        session=session, title="员工", type="menu", parent_id=esop_basic.id,
        route_path="/esop/basic/staff", route_name="EsopStaff",
        component="#/views/system/users/index.vue",
        permission_code="esop:staff:list", sort=50,
        icon="lucide:users",
    )
    esop_lines = ensure_menu(
        session=session,
        title="产线与工位",
        type="menu",
        parent_id=esop_resources.id,
        route_path="/esop/resources/lines",
        route_name="EsopLines",
        component="#/modules/esop/views/lines/index.vue",
        permission_code="esop:line:list",
        sort=50,
        icon="lucide:workflow",
    )
    esop_orders = ensure_menu(
        session=session,
        title="生产订单",
        type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/order-center/orders",
        route_name="EsopOrders",
        component="#/modules/esop/views/orders/index.vue",
        permission_code="esop:order:list",
        sort=60,
        icon="lucide:clipboard-list",
    )
    esop_plans = ensure_menu(
        session=session,
        title="排产发布",
        type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/publish-center/plans",
        route_name="EsopPlans",
        component="#/modules/esop/views/plans/index.vue",
        permission_code="esop:plan:list",
        sort=70,
        icon="lucide:calendar-check",
    )
    esop_broadcasts = ensure_menu(
        session=session, title="广播发布", type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/publish-center/broadcasts",
        route_name="EsopBroadcasts",
        component="#/modules/esop/views/broadcasts/index.vue",
        permission_code="esop:broadcast:list", sort=80,
        icon="lucide:megaphone",
    )
    esop_reports = ensure_menu(
        session=session,
        title="报工追溯",
        type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/records/reports",
        route_name="EsopReports",
        component="#/modules/esop/views/reports/index.vue",
        permission_code="esop:report:list",
        sort=80,
        icon="lucide:file-clock",
    )
    esop_alarms = ensure_menu(
        session=session,
        title="报警记录",
        type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/records/alarms",
        route_name="EsopAlarms",
        component="#/modules/esop/views/alarms/index.vue",
        permission_code="esop:alarm:list",
        sort=90,
        icon="lucide:triangle-alert",
    )
    # These two entries are explicitly ordered last under 工单&发布.
    reports_sort = max(esop_orders.sort, esop_plans.sort, esop_broadcasts.sort) + 10
    if esop_reports.sort != reports_sort or esop_alarms.sort != reports_sort + 10:
        esop_reports.sort = reports_sort
        esop_alarms.sort = reports_sort + 10
        session.add(esop_reports)
        session.add(esop_alarms)
        session.flush()
    esop_sip = ensure_menu(
        session=session,
        title="SIP 点检",
        type="menu",
        parent_id=esop_publish_center.id,
        route_path="/esop/records/sip",
        route_name="EsopSip",
        component="#/modules/esop/views/sip/index.vue",
        permission_code="esop:sip:list",
        sort=reports_sort + 5,
        icon="lucide:scan-search",
    )
    esop_data_screen = ensure_menu(
        session=session, title="数据大屏", type="menu", parent_id=esop_publish_center.id,
        route_path="/esop/publish-center/data-screen", route_name="EsopDataScreen",
        component="#/modules/esop/views/data-screen/launch.vue",
        sort=esop_alarms.sort + 10,
        icon="lucide:monitor-dot",
    )
    esop_terminals = ensure_menu(
        session=session,
        title="终端管理",
        type="menu",
        parent_id=esop_resources.id,
        route_path="/esop/resources/terminals",
        route_name="EsopTerminals",
        component="#/modules/esop/views/terminals/index.vue",
        permission_code="esop:device:list",
        sort=100,
        icon="lucide:monitor",
    )
    esop_keys = ensure_menu(
        session=session,
        title="激活密钥",
        type="menu",
        parent_id=esop_services.id,
        route_path="/esop/services/activation-keys",
        route_name="EsopActivationKeys",
        component="#/modules/esop/views/activation-keys/index.vue",
        permission_code="esop:device:key-list",
        sort=110,
        icon="lucide:key-round",
    )
    esop_storage = ensure_menu(
        session=session,
        title="存储包发放",
        type="menu",
        parent_id=esop_services.id,
        route_path="/esop/services/storage-grants",
        route_name="EsopStorageGrants",
        component="#/modules/esop/views/storage-grants/index.vue",
        permission_code="system:tenant:list",
        sort=120,
        icon="lucide:hard-drive",
    )
    esop_ota = ensure_menu(
        session=session,
        title="渠道 OTA",
        type="menu",
        parent_id=esop_services.id,
        route_path="/esop/services/ota",
        route_name="EsopOta",
        component="#/modules/esop/views/ota/index.vue",
        permission_code="esop:ota:list",
        sort=130,
        icon="lucide:cloud-download",
    )
    esop_purchase = ensure_menu(
        session=session,
        title="购买与扩容",
        type="menu",
        parent_id=esop_services.id,
        route_path="/esop/services/purchase",
        route_name="EsopPurchase",
        permission_code="esop:purchase:list",
        component="#/modules/esop/views/purchase/index.vue",
        sort=140,
        icon="lucide:shopping-cart",
    )
    esop_channel_workspace = ensure_menu(
        session=session,
        title="渠道工作台",
        type="menu",
        parent_id=esop_services.id,
        route_path="/esop/services/channel-workspace",
        route_name="EsopChannelWorkspace",
        component="#/modules/esop/views/channel-workspace/index.vue",
        permission_code="esop:channel:portal",
        sort=150,
        icon="lucide:handshake",
    )
    erp_platform_units = ensure_menu(
        session=session,
        title="平台单位管理",
        type="menu",
        parent_id=basic_settings.id,
        route_path="/erp/platform/units",
        route_name="ErpPlatformUnits",
        component="#/modules/erp/views/platform/units/index.vue",
        icon="lucide:ruler",
        permission_code="platform:erp-unit:list",
        sort=60,
    )
    erp_home = ensure_menu(
        session=session,
        title="首页",
        type="menu",
        parent_id=erp.id,
        route_path="/erp/home",
        route_name="ErpHome",
        component="#/modules/erp/views/statistics/index.vue",
        icon="lucide:house",
        permission_code="erp:statistics:query",
        sort=1,
    )
    erp_purchase = ensure_menu(
        session=session,
        title="采购管理",
        type="directory",
        parent_id=erp.id,
        route_path="/erp/purchase",
        route_name="ErpPurchase",
        icon="lucide:shopping-basket",
        sort=10,
    )
    erp_sale = ensure_menu(
        session=session,
        title="销售管理",
        type="directory",
        parent_id=erp.id,
        route_path="/erp/sale",
        route_name="ErpSale",
        icon="lucide:chart-no-axes-combined",
        sort=20,
    )
    erp_product_management = ensure_menu(
        session=session,
        title="产品管理",
        type="directory",
        parent_id=esop.id if settings.APP_EDITION == "esop" else erp.id,
        route_path="/erp/product",
        route_name="ErpProductManagement",
        icon="lucide:package",
        sort=0 if settings.APP_EDITION == "esop" else 40,
    )
    erp_products = ensure_menu(
        session=session,
        title="产品信息",
        type="menu",
        parent_id=erp_product_management.id,
        route_path="/erp/product/products",
        route_name="ErpProducts",
        component="#/modules/erp/views/products/index.vue",
        icon="lucide:package-search",
        permission_code="erp:product:list",
        sort=10,
    )
    erp_product_categories = ensure_menu(
        session=session,
        title="产品分类",
        type="menu",
        parent_id=erp_product_management.id,
        route_path="/erp/product/categories",
        route_name="ErpProductCategories",
        component="#/modules/erp/views/settings/index.vue",
        icon="lucide:folder-tree",
        permission_code="erp:product-category:list",
        sort=20,
    )
    erp_product_units = ensure_menu(
        session=session,
        title="产品单位",
        type="menu",
        parent_id=erp_product_management.id,
        route_path="/erp/product/units",
        route_name="ErpProductUnits",
        component="#/modules/erp/views/settings/index.vue",
        icon="lucide:ruler",
        permission_code="erp:product-unit:list",
        sort=30,
    )
    erp_suppliers = ensure_menu(
        session=session,
        title="供应商管理",
        type="menu",
        parent_id=erp_purchase.id,
        route_path="/erp/purchase/suppliers",
        route_name="ErpSuppliers",
        component="#/modules/erp/views/counterparties/index.vue",
        icon="lucide:contact-round",
        permission_code="erp:supplier:list",
        sort=10,
    )
    erp_purchase_orders = ensure_menu(
        session=session,
        title="采购订单",
        type="menu",
        parent_id=erp_purchase.id,
        route_path="/erp/purchase/orders",
        route_name="ErpPurchaseOrders",
        component="#/modules/erp/views/purchase/orders/index.vue",
        icon="lucide:shopping-cart",
        permission_code="erp:purchase-order:list",
        sort=20,
    )
    erp_purchase_ins = ensure_menu(
        session=session,
        title="采购入库",
        type="menu",
        parent_id=erp_purchase.id,
        route_path="/erp/purchase/ins",
        route_name="ErpPurchaseIns",
        component="#/modules/erp/views/purchase/ins/index.vue",
        icon="lucide:package-check",
        permission_code="erp:purchase-in:list",
        sort=30,
    )
    erp_purchase_returns = ensure_menu(
        session=session,
        title="采购退货",
        type="menu",
        parent_id=erp_purchase.id,
        route_path="/erp/purchase/returns",
        route_name="ErpPurchaseReturns",
        component="#/modules/erp/views/purchase/returns/index.vue",
        icon="lucide:package-x",
        permission_code="erp:purchase-return:list",
        sort=40,
    )
    erp_customers = ensure_menu(
        session=session,
        title="客户信息",
        type="menu",
        parent_id=erp_sale.id,
        route_path="/erp/sale/customers",
        route_name="ErpCustomers",
        component="#/modules/erp/views/counterparties/index.vue",
        icon="lucide:users-round",
        permission_code="erp:customer:list",
        sort=10,
    )
    erp_sale_orders = ensure_menu(
        session=session,
        title="销售订单",
        type="menu",
        parent_id=erp_sale.id,
        route_path="/erp/sale/orders",
        route_name="ErpSaleOrders",
        component="#/modules/erp/views/sale/orders/index.vue",
        icon="lucide:receipt-text",
        permission_code="erp:sale-order:list",
        sort=20,
    )
    erp_sale_outs = ensure_menu(
        session=session,
        title="销售出库",
        type="menu",
        parent_id=erp_sale.id,
        route_path="/erp/sale/outs",
        route_name="ErpSaleOuts",
        component="#/modules/erp/views/sale/outs/index.vue",
        icon="lucide:package-minus",
        permission_code="erp:sale-out:list",
        sort=30,
    )
    erp_sale_returns = ensure_menu(
        session=session,
        title="销售退货",
        type="menu",
        parent_id=erp_sale.id,
        route_path="/erp/sale/returns",
        route_name="ErpSaleReturns",
        component="#/modules/erp/views/sale/returns/index.vue",
        icon="lucide:package-plus",
        permission_code="erp:sale-return:list",
        sort=40,
    )
    # Move the current stock page before creating the /erp/stock directory so
    # existing role grants stay attached to the product-stock entry.
    erp_stock_balance = ensure_menu(
        session=session,
        title="产品库存",
        type="menu",
        route_path="/erp/stock/balances",
        route_name="ErpStockBalance",
        component="#/modules/erp/views/stock/index.vue",
        icon="lucide:boxes",
        permission_code="erp:stock:list",
        sort=20,
    )
    erp_stock_management = ensure_menu(
        session=session,
        title="产品库存管理",
        type="directory",
        parent_id=erp.id,
        route_path="/erp/stock",
        route_name="ErpStockManagement",
        icon="lucide:warehouse",
        sort=30,
    )
    erp_stock_balance = ensure_menu(
        session=session,
        title="产品库存",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/balances",
        route_name="ErpStockBalance",
        component="#/modules/erp/views/stock/index.vue",
        icon="lucide:boxes",
        permission_code="erp:stock:list",
        sort=20,
    )
    erp_stock_ledger = ensure_menu(
        session=session,
        title="出入库明细",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/ledger",
        route_name="ErpStockLedger",
        component="#/modules/erp/views/stock/index.vue",
        icon="lucide:scroll-text",
        permission_code="erp:stock-record:list",
        sort=30,
    )
    erp_warehouses = ensure_menu(
        session=session,
        title="仓库信息",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/warehouses",
        route_name="ErpWarehouses",
        component="#/modules/erp/views/settings/index.vue",
        icon="lucide:warehouse",
        permission_code="erp:warehouse:list",
        sort=10,
    )
    erp_stock_other_in = ensure_menu(
        session=session,
        title="其它入库",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/other-in",
        route_name="ErpStockOtherIn",
        component="#/modules/erp/views/stock/documents/index.vue",
        icon="lucide:package-plus",
        permission_code="erp:stock-in:list",
        sort=40,
    )
    erp_stock_other_out = ensure_menu(
        session=session,
        title="其它出库",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/other-out",
        route_name="ErpStockOtherOut",
        component="#/modules/erp/views/stock/documents/index.vue",
        icon="lucide:package-minus",
        permission_code="erp:stock-out:list",
        sort=50,
    )
    erp_stock_move = ensure_menu(
        session=session,
        title="库存调拨",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/move",
        route_name="ErpStockMove",
        component="#/modules/erp/views/stock/documents/index.vue",
        icon="lucide:arrow-left-right",
        permission_code="erp:stock-move:list",
        sort=60,
    )
    erp_stock_check = ensure_menu(
        session=session,
        title="库存盘点",
        type="menu",
        parent_id=erp_stock_management.id,
        route_path="/erp/stock/check",
        route_name="ErpStockCheck",
        component="#/modules/erp/views/stock/documents/index.vue",
        icon="lucide:clipboard-check",
        permission_code="erp:stock-check:list",
        sort=70,
    )
    erp_finance = ensure_menu(
        session=session,
        title="财务管理",
        type="directory",
        parent_id=erp.id,
        route_path="/erp/finance",
        route_name="ErpFinance",
        icon="lucide:landmark",
        sort=50,
    )
    erp_settlement_accounts = ensure_menu(
        session=session,
        title="结算账户",
        type="menu",
        parent_id=erp_finance.id,
        route_path="/erp/finance/accounts",
        route_name="ErpSettlementAccounts",
        component="#/modules/erp/views/finance/accounts/index.vue",
        icon="lucide:landmark",
        permission_code="erp:account:list",
        sort=10,
    )
    erp_finance_payments = ensure_menu(
        session=session,
        title="付款单",
        type="menu",
        parent_id=erp_finance.id,
        route_path="/erp/finance/payments",
        route_name="ErpFinancePayments",
        component="#/modules/erp/views/finance/payments/index.vue",
        icon="lucide:badge-dollar-sign",
        permission_code="erp:finance-payment:list",
        sort=20,
    )
    erp_finance_receipts = ensure_menu(
        session=session,
        title="收款单",
        type="menu",
        parent_id=erp_finance.id,
        route_path="/erp/finance/receipts",
        route_name="ErpFinanceReceipts",
        component="#/modules/erp/views/finance/receipts/index.vue",
        icon="lucide:circle-dollar-sign",
        permission_code="erp:finance-receipt:list",
        sort=30,
    )
    erp_action_logs = ensure_menu(
        session=session,
        title="操作日志",
        type="menu",
        parent_id=erp_finance.id,
        route_path="/erp/finance/action-logs",
        route_name="ErpActionLogs",
        component="#/modules/erp/views/audit/action-logs/index.vue",
        icon="lucide:history",
        permission_code="erp:audit:list",
        sort=40,
    )
    button_permissions = [
        (erp_platform_units.id, "新增平台单位", "platform:erp-unit:create", 1),
        (erp_platform_units.id, "编辑平台单位", "platform:erp-unit:update", 2),
        (tenants.id, "新增租户", "platform:tenant:create", 6),
        (tenants.id, "编辑租户", "platform:tenant:update", 7),
        (tenants.id, "停用租户", "platform:tenant:delete", 8),
        (tenants.id, "生命周期操作", "platform:tenant:lifecycle", 9),
        (tenants.id, "同步租户菜单", "platform:tenant:sync-menu", 10),
        (tenant_plans.id, "新增套餐", "platform:plan:create", 9),
        (tenant_plans.id, "编辑套餐", "platform:plan:update", 10),
        (tenant_plans.id, "删除套餐", "platform:plan:delete", 11),
        (tenant_plans.id, "套餐菜单授权", "platform:plan:grant-menu", 12),
        (tenant_plans.id, "同步套餐菜单", "platform:plan:sync-menu", 13),
        (tenant_templates.id, "新增模板", "platform:template:create", 12),
        (tenant_templates.id, "编辑模板", "platform:template:update", 13),
        (tenant_templates.id, "删除模板", "platform:template:delete", 14),
        (users.id, "新增用户", "system:user:create", 11),
        (users.id, "编辑用户", "system:user:update", 12),
        (users.id, "删除用户", "system:user:delete", 13),
        (roles.id, "新增角色", "system:role:create", 21),
        (roles.id, "编辑角色", "system:role:update", 22),
        (roles.id, "删除角色", "system:role:delete", 23),
        (menus.id, "新增菜单", "system:menu:create", 31),
        (menus.id, "编辑菜单", "system:menu:update", 32),
        (menus.id, "删除菜单", "system:menu:delete", 33),
        (erp_stock_other_in.id, "新建其他入库", "erp:stock-in:create", 1),
        (erp_stock_other_in.id, "编辑其他入库", "erp:stock-in:update", 2),
        (erp_stock_other_in.id, "删除其他入库", "erp:stock-in:delete", 3),
        (erp_stock_other_in.id, "审核其他入库", "erp:stock-in:approve", 4),
        (erp_stock_other_in.id, "反审核其他入库", "erp:stock-in:reverse", 5),
        (erp_stock_other_in.id, "导出其他入库", "erp:stock-in:export", 6),
        (erp_stock_other_out.id, "新建其他出库", "erp:stock-out:create", 1),
        (erp_stock_other_out.id, "编辑其他出库", "erp:stock-out:update", 2),
        (erp_stock_other_out.id, "删除其他出库", "erp:stock-out:delete", 3),
        (erp_stock_other_out.id, "审核其他出库", "erp:stock-out:approve", 4),
        (erp_stock_other_out.id, "反审核其他出库", "erp:stock-out:reverse", 5),
        (erp_stock_other_out.id, "导出其他出库", "erp:stock-out:export", 6),
        (erp_stock_move.id, "新建库存调拨", "erp:stock-move:create", 1),
        (erp_stock_move.id, "编辑库存调拨", "erp:stock-move:update", 2),
        (erp_stock_move.id, "删除库存调拨", "erp:stock-move:delete", 3),
        (erp_stock_move.id, "审核库存调拨", "erp:stock-move:approve", 4),
        (erp_stock_move.id, "反审核库存调拨", "erp:stock-move:reverse", 5),
        (erp_stock_move.id, "导出库存调拨", "erp:stock-move:export", 6),
        (erp_stock_check.id, "新建库存盘点", "erp:stock-check:create", 1),
        (erp_stock_check.id, "编辑库存盘点", "erp:stock-check:update", 2),
        (erp_stock_check.id, "删除库存盘点", "erp:stock-check:delete", 3),
        (erp_stock_check.id, "审核库存盘点", "erp:stock-check:approve", 4),
        (erp_stock_check.id, "反审核库存盘点", "erp:stock-check:reverse", 5),
        (erp_stock_check.id, "导出库存盘点", "erp:stock-check:export", 6),
        (erp_stock_balance.id, "导出库存余额", "erp:stock:export", 1),
        (erp_stock_ledger.id, "导出库存流水", "erp:stock-record:export", 1),
        (erp_home.id, "查看对账结果", "erp:reconciliation:read", 1),
        (erp_home.id, "执行库存与结算对账", "erp:reconciliation:execute", 2),
        (erp_product_units.id, "新增产品单位", "erp:product-unit:create", 1),
        (erp_product_units.id, "编辑产品单位", "erp:product-unit:update", 2),
        (erp_product_units.id, "删除产品单位", "erp:product-unit:delete", 3),
        (erp_product_units.id, "导出产品单位", "erp:product-unit:export", 4),
        (erp_product_categories.id, "新增产品分类", "erp:product-category:create", 1),
        (erp_product_categories.id, "编辑产品分类", "erp:product-category:update", 2),
        (erp_product_categories.id, "删除产品分类", "erp:product-category:delete", 3),
        (erp_product_categories.id, "导出产品分类", "erp:product-category:export", 4),
        (erp_warehouses.id, "新增仓库", "erp:warehouse:create", 1),
        (erp_warehouses.id, "编辑仓库", "erp:warehouse:update", 2),
        (erp_warehouses.id, "删除仓库", "erp:warehouse:delete", 3),
        (erp_warehouses.id, "导出仓库", "erp:warehouse:export", 4),
        (erp_warehouses.id, "授权仓库用户", "erp:warehouse:assign", 5),
        (erp_suppliers.id, "新增供应商", "erp:supplier:create", 1),
        (erp_suppliers.id, "编辑供应商", "erp:supplier:update", 2),
        (erp_suppliers.id, "删除供应商", "erp:supplier:delete", 3),
        (erp_suppliers.id, "导出供应商", "erp:supplier:export", 4),
        (erp_customers.id, "新增客户", "erp:customer:create", 1),
        (erp_customers.id, "编辑客户", "erp:customer:update", 2),
        (erp_customers.id, "删除客户", "erp:customer:delete", 3),
        (erp_customers.id, "导出客户", "erp:customer:export", 4),
        (erp_settlement_accounts.id, "新增结算账户", "erp:account:create", 1),
        (erp_settlement_accounts.id, "编辑结算账户", "erp:account:update", 2),
        (erp_settlement_accounts.id, "删除结算账户", "erp:account:delete", 3),
        (erp_settlement_accounts.id, "查看敏感账号", "erp:finance-sensitive:read", 4),
        (erp_settlement_accounts.id, "导出结算账户", "erp:account:export", 5),
        (erp_finance_payments.id, "新建付款单", "erp:finance-payment:create", 1),
        (erp_finance_payments.id, "编辑付款单", "erp:finance-payment:update", 2),
        (erp_finance_payments.id, "删除付款单", "erp:finance-payment:delete", 3),
        (erp_finance_payments.id, "审核付款单", "erp:finance-payment:approve", 4),
        (erp_finance_payments.id, "反审核付款单", "erp:finance-payment:reverse", 5),
        (erp_finance_payments.id, "导出付款单", "erp:finance-payment:export", 6),
        (erp_finance_receipts.id, "新建收款单", "erp:finance-receipt:create", 1),
        (erp_finance_receipts.id, "编辑收款单", "erp:finance-receipt:update", 2),
        (erp_finance_receipts.id, "删除收款单", "erp:finance-receipt:delete", 3),
        (erp_finance_receipts.id, "审核收款单", "erp:finance-receipt:approve", 4),
        (erp_finance_receipts.id, "反审核收款单", "erp:finance-receipt:reverse", 5),
        (erp_finance_receipts.id, "导出收款单", "erp:finance-receipt:export", 6),
        (erp_purchase_orders.id, "新建采购订单", "erp:purchase-order:create", 1),
        (erp_purchase_orders.id, "编辑采购订单", "erp:purchase-order:update", 2),
        (erp_purchase_orders.id, "删除采购订单", "erp:purchase-order:delete", 3),
        (erp_purchase_orders.id, "审核采购订单", "erp:purchase-order:approve", 4),
        (erp_purchase_orders.id, "反审核采购订单", "erp:purchase-order:reverse", 5),
        (erp_purchase_orders.id, "导出采购订单", "erp:purchase-order:export", 6),
        (erp_purchase_ins.id, "新建采购入库", "erp:purchase-in:create", 1),
        (erp_purchase_ins.id, "编辑采购入库", "erp:purchase-in:update", 2),
        (erp_purchase_ins.id, "删除采购入库", "erp:purchase-in:delete", 3),
        (erp_purchase_ins.id, "审核采购入库", "erp:purchase-in:approve", 4),
        (erp_purchase_ins.id, "反审核采购入库", "erp:purchase-in:reverse", 5),
        (erp_purchase_ins.id, "导出采购入库", "erp:purchase-in:export", 6),
        (erp_purchase_returns.id, "新建采购退货", "erp:purchase-return:create", 1),
        (erp_purchase_returns.id, "编辑采购退货", "erp:purchase-return:update", 2),
        (erp_purchase_returns.id, "删除采购退货", "erp:purchase-return:delete", 3),
        (erp_purchase_returns.id, "审核采购退货", "erp:purchase-return:approve", 4),
        (erp_purchase_returns.id, "反审核采购退货", "erp:purchase-return:reverse", 5),
        (erp_purchase_returns.id, "导出采购退货", "erp:purchase-return:export", 6),
        (erp_sale_orders.id, "新建销售订单", "erp:sale-order:create", 1),
        (erp_sale_orders.id, "编辑销售订单", "erp:sale-order:update", 2),
        (erp_sale_orders.id, "删除销售订单", "erp:sale-order:delete", 3),
        (erp_sale_orders.id, "审核销售订单", "erp:sale-order:approve", 4),
        (erp_sale_orders.id, "反审核销售订单", "erp:sale-order:reverse", 5),
        (erp_sale_orders.id, "导出销售订单", "erp:sale-order:export", 6),
        (erp_sale_outs.id, "新建销售出库", "erp:sale-out:create", 1),
        (erp_sale_outs.id, "编辑销售出库", "erp:sale-out:update", 2),
        (erp_sale_outs.id, "删除销售出库", "erp:sale-out:delete", 3),
        (erp_sale_outs.id, "审核销售出库", "erp:sale-out:approve", 4),
        (erp_sale_outs.id, "反审核销售出库", "erp:sale-out:reverse", 5),
        (erp_sale_outs.id, "导出销售出库", "erp:sale-out:export", 6),
        (erp_sale_returns.id, "新建销售退货", "erp:sale-return:create", 1),
        (erp_sale_returns.id, "编辑销售退货", "erp:sale-return:update", 2),
        (erp_sale_returns.id, "删除销售退货", "erp:sale-return:delete", 3),
        (erp_sale_returns.id, "审核销售退货", "erp:sale-return:approve", 4),
        (erp_sale_returns.id, "反审核销售退货", "erp:sale-return:reverse", 5),
        (erp_sale_returns.id, "导出销售退货", "erp:sale-return:export", 6),
        (erp.id, "查看单据附件", "erp:attachment:list", 91),
        (erp.id, "上传单据附件", "erp:attachment:create", 92),
        (erp.id, "删除单据附件", "erp:attachment:delete", 93),
        (departments.id, "新增部门", "system:department:create", 41),
        (departments.id, "编辑部门", "system:department:update", 42),
        (departments.id, "删除部门", "system:department:delete", 43),
        (posts.id, "新增岗位", "system:post:create", 51),
        (posts.id, "编辑岗位", "system:post:update", 52),
        (posts.id, "删除岗位", "system:post:delete", 53),
        (dictionaries.id, "新增字典", "system:dict:create", 61),
        (dictionaries.id, "编辑字典", "system:dict:update", 62),
        (dictionaries.id, "删除字典", "system:dict:delete", 63),
        (system_settings.id, "编辑参数", "system:setting:update", 71),
        (oauth2_clients.id, "新增OAuth2客户端", "system:oauth2-client:create", 82),
        (oauth2_clients.id, "编辑OAuth2客户端", "system:oauth2-client:update", 83),
        (oauth2_clients.id, "删除OAuth2客户端", "system:oauth2-client:delete", 84),
        (oauth2_tokens.id, "吊销OAuth2令牌", "system:oauth2-token:delete", 85),
        (social_clients.id, "新增三方客户端", "system:social-client:create", 86),
        (social_clients.id, "编辑三方客户端", "system:social-client:update", 87),
        (social_clients.id, "删除三方客户端", "system:social-client:delete", 88),
        (file_list.id, "上传文件", "system:file:upload", 71),
        (file_list.id, "删除文件", "system:file:delete", 72),
        (file_channels.id, "新增存储渠道", "system:file:channel:create", 73),
        (file_channels.id, "编辑存储渠道", "system:file:channel:update", 74),
        (file_channels.id, "删除存储渠道", "system:file:channel:delete", 75),
        (file_config.id, "编辑上传配置", "system:file:config:update", 76),
        (notices.id, "新增公告", "system:notice:create", 81),
        (notices.id, "编辑公告", "system:notice:update", 82),
        (notices.id, "删除公告", "system:notice:delete", 83),
        (
            site_message_templates.id,
            "新增站内信模板",
            "system:site-message-template:create",
            84,
        ),
        (
            site_message_templates.id,
            "编辑站内信模板",
            "system:site-message-template:update",
            85,
        ),
        (
            site_message_templates.id,
            "删除站内信模板",
            "system:site-message-template:delete",
            86,
        ),
        (
            site_message_templates.id,
            "发送测试站内信",
            "system:site-message-template:send",
            87,
        ),
        (
            site_message_list.id,
            "删除站内信",
            "system:site-message:delete",
            88,
        ),
        (sms_channels.id, "新增短信渠道", "system:sms-channel:create", 91),
        (sms_channels.id, "编辑短信渠道", "system:sms-channel:update", 92),
        (sms_channels.id, "删除短信渠道", "system:sms-channel:delete", 93),
        (sms_templates.id, "新增短信模板", "system:sms-template:create", 94),
        (sms_templates.id, "编辑短信模板", "system:sms-template:update", 95),
        (sms_templates.id, "删除短信模板", "system:sms-template:delete", 96),
        (sms_templates.id, "发送测试短信", "system:sms-template:send", 97),
        (mail_accounts.id, "新增邮箱账号", "system:mail-account:create", 101),
        (mail_accounts.id, "编辑邮箱账号", "system:mail-account:update", 102),
        (mail_accounts.id, "删除邮箱账号", "system:mail-account:delete", 103),
        (mail_templates.id, "新增邮件模板", "system:mail-template:create", 104),
        (mail_templates.id, "编辑邮件模板", "system:mail-template:update", 105),
        (mail_templates.id, "删除邮件模板", "system:mail-template:delete", 106),
        (mail_templates.id, "发送测试邮件", "system:mail-template:send", 107),
        (mail_logs.id, "重发邮件", "system:mail-log:resend", 108),
        (items.id, "新增示例", "business:item:create", 51),
        (items.id, "编辑示例", "business:item:update", 52),
        (items.id, "删除示例", "business:item:delete", 53),
        (erp_products.id, "新增产品", "erp:product:create", 21),
        (erp_products.id, "编辑产品", "erp:product:update", 22),
        (erp_products.id, "删除产品", "erp:product:delete", 23),
        (erp_products.id, "导出产品", "erp:product:export", 24),
        (esop_operations.id, "新增工序", "esop:operation:create", 1),
        (esop_operations.id, "编辑工序", "esop:operation:update", 2),
        (esop_operations.id, "删除工序", "esop:operation:delete", 3),
        (esop_routes.id, "新增流程", "esop:route:create", 1),
        (esop_routes.id, "编辑流程", "esop:route:update", 2),
        (esop_operations.id, "新增SOP", "esop:sop:create", 4),
        (esop_operations.id, "编辑SOP", "esop:sop:update", 5),
        (esop_operations.id, "提交审核", "esop:sop:submit", 6),
        (esop_operations.id, "上传SOP文件", "esop:sop:upload", 7),
        (esop_lines.id, "新增车间", "esop:workshop:create", 2),
        (esop_lines.id, "编辑车间", "esop:workshop:update", 3),
        (esop_workshops.id, "删除车间", "esop:workshop:delete", 1),
        (esop_lines.id, "新增产线", "esop:line:create", 4),
        (esop_lines.id, "编辑产线", "esop:line:update", 5),
        (esop_lines.id, "删除产线", "esop:line:delete", 6),
        (esop_orders.id, "新增订单", "esop:order:create", 1),
        (esop_orders.id, "编辑订单", "esop:order:update", 2),
        (esop_plans.id, "新增排产", "esop:plan:create", 1),
        (esop_plans.id, "编辑排产", "esop:plan:update", 2),
        (esop_plans.id, "发布排产", "esop:plan:publish", 3),
        (esop_broadcasts.id, "维护广播", "esop:broadcast:manage", 1),
        (esop_reports.id, "导出报工", "esop:report:export", 1),
        (esop_reports.id, "新增报工", "esop:report:create", 2),
        (esop_alarms.id, "管理报警类型", "esop:alarm:type:manage", 1),
        (esop_alarms.id, "解除报警", "esop:alarm:resolve", 2),
        (esop_terminals.id, "绑定工位", "esop:device:bind", 1),
        (esop_keys.id, "发放密钥", "esop:device:issue", 1),
        (esop_ota.id, "维护渠道与硬件", "esop:ota:manage", 1),
        (esop_ota.id, "发布升级包", "esop:ota:publish", 2),
        (esop_ota.id, "关联渠道管理员", "esop:channel:admin", 3),
        (esop_ota.id, "批量发放渠道密钥", "esop:channel:issue", 4),
    ]
    buttons = [
        ensure_menu(
            session=session,
            title=title,
            type="button",
            parent_id=parent_id,
            permission_code=permission_code,
            sort=sort,
            is_visible=False,
        )
        for parent_id, title, permission_code, sort in button_permissions
    ]
    # Existing SOP editors and operation editors both need the combined list page.
    for source, target in ((esop_sops, esop_operations), (esop_operations, esop_sops)):
        for grant in session.exec(select(RoleMenu).where(RoleMenu.menu_id == source.id)).all():
            if session.get(RoleMenu, (grant.role_id, target.id)) is None:
                session.add(RoleMenu(role_id=grant.role_id, menu_id=target.id))
    # Existing production-record viewers can see the new quantity trace page.
    for grant in session.exec(select(RoleMenu).where(RoleMenu.menu_id == esop_reports.id)).all():
        if session.get(RoleMenu, (grant.role_id, esop_sip.id)) is None:
            session.add(RoleMenu(role_id=grant.role_id, menu_id=esop_sip.id))
    for grant in session.exec(select(RoleMenu).where(RoleMenu.menu_id == dashboard.id)).all():
        if session.get(RoleMenu, (grant.role_id, esop_data_screen.id)) is None:
            session.add(RoleMenu(role_id=grant.role_id, menu_id=esop_data_screen.id))
    session.flush()
    return [
        dashboard,
        system,
        tenant_center,
        basic_settings,
        tenants,
        tenant_plans,
        tenant_templates,
        users,
        roles,
        menus,
        departments,
        posts,
        dictionaries,
        system_settings,
        oauth2,
        oauth2_clients,
        oauth2_tokens,
        social,
        social_clients,
        social_users,
        message_center,
        logs,
        login_logs,
        operation_logs,
        files,
        file_channels,
        file_config,
        file_list,
        notices,
        messages,
        site_messages,
        site_message_templates,
        site_message_list,
        sms,
        sms_channels,
        sms_templates,
        sms_logs,
        mail,
        mail_accounts,
        mail_templates,
        mail_logs,
        items,
        erp,
        esop,
        esop_basic,
        esop_resources,
        esop_sop_center,
        esop_order_center,
        esop_publish_center,
        esop_records,
        esop_services,
        esop_products,
        esop_operations,
        esop_routes,
        esop_workshops,
        esop_staff,
        esop_sops,
        esop_review,
        esop_lines,
        esop_orders,
        esop_plans,
        esop_broadcasts,
        esop_data_screen,
        esop_reports,
        esop_sip,
        esop_alarms,
        esop_terminals,
        esop_keys,
        esop_storage,
        esop_ota,
        esop_purchase,
        esop_channel_workspace,
        erp_platform_units,
        erp_home,
        erp_purchase,
        erp_sale,
        erp_product_management,
        erp_stock_management,
        erp_finance,
        erp_products,
        erp_product_categories,
        erp_product_units,
        erp_suppliers,
        erp_customers,
        erp_settlement_accounts,
        erp_finance_payments,
        erp_finance_receipts,
        erp_action_logs,
        erp_purchase_orders,
        erp_purchase_ins,
        erp_purchase_returns,
        erp_sale_orders,
        erp_sale_outs,
        erp_sale_returns,
        erp_warehouses,
        erp_stock_balance,
        erp_stock_ledger,
        erp_stock_other_in,
        erp_stock_other_out,
        erp_stock_move,
        erp_stock_check,
        *buttons,
    ]


def remove_obsolete_menus(*, session: Session) -> None:
    obsolete_route_paths = {
        "/system/codegen",
        "/system/online-users",
        "/system/operations",
        "/workflows",
        "/esop/purchase",
    }
    obsolete_permission_prefixes = (
        "system:api-log:",
        "system:codegen:",
        "system:exception-log:",
        "system:scheduled-task:",
        "system:scheduled-task-log:",
        "system:session:",
        "system:translation:",
        "workflow:",
    )
    obsolete_menus = [
        menu
        for menu in session.exec(select(Menu)).all()
        if menu.route_path in obsolete_route_paths
        or (menu.route_path or "").startswith("/system/operations/")
        or (menu.component or "").startswith("#/views/operations/")
        or (menu.component or "").startswith("#/views/system/online-users/")
        or (menu.permission_code or "").startswith(obsolete_permission_prefixes)
    ]
    if not obsolete_menus:
        return

    obsolete_menu_ids = {menu.id for menu in obsolete_menus}
    for role_menu in session.exec(select(RoleMenu)).all():
        if role_menu.menu_id in obsolete_menu_ids:
            session.delete(role_menu)
    session.flush()

    remaining = {menu.id: menu for menu in obsolete_menus}
    while remaining:
        parent_ids = {
            menu.parent_id for menu in remaining.values() if menu.parent_id in remaining
        }
        leaves = [
            menu for menu_id, menu in remaining.items() if menu_id not in parent_ids
        ]
        for menu in leaves:
            session.delete(menu)
            remaining.pop(menu.id)
        session.flush()


def migrate_directory_menu(
    *,
    session: Session,
    parent: Menu,
    route_name: str,
    legacy_paths: tuple[str, ...],
    target_path: str,
    sort: int,  # noqa: ARG001 - compatibility; preserve user-managed order
) -> None:
    legacy_menu = session.exec(
        select(Menu).where(
            Menu.route_name == route_name,
            Menu.route_path.in_(legacy_paths),
        )
    ).first()
    if not legacy_menu:
        return

    target_menu = session.exec(
        select(Menu).where(Menu.route_path == target_path)
    ).first()
    if not target_menu:
        legacy_menu.parent_id = parent.id
        legacy_menu.route_path = target_path
        legacy_menu.updated_at = get_datetime_utc()
        session.add(legacy_menu)
        session.flush()
        return

    for role_menu in session.exec(
        select(RoleMenu).where(RoleMenu.menu_id == legacy_menu.id)
    ).all():
        target_mapping = session.exec(
            select(RoleMenu).where(
                RoleMenu.role_id == role_menu.role_id,
                RoleMenu.menu_id == target_menu.id,
            )
        ).first()
        if not target_mapping:
            session.add(RoleMenu(role_id=role_menu.role_id, menu_id=target_menu.id))
        session.delete(role_menu)
    session.flush()
    session.delete(legacy_menu)
    session.flush()
