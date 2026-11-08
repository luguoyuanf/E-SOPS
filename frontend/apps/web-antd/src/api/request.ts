/**
 * 该文件可自行根据业务逻辑进行调整
 */
import type { RequestClientOptions } from '@vben/request';

import { useAppConfig } from '@vben/hooks';
import { preferences } from '@vben/preferences';
import {
  authenticateResponseInterceptor,
  defaultResponseInterceptor,
  errorMessageResponseInterceptor,
  RequestClient,
} from '@vben/request';
import { useAccessStore } from '@vben/stores';

import { message } from 'ant-design-vue';

import { useAuthStore } from '#/store';

import { refreshTokenApi } from './core';
import { requestErrorMessage } from './core/request-error-message';

const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);

function createRequestClient(baseURL: string, options?: RequestClientOptions) {
  const client = new RequestClient({
    ...options,
    baseURL,
  });

  /**
   * 重新认证逻辑
   */
  async function doReAuthenticate(forceLogout = false) {
    const accessStore = useAccessStore();
    if (!accessStore.accessToken) return;
    console.warn('Access token or refresh token is invalid or expired. ');
    const authStore = useAuthStore();
    accessStore.setAccessToken(null);
    if (
      !forceLogout &&
      preferences.app.loginExpiredMode === 'modal' &&
      accessStore.isAccessChecked
    ) {
      accessStore.setLoginExpired(true);
    } else {
      await authStore.logout(false);
    }
  }

  function isCurrentUserMissing(error: any) {
    const { config, response } = error ?? {};
    const data = response?.data ?? {};
    return (
      response?.status === 404 &&
      config?.url?.includes('/users/me') &&
      (data?.code === 'USER_NOT_FOUND' || data?.message === 'User not found')
    );
  }

  function isAuthenticationFailure(error: any) {
    const { response } = error ?? {};
    const data = response?.data ?? {};
    return (
      response?.status === 401 ||
      (response?.status === 403 &&
        (data?.code === 'AUTH_TOKEN_INVALID' ||
          data?.code === 'BACKOFFICE_MENU_REQUIRED' ||
          data?.message === 'Could not validate credentials'))
    );
  }

  /**
   * 刷新token逻辑
   */
  async function doRefreshToken() {
    const accessStore = useAccessStore();
    const resp = await refreshTokenApi();
    const newToken = resp.data;
    accessStore.setAccessToken(newToken);
    return newToken;
  }

  function formatToken(token: null | string) {
    return token ? `Bearer ${token}` : null;
  }

  // 请求头处理
  client.addRequestInterceptor({
    fulfilled: async (config) => {
      const accessStore = useAccessStore();

      config.headers.Authorization = formatToken(accessStore.accessToken);
      config.headers['Accept-Language'] = preferences.app.locale;
      return config;
    },
  });

  client.addResponseInterceptor(
    defaultResponseInterceptor({
      codeField: 'code',
      dataField: 'data',
      successCode: 0,
    }),
  );

  // token过期的处理
  client.addResponseInterceptor(
    authenticateResponseInterceptor({
      client,
      doReAuthenticate,
      doRefreshToken,
      enableRefreshToken: preferences.app.enableRefreshToken,
      formatToken,
    }),
  );

  client.addResponseInterceptor({
    rejected: async (error) => {
      if (error?.config?.skipErrorMessage) {
        error.__skipErrorMessage = true;
      }
      if (isAuthenticationFailure(error) || isCurrentUserMissing(error)) {
        error.__skipErrorMessage = true;
        await doReAuthenticate(error?.response?.data?.code === 'BACKOFFICE_MENU_REQUIRED');
      }
      throw error;
    },
  });

  // 通用的错误处理,如果没有进入上面的错误处理逻辑，就会进入这里
  client.addResponseInterceptor(
    errorMessageResponseInterceptor((msg: string, error) => {
      if (error?.__skipErrorMessage) {
        return;
      }
      message.error(requestErrorMessage(error, msg));
    }),
  );

  return client;
}

export const requestClient = createRequestClient(apiURL, {
  responseReturn: 'body',
});

export const baseRequestClient = new RequestClient({ baseURL: apiURL });
