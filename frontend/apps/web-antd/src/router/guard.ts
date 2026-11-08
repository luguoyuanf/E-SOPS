import type { Router } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { useAccessStore, useUserStore } from '@vben/stores';
import { startProgress, stopProgress } from '@vben/utils';

import { getAccessCodesApi } from '#/api';
import { buildManifest } from '#/modules/build-manifest';
import { accessRoutes, coreRouteNames } from '#/router/routes';
import { useAuthStore } from '#/store';

import { generateAccess, loadBackendMenus } from './access';

/**
 * 通用守卫配置
 * @param router
 */
function setupCommonGuard(router: Router) {
  // 记录已经加载的页面
  const loadedPaths = new Set<string>();

  router.beforeEach((to) => {
    to.meta.loaded = loadedPaths.has(to.path);

    // 页面加载进度条
    if (!to.meta.loaded && preferences.transition.progress) {
      startProgress();
    }
    return true;
  });

  router.afterEach((to) => {
    // 记录页面是否加载,如果已经加载，后续的页面切换动画等效果不在重复执行

    loadedPaths.add(to.path);

    // 关闭页面加载进度条
    if (preferences.transition.progress) {
      stopProgress();
    }
  });
}

/**
 * 权限访问守卫配置
 * @param router
 */
function setupAccessGuard(router: Router) {
  router.beforeEach(async (to, from) => {
    if (to.meta.ignoreAccess) return true;
    const accessStore = useAccessStore();
    const userStore = useUserStore();
    const authStore = useAuthStore();

    // 基本路由通常不需要进入权限拦截。个人中心使用基础布局，
    // 刷新时仍需初始化动态菜单，否则侧边栏会保持为空。
    const needsMenuInitialization = to.name === 'Profile' || to.name === 'Welcome' || to.name === 'HomepageSettings';
    if (coreRouteNames.includes(to.name as string) && !needsMenuInitialization) {
      return true;
    }

    // accessToken 检查
    if (!accessStore.accessToken) {
      // 明确声明忽略权限访问权限，则可以访问
      if (to.meta.ignoreAccess) {
        return true;
      }

      // 没有访问权限，跳转登录页面
      if (to.fullPath !== LOGIN_PATH) {
        return {
          path: buildManifest.edition === 'esop' && to.fullPath === preferences.app.defaultHomePath
            ? '/'
            : LOGIN_PATH,
          // 如不需要，直接删除 query
          query:
            to.fullPath === preferences.app.defaultHomePath
              ? {}
              : { redirect: encodeURIComponent(to.fullPath) },
          // 携带当前跳转的页面，登录后重新跳转该页面
          replace: true,
        };
      }
      return to;
    }

    // 是否已经生成过动态路由
    if (accessStore.isAccessChecked) {
      if (
        to.path === preferences.app.defaultHomePath &&
        !accessStore.accessCodes.includes('dashboard:view')
      ) {
        return { path: '/welcome', replace: true };
      }
      return true;
    }

    // 生成路由表
    // 当前登录用户拥有的角色标识列表
    const [userInfo, accessCodes, menus] = await Promise.all([
      userStore.userInfo || authStore.fetchUserInfo(),
      getAccessCodesApi(),
      loadBackendMenus(),
    ]);
    accessStore.setAccessCodes(accessCodes);
    const userRoles = userInfo.roles ?? [];

    // 生成菜单和路由
    const { accessibleMenus, accessibleRoutes } = await generateAccess({
      roles: [...userRoles, ...accessCodes],
      router,
      // 则会在菜单中显示，但是访问会被重定向到403
      routes: accessRoutes,
    }, menus);

    // 保存菜单信息和路由信息
    accessStore.setAccessMenus(accessibleMenus);
    accessStore.setAccessRoutes(accessibleRoutes);
    accessStore.setIsAccessChecked(true);
    if (accessibleRoutes.length === 0) {
      return { path: '/no-access', replace: true };
    }
    if (
      to.path === preferences.app.defaultHomePath &&
      !accessCodes.includes('dashboard:view')
    ) {
      return { path: '/welcome', replace: true };
    }
    const redirectPath = (from.query.redirect ??
      (to.path === preferences.app.defaultHomePath
        ? userInfo.homePath || preferences.app.defaultHomePath
        : to.fullPath)) as string;

    return {
      ...router.resolve(decodeURIComponent(redirectPath)),
      replace: true,
    };
  });
}

/**
 * 项目守卫配置
 * @param router
 */
function createRouterGuard(router: Router) {
  /** 通用 */
  setupCommonGuard(router);
  /** 权限访问 */
  setupAccessGuard(router);
}

export { createRouterGuard };
