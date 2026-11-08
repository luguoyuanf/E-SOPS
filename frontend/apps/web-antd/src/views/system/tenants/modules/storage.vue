<script lang="ts" setup>
import type { FormInstance } from 'ant-design-vue';

import type { TenantRecord } from '#/api';
import type { StorageGrant, StorageUsage } from '#/api/core/tenant-storage';

import { computed, reactive, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';

import { Alert, Button, Descriptions, DescriptionsItem, Form, Input, InputNumber, message, Table, Tag } from 'ant-design-vue';

import { getStorageUsage, grantStorage, listStorageGrants } from '#/api/core/tenant-storage';
import { $t } from '#/locales';

const emits = defineEmits<{ success: [] }>();
const mib = 1024 * 1024;
const tenant = ref<TenantRecord>();
const usage = ref<StorageUsage>();
const grants = ref<StorageGrant[]>([]);
const loading = ref(false);
const loadFailed = ref(false);
const saving = ref(false);
const formRef = ref<FormInstance>();
const form = reactive({ capacity_mb: 1024, starts_on: '', note: '' });
const size = (bytes: number) => `${(bytes / mib).toFixed(2)} MiB`;
const remaining = computed(() => Math.max(0, (usage.value?.limit_bytes ?? 0) - (usage.value?.used_bytes ?? 0)));
const columns = computed(() => [
  { title: $t('system.tenant.storageSource'), key: 'source', width: 120 },
  { title: $t('system.tenant.storageCapacity'), key: 'capacity', width: 130, align: 'right' as const },
  { title: $t('system.tenant.storageStarts'), dataIndex: 'starts_at', key: 'starts_at', width: 180 },
  { title: $t('system.tenant.storageExpires'), dataIndex: 'expires_at', key: 'expires_at', width: 180 },
  { title: $t('system.tenant.lifecycleStatus'), key: 'status', width: 100 },
  { title: $t('system.tenant.storageNote'), dataIndex: 'note', key: 'note', width: 160 },
]);

function status(grant: StorageGrant) {
  if (grant.expires_at && new Date(grant.expires_at).getTime() <= Date.now()) return { label: $t('system.tenant.storageExpired'), color: 'default' };
  if (new Date(grant.starts_at).getTime() > Date.now()) return { label: $t('system.tenant.storagePending'), color: 'processing' };
  return { label: $t('system.tenant.storageActive'), color: 'success' };
}

async function load() {
  if (!tenant.value) return;
  loading.value = true;
  loadFailed.value = false;
  try {
    const [current, history] = await Promise.all([
      getStorageUsage(tenant.value.id), listStorageGrants(tenant.value.id),
    ]);
    usage.value = current;
    grants.value = history.items;
  } catch {
    loadFailed.value = true;
  } finally {
    loading.value = false;
  }
}

const [Drawer, drawerApi] = useVbenDrawer({
  async onConfirm() {
    if (!tenant.value || !usage.value || loadFailed.value || loading.value || saving.value) return;
    if (!formRef.value) return;
    try {
      await formRef.value.validate();
    } catch {
      return;
    }
    if (saving.value) return;
    const start = new Date(`${form.starts_on}T00:00:00`);
    if (Number.isNaN(start.getTime())) return;
    const end = new Date(start);
    end.setFullYear(end.getFullYear() + 1);
    saving.value = true;
    drawerApi.lock();
    try {
      await grantStorage({
        tenant_id: tenant.value.id,
        capacity_bytes: form.capacity_mb * mib,
        starts_at: start.toISOString(),
        expires_at: end.toISOString(),
        note: form.note.trim() || undefined,
      });
      message.success($t('system.tenant.storageGranted'));
      emits('success');
      await load();
    } finally {
      saving.value = false;
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    tenant.value = drawerApi.getData<TenantRecord>();
    usage.value = undefined;
    grants.value = [];
    const now = new Date();
    form.capacity_mb = 1024;
    form.starts_on = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    form.note = '';
    formRef.value?.clearValidate();
    await load();
  },
});
</script>

<template>
  <Drawer :title="`${$t('system.tenant.storageExpansion')} - ${tenant?.name ?? ''}`" :confirm-text="$t('system.tenant.storageGrant')" :confirm-disabled="loading || loadFailed || !usage" class="w-[min(820px,100vw)]">
    <Alert v-if="loadFailed" :message="$t('system.tenant.storageLoadFailed')" type="error" class="mb-4">
      <template #action><Button size="small" @click="load">{{ $t('system.tenant.storageRetry') }}</Button></template>
    </Alert>
    <Descriptions v-if="usage" :column="1" bordered size="small" class="mb-5">
      <DescriptionsItem :label="$t('system.tenant.storageTotal')">{{ size(usage.limit_bytes) }}</DescriptionsItem>
      <DescriptionsItem :label="$t('system.tenant.storageUsage')">{{ size(usage.used_bytes) }}</DescriptionsItem>
      <DescriptionsItem :label="$t('system.tenant.storageRemaining')">{{ size(remaining) }}</DescriptionsItem>
      <DescriptionsItem :label="$t('system.tenant.storageBase')">{{ size(usage.base_bytes) }}</DescriptionsItem>
      <DescriptionsItem :label="$t('system.tenant.storageExpansionActive')">{{ size(usage.active_grant_bytes) }}</DescriptionsItem>
    </Descriptions>
    <h3 class="mb-3 text-sm font-semibold">{{ $t('system.tenant.storageGrant') }}</h3>
    <Form ref="formRef" :model="form" layout="vertical" :disabled="loading || saving || loadFailed || !usage">
      <Form.Item :label="$t('system.tenant.storageCapacityMb')" name="capacity_mb" :rules="[{ required: true, type: 'integer', min: 1, max: Math.floor(Number.MAX_SAFE_INTEGER / mib), message: $t('system.tenant.storageCapacityRequired') }]">
        <InputNumber v-model:value="form.capacity_mb" :min="1" :precision="0" class="w-full" />
      </Form.Item>
      <Form.Item :label="$t('system.tenant.storageStarts')" name="starts_on" :rules="[{ required: true, message: $t('system.tenant.storageDateRequired') }]">
        <Input v-model:value="form.starts_on" type="date" />
      </Form.Item>
      <p class="mb-4 text-sm text-gray-500">{{ $t('system.tenant.storageTerm') }}</p>
      <Form.Item :label="$t('system.tenant.storageNote')"><Input v-model:value="form.note" :maxlength="500" /></Form.Item>
    </Form>
    <h3 class="mb-3 text-sm font-semibold">{{ $t('system.tenant.storageHistory') }}</h3>
    <p class="mb-3 text-sm text-gray-500">{{ $t('system.tenant.storageLedgerFormula') }}</p>
    <Table :columns="columns" :data-source="grants" :loading="loading" :pagination="false" :scroll="{ x: 870 }" row-key="id" size="small">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'source'">{{ record.source === 'opening_gift' ? $t('system.tenant.storageOpeningGift') : $t('system.tenant.storagePackage') }}</span>
        <span v-else-if="column.key === 'capacity'">{{ size(record.capacity_bytes) }}</span>
        <span v-else-if="column.key === 'starts_at' || column.key === 'expires_at'">{{ record[column.key] ? formatDateTime(record[column.key]) : $t('system.tenant.storagePermanent') }}</span>
        <Tag v-else-if="column.key === 'status'" :color="status(record as StorageGrant).color">{{ status(record as StorageGrant).label }}</Tag>
      </template>
    </Table>
  </Drawer>
</template>
