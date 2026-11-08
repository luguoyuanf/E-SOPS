import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [{
  path: '/web-terminal/:terminalId',
  name: 'EsopWebTerminal',
  component: () => import('./views/web-terminal/index.vue'),
  meta: { ignoreAccess: true, hideInMenu: true, hideInTab: true, title: 'Web终端' },
}];
export default routes;
