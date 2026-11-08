<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { Terminal } from '../../api/operations';
import type { ProductionLine } from '../../api/production';

import { computed, onMounted, onUnmounted, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';

import { Button, Descriptions, DescriptionsItem, Dropdown, Input, Menu, MenuItem, message, Modal, Select, Tag } from 'ant-design-vue';

import { getWebTerminalAccess, listTerminals, openWebTerminal, updateTerminalName } from '../../api/operations';
import { listLines } from '../../api/production';
import StationDeviceBinding from '../../components/station-device-binding.vue';
import { stationLabel } from '../../utils/line-layout';

const terminals = ref<Terminal[]>([]);
const terminalQuery = ref('');
const selectedLineId = ref<string>();
const selectedStationId = ref<string>();
const lines = ref<ProductionLine[]>([]);
const lineByStation = computed(() => new Map(lines.value.flatMap((line) => line.stations.map((station) => [station.id, line.id] as const))));
const lineOptions = computed(() => lines.value.map((line) => ({ label: line.name, value: line.id })));
const stationOptions = computed(() => lines.value.filter((line) => !selectedLineId.value || line.id === selectedLineId.value)
  .flatMap((line) => line.stations.map((station) => ({ label: `${line.name} · ${stationLabel(station)}`, value: station.id }))));
const filteredTerminals = computed(() => {
  const query = terminalQuery.value.trim().toLocaleLowerCase();
  return terminals.value.filter((terminal) => {
    if (query && !`${terminal.serial_number} ${terminal.device_name || ''}`.toLocaleLowerCase().includes(query)) return false;
    if (selectedLineId.value && lineByStation.value.get(terminal.station_id || '') !== selectedLineId.value) return false;
    return !selectedStationId.value || terminal.station_id === selectedStationId.value;
  });
});
const loading = ref(false);
const canOpenWeb = ref(false);
const opening = ref(false);
async function openWeb(row: Terminal) {
  if (opening.value) return;
  const tab = window.open('about:blank', '_blank');
  if (tab) tab.opener = null;
  opening.value = true;
  try {
    const result = await openWebTerminal(row.id);
    if (tab) tab.location.href = result.path;
    else window.location.assign(result.path);
  } catch { tab?.close(); }
  finally { opening.value = false; }
}
const bindingOpen = ref(false);
const detailTerminalId = ref<string>();
const detailTerminal = computed(() => terminals.value.find((row) => row.id === detailTerminalId.value));
let detailTrigger: HTMLElement | null = null;
function openDetail(row: Terminal, event: Event) {
  detailTrigger = event.currentTarget as HTMLElement;
  detailTerminalId.value = row.id;
}
function restoreDetailFocus() { detailTrigger?.focus(); }
const selectedTerminalId = ref<string>();
const namingTerminal = ref<Terminal>();
const nameDraft = ref('');
const savingName = ref(false);
let moreTrigger: HTMLElement | null = null;
function rememberMore(event: Event) { moreTrigger = event.currentTarget as HTMLElement; }
let bindingTrigger: HTMLElement | null = null;
let nameTrigger: HTMLElement | null = null;
const stationMap = computed(() => new Map(lines.value.flatMap((line) => line.stations.map((station) => [
  station.id,
  `${line.name} · ${stationLabel(station)} · ${station.row} 排 ${station.column} 位`,
] as const))));
const columns = [
  { title: '设备编号', dataIndex: 'serial_number', key: 'serial_number', width: 160 },
  { title: '设备名称', key: 'device_name', width: 180 },
  { title: '绑定工位', key: 'station', width: 240 },
  { title: '应用版本', dataIndex: 'app_version', key: 'app_version', width: 130 },
  { title: '状态', key: 'status', width: 100 },
  { title: '在线状态', key: 'online', width: 110 },
  { title: '最后上线时间', dataIndex: 'last_seen_at', key: 'last_seen_at', width: 190 },
  { title: '操作', key: 'action', width: 350 },
];

async function refresh() {
  loading.value = true;
  try {
    const [terminalResult, lineResult, access] = await Promise.all([listTerminals(), listLines(), getWebTerminalAccess()]);
    canOpenWeb.value = access.allowed;
    terminals.value = terminalResult.items;
    lines.value = lineResult.items;
  } finally {
    loading.value = false;
  }
}

function openBinding(row: Terminal, event: Event) {
  bindingTrigger = row.device_code === 'WEB' && moreTrigger ? moreTrigger : event.currentTarget as HTMLElement;
  selectedTerminalId.value = row.id;
  bindingOpen.value = true;
}
function restoreBindingFocus() { bindingTrigger?.focus(); }
function restoreNameFocus() { nameTrigger?.focus(); }
function openNameEditor(row: Terminal, event: Event) {
  nameTrigger = row.device_code === 'WEB' && moreTrigger ? moreTrigger : event.currentTarget as HTMLElement;
  namingTerminal.value = row;
  nameDraft.value = row.device_name || '';
}
async function saveName() {
  if (!namingTerminal.value) return;
  const name = nameDraft.value.trim();
  if (!name) return message.warning('请输入设备名称');
  savingName.value = true;
  try {
    const updated = await updateTerminalName(namingTerminal.value.id, name);
    terminals.value = terminals.value.map((row) => row.id === updated.id ? updated : row);
    namingTerminal.value = undefined;
    message.success('设备名称已保存');
  } finally { savingName.value = false; }
}

let refreshTimer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  void refresh();
  refreshTimer = setInterval(() => {
    void listTerminals().then((result) => { terminals.value = result.items; }).catch(() => {});
  }, 30_000);
});
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer); });
</script>

