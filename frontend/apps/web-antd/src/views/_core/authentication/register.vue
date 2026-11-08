<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';
import type { Recordable } from '@vben/types';

import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { AuthenticationRegister, Verification, z } from '@vben/common-ui';
import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { $t } from '@vben/locales';

import { Alert, Button, Result, message } from 'ant-design-vue';

import {
  getRegistrationStatusApi,
  getSliderCaptchaApi,
  checkSliderCaptchaApi,
  checkRegistrationTenantCodeApi,
  sendRegistrationEmailCodeApi,
  sendLoginSmsCodeApi,
} from '#/api';
import { useAuthStore } from '#/store';
import esopsLogo from '#/assets/esops-logo.png';
import { buildManifest } from '#/modules/build-manifest';
const isEsops = buildManifest.edition === 'esop';

defineOptions({ name: 'Register' });

const authStore = useAuthStore();
const router = useRouter();
const registerRef = ref<InstanceType<typeof AuthenticationRegister>>();
const registrationEnabled = ref<boolean>();
const sending = ref(false);
const emailVerificationEnabled = ref(false);
const freeActivationKey = ref('');
const verificationRef = ref<InstanceType<typeof Verification>>();
let finishCaptcha: ((proof: string | undefined) => void) | undefined;
function cancelCaptcha() { const done = finishCaptcha; finishCaptcha = undefined; done?.(undefined); }
function onCaptchaSuccess({ captchaVerification }: { captchaVerification: string }) {
  const done = finishCaptcha; finishCaptcha = undefined; done?.(captchaVerification);
  verificationRef.value?.onClose();
}
function onCaptchaError() { cancelCaptcha(); verificationRef.value?.onClose(); message.error($t('authentication.loginError.captchaFailed')); }
onBeforeUnmount(cancelCaptcha);
const CODE_LENGTH = 6;
const platformTenantCode =
  import.meta.env.VITE_APP_DEFAULT_TENANT_CODE || 'default';

async function handleSendCode() {
  const formApi = registerRef.value?.getFormApi();
  if (!formApi) {
    return false;
  }
  const addressField = isEsops ? 'email' : 'mobile';
  await formApi.validateField(addressField);
  if (!(await formApi.isFieldValid(addressField))) {
    return false;
  }
  const values = await formApi.getValues();
  if (sending.value || finishCaptcha) return false;
  try {
    if (isEsops) {
      const proof = await new Promise<string | undefined>((resolve) => { finishCaptcha = resolve; verificationRef.value?.show(); });
      if (!proof) return false;
      sending.value = true;
      await sendRegistrationEmailCodeApi({ email: String(values.email).trim(), captcha_verification: proof });
      message.success($t('authentication.home.emailSent'));
      return;
    }
    sending.value = true;
    const result = await sendLoginSmsCodeApi({
      mobile: String(values.mobile),
      scene: 'register',
      tenant_code: platformTenantCode,
    });
    if (result.debug_code) {
      await formApi.setFieldValue('sms_code', result.debug_code);
      message.success('调试验证码已自动填入');
    } else {
      message.success('验证码已发送');
    }
  } finally {
    sending.value = false;
  }
}

const formSchema = computed((): VbenFormSchema[] => [
  {
    component: 'VbenInput',
    componentProps: { autocomplete: 'organization', placeholder: $t('authentication.registration.companyExample') },
    fieldName: 'tenant_name',
    label: $t('authentication.registration.company'),
    rules: z.string().min(2, { message: '租户名称至少 2 个字符' }),
  },
  {
    component: 'VbenInput',
    componentProps: { placeholder: $t('authentication.registration.codeExample') },
    fieldName: 'tenant_code',
    label: $t('authentication.registration.code'),
    description: $t('authentication.registration.codeRule'),
    rules: z
      .string()
      .trim()
      .min(5, { message: $t('authentication.registration.codeRule') })
      .regex(/^[a-z][a-z0-9-]{4,31}$/, $t('authentication.registration.codeRule'))
      .superRefine(async (value, context) => {
        if (!/^[a-z][a-z0-9-]{4,31}$/.test(value)) return;
        try {
          if (!(await checkRegistrationTenantCodeApi(value)).available) {
            context.addIssue({ code: z.ZodIssueCode.custom, message: $t('authentication.registration.codeTaken') });
          }
        } catch {
          context.addIssue({ code: z.ZodIssueCode.custom, message: $t('authentication.registration.codeCheckFailed') });
        }
      }),
  },
  {
    component: 'VbenInput',
    componentProps: { autocomplete: 'name', placeholder: $t('authentication.registration.nameExample') },
    fieldName: 'full_name',
    label: $t('authentication.registration.name'),
    rules: z.string().min(1, { message: '请输入管理员姓名' }),
  },
  {
    component: 'VbenInput',
    componentProps: {
      autocomplete: 'email',
      placeholder: $t('authentication.registration.emailExample'),
    },
    fieldName: 'email',
    label: $t('authentication.registration.email'),
    rules: z
      .string()
      .min(1, { message: $t('authentication.emailTip') })
      .email($t('authentication.emailValidErrorTip')),
  },
  ...(isEsops ? [] : [
  {
    component: 'VbenInput',
    componentProps: {
      autocomplete: 'tel',
      inputmode: 'tel',
      maxlength: 20,
      placeholder: '国际号码请输入 +国家码手机号',
    },
    fieldName: 'mobile',
    label: $t('authentication.mobile'),
    rules: z.string().refine((value) => /^1[3-9]\d{9}$/.test(value) || /^\+[1-9]\d{7,14}$/.test(value), {
      message: '请输入中国大陆手机号或 +国家码国际号码',
    }),
  },
  ]),
  {
    component: 'VbenPinInput',
    componentProps: {
      codeLength: CODE_LENGTH,
      disabled: isEsops && (!registrationEnabled.value || !emailVerificationEnabled.value),
      createText: (countdown: number) =>
        countdown > 0
          ? $t('authentication.sendText', [countdown])
          : $t('authentication.sendCode'),
      handleSendCode,
      loading: sending.value,
      maxTime: 60,
    },
    fieldName: isEsops ? 'email_code' : 'sms_code',
    label: isEsops ? $t('authentication.home.emailCode') : $t('authentication.code'),
    description: isEsops ? $t('authentication.registration.verificationHint') : undefined,
    rules: z.string().length(CODE_LENGTH, {
      message: $t('authentication.codeTip', [CODE_LENGTH]),
    }),
  },
  {
    component: 'VbenInputPassword',
    componentProps: {
      autocomplete: 'new-password',
      passwordStrength: true,
      placeholder: $t('authentication.registration.passwordExample'),
    },
    fieldName: 'password',
    label: $t('authentication.password'),
    rules: z.string().min(8, { message: '密码至少 8 位' }),
  },
  {
    component: 'VbenInputPassword',
    componentProps: {
      autocomplete: 'new-password',
      placeholder: $t('authentication.registration.confirmExample'),
    },
    dependencies: {
      rules(values) {
        return z
          .string()
          .min(8, { message: '密码至少 8 位' })
          .refine((value) => value === values.password, {
            message: $t('authentication.confirmPasswordTip'),
          });
      },
      triggerFields: ['password'],
    },
    fieldName: 'confirmPassword',
    label: $t('authentication.confirmPassword'),
  },
  {
    component: 'VbenCheckbox',
    fieldName: 'agreePolicy',
    hideLabel: true,
    componentProps: { 'aria-required': true },
    renderComponentContent: () => ({
      default: () =>
        h('span', [
          h('span', { class: 'mr-1 text-destructive', 'aria-hidden': true }, '*'),
          $t('authentication.agree'),
          h(
            'span',
            { class: 'ml-1 text-muted-foreground' },
            `${$t('authentication.privacyPolicy')} & ${$t('authentication.terms')}`,
          ),
        ]),
    }),
    rules: z.boolean().refine(Boolean, {
      message: $t('authentication.agreeTip'),
    }),
  },
]);

