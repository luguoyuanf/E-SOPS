<script lang="ts" setup>
import type { Alarm, AlarmType } from '../../api/operations';

import { computed, onMounted, reactive, ref, watch } from 'vue';

import { useAccess } from '@vben/access';
import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';

import { Alert, Button, Drawer, Input, message, Modal, Select, Switch, Table, Tabs, Tag } from 'ant-design-vue';

import {
  createPlatformAlarmType,
  createTenantAlarmType,
  listAlarmTypes,
  listAlarms,
  resolveAlarm,
  renamePlatformAlarmType,
  renameTenantAlarmType,
  saveAlarmTypePreferences,
} from '../../api/operations';

const { hasAccessByCodes } = useAccess();
const canManageTypes = computed(() => hasAccessByCodes(['esop:alarm:type:manage']));
const canResolve = computed(() => hasAccessByCodes(['esop:alarm:resolve']));
const filterType = ref<string>();
const filterStatus = ref<string>();
const resolvingId = ref<string>();
const tab = ref('records');
const records = ref<Alarm[]>([]);
const types = ref<AlarmType[]>([]);
const canManageGlobal = ref(false);
const recordsLoading = ref(false);
const typesLoading = ref(false);
const typesLoaded = ref(false);
const savingPreferences = ref(false);
const editorOpen = ref(false);
const editorSaving = ref(false);
const editTarget = ref<AlarmType>();
const editScope = ref<'platform' | 'tenant'>('tenant');
const form = reactive({ name: '' });
let editorTrigger: HTMLElement | null = null;
let savedPreferences = '';

const recordColumns = [
  { title: '报警类型', key: 'type', width: 180 },
  { title: '报警人', dataIndex: 'staff_name', key: 'staff_name', width: 140 },
  { title: '终端', dataIndex: 'terminal_name', key: 'terminal_name', width: 240 },
  { title: '工位', dataIndex: 'station_name', key: 'station_name', width: 180 },
  { title: '旧版灯色', key: 'legacyLevel', width: 110 },
  { title: '说明', key: 'legacyReason', width: 220 },
  { title: '状态', key: 'status', width: 100 },
  { title: '解除时间', key: 'resolved_at', width: 190 },
  { title: '报警时间', key: 'created_at', width: 190 },
  { title: '操作', key: 'resolve', width: 110 },
];
const typeColumns = [
  { title: '排序', key: 'sort', width: 145 },
  { title: '报警类型', dataIndex: 'name', key: 'name', width: 230 },
  { title: '来源', key: 'source', width: 135 },
  { title: '本租户状态', key: 'enabled', width: 145 },
  { title: '操作', key: 'action', width: 105 },
];
const sourceLabels: Record<AlarmType['source'], string> = {
  builtin: '内置',
  platform: '平台新增',
  tenant: '本租户新增',
};
const typePreferences = computed(() => types.value.map(({ code, enabled, sort }) => ({ code, enabled, sort })));
const preferencesChanged = computed(() => JSON.stringify(typePreferences.value) !== savedPreferences);

const recordTypeOptions = computed(() => [...new Map(records.value.map(row => [row.type_code || '', {value: row.type_code || '', label: row.type_name || '历史未分类'}])).values()]);
const filteredRecords = computed(() => records.value.filter(row =>
  (filterType.value === undefined || (row.type_code || '') === filterType.value) &&
  (!filterStatus.value || (row.resolved_at ? 'resolved' : 'unresolved') === filterStatus.value)));
function confirmResolve(row: Alarm, event: Event) {
  const trigger = event.currentTarget as HTMLElement;
  Modal.confirm({title: '解除报警', content: `确认解除“${row.type_name || '报警'}”？`, keyboard: true,
    okText: '确认解除', cancelText: '取消', afterClose: () => trigger?.focus(),
    async onOk() {
      resolvingId.value = row.id;
      try { await resolveAlarm(row.id); await refreshRecords(); message.success('报警已解除'); }
      finally { resolvingId.value = undefined; }
    },
  });
}

async function refreshRecords() {
  recordsLoading.value = true;
  try {
    records.value = (await listAlarms()).items;
  } finally {
    recordsLoading.value = false;
  }
}

async function refreshTypes() {
  typesLoading.value = true;
  try {
    const result = await listAlarmTypes();
    types.value = [...result.items].sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name));
    canManageGlobal.value = result.can_manage_global;
    typesLoaded.value = true;
    savedPreferences = JSON.stringify(typePreferences.value);
  } finally {
    typesLoading.value = false;
  }
}

