<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';
import type { Recordable } from '@vben/types';

import { computed, onMounted, ref } from 'vue';

import {
  AuthenticationLogin,
  Verification,
  z,
} from '@vben/common-ui';
import { SvgGoogleIcon } from '@vben/icons';
import { $t } from '@vben/locales';

import { Alert } from 'ant-design-vue';

import {
  checkSliderCaptchaApi,
  getLoginCaptchaApi,
  getEnterpriseOidcStatusApi,
  getRegistrationStatusApi,
  getSliderCaptchaApi,
} from '#/api';
import { useAuthStore } from '#/store';
import { buildManifest } from '#/modules/build-manifest';
import esopsLogo from '#/assets/esops-logo.png';
const isEsops = buildManifest.edition === 'esop';
import { consumeGoogleLoginError, loginErrorBody, loginErrorMessageKey } from '#/api/core/login-error';

defineOptions({ name: 'Login' });

const authStore = useAuthStore();
const loginError = ref('');
const captchaId = ref('');
const captchaChallenge = ref('');
const showCaptcha = ref(false);
const showMfa = ref(false);
const verifyRef = ref<InstanceType<typeof Verification>>();
const pendingLoginValues = ref<null | Recordable<any>>(null);
const registrationEnabled = ref(false);
const googleLoginUrl = ref('');
const defaultTenantCode =
  import.meta.env.VITE_APP_DEFAULT_TENANT_CODE || 'default';

const formSchema = computed((): VbenFormSchema[] => {
  const schemas: VbenFormSchema[] = [
    {
      component: 'VbenInput',
      componentProps: {
        autocomplete: 'organization',
        placeholder: $t('authentication.loginForm.tenantPlaceholder'),
      },
      fieldName: 'tenant_code',
      defaultValue: defaultTenantCode,
      label: isEsops ? $t('authentication.esops.tenantCode') : $t('authentication.loginForm.tenant'),
      rules: z
        .string()
        .min(1, { message: $t('authentication.loginForm.tenantPlaceholder') })
        .max(100, { message: $t('authentication.loginForm.tenantTooLong') })
        .default(defaultTenantCode),
    },
    {
      component: 'VbenInput',
      componentProps: {
        autocomplete: 'username',
        placeholder: $t('authentication.loginForm.accountPlaceholder'),
      },
      fieldName: 'username',
      label: $t('authentication.loginForm.account'),
      rules: z
        .string()
        .trim()
        .min(1, { message: $t('authentication.loginForm.accountRequired') })
        .max(254, { message: $t('authentication.loginForm.accountTooLong') }),
    },
    {
      component: 'VbenInputPassword',
      componentProps: {
        autocomplete: 'current-password',
        placeholder: $t('authentication.password'),
      },
      fieldName: 'password',
      label: $t('authentication.password'),
      rules: z.string().min(1, { message: $t('authentication.passwordTip') }),
    },
  ];
  if (showCaptcha.value) {
    schemas.push({
      component: 'VbenInput',
      componentProps: {
        placeholder: $t('authentication.loginForm.captchaPlaceholder', [captchaChallenge.value]),
      },
      fieldName: 'captcha_code',
      label: $t('authentication.loginForm.captchaLabel', [captchaChallenge.value]),
      rules: z.string().min(1, { message: $t('authentication.loginForm.captchaRequired') }),
    });
  }
  if (showMfa.value) {
    schemas.push({
      component: 'VbenInput',
      componentProps: {
        autocomplete: 'one-time-code',
        maxlength: 32,
        placeholder: $t('authentication.loginForm.mfaPlaceholder'),
      },
      fieldName: 'mfa_code',
      label: $t('authentication.loginForm.mfaLabel'),
      rules: z
        .string()
        .min(6, { message: $t('authentication.loginForm.mfaRequired') }),
    });
  }
  return isEsops ? schemas.map((schema) => ({
    ...schema,
    hideLabel: false,
    labelClass: 'esops-field-label',
    formItemClass: 'esops-login-field',
  })) : schemas;
});

async function loadCaptcha(username: string) {
  const captcha = await getLoginCaptchaApi(username);
  captchaId.value = captcha.captcha_id;
  captchaChallenge.value = captcha.challenge_text;
  showCaptcha.value = true;
}

async function handleSubmit(values: Recordable<any>) {
  loginError.value = '';
  pendingLoginValues.value = { ...values };
  verifyRef.value?.show();
}

async function handleVerifySuccess({ captchaVerification }: { captchaVerification: string }) {
  const values = pendingLoginValues.value;
  pendingLoginValues.value = null;
  verifyRef.value?.onClose();
  if (!values) return;

  try {
    await authStore.authLogin({
      ...values,
      captcha_id: showCaptcha.value ? captchaId.value : undefined,
      captcha_verification: captchaVerification,
    });
  } catch (error: unknown) {
    loginError.value = $t(loginErrorMessageKey(error));
    const errorCode = loginErrorBody(error).code;
    const username = String(values.username || '');
    if (
      username &&
      (errorCode === 'AUTH_CAPTCHA_REQUIRED' ||
        errorCode === 'AUTH_CAPTCHA_INVALID')
    ) {
      try { await loadCaptcha(username); }
      catch (captchaError) { loginError.value = $t(loginErrorMessageKey(captchaError)); }
    }
    if (errorCode === 'AUTH_MFA_REQUIRED' || errorCode === 'AUTH_MFA_INVALID') {
      showMfa.value = true;
    }
  }
}

