import type { Recordable } from '@vben/types';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { resetAllStores, useAccessStore, useUserStore } from '@vben/stores';

import { Modal, notification } from 'ant-design-vue';
import { defineStore } from 'pinia';

import {
  exchangeEnterpriseOidcTicketApi,
  exchangeQrCodeLoginApi,
  getAccessCodesApi,
  getCurrentStorageUsageApi,
  getUserInfoApi,
  loginApi,
  logoutApi,
  registerTenantApi,
  smsLoginApi,
  switchTenantApi,
} from '#/api';
import { $t } from '#/locales';

export const useAuthStore = defineStore('auth', () => {
  const accessStore = useAccessStore();
  const userStore = useUserStore();
  const router = useRouter();

  const loginLoading = ref(false);

  /**
   * 异步处理登录操作
   * Asynchronously handle the login process
   * @param params 登录表单数据
   */
  async function completeLogin(
    accessToken: string,
    onSuccess?: () => Promise<void> | void,
  ) {
    resetAllStores();
    accessStore.setAccessToken(accessToken);

    const [userInfo, accessCodes] = await Promise.all([
      fetchUserInfo(),
      getAccessCodesApi(),
    ]);
    userStore.setUserInfo(userInfo);
    accessStore.setAccessCodes(accessCodes);

    if (accessStore.loginExpired) {
      accessStore.setLoginExpired(false);
    } else {
      onSuccess
        ? await onSuccess?.()
        : await router.push(
            typeof router.currentRoute.value.query.redirect === 'string'
              ? decodeURIComponent(router.currentRoute.value.query.redirect)
              : userInfo.homePath || preferences.app.defaultHomePath,
          );
    }

    if (userInfo?.realName) {
      notification.success({
        description: `${$t('authentication.loginSuccessDesc')}:${userInfo?.realName}`,
        duration: 3,
        message: $t('authentication.loginSuccess'),
      });
    }

    // A reminder failure must not turn a successful login into a login failure.
    void remindStorageUsage();
    return { userInfo };
  }

  async function remindStorageUsage() {
    const token = accessStore.accessToken;
    try {
      const usage = await getCurrentStorageUsageApi();
      if (token !== accessStore.accessToken) return;
      if (!usage.warning || usage.limit_bytes === null) return;
      const format = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
      Modal.warning({
        title: usage.used_bytes >= usage.limit_bytes ? '存储空间已用完' : '存储空间即将用完',
        content: `已使用 ${format(usage.used_bytes)}，总容量 ${format(usage.limit_bytes)}，剩余 ${format(usage.remaining_bytes ?? 0)}。租户所有上传文件统一计入容量；上传后超过总容量的文件将被禁止上传。请前往“购买与扩容”联系购买存储扩容包。`,
        okText: '我知道了',
        keyboard: true,
        closable: true,
      });
    } catch (error) {
      console.warn('获取存储容量提醒失败', error);
    }
  }

  async function authLogin(
    params: Recordable<any>,
    onSuccess?: () => Promise<void> | void,
  ) {
    try {
      loginLoading.value = true;
      const { accessToken } = await loginApi(params);
      return await completeLogin(accessToken, onSuccess);
    } finally {
      loginLoading.value = false;
    }
  }

  async function authEnterpriseOidcLogin(
    ticket: string,
    onSuccess?: () => Promise<void> | void,
  ) {
    try {
      loginLoading.value = true;
      const { accessToken } = await exchangeEnterpriseOidcTicketApi(ticket);
      return await completeLogin(accessToken, onSuccess);
    } finally {
      loginLoading.value = false;
    }
  }

  async function authSmsLogin(
    params: Parameters<typeof smsLoginApi>[0],
    onSuccess?: () => Promise<void> | void,
  ) {
    try {
      loginLoading.value = true;
      const { accessToken } = await smsLoginApi(params);
      return await completeLogin(accessToken, onSuccess);
    } finally {
      loginLoading.value = false;
    }
  }

  async function authQrCodeLogin(
    params: Parameters<typeof exchangeQrCodeLoginApi>[0],
    onSuccess?: () => Promise<void> | void,
  ) {
    try {
      loginLoading.value = true;
      const { accessToken } = await exchangeQrCodeLoginApi(params);
      return await completeLogin(accessToken, onSuccess);
    } finally {
      loginLoading.value = false;
    }
  }

  async function authTenantRegister(
    params: Parameters<typeof registerTenantApi>[0],
    onSuccess?: () => Promise<void> | void,
  ) {
    try {
      loginLoading.value = true;
      const { accessToken, freeActivationKey } = await registerTenantApi(params);
      const result = await completeLogin(accessToken, onSuccess);
      return { ...result, freeActivationKey };
    } finally {
      loginLoading.value = false;
    }
  }

  async function logout(redirect: boolean = true) {
    if (accessStore.accessToken) {
      try {
        await logoutApi();
      } catch {
        // 不做任何处理
      }
    }
    resetAllStores();
    accessStore.setLoginExpired(false);

    // 回登录页带上当前路由地址
    await router.replace({
      path: LOGIN_PATH,
      query: redirect
        ? {
            redirect: encodeURIComponent(router.currentRoute.value.fullPath),
          }
        : {},
    });
  }

  async function fetchUserInfo() {
    const userInfo = await getUserInfoApi();
    userStore.setUserInfo(userInfo);
    return userInfo;
  }

  async function switchTenant(tenantId: string) {
    const { accessToken } = await switchTenantApi({ tenant_id: tenantId });
    accessStore.setAccessToken(accessToken);
    const homePath =
      userStore.userInfo?.homePath || preferences.app.defaultHomePath;
    window.location.assign(router.resolve(homePath).href);
  }

  function $reset() {
    loginLoading.value = false;
  }

  return {
    $reset,
    authEnterpriseOidcLogin,
    authLogin,
    authQrCodeLogin,
    authSmsLogin,
    authTenantRegister,
    fetchUserInfo,
    loginLoading,
    logout,
    switchTenant,
  };
});
