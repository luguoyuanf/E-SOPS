<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { ChannelBatch, ChannelCustomer, ChannelKey, ChannelWorkspace } from '../../api/channel';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';

import { Alert, Button, Checkbox, DatePicker, Drawer, Form, Input, message, Select, Table as RawTable, Tag } from 'ant-design-vue';
import { createdRangeQuery } from '#/utils/created-range';

import { getCurrentUserApi } from '#/api/core/auth';

import { assignChannelKeys, createChannelCustomer, exportChannelKeys, getChannelWorkspace, listChannelBatches, listChannelCustomers, listChannelKeys } from '../../api/channel';

const workspace = ref<ChannelWorkspace>();
const unavailable = ref(false);
const customers = ref<ChannelCustomer[]>([]);
const batches = ref<ChannelBatch[]>([]);
const keys = ref<ChannelKey[]>([]);
const keyCreatedRange = ref<[string, string]>();
const page = ref(1);
const total = ref(0);
const batchId = ref<string>();
const loading = ref(false);
const saving = ref(false);
const customerOpen = ref(false);
const assignOpen = ref(false);
const selectedIds = ref<string[]>([]);
const selectedTenant = ref<string>();
const customerForm = reactive({ code: '', name: '' });
const customerNames = computed(() => new Map(customers.value.map((item) => [item.tenant_id, item.tenant_name])));
const customerOptions = computed(() => customers.value.map((item) => ({ label: `${item.tenant_name} (${item.tenant_code})`, value: item.tenant_id })));
const available = computed(() => batches.value.reduce((sum, item) => sum + item.quantity - item.assigned_count, 0));
const assigned = computed(() => batches.value.reduce((sum, item) => sum + item.assigned_count - item.activated_count, 0));
const used = computed(() => batches.value.reduce((sum, item) => sum + item.activated_count, 0));
const batchOptions = computed(() => batches.value.map((item) => ({ label: `${item.batch_id.slice(0, 8)} · ${item.quantity} 个`, value: item.batch_id })));
const columns = [
  { title: '选择', key: 'select', width: 65 }, { title: '密钥', key: 'key', width: 140 },
  { title: '批次', key: 'batch', width: 120 }, { title: '客户', key: 'customer' },
  { title: '状态', key: 'status', width: 100 }, { title: '激活时间', dataIndex: 'used_at', key: 'used_at', width: 190 },
];
const customerColumns = [
  { title: '客户编码', dataIndex: 'tenant_code', key: 'tenant_code' },
  { title: '客户企业', dataIndex: 'tenant_name', key: 'tenant_name' },
];

async function refresh() {
  loading.value = true;
  try {
    if ((await getCurrentUserApi()).is_superuser) { unavailable.value = true; return; }
    try { workspace.value = await getChannelWorkspace(); }
    catch { unavailable.value = true; return; }
    const [batchResult, customerResult] = await Promise.all([listChannelBatches(), listChannelCustomers()]);
    batches.value = batchResult.items;
    customers.value = customerResult.items;
    await loadKeys();
    selectedIds.value = [];
  } finally { loading.value = false; }
}

async function loadKeys() {
  const result = await listChannelKeys({ batch_id: batchId.value, page: page.value, page_size: 20, ...createdRangeQuery(keyCreatedRange.value) });
  keys.value = result.items;
  total.value = result.total;
}

async function changeBatch() {
  page.value = 1;
  selectedIds.value = [];
  await loadKeys();
}

async function changePage(pagination: { current?: number }) {
  page.value = pagination.current || 1;
  selectedIds.value = [];
  await loadKeys();
}

