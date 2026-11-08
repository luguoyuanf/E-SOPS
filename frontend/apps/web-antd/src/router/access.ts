import type {
  ComponentRecordType,
  GenerateMenuAndRoutesOptions,
} from '@vben/types';

import { generateAccessible } from '@vben/access';
import { preferences } from '@vben/preferences';

import { message } from 'ant-design-vue';

import { getAllMenusApi, getBuildManifestApi } from '#/api';
import { BasicLayout, IFrameView } from '#/layouts';
import { $t } from '#/locales';
import { assertManifestCompatibility, ManifestMismatchError } from '#/modules/manifest-compatibility';

import { modulePageMap } from './generated-module-pages';

const forbiddenComponent = () => import('#/views/_core/fallback/forbidden.vue');
let activeRouteNames: Array<string | symbol> = [];

export async function loadBackendMenus() {
  const closeLoading = message.loading({ content: `${$t('common.loadingMenu')}...`, duration: 0 });
  try {
    const [backendManifest, menus] = await Promise.all([getBuildManifestApi(), getAllMenusApi()]);
    try {
      assertManifestCompatibility(backendManifest);
    } catch (error) {
      if (!(error instanceof ManifestMismatchError)) throw error;
      message.warning({ content: $t('authentication.loginError.versionMismatch'), duration: 6, key: 'manifest-version-mismatch' });
    }
    return menus;
  } finally {
    closeLoading();
  }
}

async function generateAccess(options: GenerateMenuAndRoutesOptions, menus?: Awaited<ReturnType<typeof getAllMenusApi>>) {
  for (const name of activeRouteNames) {
    if (options.router.hasRoute(name)) options.router.removeRoute(name);
  }
  activeRouteNames = [];
  const pageMap: ComponentRecordType = {
    ...import.meta.glob('../views/**/*.vue'),
    ...modulePageMap,
  };

  const layoutMap: ComponentRecordType = {
    BasicLayout,
    IFrameView,
  };

  const result = await generateAccessible(preferences.app.accessMode, {
    ...options,
    fetchMenuListAsync: async () => menus ?? await loadBackendMenus(),
    // 可以指定没有权限跳转403页面
    forbiddenComponent,
    // 如果 route.meta.menuVisibleWithForbidden = true
    layoutMap,
    pageMap,
  });
  activeRouteNames = result.accessibleRoutes
    .map((route) => route.name)
    .filter((name): name is string | symbol => name !== undefined && name !== null);
  return result;
}

export { generateAccess };
