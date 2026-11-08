import type { RouteRecordStringComponent } from '@vben/types';

import { getMyMenusApi } from './rbac';

interface BackendMenuRoute {
  component?: null | string;
  icon?: null | string;
  id?: string;
  name?: string;
  parent_id?: null | string;
  path?: string;
  permission_code?: null | string;
  route_name?: null | string;
  route_path?: null | string;
  sort?: number;
  title: string;
  type?: string;
}

function normalizeComponent(component?: null | string) {
  return component?.replace(/^#\/views/, '').replace(/^#/, '');
}

/** 兼容数据库中仍使用中文标题的旧菜单数据 */
const LEGACY_MENU_TITLE_KEYS: Record<string, string> = {
  业务示例: 'menu.items',
  基础设施: 'menu.infrastructure',
  基础设置: 'menu.infrastructure',
  任务示例: 'menu.items',
  仪表盘: 'menu.dashboard',
  参数配置: 'menu.systemSettings',
  字典管理: 'menu.systemDictionaries',
  文件管理: 'menu.files',
  租户中心: 'menu.systemTenantCenter',
  审计日志: 'menu.logs',
  日志审计: 'menu.logs',
  操作日志记录: 'menu.operationLogs',
  操作日志: 'menu.operationLogs',
  用户管理: 'menu.systemUsers',
  系统访问记录: 'menu.loginLogs',
  登录日志: 'menu.loginLogs',
  示例资源: 'menu.items',
  系统管理: 'menu.system',
  'ERP 系统': 'menu.erpSystem',
  'ESOP 作业指导': 'menu.esopSystem',
  基础资料: 'menu.esopBasic',
  产线与终端: 'menu.esopResources',
  'SOP 管理': 'menu.esopSopCenter',
  '工单&发布': 'menu.esopPublishCenter',
  生产订单: 'menu.esopOrders',
  生产记录: 'menu.esopRecords',
  授权与服务: 'menu.esopServices',
  产品: 'menu.esopProducts',
  SOP列表: 'menu.esopSopList',
  工艺流程: 'menu.esopRoutes',
  'SOP 审核': 'menu.esopReview',
  车间: 'menu.esopWorkshops',
  员工: 'menu.esopStaff',
  产线与工位: 'menu.esopLines',
  排产发布: 'menu.esopPlans',
  广播发布: 'menu.esopBroadcasts',
  报工追溯: 'menu.esopReports',
  'SIP 点检': 'menu.esopSip',
  报警记录: 'menu.esopAlarms',
  终端管理: 'menu.esopTerminals',
  激活密钥: 'menu.esopActivationKeys',
  存储包发放: 'menu.esopStorageGrants',
  '渠道 OTA': 'menu.esopOta',
  购买与扩容: 'menu.esopPurchase',
  菜单管理: 'menu.systemMenus',
  角色管理: 'menu.systemRoles',
  部门管理: 'menu.systemDepartments',
  岗位管理: 'menu.systemPosts',
  消息中心: 'menu.messageCenter',
  我的消息: 'menu.messages',
  通知公告: 'menu.notices',
  公告管理: 'menu.notices',
  站内信管理: 'menu.siteMessages',
  站内信模板: 'menu.siteMessageTemplates',
  站内信: 'menu.siteMessageList',
  短信管理: 'menu.sms',
  短信渠道: 'menu.smsChannels',
  短信模板: 'menu.smsTemplates',
  短信日志: 'menu.smsLogs',
  邮箱管理: 'menu.mail',
  邮箱账号: 'menu.mailAccounts',
  邮件模板: 'menu.mailTemplates',
  邮件日志: 'menu.mailLogs',
};

const ERP_MENU_TITLES = new Set([
  '产品信息', '产品分类', '产品单位', '产品库存', '产品库存管理', '产品管理',
  '仓库信息', '付款单', '供应商管理', '其它入库', '其它出库', '出入库明细',
  '客户信息', '平台单位管理', '库存盘点', '库存调拨', '收款单', '渠道工作台',
  '结算账户', '财务管理', '采购入库', '采购管理', '采购订单', '采购退货',
  '销售出库', '销售管理', '销售订单', '销售退货', '首页',
]);

function resolveMenuTitle(title: string) {
  if (title.includes('.')) {
    return title;
  }
  return LEGACY_MENU_TITLE_KEYS[title] ?? (ERP_MENU_TITLES.has(title) ? `menu.erp.${title}` : title);
}

function toRoute(menu: BackendMenuRoute): RouteRecordStringComponent {
  return {
    children: [],
    component:
      normalizeComponent(menu.component) ||
      (menu.type === 'directory' && !menu.parent_id ? 'BasicLayout' : ''),
    meta: {
      authority: menu.permission_code ? [menu.permission_code] : undefined,
      icon: menu.icon || undefined,
      order: menu.sort,
      title: resolveMenuTitle(menu.title),
    },
    name: menu.route_name || menu.name || menu.id,
    path: menu.route_path || menu.path || '/',
  };
}

/**
 * 获取用户所有菜单
 */
export async function getAllMenusApi() {
  const menus = (await getMyMenusApi()) as unknown as BackendMenuRoute[];
  const routeById = new Map<string, RouteRecordStringComponent>();
  const roots: RouteRecordStringComponent[] = [];

  for (const menu of menus.filter((item) => item.type !== 'button')) {
    if (!menu.id) continue;
    routeById.set(menu.id, toRoute(menu));
  }

  for (const menu of menus.filter((item) => item.type !== 'button')) {
    if (!menu.id) continue;
    const route = routeById.get(menu.id);
    if (!route) continue;
    if (menu.parent_id && routeById.has(menu.parent_id)) {
      const parent = routeById.get(menu.parent_id);
      parent?.children?.push(route);
    } else {
      roots.push(route);
    }
  }

  return roots;
}