function moveType(index: number, direction: -1 | 1) {
  const destination = index + direction;
  if (destination < 0 || destination >= types.value.length) return;
  const first = types.value[index]!;
  const second = types.value[destination]!;
  types.value[index] = second;
  types.value[destination] = first;
  types.value.forEach((row, position) => { row.sort = position + 1; });
}

function openEditor(scope: 'platform' | 'tenant', row?: AlarmType, event?: Event) {
  if (preferencesChanged.value) { message.warning('请先保存启用与排序'); return; }
  editorTrigger = event?.currentTarget as HTMLElement | null;
  editScope.value = scope;
  editTarget.value = row;
  form.name = row?.name ?? '';
  editorOpen.value = true;
}

function closeEditor() { editorOpen.value = false; }
function restoreEditorFocus(open: boolean) { if (!open) editorTrigger?.focus(); }

async function saveEditor() {
  const name = form.name.trim();
  if (!name) { message.warning('请填写报警类型名称'); return; }
  if (editorSaving.value) return;
  editorSaving.value = true;
  try {
    if (editScope.value === 'platform') {
      if (editTarget.value) await renamePlatformAlarmType(editTarget.value.code, name);
      else await createPlatformAlarmType(name);
    } else if (editTarget.value) {
      await renameTenantAlarmType(editTarget.value.code, name);
    } else {
      await createTenantAlarmType(name);
    }
    editorOpen.value = false;
    await refreshTypes();
    message.success('报警类型已保存');
  } finally {
    editorSaving.value = false;
  }
}

async function savePreferences() {
  if (!preferencesChanged.value || savingPreferences.value) return;
  savingPreferences.value = true;
  try {
    await saveAlarmTypePreferences(typePreferences.value);
    await refreshTypes();
    message.success('本租户的启用状态与排序已保存');
  } finally {
    savingPreferences.value = false;
  }
}

watch(tab, (value) => { if (value === 'types' && !typesLoaded.value) void refreshTypes(); });
onMounted(() => void refreshRecords());
</script>