function handleCaptchaError(error: unknown) {
  const key = loginErrorMessageKey(error);
  loginError.value = $t(key === 'authentication.loginError.failed' ? 'authentication.loginError.captchaFailed' : key);
  pendingLoginValues.value = null;
  verifyRef.value?.onClose();
}

onMounted(async () => {
  const googleResult = consumeGoogleLoginError(window.location.href);
  if (googleResult.failed) {
    window.history.replaceState({}, document.title, googleResult.url);
    loginError.value = $t('authentication.loginError.googleLoginFailed');
  }
  const hashQuery = window.location.hash.split('?', 2)[1] || '';
  const ticket =
    new URLSearchParams(window.location.search).get('enterprise_ticket') ||
    new URLSearchParams(hashQuery).get('enterprise_ticket');
  if (ticket) {
    const routeHash = window.location.hash.split('?', 1)[0];
    window.history.replaceState(
      {},
      document.title,
      `${window.location.pathname}${routeHash}`,
    );
    try {
      await authStore.authEnterpriseOidcLogin(ticket);
      return;
    } catch (error) {
      const key = loginErrorMessageKey(error);
      loginError.value = $t(key === 'authentication.loginError.googleMfaUnsupported' ? key : 'authentication.loginError.ssoFailed');
    }
  }
  try {
    const status = await getRegistrationStatusApi();
    registrationEnabled.value = status.enabled;
  } catch {
    registrationEnabled.value = false;
  }
  if (isEsops) {
    try {
      const status = await getEnterpriseOidcStatusApi();
      if (status.enabled && status.login_url === '/api/v1/login/enterprise-oidc') {
        googleLoginUrl.value = status.login_url;
      }
    } catch {
      googleLoginUrl.value = '';
    }
  }
});
</script>

<template>
  <div class="w-full" :class="{ 'esops-login': isEsops }">
    <Alert v-if="loginError" class="mb-4" type="error" role="alert" show-icon :message="loginError" />
    <AuthenticationLogin
      :form-schema="formSchema"
      :loading="authStore.loginLoading"
      :show-code-login="false"
      :show-qrcode-login="false"
      :show-forget-password="true"
      :show-register="registrationEnabled"
      :show-third-party-login="false"
      :sub-title="$t('authentication.loginForm.subtitle')"
      @submit="handleSubmit"
    >
      <template v-if="isEsops" #title>
        <div class="esops-login-heading">
          <h1>{{ $t('authentication.esops.loginTitle') }}</h1>
          <p>{{ $t('authentication.esops.loginHint') }}</p>
        </div>
      </template>
      <template #to-register>
        <div v-if="registrationEnabled" class="mt-3 text-center text-sm">
          {{ $t('authentication.loginForm.noTenant') }}
          <RouterLink class="vben-link text-sm font-normal" to="/auth/register">
            {{ $t('authentication.loginForm.createTenant') }}
          </RouterLink>
        </div>
      </template>
    </AuthenticationLogin>

    <a v-if="googleLoginUrl" :href="googleLoginUrl" class="google-login">
      <SvgGoogleIcon aria-hidden="true" class="size-5 shrink-0" />
      {{ $t('authentication.esops.googleLogin') }}
    </a>

    <Verification
      ref="verifyRef"
      :brand-logo="isEsops ? esopsLogo : undefined"
      :check-captcha-api="checkSliderCaptchaApi"
      :get-captcha-api="getSliderCaptchaApi"
      :img-size="{ width: '400px', height: '200px' }"
      mode="pop"
      @on-success="handleVerifySuccess"
      @on-error="handleCaptchaError"
    />
  </div>
</template>

<style scoped>
.google-login { display: flex; justify-content: center; align-items: center; gap: 10px; min-height: 48px; margin-top: 20px; border: 1px solid #cbd5d0; border-radius: 8px; font-weight: 600; color: inherit; background: transparent; }
.google-login:hover { border-color: #059669; color: #047857; }
.esops-login-heading { margin-bottom: 32px; }
.esops-login-heading h1 { font-size: 32px; font-weight: 700; line-height: 1.4; margin: 0 0 12px; color: inherit; }
.esops-login-heading p { font-size: 15px; line-height: 1.7; color: var(--login-muted); }
.esops-login :deep(.esops-login-field) { margin-bottom: 8px; flex-direction: column; align-items: stretch; }
.esops-login :deep(.esops-field-label) { width: auto !important; justify-content: flex-start; margin-right: 0; font-size: 15px; font-weight: 500; padding-bottom: 8px; color: inherit; }
.esops-login :deep(input) { min-height: 52px; font-size: 16px; border-radius: 8px; }
.esops-login :deep(button.auth-login-submit) { min-height: 54px; border-radius: 8px; font-size: 18px; background: #059669; color: white; margin-top: 8px; }
.esops-login :deep(button.auth-login-submit:hover) { background: #047857; }
.esops-login :deep(.vben-link) { color: #047857; }
.esops-login :deep([data-state='checked']) { background-color: #059669; border-color: #059669; }
@media (max-width: 600px) { .esops-login-heading h1 { font-size: 27px; } }
</style>