async function handleSubmit(values: Recordable<any>) {
  if (isEsops && (!registrationEnabled.value || !emailVerificationEnabled.value)) {
    message.info($t('authentication.home.emailPending'));
    return;
  }
  const result = await authStore.authTenantRegister({
    email: String(values.email),
    full_name: String(values.full_name),
    password: String(values.password),
    ...(isEsops
      ? { email_code: String(values.email_code) }
      : { mobile: String(values.mobile), sms_code: String(values.sms_code) }),
    tenant_code: String(values.tenant_code ?? '').trim(),
    tenant_name: String(values.tenant_name),
  }, async () => {});
  if (result.freeActivationKey) {
    freeActivationKey.value = result.freeActivationKey;
  } else {
    await router.push(preferences.app.defaultHomePath);
  }
}

onMounted(async () => {
  try {
    const status = await getRegistrationStatusApi();
    registrationEnabled.value = status.enabled;
    emailVerificationEnabled.value = status.email_verification_enabled === true;
  } catch {
    registrationEnabled.value = false;
  }
});
</script>

<template>
  <div class="w-full">
  <Alert v-if="isEsops && (!registrationEnabled || !emailVerificationEnabled)" class="mb-6" type="info" show-icon :message="$t(registrationEnabled === false ? 'authentication.home.registrationClosed' : 'authentication.home.emailPending')" />
  <p v-if="!isEsops && registrationEnabled === undefined" role="status">{{ $t('authentication.home.loading') }}</p>
  <AuthenticationRegister
    v-if="(isEsops || registrationEnabled) && !freeActivationKey"
    ref="registerRef"
    show-labels
    :form-schema="formSchema"
    :loading="authStore.loginLoading"
    class="pb-16"
    :sub-title="isEsops ? $t('authentication.home.registerHint') : '创建租户并初始化管理员账号'"
    :title="isEsops ? $t('authentication.home.registerTitle') : '创建租户'"
    @submit="handleSubmit"
  >
    <template v-if="isEsops" #title>{{ $t('authentication.home.registerTitle') }}</template>
  </AuthenticationRegister>
  <Result
    v-else-if="freeActivationKey"
    status="success"
    title="注册成功，已获赠一个永久终端密钥"
    sub-title="请复制保存。此密钥仅在这里显示一次，设备激活后即可使用。"
  >
    <template #extra>
      <div class="mb-4 select-all font-mono text-2xl">{{ freeActivationKey }}</div>
      <Button type="primary" @click="router.push(preferences.app.defaultHomePath)">进入管理后台</Button>
    </template>
  </Result>
  <Result
    v-else-if="registrationEnabled === false"
    status="403"
    sub-title="请联系平台管理员开通公开注册"
    title="公开注册未开放"
  >
    <template #extra>
      <Button type="primary" @click="router.push(LOGIN_PATH)">返回登录</Button>
    </template>
  </Result>
  <Verification ref="verificationRef" :brand-logo="esopsLogo" :check-captcha-api="checkSliderCaptchaApi" :get-captcha-api="getSliderCaptchaApi" :img-size="{ width: '400px', height: '200px' }" mode="pop" @on-success="onCaptchaSuccess" @on-close="cancelCaptcha" @on-error="onCaptchaError" />
  </div>
</template>
