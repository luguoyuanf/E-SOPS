<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { useQRCode } from '@vueuse/integrations/useQRCode';

import {
  Alert,
  Button,
  Card,
  Descriptions,
  DescriptionsItem,
  Input,
  InputPassword,
  Modal,
  Tag,
  message,
} from 'ant-design-vue';

import {
  disableCurrentUserMfaApi,
  enableCurrentUserMfaApi,
  getCurrentUserMfaStatusApi,
  getGoogleBindingApi,
  startGoogleBindingApi,
  setupCurrentUserMfaApi,
  type AuthApi,
} from '#/api';
import { buildManifest } from '#/modules/build-manifest';
import { loginErrorBody } from '#/api/core/login-error';
import { googleBindingNeedsLocalhost, validGoogleBindingMfa } from './google-binding';

const loading = ref(false);
const setupCode = ref('');
const setupData = ref<AuthApi.MfaSetup>();
const setupModalOpen = ref(false);
const recoveryCodes = ref<string[]>([]);
const recoveryModalOpen = ref(false);
const status = ref<AuthApi.MfaStatus>();
const disableCode = ref('');
const disableModalOpen = ref(false);
const currentPassword = ref('');
const googleBinding = ref<{ eligible: boolean; bound: boolean; email: null | string }>();
const googleLoading = ref(false);
const googleModalOpen = ref(false);
const googlePassword = ref('');
const googleMfaCode = ref('');
const googleMfaRequired = ref(false);

async function openGoogleBindingModal() {
  if (googleBindingNeedsLocalhost(window.location.hostname)) {
    message.warning('请使用 http://localhost:18095 重新登录后绑定 Google 账号');
    return;
  }
  googleLoading.value = true;
  try {
    await refreshStatus();
    if (!status.value) throw new Error('MFA status unavailable');
    googleMfaRequired.value = status.value.enabled;
    googlePassword.value = '';
    googleMfaCode.value = '';
    googleModalOpen.value = true;
  } catch {
    message.error('无法获取多重验证状态，请稍后重试');
  } finally { googleLoading.value = false; }
}

async function refreshGoogleBinding() {
  if (buildManifest.edition !== 'esop') return;
  try { googleBinding.value = await getGoogleBindingApi(); }
  catch { googleBinding.value = undefined; }
}

async function beginGoogleBinding() {
  if (googleLoading.value) return;
  if (!googlePassword.value) {
    message.warning('请输入当前账号密码');
    return;
  }
  if (!validGoogleBindingMfa(googleMfaRequired.value, googleMfaCode.value)) {
    message.warning('请输入身份验证器中的 6 位验证码');
    return;
  }
  googleLoading.value = true;
  try {
    const { authorization_url: authorizationUrl } = await startGoogleBindingApi(googlePassword.value, googleMfaRequired.value ? googleMfaCode.value : undefined);
    const url = new URL(authorizationUrl);
    if (url.protocol !== 'https:' || url.hostname !== 'accounts.google.com') {
      throw new Error('Invalid Google authorization URL');
    }
    window.location.assign(url.href);
  } catch (error) {
    const body = loginErrorBody(error);
    if (body.code === 'AUTH_MFA_REQUIRED' || body.code === 'AUTH_MFA_INVALID' || body.message === 'MFA verification required') {
      message.error('多重验证失败，请检查验证码后重试');
    } else {
      message.error('无法开始 Google 账号绑定，请检查密码和账号状态后重试');
    }
    googleLoading.value = false;
  }
}

const qrCode = useQRCode(
  computed(() => setupData.value?.otpauth_uri || ''),
  {
    errorCorrectionLevel: 'M',
    margin: 2,
  },
);

const isEnabled = computed(() => status.value?.enabled === true);
const statusText = computed(() => (isEnabled.value ? '已启用' : '未启用'));

function normalizedCode(code: string) {
  return code.replaceAll(/\D/g, '');
}

async function refreshStatus() {
  status.value = await getCurrentUserMfaStatusApi();
}

async function beginSetup() {
  loading.value = true;
  try {
    setupData.value = await setupCurrentUserMfaApi();
    setupCode.value = '';
    setupModalOpen.value = true;
  } finally {
    loading.value = false;
  }
}

async function confirmSetup() {
  const code = normalizedCode(setupCode.value);
  if (code.length !== 6) {
    message.warning('请输入认证器中的 6 位验证码');
    return;
  }

  loading.value = true;
  try {
    const result = await enableCurrentUserMfaApi({ code });
    setupData.value = undefined;
    setupModalOpen.value = false;
    recoveryCodes.value = result.recovery_codes;
    recoveryModalOpen.value = true;
    await refreshStatus();
    message.success('MFA 已启用');
  } finally {
    loading.value = false;
  }
}

function openDisableModal() {
  currentPassword.value = '';
  disableCode.value = '';
  disableModalOpen.value = true;
}

async function confirmDisable() {
  const code = normalizedCode(disableCode.value);
  if (!currentPassword.value) {
    message.warning('请输入当前密码');
    return;
  }
  if (code.length !== 6) {
    message.warning('请输入认证器中的 6 位验证码');
    return;
  }

  loading.value = true;
  try {
    await disableCurrentUserMfaApi({
      code,
      current_password: currentPassword.value,
    });
    disableModalOpen.value = false;
    await refreshStatus();
    message.success('MFA 已关闭');
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void refreshStatus();
  void refreshGoogleBinding();
});
</script>

