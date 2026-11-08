<script lang="ts" setup>
import type { FormInstance } from 'ant-design-vue';
import type { PurchasePageContent } from '../../api/commercial';
import type { FileStorageUsagePublic } from '#/api/generated';

import { onMounted, ref } from 'vue';
import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Form, Input, message, Modal, Spin, Table } from 'ant-design-vue';
import { getCurrentUserApi } from '#/api/core/auth';
import { getCurrentStorageUsageApi } from '#/api/core/files';
import { getPurchaseContent, savePurchaseContent } from '../../api/commercial';

const columns = [
  { title: '客户类型', dataIndex: 'customer', key: 'customer' },
  { title: '一次购买终端密钥数量', dataIndex: 'quantity', key: 'quantity' },
  { title: '设备授权价格', dataIndex: 'price', key: 'price' },
];
const content = ref<PurchasePageContent>();
const storageUsage = ref<FileStorageUsagePublic>();
const formatStorage = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
const draft = ref<PurchasePageContent>();
const isAdmin = ref(false);
const loading = ref(false);
const saving = ref(false);
const editorOpen = ref(false);
const formRef = ref<FormInstance>();
const priceRowKey = (_row: unknown, index?: number) => index ?? 0;
const required = [{ required: true, whitespace: true, message: '请填写内容' }];

async function load() {
  loading.value = true;
  try {
    const [page, user, usage] = await Promise.all([getPurchaseContent(), getCurrentUserApi(), getCurrentStorageUsageApi()]);
    storageUsage.value = usage;
    content.value = page;
    isAdmin.value = !!user.is_superuser;
  } finally { loading.value = false; }
}
function openEditor() {
  draft.value = JSON.parse(JSON.stringify(content.value));
  editorOpen.value = true;
}
function closeEditor() {
  editorOpen.value = false;
}
async function save() {
  if (!draft.value || saving.value) return;
  await formRef.value?.validate();
  if (draft.value.prices?.some(row => !row.customer.trim() || !row.quantity.trim() || !row.price.trim())) {
    return message.warning('请完整填写每一行价格信息，或删除空行');
  }
  saving.value = true;
  try {
    content.value = await savePurchaseContent(draft.value);
    editorOpen.value = false;
    message.success('内容已保存，渠道和租户可查看最新内容');
  } finally { saving.value = false; }
}
onMounted(() => void load());
</script>

<template>
  <Page :title="content?.title || '购买与扩容'">
    <Spin :spinning="loading">
      <template v-if="content">
        <div v-if="isAdmin" class="mb-4 flex justify-end"><Button type="primary" @click="openEditor">编辑内容</Button></div>
        <Alert class="mb-5 whitespace-pre-line" :message="content.contact_text" type="info" show-icon />
        <Card :title="content.device_title" class="mb-5">
          <p class="mb-4 whitespace-pre-line text-sm text-gray-500">{{ content.device_description }}</p>
          <Table :columns="columns" :data-source="content.prices" :row-key="priceRowKey" :pagination="false" size="small" />
        </Card>
        <Card :title="content.storage_title">
          <Alert v-if="storageUsage" class="mb-4" :type="storageUsage.warning ? 'warning' : 'info'" show-icon>
            <template #message>
              已使用 {{ formatStorage(storageUsage.used_bytes) }} / 总容量 {{ storageUsage.limit_bytes === null ? '不限' : formatStorage(storageUsage.limit_bytes) }}
              <span v-if="storageUsage.remaining_bytes !== null">，剩余 {{ formatStorage(storageUsage.remaining_bytes) }}</span>
            </template>
            <template #description>租户所有上传文件统一计入存储容量。剩余不足时，请联系购买存储扩容包。</template>
          </Alert>
          <p class="whitespace-pre-line">{{ content.storage_description }}</p>
          <p class="mt-2 whitespace-pre-line text-sm text-gray-500">{{ content.storage_note }}</p>
        </Card>
      </template>
      <Alert v-else-if="!loading" message="内容加载失败，请重试。" type="error"><template #action><Button @click="load">重新加载</Button></template></Alert>
    </Spin>
    <Modal :open="editorOpen" title="编辑购买与扩容内容" :width="900" :keyboard="true" :confirm-loading="saving" ok-text="保存内容" :destroy-on-close="true" @ok="save" @cancel="closeEditor">
      <Form v-if="draft" ref="formRef" :model="draft" layout="vertical" class="max-h-[65vh] overflow-y-auto pr-2">
        <Form.Item label="页面标题" name="title" :rules="required"><Input v-model:value="draft.title" :maxlength="100" /></Form.Item>
        <Form.Item label="购买联系说明" name="contact_text" :rules="required"><Input.TextArea v-model:value="draft.contact_text" :maxlength="2000" :rows="2" /></Form.Item>
        <Form.Item label="设备授权标题" name="device_title" :rules="required"><Input v-model:value="draft.device_title" :maxlength="100" /></Form.Item>
        <Form.Item label="设备授权说明" name="device_description" :rules="required"><Input.TextArea v-model:value="draft.device_description" :maxlength="4000" :rows="3" /></Form.Item>
        <Form.Item label="设备授权价格表">
          <div v-for="(row, index) in draft.prices" :key="index" class="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
            <Input v-model:value="row.customer" :maxlength="100" :aria-label="`第${index + 1}行客户类型`" placeholder="客户类型" />
            <Input v-model:value="row.quantity" :maxlength="100" :aria-label="`第${index + 1}行终端数量`" placeholder="终端数量" />
            <Input v-model:value="row.price" :maxlength="100" :aria-label="`第${index + 1}行授权价格`" placeholder="授权价格" />
            <Button danger @click="draft.prices?.splice(index, 1)">删除</Button>
          </div>
          <Button :disabled="(draft.prices?.length || 0) >= 30" @click="(draft.prices ||= []).push({ customer: '', quantity: '', price: '' })">添加价格行</Button>
        </Form.Item>
        <Form.Item label="存储扩容标题" name="storage_title" :rules="required"><Input v-model:value="draft.storage_title" :maxlength="100" /></Form.Item>
        <Form.Item label="存储扩容说明" name="storage_description" :rules="required"><Input.TextArea v-model:value="draft.storage_description" :maxlength="4000" :rows="4" /></Form.Item>
        <Form.Item label="存储补充说明" name="storage_note"><Input.TextArea v-model:value="draft.storage_note" :maxlength="2000" :rows="2" /></Form.Item>
      </Form>
    </Modal>
  </Page>
</template>