<template>
  <Page title="终端管理">
    <Table date-field="created_at" :columns="columns" :data-source="filteredTerminals" :loading="loading" :pagination="false" row-key="id">
      <template #toolbar>
        <Input.Search v-model:value="terminalQuery" allow-clear style="width: 256px; flex: 0 0 256px" placeholder="搜索终端编号或名称" aria-label="终端编号或名称模糊搜索" />
        <Select v-model:value="selectedLineId" allow-clear show-search option-filter-prop="label" :options="lineOptions" class="!w-40 shrink-0" placeholder="全部产线" aria-label="产线筛选" @change="selectedStationId = undefined" />
        <Select v-model:value="selectedStationId" allow-clear show-search option-filter-prop="label" :options="stationOptions" class="!w-48 shrink-0" placeholder="全部工位" aria-label="工位筛选" />
      </template>
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'device_name'">{{ (record as Terminal).device_name || '未命名' }}</span>
        <span v-else-if="column.key === 'station'">{{ stationMap.get((record as Terminal).station_id || '') || '未绑定' }}</span>
        <span v-else-if="column.key === 'last_seen_at'">{{ (record as Terminal).last_seen_at ? formatDateTime((record as Terminal).last_seen_at || undefined) : '—' }}</span>
        <Tag v-else-if="column.key === 'status'" :color="(record as Terminal).is_active ? 'green' : undefined">{{ (record as Terminal).is_active ? '已激活' : '停用' }}</Tag>
        <button v-else-if="column.key === 'online'" type="button" class="cursor-pointer" :aria-label="`查看${(record as Terminal).device_name || (record as Terminal).serial_number}的终端信息`" @click="openDetail(record as Terminal, $event)">
          <Tag :color="(record as Terminal).is_online ? 'success' : 'default'" class="!mr-0">{{ (record as Terminal).is_online ? '在线' : '离线' }}</Tag>
        </button>
        <template v-else-if="column.key === 'action'">
          <div class="flex items-center gap-1 whitespace-nowrap">
            <Button v-if="canOpenWeb && (record as Terminal).device_code === 'WEB'" type="link" :loading="opening" :disabled="!(record as Terminal).is_active" @click="openWeb(record as Terminal)">打开 Web 终端</Button>
            <Dropdown v-if="canOpenWeb && (record as Terminal).device_code === 'WEB'" :trigger="['click']">
              <Button v-access:code="'esop:device:bind'" type="link" @click="rememberMore">更多操作</Button>
              <template #overlay><Menu>
                <MenuItem key="name" @click="openNameEditor(record as Terminal, $event)">编辑名称</MenuItem>
                <MenuItem key="station" :disabled="!(record as Terminal).is_active" @click="openBinding(record as Terminal, $event)">绑定工位</MenuItem>
              </Menu></template>
            </Dropdown>
            <template v-else>
              <Button v-access:code="'esop:device:bind'" type="link" @click="openNameEditor(record as Terminal, $event)">编辑名称</Button>
              <Button v-access:code="'esop:device:bind'" type="link" :disabled="!(record as Terminal).is_active" @click="openBinding(record as Terminal, $event)">绑定工位</Button>
            </template>
          </div>
        </template>
      </template>
    </Table>
    <StationDeviceBinding v-model:open="bindingOpen" :initial-terminal-id="selectedTerminalId" @bound="refresh" @closed="restoreBindingFocus" />
    <Modal :open="!!detailTerminalId" title="终端基本信息" :footer="null" :keyboard="true" @cancel="detailTerminalId = undefined" @after-close="restoreDetailFocus">
      <Descriptions v-if="detailTerminal" bordered size="small" :column="1">
        <DescriptionsItem label="设备编号">{{ detailTerminal.serial_number }}</DescriptionsItem>
        <DescriptionsItem label="设备名称">{{ detailTerminal.device_name || '未命名' }}</DescriptionsItem>
        <DescriptionsItem label="绑定工位">{{ stationMap.get(detailTerminal.station_id || '') || '未绑定' }}</DescriptionsItem>
        <DescriptionsItem label="应用版本">{{ detailTerminal.app_version || '—' }}</DescriptionsItem>
        <DescriptionsItem label="激活状态">{{ detailTerminal.is_active ? '已激活' : '停用' }}</DescriptionsItem>
        <DescriptionsItem label="在线状态"><Tag :color="detailTerminal.is_online ? 'success' : 'default'">{{ detailTerminal.is_online ? '在线' : '离线' }}</Tag></DescriptionsItem>
        <DescriptionsItem label="最近连接 IP">{{ detailTerminal.last_ip || '暂无记录' }}</DescriptionsItem>
        <DescriptionsItem label="最后上线时间">{{ detailTerminal.last_seen_at ? formatDateTime(detailTerminal.last_seen_at) : '—' }}</DescriptionsItem>
      </Descriptions>
    </Modal>
    <Modal :open="!!namingTerminal" title="编辑设备名称" :keyboard="true" :confirm-loading="savingName" ok-text="保存" cancel-text="取消" :ok-button-props="{ disabled: !nameDraft.trim() }" @ok="saveName" @cancel="namingTerminal = undefined" @after-close="restoreNameFocus">
      <label for="terminal-device-name">设备名称</label>
      <Input id="terminal-device-name" v-model:value="nameDraft" class="mt-2" :maxlength="100" show-count placeholder="请输入设备名称" @press-enter="saveName" />
    </Modal>
  </Page>
</template>
