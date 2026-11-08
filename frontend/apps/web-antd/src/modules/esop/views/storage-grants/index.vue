<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { StorageGrant, StorageUsage } from '../../api/commercial';

import type { TenantRecord } from '#/api/core/tenants';

import { computed, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';

import { Button, Drawer, Form, Input, InputNumber, message, Select, Tag } from 'ant-design-vue';

import { getCurrentUserApi } from '#/api/core/auth';
import { listTenantsApi } from '#/api/core/tenants';

import { getStorageUsage, grantStorage, listStorageGrants } from '../../api/commercial';

const mib = 1024 * 1024;
const tenantId = ref<string>();
const tenants = ref<TenantRecord[]>([]);
const grants = ref<StorageGrant[]>([]);
const usage = ref<StorageUsage>();
const loading = ref(false);
const saving = ref(false);
const open = ref(false);
const isPlatformAdmin = ref(false);
const form = reactive({ capacity_mb: 1024, starts_on: '', note: '' });
const tenantOptions = computed(() => tenants.value.map((tenant) => ({
  label: `${tenant.name} (${tenant.code})`,
  value: tenant.id,
})));
const columns = [
  { title: '来源', key: 'source', width: 120 },
  { title: '容量', key: 'capacity', width: 140 },
  { title: '生效', dataIndex: 'starts_at', key: 'starts_at', width: 220 },
  { title: '到期', dataIndex: 'expires_at', key: 'expires_at', width: 220 },
  { title: '状态', key: 'status', width: 110 },
  { title: '备注', dataIndex: 'note', key: 'note' },
];

function size(bytes: number) {
  return bytes >= 1024 * mib
    ? `${(bytes / (1024 * mib)).toFixed(2)} GB`
    : `${(bytes / mib).toFixed(0)} MB`;
}

function localDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function grantStatus(grant: StorageGrant) {
  const now = Date.now();
  if (new Date(grant.starts_at).getTime() > now) return '未生效';
  if (grant.expires_at && new Date(grant.expires_at).getTime() <= now) return '已到期';
  return '生效中';
}

async function searchTenants(keyword = '') {
  tenants.value = (await listTenantsApi({ keyword, page: 1, page_size: 50 })).items;
}

async function selectTenant() {
  if (!tenantId.value) {
    grants.value = [];
    usage.value = undefined;
    return;
  }
  loading.value = true;
  try {
    const [grantResult, usageResult] = await Promise.all([
      listStorageGrants(tenantId.value),
      getStorageUsage(tenantId.value),
    ]);
    grants.value = grantResult.items;
    usage.value = usageResult;
  } finally {
    loading.value = false;
  }
}

function openGrant() {
  const start = new Date();
  form.capacity_mb = 1024;
  form.starts_on = localDate(start);
  form.note = '';
  open.value = true;
}

async function saveGrant() {
  if (!tenantId.value || !form.starts_on || form.capacity_mb < 1) {
    message.warning('请选择企业、容量和有效期');
    return;
  }
  const start = new Date(`${form.starts_on}T00:00:00`);
  const end = new Date(start);
  end.setFullYear(end.getFullYear() + 1);
  saving.value = true;
  try {
    await grantStorage({
      tenant_id: tenantId.value,
      capacity_bytes: Math.round(form.capacity_mb * mib),
      starts_at: start.toISOString(),
      expires_at: end.toISOString(),
      note: form.note.trim() || undefined,
    });
    open.value = false;
    await selectTenant();
    message.success('存储包已发放');
  } finally {
    saving.value = false;
  }
}

void Promise.all([searchTenants(), getCurrentUserApi().then((user) => { isPlatformAdmin.value = user.is_superuser === true; })]);
</script>

<template>
  <Page title="存储包发放">
    <div class="mb-5 flex flex-wrap items-center gap-3">
      <Select v-model:value="tenantId" show-search :filter-option="false" :options="tenantOptions" class="min-w-72" placeholder="搜索企业名称或编码" @search="searchTenants" @change="selectTenant" />
      <Button v-if="isPlatformAdmin" :disabled="!tenantId" type="primary" @click="openGrant">发放存储包</Button>
    </div>
    <div v-if="usage" class="mb-6 rounded bg-[var(--vben-bg-color)] p-5">
      <h2 class="mb-3 text-base font-semibold">{{ tenants.find((item) => item.id === tenantId)?.name || '当前企业' }} · 存储容量</h2>
      <p>已使用 {{ size(usage.used_bytes) }} / 可用 {{ size(usage.limit_bytes) }}</p>
      <p class="mt-1 text-sm">基础容量 {{ size(usage.base_bytes) }}，当前生效的扩容 {{ size(usage.active_grant_bytes) }}</p>
    </div>
    <Table date-field="created_at" :columns="columns" :data-source="grants" :loading="loading" :pagination="false" row-key="id">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'source'">{{ record.source === 'opening_gift' ? '开户赠送' : '扩容包' }}</span>
        <span v-else-if="column.key === 'capacity'">{{ size((record as StorageGrant).capacity_bytes) }}</span>
        <span v-else-if="column.key === 'starts_at' || column.key === 'expires_at'">{{ (record as StorageGrant)[column.key] ? formatDateTime((record as StorageGrant)[column.key]!) : '永久有效' }}</span>
        <Tag v-else-if="column.key === 'status'" :color="grantStatus(record as StorageGrant) === '生效中' ? 'green' : undefined">{{ grantStatus(record as StorageGrant) }}</Tag>
      </template>
    </Table>

    <Drawer :open="open" :keyboard="true" title="发放存储包" width="min(520px, 100vw)" @close="open = false">
      <Form :model="form" layout="vertical">
        <Form.Item label="容量（MB）" required><InputNumber v-model:value="form.capacity_mb" :min="1" :precision="0" class="w-full" /></Form.Item>
        <Form.Item label="生效日期" required><Input v-model:value="form.starts_on" type="date" /></Form.Item>
        <p class="mb-4 text-sm text-gray-500">有效期：自生效日期起一年。</p>
        <Form.Item label="备注"><Input v-model:value="form.note" :maxlength="200" /></Form.Item>
      </Form>
      <template #footer>
        <Button class="mr-2" @click="open = false">取消</Button>
        <Button :loading="saving" type="primary" @click="saveGrant">确认发放</Button>
      </template>
    </Drawer>
  </Page>
</template>
