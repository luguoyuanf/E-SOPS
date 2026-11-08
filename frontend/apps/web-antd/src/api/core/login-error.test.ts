import { describe, expect, it } from 'vitest';
import zh from '../../locales/langs/zh-CN/authentication.json';
import { consumeGoogleLoginError, loginErrorBody, loginErrorMessageKey } from './login-error';

describe('visible login error mapping', () => {
  it('recognizes RequestClient unwrapped bodies and Axios response errors', () => {
    const body = {code:'AUTH_INVALID_CREDENTIALS',message:'Incorrect email or password'};
    expect(loginErrorBody(body)).toEqual(body);
    expect(loginErrorBody({response:{data:body}})).toEqual(body);
    expect(loginErrorMessageKey(body)).toBe('authentication.loginError.invalidCredentials');
    expect(loginErrorMessageKey({response:{data:body}})).toBe('authentication.loginError.invalidCredentials');
    expect(zh.loginError.invalidCredentials).toBe('账号或密码错误');
  });
  it.each([
    ['AUTH_CAPTCHA_REQUIRED','captchaRequired'],['AUTH_CAPTCHA_INVALID','captchaInvalid'],
    ['AUTH_SLIDER_CAPTCHA_INVALID','captchaInvalid'],['AUTH_MFA_REQUIRED','mfaRequired'],
    ['AUTH_MFA_INVALID','mfaInvalid'],['TENANT_NOT_FOUND','tenantNotFound'],
    ['TENANT_MEMBERSHIP_REQUIRED','tenantForbidden'],['USER_INACTIVE','inactiveUser'],
    ['AUTH_RATE_LIMITED','rateLimited'],['ERR_NETWORK','network'],['ECONNABORTED','network'],
  ])('maps %s to a persistent user-facing error', (code,key) => {
    expect(loginErrorMessageKey({code})).toBe(`authentication.loginError.${key}`);
    expect(zh.loginError[key as keyof typeof zh.loginError]).toBeTruthy();
  });
  it('provides a safe fallback without leaking server details', () => {
    expect(loginErrorMessageKey({message:'SQL database internal stack'})).toBe('authentication.loginError.failed');
    expect(loginErrorMessageKey(null)).toBe('authentication.loginError.failed');
    expect(loginErrorMessageKey(new Error('Network Error'))).toBe('authentication.loginError.network');
  });
  it('shows the MFA fallback for an unwrapped or nested Google login error', () => {
    const body = { code: 'AUTH_GOOGLE_MFA_UNSUPPORTED' };
    expect(loginErrorMessageKey(body)).toBe('authentication.loginError.googleMfaUnsupported');
    expect(loginErrorMessageKey({ response: { data: body } })).toBe('authentication.loginError.googleMfaUnsupported');
    expect(zh.loginError.googleMfaUnsupported).toContain('MFA');
  });
  it('removes the Google callback failure from history without losing other route state', () => {
    expect(consumeGoogleLoginError('https://example.test/auth/login?google_error=login_failed&next=home#section'))
      .toEqual({ failed: true, url: '/auth/login?next=home#section' });
    expect(consumeGoogleLoginError('https://example.test/#/auth/login?next=home&google_error=login_failed'))
      .toEqual({ failed: true, url: '/#/auth/login?next=home' });
    expect(consumeGoogleLoginError('https://example.test/auth/login'))
      .toEqual({ failed: false, url: '/auth/login' });
  });
});
