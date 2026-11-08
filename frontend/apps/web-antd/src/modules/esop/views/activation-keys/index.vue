<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { ActivationKey, IssuedActivationKey } from '../../api/operations';
import type { Channel, HardwareModel } from '../../api/ota';
import { activationKeyColumns } from './activation-key-view';

import { computed, onMounted, ref } from 'vue';
import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';
import { Button, Input, message, Modal, Select, Tag } from 'ant-design-vue';
import { getCurrentUserApi } from '#/api/core/auth';
import { listTenantsApi } from '#/api/core/tenants';
import { assignChannelKeys, getChannelWorkspace, listChannelCustomers } from '../../api/channel';
import { exportActivationKeys, issueActivationKey, listActivationKeys, unbindActivationKey } from '../../api/operations';
import { listChannels, listHardwareModels } from '../../api/ota';

const rows = ref<ActivationKey[]>([]);
const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const isAdmin = ref(false);
const isChannel = ref(false);
const issued = ref<IssuedActivationKey>();
const issueOpen = ref(false);
const selectedChannel = ref<string>();
const selectedModel = ref<string>();
const selectedTenant = ref<string>();
const filterTenant = ref<string>();
const filterChannel = ref<string>();
const used = ref<string>();
const channels = ref<Channel[]>([]);
const models = ref<HardwareModel[]>([]);
const tenants = ref<{ label: string; value: string }[]>([]);
const assigning = ref<ActivationKey>();
const unbinding = ref<ActivationKey>();
const reason = ref('');
const channelOptions = computed(() => channels.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const modelOptions = computed(() => models.value.filter((item) => item.channel_id === selectedChannel.value).map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const columns = computed(() => activationKeyColumns(isAdmin.value, isChannel.value));
const filters = () => ({ is_used: used.value === undefined ? undefined : used.value === 'used', tenant_id: filterTenant.value, channel_id: filterChannel.value });

async function refresh() {
  loading.value = true;
  try { rows.value = (await listActivationKeys(filters())).items; }
  finally { loading.value = false; }
}
async function searchTenants(keyword = '') {
  if (!isAdmin.value) return;
  const result = await listTenantsApi({ keyword, page: 1, page_size: 100 });
  tenants.value = result.items.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id }));
}
async function initialize() {
  isAdmin.value = !!(await getCurrentUserApi()).is_superuser;
  if (isAdmin.value) {
    const [channelResult, modelResult] = await Promise.all([listChannels(), listHardwareModels(), searchTenants()]);
    channels.value = channelResult.items;
    models.value = modelResult.items;
  } else {
    // Channel access is optional; tenant users still load their own inventory.
    try {
      await getChannelWorkspace(true);
      isChannel.value = true;
      tenants.value = (await listChannelCustomers()).items.map((item) => ({ label: `${item.tenant_name} (${item.tenant_code})`, value: item.tenant_id }));
    } catch { isChannel.value = false; }
  }
  await refresh();
}
function openIssue() {
  selectedChannel.value = undefined;
  selectedModel.value = undefined;
  selectedTenant.value = undefined;
  issueOpen.value = true;
}
async function issue() {
  if (!selectedTenant.value && !selectedChannel.value) return message.warning('请选择租户或渠道');
  saving.value = true;
  try {
    issued.value = await issueActivationKey({ tenant_id: selectedTenant.value, channel_id: selectedChannel.value, hardware_model_id: selectedModel.value });
    issueOpen.value = false;
    await refresh();
  } finally { saving.value = false; }
}
async function exportKeys(unusedOnly = false) {
  exporting.value = true;
  try {
    const blob = await exportActivationKeys(unusedOnly ? { ...filters(), is_used: false } : filters());
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = unusedOnly ? '未使用激活密钥.csv' : '激活密钥.csv';
    link.click();
    URL.revokeObjectURL(url);
  } finally { exporting.value = false; }
}
async function assign() {
  if (!selectedTenant.value || !assigning.value) return message.warning('请选择租户');
  saving.value = true;
  try {
    await assignChannelKeys({ tenant_id: selectedTenant.value, key_ids: [assigning.value.id] });
    assigning.value = undefined;
    await refresh();
  } finally { saving.value = false; }
}
async function unbind() {
  if (!unbinding.value || !reason.value.trim()) return message.warning('请填写解绑原因');
  saving.value = true;
  try {
    await unbindActivationKey(unbinding.value.id, reason.value.trim());
    unbinding.value = undefined;
    await refresh();
    message.success('已撤销原设备授权，密钥保留原租户归属');
  } finally { saving.value = false; }
}
onMounted(() => void initialize());
</script>

