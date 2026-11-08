<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Button, Card, Form, FormItem, Input, InputPassword, Modal, Switch, Tag, message } from 'ant-design-vue';
import { getGoogleClientConfigApi, updateGoogleClientConfigApi, type GoogleClientConfig } from '#/api';

const config = ref<GoogleClientConfig>();
const open = ref(false);
const saving = ref(false);
const clientId = ref('');
const secret = ref('');
const password = ref('');
const mfaCode = ref('');
const enabled = ref(false);

async function load() {
  try { config.value = await getGoogleClientConfigApi(); }
  catch { config.value = undefined; }
}
function edit() {
  if (!config.value) return;
  clientId.value = config.value.client_id;
  enabled.value = config.value.enabled;
  secret.value = '';
  password.value = '';
  mfaCode.value = '';
  open.value = true;
}
function cancel() { secret.value = ''; password.value = ''; mfaCode.value = ''; }
async function save() {
  if (!clientId.value.trim() || !password.value) {
    message.warning('请填写 Client ID 和当前管理员密码');
    return;
  }
  saving.value = true;
  try {
    config.value = await updateGoogleClientConfigApi({
      client_id: clientId.value.trim(), enabled: enabled.value,
      current_password: password.value,
      ...(mfaCode.value ? { mfa_code: mfaCode.value } : {}),
      ...(secret.value ? { client_secret: secret.value } : {}),
    });
    open.value = false;
    cancel();
    message.success('Google 登录配置已保存');
  } finally { saving.value = false; }
}
onMounted(load);
</script>

<template>
  <Card v-if="config" title="Google 登录" class="mb-4">
    <template #extra><Button @click="edit">编辑配置</Button></template>
    <p>状态：<Tag :color="config.enabled ? 'success' : 'default'">{{ config.enabled ? '启用' : '停用' }}</Tag></p>
    <p>Client ID：{{ config.client_id || '未配置' }}</p>
    <p>Client Secret：{{ config.client_secret_configured ? '已配置' : '未配置' }}</p>
    <p>授权回调地址：{{ config.redirect_uri }}</p>
  </Card>
  <Modal v-model:open="open" title="Google 登录配置" :confirm-loading="saving" @ok="save" @cancel="cancel">
    <Form layout="vertical">
      <FormItem label="启用 Google 登录"><Switch v-model:checked="enabled" /></FormItem>
      <FormItem label="Client ID" required><Input v-model:value="clientId" autocomplete="off" /></FormItem>
      <FormItem label="Client Secret"><InputPassword v-model:value="secret" autocomplete="new-password" placeholder="留空保留现有密钥" /></FormItem>
      <FormItem label="当前管理员密码" required><InputPassword v-model:value="password" autocomplete="current-password" /></FormItem>
      <FormItem label="MFA 验证码"><Input v-model:value="mfaCode" autocomplete="one-time-code" placeholder="账号启用 MFA 时必填" /></FormItem>
      <p>授权回调地址：{{ config?.redirect_uri }}</p>
    </Form>
  </Modal>
</template>