<template>
  <Card v-if="buildManifest.edition === 'esop' && googleBinding?.eligible !== false" class="mb-4 max-w-3xl" :bordered="false" title="Google 登录">
    <template #extra><Tag :color="googleBinding?.bound ? 'success' : 'default'">{{ googleBinding ? (googleBinding.bound ? '已绑定' : '未绑定') : '状态不可用' }}</Tag></template>
    <p v-if="googleBinding?.bound">Google 账号已绑定{{ googleBinding.email ? `：${googleBinding.email}` : '' }}。绑定后不可解绑。</p>
    <p v-else-if="googleBinding">绑定 Google 账号后可使用 Google 登录当前企业，绑定后不可解绑。</p>
    <p v-else>暂时无法获取 Google 绑定状态，请重试。</p>
    <Button v-if="googleBinding && !googleBinding.bound" class="mt-4" :loading="googleLoading" @click="openGoogleBindingModal">绑定 Google 账号</Button>
    <Button v-if="!googleBinding" class="mt-4" @click="refreshGoogleBinding">重新获取状态</Button>
  </Card>
  <Modal v-model:open="googleModalOpen" title="验证当前账号" :confirm-loading="googleLoading" @ok="beginGoogleBinding" @cancel="googlePassword = ''; googleMfaCode = ''">
    <p class="mb-3">为保护账号，请输入当前密码。绑定后不可解绑。</p>
    <InputPassword v-model:value="googlePassword" autocomplete="current-password" placeholder="当前密码" @press-enter="beginGoogleBinding" />
    <Input v-if="googleMfaRequired" v-model:value="googleMfaCode" class="mt-3" autocomplete="one-time-code" inputmode="numeric" :maxlength="6" placeholder="6 位 MFA 验证码" @press-enter="beginGoogleBinding" />
  </Modal>
  <Card class="max-w-3xl" :bordered="false">
    <template #title>多重验证</template>
    <template #extra>
      <Tag :color="isEnabled ? 'success' : 'default'">{{ statusText }}</Tag>
    </template>

    <Descriptions :column="1" size="small">
      <DescriptionsItem label="验证方式">
        {{ isEnabled ? '身份验证器（TOTP）' : '尚未绑定' }}
      </DescriptionsItem>
      <DescriptionsItem label="登录二次验证">
        {{ isEnabled ? '已启用' : '未启用' }}
      </DescriptionsItem>
      <DescriptionsItem v-if="isEnabled" label="剩余恢复码">
        {{ status?.recovery_codes_remaining || 0 }} 个
      </DescriptionsItem>
    </Descriptions>

    <div class="mt-6 flex gap-3">
      <Button v-if="!isEnabled" type="primary" :loading="loading" @click="beginSetup">
        {{ status?.pending_setup ? '重新开始绑定' : '开始绑定' }}
      </Button>
      <Button v-else danger :loading="loading" @click="openDisableModal">
        关闭 MFA
      </Button>
    </div>
  </Card>

  <Modal
    v-model:open="setupModalOpen"
    :confirm-loading="loading"
    :mask-closable="!loading"
    title="绑定身份验证器"
    @ok="confirmSetup"
  >
    <div v-if="setupData" class="space-y-4 py-2">
      <Alert
        message="请使用身份验证器扫描二维码，然后输入当前显示的验证码确认绑定。"
        show-icon
        type="info"
      />
      <div class="flex justify-center">
        <img :src="qrCode" alt="TOTP 二维码" class="size-52" />
      </div>
      <div>
        <div class="mb-1 text-sm text-muted-foreground">手动密钥</div>
        <div class="break-all rounded border bg-muted px-3 py-2 font-mono text-sm">
          {{ setupData.secret }}
        </div>
      </div>
      <Input
        v-model:value="setupCode"
        autocomplete="one-time-code"
        inputmode="numeric"
        :maxlength="6"
        placeholder="输入 6 位验证码"
      />
    </div>
  </Modal>

  <Modal
    v-model:open="recoveryModalOpen"
    :closable="false"
    :mask-closable="false"
    :footer="null"
    title="保存恢复码"
  >
    <div class="space-y-4 py-2">
      <Alert
        message="每个恢复码只能使用一次。关闭此窗口后无法再次查看，请立即保存。"
        show-icon
        type="warning"
      />
      <div class="grid grid-cols-2 gap-2 rounded border bg-muted p-3 font-mono text-sm">
        <span v-for="code in recoveryCodes" :key="code">{{ code }}</span>
      </div>
      <div class="flex justify-end">
        <Button type="primary" @click="recoveryModalOpen = false">我已保存</Button>
      </div>
    </div>
  </Modal>

  <Modal
    v-model:open="disableModalOpen"
    :confirm-loading="loading"
    :mask-closable="!loading"
    title="关闭 MFA"
    @ok="confirmDisable"
  >
    <div class="space-y-4 py-2">
      <Alert
        message="关闭前需要验证当前密码和身份验证器验证码。"
        show-icon
        type="warning"
      />
      <InputPassword
        v-model:value="currentPassword"
        autocomplete="current-password"
        placeholder="当前密码"
      />
      <Input
        v-model:value="disableCode"
        autocomplete="one-time-code"
        inputmode="numeric"
        :maxlength="6"
        placeholder="身份验证器中的 6 位验证码"
      />
    </div>
  </Modal>
</template>