async function exportKeys(selection: 'batch' | 'selected') {
  if (selection === 'batch' && !batchId.value) return message.warning('请先选择批次');
  if (selection === 'selected' && selectedIds.value.length === 0) return message.warning('请先勾选密钥');
  const blob = await exportChannelKeys(selection === 'batch' ? { batch_id: batchId.value } : { key_ids: selectedIds.value });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `渠道密钥-${selection === 'batch' ? batchId.value : '已选'}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function toggle(id: string, checked: boolean) {
  selectedIds.value = checked ? [...selectedIds.value, id] : selectedIds.value.filter((item) => item !== id);
}

function openCustomer() {
  customerForm.code = '';
  customerForm.name = '';
  customerOpen.value = true;
}

async function saveCustomer() {
  if (customerForm.name.trim().length < 2) return message.warning('企业名称至少 2 位');
  saving.value = true;
  try {
    await createChannelCustomer({ code: customerForm.code.trim(), name: customerForm.name.trim() });
    customerOpen.value = false;
    await refresh();
    message.success('客户租户已创建');
  } finally { saving.value = false; }
}

function openAssign() {
  if (selectedIds.value.length === 0 || keys.value.some((item) => selectedIds.value.includes(item.id) && item.status !== 'unassigned')) return message.warning('请只选择未分配的密钥');
  selectedTenant.value = undefined;
  assignOpen.value = true;
}

async function saveAssign() {
  if (!selectedTenant.value) return message.warning('请选择客户企业');
  saving.value = true;
  try {
    const result = await assignChannelKeys({ tenant_id: selectedTenant.value, key_ids: selectedIds.value });
    assignOpen.value = false;
    await refresh();
    message.success(`已分配 ${result.assigned_count} 个密钥`);
  } finally { saving.value = false; }
}

onMounted(() => void refresh());
</script>

<template>
  <Page :title="workspace ? `${workspace.channel_name} · 渠道工作台` : '渠道工作台'">
    <Alert v-if="unavailable" message="请使用已关联渠道的管理员账号进入工作台。" type="info" show-icon />
    <template v-else-if="workspace">
    <div class="mb-5 grid gap-3 sm:grid-cols-3">
      <div class="rounded bg-[var(--vben-bg-color)] p-4"><div class="text-sm text-gray-500">可分配</div><div class="text-2xl font-semibold">{{ available }}</div></div>
      <div class="rounded bg-[var(--vben-bg-color)] p-4"><div class="text-sm text-gray-500">已分配</div><div class="text-2xl font-semibold">{{ assigned }}</div></div>
      <div class="rounded bg-[var(--vben-bg-color)] p-4"><div class="text-sm text-gray-500">已激活</div><div class="text-2xl font-semibold">{{ used }}</div></div>
    </div>
    <div class="mb-4 flex items-center justify-between"><h2 class="text-base font-semibold">客户企业</h2><Button v-access:code="'esop:channel:portal'" type="primary" @click="openCustomer">开通客户租户</Button></div>
    <Table class="mb-7" date-field="created_at" :columns="customerColumns" :data-source="customers" :loading="loading" :pagination="false" row-key="tenant_id" />
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
<h2 class="text-base font-semibold">授权密钥库存</h2>
      <div class="flex flex-wrap items-center gap-2">
        <Select v-model:value="batchId" :options="batchOptions" allow-clear class="min-w-52" placeholder="全部批次" @change="changeBatch" />
        <DatePicker.RangePicker v-model:value="keyCreatedRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" @change="changeBatch" />
        <Button :disabled="!batchId" @click="exportKeys('batch')">导出当前批次</Button>
        <Button :disabled="!selectedIds.length" @click="exportKeys('selected')">导出所选（{{ selectedIds.length }}）</Button>
        <Button v-access:code="'esop:channel:portal'" :disabled="!selectedIds.length" type="primary" @click="openAssign">分配所选</Button>
      </div>
    </div>
    <p class="mb-3 text-sm text-gray-500">可重复查看和导出密钥。旧密钥若不可回读，会显示“不可回读”。</p>
    <p class="mb-2 text-sm text-muted-foreground">已选 {{ selectedIds.length }} 项</p>
    <RawTable :columns="columns" :data-source="keys" :loading="loading" :pagination="{ current: page, pageSize: 20, total, showSizeChanger: false }" row-key="id" @change="changePage">
      <template #bodyCell="{ column, record }">
        <Checkbox v-if="column.key === 'select'" :checked="selectedIds.includes((record as ChannelKey).id)" @change="toggle((record as ChannelKey).id, $event.target.checked)" />
        <span v-else-if="column.key === 'used_at'">{{ (record as ChannelKey).used_at ? formatDateTime((record as ChannelKey).used_at || undefined) : '—' }}</span>
        <code v-else-if="column.key === 'key'">{{ (record as ChannelKey).key || '不可回读' }}</code>
        <span v-else-if="column.key === 'batch'" :title="(record as ChannelKey).batch_id || undefined">{{ (record as ChannelKey).batch_id?.slice(0, 8) || '旧密钥' }}</span>
        <span v-else-if="column.key === 'customer'">{{ customerNames.get((record as ChannelKey).tenant_id || '') || '—' }}</span>
        <Tag v-else-if="column.key === 'status'" :color="(record as ChannelKey).status === 'activated' ? 'green' : (record as ChannelKey).status === 'assigned' ? 'blue' : undefined">{{ { unassigned: '可分配', assigned: '已分配', activated: '已激活' }[(record as ChannelKey).status] }}</Tag>
      </template>
    </RawTable>

    <Drawer :open="customerOpen" :keyboard="true" title="开通客户租户" width="min(480px, 100vw)" @close="customerOpen = false">
      <Form :model="customerForm" layout="vertical">
        <Form.Item label="客户编码"><Input v-model:value="customerForm.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
        <Form.Item label="企业名称" required><Input v-model:value="customerForm.name" :maxlength="100" /></Form.Item>
      </Form>
      <template #footer><Button class="mr-2" @click="customerOpen = false">取消</Button><Button :loading="saving" type="primary" @click="saveCustomer">创建</Button></template>
    </Drawer>
    <Drawer :open="assignOpen" :keyboard="true" title="分配授权密钥" width="min(480px, 100vw)" @close="assignOpen = false">
      <p class="mb-4">将 {{ selectedIds.length }} 个密钥分配给：</p>
      <Select v-model:value="selectedTenant" :options="customerOptions" class="w-full" placeholder="选择客户企业" />
      <template #footer><Button class="mr-2" @click="assignOpen = false">取消</Button><Button :loading="saving" type="primary" @click="saveAssign">确认分配</Button></template>
    </Drawer>
    </template>
  </Page>
</template>
