type LoginErrorBody = { code?: string; detail?: unknown; message?: string; };

/** Strip the callback status while preserving unrelated route/query parameters. */
export function consumeGoogleLoginError(href: string): { failed: boolean; url: string } {
  const url = new URL(href);
  const params = url.searchParams;
  const [hashPath = '', hashQuery = ''] = url.hash.split('?', 2);
  const hashParams = new URLSearchParams(hashQuery);
  const failed = params.get('google_error') === 'login_failed' || hashParams.get('google_error') === 'login_failed';
  params.delete('google_error');
  hashParams.delete('google_error');
  const remainingHashQuery = hashParams.toString();
  const hash = hashPath ? hashPath + (remainingHashQuery ? `?${remainingHashQuery}` : '') : '';
  return { failed, url: `${url.pathname}${url.search}${hash}` };
}

/** RequestClient throws response bodies; Axios/network failures may retain response. */
export function loginErrorBody(error: unknown): LoginErrorBody {
  if (!error || typeof error !== 'object') return {};
  const value = error as LoginErrorBody & { response?: { data?: LoginErrorBody } };
  return value.response?.data ?? value;
}

export function loginErrorMessageKey(error: unknown): string {
  const body = loginErrorBody(error);
  const keys: Record<string, string> = {
    AUTH_INVALID_CREDENTIALS: 'invalidCredentials',
    BACKOFFICE_MENU_REQUIRED: 'backofficeMenuRequired',
    USER_INACTIVE: 'inactiveUser',
    AUTH_RATE_LIMITED: 'rateLimited',
    AUTH_CAPTCHA_REQUIRED: 'captchaRequired',
    AUTH_CAPTCHA_INVALID: 'captchaInvalid',
    AUTH_SLIDER_CAPTCHA_INVALID: 'captchaInvalid',
    AUTH_MFA_REQUIRED: 'mfaRequired',
    AUTH_MFA_INVALID: 'mfaInvalid',
    AUTH_GOOGLE_MFA_UNSUPPORTED: 'googleMfaUnsupported',
    TENANT_NOT_FOUND: 'tenantNotFound',
    TENANT_CODE_INVALID: 'tenantInvalid',
    TENANT_MEMBERSHIP_REQUIRED: 'tenantForbidden',
    TENANT_CONTEXT_INVALID: 'tenantForbidden',
    TENANT_INACTIVE: 'tenantInactive',
    TENANT_FROZEN: 'tenantInactive',
    TENANT_EXPIRED: 'tenantInactive',
    ERR_NETWORK: 'network',
    ECONNABORTED: 'network',
    ETIMEDOUT: 'network',
  };
  if (body.code && keys[body.code]) return `authentication.loginError.${keys[body.code]}`;
  if (body.message === 'Network Error' || body.message === 'Failed to fetch') return 'authentication.loginError.network';
  if (body.message === 'Incorrect email or password') return 'authentication.loginError.invalidCredentials';
  if (body.code === 'VALIDATION_ERROR' || body.code === 'REQUEST_VALIDATION_ERROR') {
    return 'authentication.loginError.validation';
  }
  return 'authentication.loginError.failed';
}
