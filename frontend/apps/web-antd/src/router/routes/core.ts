import type { RouteRecordRaw } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';

import { $t } from '#/locales';
import { buildManifest } from '#/modules/build-manifest';

const BasicLayout = () => import('#/layouts/basic.vue');
const AuthPageLayout = () => import('#/layouts/auth.vue');
/** 全局404页面 */
const fallbackNotFoundRoute: RouteRecordRaw = {
  component: () => import('#/views/_core/fallback/not-found.vue'),
  meta: {
    hideInBreadcrumb: true,
    hideInMenu: true,
    hideInTab: true,
    title: '404',
  },
  name: 'FallbackNotFound',
  path: '/:path(.*)*',
};

/** 基本路由，这些路由是必须存在的 */
const coreRoutes: RouteRecordRaw[] = [
  /**
   * 根路由
   * 使用基础布局，作为所有页面的父级容器，子级就不必配置BasicLayout。
   * 保留此容器供后台动态路由挂载；ESOP仅在精确根路径展示公开首页。
   */
  {
    component: buildManifest.edition === 'esop' ? () => import('#/layouts/esop-root.vue') : BasicLayout,
    meta: {
      hideInBreadcrumb: true,
      title: buildManifest.edition === 'esop' ? 'ESOPS' : 'Root',
    },
    name: 'Root',
    path: '/',
    redirect: buildManifest.edition === 'esop' ? undefined : preferences.app.defaultHomePath,
    children: [],
  },
  {
    component: AuthPageLayout,
    meta: {
      hideInTab: true,
      title: 'Authentication',
    },
    name: 'Authentication',
    path: '/auth',
    redirect: LOGIN_PATH,
    children: [
      {
        name: 'ProductHome',
        path: 'home',
        redirect: { path: '/' },
        meta: { title: 'ESOPS', ignoreAccess: true },
      },
      {
        name: 'TerminalDownload',
        path: '/downloads',
        component: () => import('#/views/_core/authentication/terminal-download.vue'),
        meta: { title: '下载 ESOPS 终端', ignoreAccess: true },
      },
      {
        name: 'Login',
        path: 'login',
        component: () => import('#/views/_core/authentication/login.vue'),
        meta: {
          title: $t('page.auth.login'),
        },
      },
      {
        name: 'ForgetPassword',
        path: 'forget-password',
        component: () =>
          import('#/views/_core/authentication/forget-password.vue'),
        meta: {
          title: $t('page.auth.forgetPassword'),
        },
      },
      {
        name: 'CodeLogin',
        path: 'code-login',
        component: () =>
          import('#/views/_core/authentication/code-login.vue'),
        meta: {
          title: $t('page.auth.codeLogin'),
        },
      },
      {
        name: 'QrCodeLogin',
        path: 'qrcode-login',
        component: () =>
          import('#/views/_core/authentication/qrcode-login.vue'),
        meta: {
          title: $t('page.auth.qrcodeLogin'),
        },
      },
      {
        name: 'QrCodeLoginConfirm',
        path: 'qrcode-confirm',
        component: () =>
          import('#/views/_core/authentication/qrcode-confirm.vue'),
        meta: {
          title: '确认扫码登录',
        },
      },
      {
        name: 'Register',
        path: 'register',
        component: () =>
          import('#/views/_core/authentication/register.vue'),
        meta: {
          title: $t('page.auth.register'),
        },
      },
    ],
  },
  {
    component: BasicLayout,
    meta: { hideInMenu: true, title: '官网首页内容' },
    name: 'HomepageSettingsRoot',
    path: '/basic-settings/homepage',
    children: [
      {
        component: () => import('#/views/system/settings/homepage.vue'),
        meta: { hideInMenu: true, title: '官网首页内容' },
        name: 'HomepageSettings',
        path: '',
      },
    ],
  },
  {
    component: AuthPageLayout,
    meta: {
      hideInTab: true,
      title: '重置密码',
    },
    name: 'ResetPasswordRoot',
    path: '/reset-password',
    children: [
      {
        name: 'ResetPassword',
        path: '',
        component: () =>
          import('#/views/_core/authentication/reset-password.vue'),
        meta: {
          title: '重置密码',
        },
      },
    ],
  },
  {
    component: BasicLayout,
    meta: {
      hideInBreadcrumb: true,
      title: 'ProfileRoot',
    },
    name: 'ProfileRoot',
    path: '/profile',
    children: [
      {
        component: () => import('#/views/_core/profile/index.vue'),
        meta: {
          hideInMenu: true,
          icon: 'lucide:user',
          title: $t('page.auth.profile'),
        },
        name: 'Profile',
        path: '',
      },
    ],
  },
  {
    component: BasicLayout,
    meta: { hideInMenu: true, title: '欢迎使用' },
    name: 'WelcomeRoot',
    path: '/welcome',
    children: [{
      component: () => import('#/views/_core/welcome/index.vue'),
      meta: { hideInMenu: true, title: '欢迎使用' },
      name: 'Welcome',
      path: '',
    }],
  },
  {
    component: BasicLayout,
    meta: { hideInMenu: true, title: '无访问权限' },
    name: 'NoAccessRoot',
    path: '/no-access',
    children: [{
      component: () => import('#/views/_core/fallback/forbidden.vue'),
      meta: { hideInMenu: true, title: '无访问权限' },
      name: 'NoAccess',
      path: '',
    }],
  },
];

export { coreRoutes, fallbackNotFoundRoute };
