<script lang="ts" setup>
import { onBeforeUnmount, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Verification } from '@vben/common-ui';
import { $t } from '@vben/locales';
import { Button, Form, FormItem, Input, InputPassword, message } from 'ant-design-vue';
import type { FormInstance } from 'ant-design-vue';
import { checkSliderCaptchaApi, getSliderCaptchaApi, sendPasswordRecoveryCodeApi, verifyPasswordRecoveryCodeApi, completePasswordRecoveryApi } from '#/api';
import esopsLogo from '#/assets/esops-logo.png';

defineOptions({ name: 'ForgetPassword' });
const router = useRouter();
const formRef = ref<FormInstance>();
const verificationRef = ref<InstanceType<typeof Verification>>();
const busy = ref(false);
const remaining = ref(0);
const step = ref(0);
const resetToken = ref('');
const form = reactive({ tenant_code: '', email: '', code: '', new_password: '', confirm_password: '' });
let timer: ReturnType<typeof setInterval> | undefined;
let pendingAddress: null | { tenant_code: string; email: string } = null;
onBeforeUnmount(() => { if (timer) clearInterval(timer); resetToken.value = ''; pendingAddress = null; });

async function requestCode() {
  try { await formRef.value?.validateFields(['tenant_code', 'email']); } catch { return; }
  pendingAddress = { tenant_code: form.tenant_code.trim(), email: form.email.trim() };
  verificationRef.value?.show();
}
async function onVerified({ captchaVerification }: { captchaVerification: string }) {
  const target = pendingAddress;
  pendingAddress = null;
  verificationRef.value?.onClose();
  if (!target || busy.value) return;
  busy.value = true;
  try {
    const result = await sendPasswordRecoveryCodeApi({ ...target, captcha_verification: captchaVerification });
    remaining.value = result.retry_after_seconds ?? 60;
    if (timer) clearInterval(timer);
    timer = setInterval(() => { if (remaining.value > 0) remaining.value--; else if (timer) clearInterval(timer); }, 1000);
    message.success($t('authentication.recovery.sent'));
  } finally { busy.value = false; }
}
function onVerificationError() {
  pendingAddress = null;
  verificationRef.value?.onClose();
  message.error($t('authentication.loginError.captchaFailed'));
}
async function next() {
  if (busy.value) return;
  try { await formRef.value?.validate(); } catch { return; }
  busy.value = true;
  try {
    const result = await verifyPasswordRecoveryCodeApi({ tenant_code: form.tenant_code.trim(), email: form.email.trim(), code: form.code });
    resetToken.value = result.reset_token;
    form.code = '';
    step.value = 1;
    formRef.value?.clearValidate();
  } finally { busy.value = false; }
}
async function confirmPassword(_rule: unknown, value: string) {
  if (value !== form.new_password) throw new Error($t('authentication.recovery.mismatch'));
}
async function reset() {
  if (busy.value) return;
  try { await formRef.value?.validate(); } catch { return; }
  busy.value = true;
  try {
    await completePasswordRecoveryApi({ reset_token: resetToken.value, new_password: form.new_password, confirm_password: form.confirm_password });
    resetToken.value = ''; form.new_password = ''; form.confirm_password = '';
    message.success($t('authentication.recovery.success'));
    await router.replace('/auth/login');
  } finally { busy.value = false; }
}
</script>