<template>
  <Page title="激活密钥">
    <div class="mb-4 flex flex-wrap gap-2">
      <Select v-model:value="used" :options="[{ label: '未使用', value: 'unused' }, { label: '已使用', value: 'used' }]" allow-clear class="w-36" placeholder="全部状态" @change="refresh" />
      <Select v-if="isAdmin || isChannel" v-model:value="filterTenant" :options="tenants" show-search option-filter-prop="label" :filter-option="!isAdmin ? undefined : false" allow-clear class="w-64" placeholder="搜索租户名称" @search="searchTenants" @change="refresh" />
      <Select v-if="isAdmin" v-model:value="filterChannel" :options="channelOptions" allow-clear class="w-52" placeholder="全部渠道" @change="refresh" />
      <Button :loading="loading" @click="refresh">刷新</Button>
      <Button :loading="exporting" @click="exportKeys(true)">导出未使用密钥</Button>
      <Button :loading="exporting" @click="exportKeys()">导出筛选结果</Button>
      <Button v-if="isAdmin" v-access:code="'esop:device:issue'" type="primary" @click="openIssue">生成密钥</Button>
    </div>
    <p class="mb-3 text-sm text-gray-500">密钥分发后永久归属该租户；解绑设备不会改变租户归属。历史密钥无法解密时显示“不可回读”。</p>
    <Table date-field="created_at" :columns="columns" :data-source="rows" :loading="loading" :pagination="{ pageSize: 20 }" :scroll="{ x: isAdmin ? 1200 : isChannel ? 1130 : 820 }" row-key="id">
      <template #bodyCell="{ column, record }">
        <code v-if="column.key === 'key'">{{ record.key || '不可回读' }}</code>
        <span v-else-if="column.key === 'tenant'">{{ tenants.find(item => item.value === record.tenant_id)?.label || record.tenant_id || '待分发' }}</span>
        <span v-else-if="column.key === 'channel'">{{ channels.find(item => item.id === record.channel_id)?.name || record.channel_id || '—' }}</span>
        <Tag v-else-if="column.key === 'status'" :color="record.is_used ? 'green' : undefined">{{ record.is_used ? '已使用' : '未使用' }}</Tag>
        <span v-else-if="column.key === 'used_at' || column.key === 'created_at'">{{ record[column.key] ? formatDateTime(record[column.key]) : '—' }}</span>
        <template v-else-if="column.key === 'action'">
          <Button v-if="isAdmin && record.is_used" danger size="small" @click="unbinding = record as ActivationKey; reason = ''">解绑设备</Button>
          <Button v-if="isChannel && !record.tenant_id" size="small" @click="assigning = record as ActivationKey; selectedTenant = undefined">绑定租户</Button>
        </template>
      </template>
    </Table>
    <Modal :open="issueOpen" :keyboard="true" title="生成激活密钥" :confirm-loading="saving" ok-text="确认生成" @ok="issue" @cancel="issueOpen = false">
      <p class="mb-4">选择租户可直接发放；只选择渠道则进入渠道待分发库存。</p>
      <Select v-model:value="selectedTenant" :options="tenants" show-search :filter-option="false" allow-clear class="mb-3 w-full" placeholder="搜索接收租户（可选）" @search="searchTenants" />
      <Select v-model:value="selectedChannel" :options="channelOptions" allow-clear class="mb-3 w-full" placeholder="渠道（可选）" @change="selectedModel = undefined" />
      <Select v-model:value="selectedModel" :disabled="!selectedChannel" :options="modelOptions" allow-clear class="w-full" placeholder="硬件型号（可选）" />
    </Modal>
    <Modal :open="!!issued" :keyboard="true" title="激活密钥已生成" :footer="null" @cancel="issued = undefined">
      <p class="mb-3">密钥可在列表中再次查看和导出。</p><code class="text-2xl">{{ issued?.key }}</code>
    </Modal>
    <Modal :open="!!assigning" :keyboard="true" title="绑定租户" :confirm-loading="saving" @ok="assign" @cancel="assigning = undefined">
      <p class="mb-4">绑定后永久归属该租户，不可跨租户转移。</p>
      <Select v-model:value="selectedTenant" :options="tenants" class="w-full" placeholder="选择下属租户" />
    </Modal>
    <Modal :open="!!unbinding" :keyboard="true" title="解绑设备授权" :confirm-loading="saving" ok-text="确认解绑" @ok="unbind" @cancel="unbinding = undefined">
      <p class="mb-4">设备 {{ unbinding?.device_code }} 的授权将被撤销。密钥保留原租户归属，只能用于同一租户。</p>
      <Input.TextArea v-model:value="reason" :maxlength="500" placeholder="解绑原因（必填）" />
    </Modal>
  </Page>
</template>