<template>
  <Page title="报警记录">
    <Tabs v-model:active-key="tab">
      <Tabs.TabPane key="records" tab="报警记录" />
      <Tabs.TabPane key="types" tab="报警类型" />
    </Tabs>

    <template v-if="tab === 'records'">
      <div class="mb-3 flex flex-wrap items-center gap-3">
        <Select v-model:value="filterType" allow-clear aria-label="报警类型筛选" placeholder="全部类型" :options="recordTypeOptions" style="width: 200px" />
        <Select v-model:value="filterStatus" allow-clear aria-label="报警状态筛选" placeholder="全部状态" :options="[{ value: 'unresolved', label: '未解除' }, { value: 'resolved', label: '已解除' }]" style="width: 160px" />
        <Button :loading="recordsLoading" @click="refreshRecords">刷新记录</Button>
      </div>
      <Table :columns="recordColumns" :data-source="filteredRecords" :loading="recordsLoading" :pagination="{ pageSize: 20, showSizeChanger: true }" :scroll="{ x: 1660 }" row-key="id">
        <template #bodyCell="{ column, record }">
          <span v-if="column.key === 'created_at'">{{ formatDateTime((record as Alarm).created_at) }}</span>
          <span v-else-if="column.key === 'staff_name'">{{ (record as Alarm).staff_name || '—' }}</span>
          <span v-else-if="column.key === 'terminal_name'">{{ (record as Alarm).terminal_name || '—' }}</span>
          <span v-else-if="column.key === 'station_name'">{{ (record as Alarm).station_name || '—' }}</span>
          <Tag v-else-if="column.key === 'type'" :color="(record as Alarm).type_code ? 'blue' : 'default'">{{ (record as Alarm).type_name || '历史未分类' }}</Tag>
          <Tag v-else-if="column.key === 'status'" :color="(record as Alarm).resolved_at ? 'green' : 'red'">{{ (record as Alarm).resolved_at ? '已解除' : '未解除' }}</Tag>
          <span v-else-if="column.key === 'resolved_at'">{{ (record as Alarm).resolved_at ? formatDateTime((record as Alarm).resolved_at!) : '—' }}</span>
          <template v-else-if="column.key === 'resolve'">
            <Button v-if="canResolve && !(record as Alarm).resolved_at" type="link" :loading="resolvingId === (record as Alarm).id" :disabled="!!resolvingId" @click="confirmResolve(record as Alarm, $event)">解除报警</Button><span v-else>—</span>
          </template>
          <span v-else-if="column.key === 'legacyLevel'">{{ (record as Alarm).type_code ? '—' : ((record as Alarm).level || '—') }}</span>
          <span v-else-if="column.key === 'legacyReason'">{{ (record as Alarm).reason || '—' }}</span>
        </template>
      </Table>
    </template>

    <template v-else>
      <Alert class="mb-4" show-icon type="info" message="内置类型由平台统一维护。本租户可以暂停使用并调整显示顺序；停用后不影响已有报警记录。" />
      <div class="mb-4 flex flex-wrap justify-end gap-2">
        <Button :loading="typesLoading" :disabled="preferencesChanged" @click="refreshTypes">刷新类型</Button>
        <Button v-if="canManageTypes" :disabled="preferencesChanged" @click="openEditor('tenant', undefined, $event)">新增本租户类型</Button>
        <Button v-if="canManageGlobal" type="primary" :disabled="preferencesChanged" @click="openEditor('platform', undefined, $event)">新增平台类型</Button>
        <Button v-if="canManageTypes" type="primary" :disabled="!preferencesChanged || typesLoading" :loading="savingPreferences" @click="savePreferences">保存启用与排序</Button>
      </div>
      <p v-if="preferencesChanged" class="mb-3 text-sm text-amber-700">启用状态或排序尚未保存，请先保存再刷新或新增类型。</p>
      <Table :columns="typeColumns" :data-source="types" :loading="typesLoading" :pagination="false" :scroll="{ x: 780 }" row-key="code">
        <template #bodyCell="{ column, record, index }">
          <div v-if="column.key === 'sort'" class="flex items-center gap-1">
            <Button v-if="canManageTypes" size="small" :disabled="index === 0" aria-label="上移" @click="moveType(index, -1)">↑</Button>
            <Button v-if="canManageTypes" size="small" :disabled="index === types.length - 1" aria-label="下移" @click="moveType(index, 1)">↓</Button>
            <span v-if="!canManageTypes">{{ index + 1 }}</span>
          </div>
          <Tag v-else-if="column.key === 'source'" :color="(record as AlarmType).source === 'tenant' ? 'purple' : 'blue'">{{ sourceLabels[(record as AlarmType).source] }}</Tag>
          <div v-else-if="column.key === 'enabled'" class="flex items-center gap-2">
            <Switch v-if="canManageTypes" v-model:checked="(record as AlarmType).enabled" :aria-label="`${(record as AlarmType).name}启用状态`" />
            <Tag :color="(record as AlarmType).enabled ? 'green' : 'default'">{{ (record as AlarmType).enabled ? '启用' : '停用' }}</Tag>
          </div>
          <template v-else-if="column.key === 'action'">
            <Button v-if="(record as AlarmType).source === 'tenant' && canManageTypes" type="link" @click="openEditor('tenant', record as AlarmType, $event)">改名</Button>
            <Button v-else-if="(record as AlarmType).source !== 'tenant' && canManageGlobal" type="link" @click="openEditor('platform', record as AlarmType, $event)">改名</Button>
            <span v-else>—</span>
          </template>
        </template>
      </Table>
    </template>

    <Drawer :open="editorOpen" :keyboard="true" :title="editTarget ? '修改报警类型' : (editScope === 'platform' ? '新增平台类型' : '新增本租户类型')" width="min(480px, 100vw)" @close="closeEditor" @after-open-change="restoreEditorFocus">
      <label class="mb-2 block" for="alarm-type-name">类型名称</label>
      <Input id="alarm-type-name" v-model:value="form.name" :maxlength="40" placeholder="请输入报警类型名称" @press-enter="saveEditor" />
      <p class="mt-3 text-sm text-muted-foreground">{{ editScope === 'platform' ? '保存后默认对所有租户可用；租户可自行停用和排序。' : '仅当前租户可见。' }}</p>
      <template #footer><Button class="mr-2" @click="closeEditor">取消</Button><Button type="primary" :loading="editorSaving" @click="saveEditor">保存</Button></template>
    </Drawer>
  </Page>
</template>