<template>
  <section class="recovery-form">
    <h1>{{ $t('authentication.recovery.title') }}</h1>
    <p class="intro">{{ $t('authentication.recovery.intro') }}</p>
    <ol class="steps" :aria-label="$t('authentication.recovery.title')"><li :class="{ active: step === 0 }">{{ $t('authentication.recovery.verifyStep') }}</li><li :class="{ active: step === 1 }">{{ $t('authentication.recovery.passwordStep') }}</li></ol>
    <Form ref="formRef" :model="form" layout="vertical" @finish="step === 0 ? next() : reset()">
      <template v-if="step === 0">
        <FormItem name="tenant_code" :label="$t('authentication.recovery.tenant')" :rules="[{ required: true, whitespace: true, message: $t('authentication.recovery.tenantRequired') }]">
          <Input v-model:value="form.tenant_code" autocomplete="organization" :maxlength="100" :placeholder="$t('authentication.recovery.tenantExample')" />
        </FormItem>
        <FormItem name="email" :label="$t('authentication.registration.email')" :rules="[{ required: true, type: 'email', message: $t('authentication.emailValidErrorTip') }]">
          <Input v-model:value="form.email" autocomplete="email" :maxlength="255" :placeholder="$t('authentication.registration.emailExample')" />
        </FormItem>
        <FormItem name="code" :label="$t('authentication.home.emailCode')" :rules="[{ required: true, pattern: /^[0-9]{6}$/, message: $t('authentication.recovery.codeRequired') }]">
          <div class="code-row"><Input v-model:value="form.code" autocomplete="one-time-code" inputmode="numeric" :maxlength="6" :placeholder="$t('authentication.recovery.codePlaceholder')" /><Button :loading="busy" :disabled="remaining > 0" @click="requestCode">{{ remaining > 0 ? $t('authentication.sendText', [remaining]) : $t('authentication.sendCode') }}</Button></div>
          <p class="hint">{{ $t('authentication.recovery.codeHint') }}</p>
        </FormItem>
        <Button block type="primary" html-type="submit" :loading="busy">{{ $t('authentication.recovery.next') }}</Button>
      </template>
      <template v-else>
        <p class="verified">{{ $t('authentication.recovery.verified') }}</p>
        <FormItem name="new_password" :label="$t('authentication.recovery.newPassword')" :rules="[{ required: true, min: 8, max: 128, message: $t('authentication.recovery.passwordRule') }]">
          <InputPassword v-model:value="form.new_password" autocomplete="new-password" :maxlength="128" :placeholder="$t('authentication.registration.passwordExample')" />
        </FormItem>
        <FormItem name="confirm_password" :label="$t('authentication.confirmPassword')" :rules="[{ required: true, message: $t('authentication.recovery.confirmRequired') }, { validator: confirmPassword }]">
          <InputPassword v-model:value="form.confirm_password" autocomplete="new-password" :maxlength="128" :placeholder="$t('authentication.registration.confirmExample')" />
        </FormItem>
        <Button block type="primary" html-type="submit" :loading="busy">{{ $t('authentication.recovery.submit') }}</Button>
        <Button block type="text" class="mt-3" :disabled="busy" @click="step = 0; resetToken = ''">{{ $t('authentication.recovery.restart') }}</Button>
      </template>
    </Form>
    <RouterLink class="back" to="/auth/login">{{ $t('authentication.recovery.back') }}</RouterLink>
    <Verification ref="verificationRef" :brand-logo="esopsLogo" :check-captcha-api="checkSliderCaptchaApi" :get-captcha-api="getSliderCaptchaApi" :img-size="{ width: '400px', height: '200px' }" mode="pop" @on-success="onVerified" @on-close="pendingAddress = null" @on-error="onVerificationError" />
  </section>
</template>

<style scoped>
.recovery-form { width: 100%; min-width: 0; } h1 { font-size: 30px; font-weight: 700; line-height: 1.4; }.intro { margin: 12px 0 28px; color: var(--login-muted, #52665a); line-height: 1.7; }.steps { display: flex; gap: 24px; margin-bottom: 28px; padding: 0; list-style: none; color: var(--login-muted, #52665a); }.steps li { flex: 1; padding-bottom: 12px; border-bottom: 2px solid #dce6df; }.steps .active { color: #047857; border-color: #047857; font-weight: 600; }.code-row { display: flex; gap: 10px; }.code-row .ant-input { min-width: 0; }.hint { margin: 8px 0 0; font-size: 13px; color: var(--login-muted, #52665a); line-height: 1.6; }.verified { margin-bottom: 24px; color: #047857; }.back { display: block; text-align: center; margin-top: 24px; color: #047857; }.recovery-form :deep(.ant-input), .recovery-form :deep(.ant-input-affix-wrapper), .recovery-form :deep(.ant-btn) { min-height: 44px; }.recovery-form :deep(.ant-btn-primary) { background: #047857; }@media(max-width: 480px) { .code-row { flex-direction: column; }.steps { gap: 12px; font-size: 14px; }h1 { font-size: 26px; } }
</style>
