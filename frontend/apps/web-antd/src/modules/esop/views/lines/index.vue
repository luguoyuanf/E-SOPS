<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { ProductionLine, Station, Workshop } from '../../api/production';

import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { IconifyIcon } from '@vben/icons';

import { Page } from '@vben/common-ui';

import { Button, Drawer, Form, Input, InputNumber, message, Modal, Select, Tabs } from 'ant-design-vue';

import { deleteLine, deleteWorkshop, listLines, listWorkshops, saveLine, saveWorkshop } from '../../api/production';
import LineLayoutIcon from '../../components/line-layout-icon.vue';
import StationDeviceBinding from '../../components/station-device-binding.vue';
import { buildStationColumns } from '../../utils/line-layout';

const route = useRoute();
const tab = ref('lines');
watch(() => route.path, (path) => { tab.value = path.endsWith('/workshops') ? 'workshops' : 'lines'; }, { immediate: true });
const workshops = ref<Workshop[]>([]);
const lines = ref<ProductionLine[]>([]);
const loading = ref(false);
const saving = ref(false);
const deletingId = ref<string>();
const workshopOpen = ref(false);
const lineOpen = ref(false);
const bindingOpen = ref(false);
const bindingLineId = ref<string>();
const workshopId = ref<string>();
const lineId = ref<string>();
const workshopForm = reactive({ code: '', name: '' });
const lineForm = reactive({ workshop_id: '', code: '', name: '', layout: 'single' as ProductionLine['layout'], station_count: 1, numbering_mode: 'sequential' as NonNullable<ProductionLine['numbering_mode']> });
const workshopNames = computed(() => new Map(workshops.value.map((item) => [item.id, item.name])));
const workshopOptions = computed(() => workshops.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const savedStations = computed(() => lines.value.find((line) => line.id === lineId.value)?.stations ?? []);
const stationNames = ref<Record<number, string>>({});
const previewColumns = computed(() => buildStationColumns(lineForm.layout, lineForm.station_count || 0, savedStations.value, lineForm.numbering_mode));
const numberingOptions = [{ value: 'sequential', label: '横向连续（上排 1、2、3，下排接续）' }, { value: 'odd_even', label: '奇偶分排（上排 1、3、5，下排 2、4、6）' }];
function stationName(station: Station) { return stationNames.value[station.position] ?? station.name ?? ''; }
const boundCount = computed(() => previewColumns.value.flat().filter((station) => station.terminal_code).length);
const quickWorkshop = ref(false);
let lineTrigger: HTMLElement | null = null;
let bindingTrigger: HTMLElement | null = null;
let workshopTrigger: HTMLElement | null = null;
const layoutOptions = [{ value: 'single', label: '单排' }, { value: 'double', label: '双排' }] as const;
function closeLine() { if (!workshopOpen.value) lineOpen.value = false; }
function afterLineOpenChange(open: boolean) { if (!open) lineTrigger?.focus(); }
function closeWorkshop() { workshopOpen.value = false; }
function afterWorkshopOpenChange(open: boolean) { if (!open) workshopTrigger?.focus(); }
const workshopColumns = [
  { title: '编码', dataIndex: 'code', key: 'code' },
  { title: '车间', dataIndex: 'name', key: 'name' },
  { title: '操作', key: 'action', width: 160 },
];
const lineColumns = [
  { title: '产线编码', dataIndex: 'code', key: 'code', width: '18%' },
  { title: '产线', dataIndex: 'name', key: 'name', width: '25%' },
  { title: '车间', key: 'workshop', width: '20%' },
  { title: '布局', key: 'layout', width: '16%' },
  { title: '工位', dataIndex: 'station_count', key: 'station_count', width: '10%', align: 'right' as const },
  { title: '操作', key: 'action', width: 240 },
];

async function refresh() {
  loading.value = true;
  try {
    const [workshopResult, lineResult] = await Promise.all([listWorkshops(), listLines()]);
    workshops.value = workshopResult.items;
    lines.value = lineResult.items;
  } finally {
    loading.value = false;
  }
}

function editWorkshop(row?: Workshop, event?: Event, quick = false) {
  workshopTrigger = (event?.currentTarget as HTMLElement) ?? null;
  quickWorkshop.value = quick;
  workshopId.value = row?.id;
  workshopForm.code = row?.code ?? '';
  workshopForm.name = row?.name ?? '';
  workshopOpen.value = true;
}

function editLine(row?: ProductionLine, event?: Event) {
  lineTrigger = (event?.currentTarget as HTMLElement) ?? null;
  lineId.value = row?.id;
  lineForm.workshop_id = row?.workshop_id ?? '';
  lineForm.code = row?.code ?? '';
  lineForm.name = row?.name ?? '';
  lineForm.layout = row?.layout ?? 'single';
  lineForm.station_count = row?.station_count ?? 1;
  lineForm.numbering_mode = row?.numbering_mode ?? (row ? 'odd_even' : 'sequential');
  stationNames.value = Object.fromEntries((row?.stations ?? []).map((station) => [station.position, station.name ?? '']));
  lineOpen.value = true;
}

function openBinding(row: ProductionLine, event: Event) {
  bindingTrigger = event.currentTarget as HTMLElement;
  bindingLineId.value = row.id;
  bindingOpen.value = true;
}
function restoreBindingFocus() { bindingTrigger?.focus(); }

async function refreshBinding() {
  const result = await listLines();
  lines.value = result.items;
}

function confirmDeleteLine(row: ProductionLine, event?: Event) {
  const trigger = event?.currentTarget as HTMLElement | undefined;
  Modal.confirm({
    title: '删除产线',
    afterClose: () => trigger?.focus(),
    content: `确定删除产线“${row.name}”及其工位吗？系统会检查排产、发布、报工、报警和终端绑定；存在关联依赖时将禁止删除。`,
    keyboard: true,
    okText: '删除',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      deletingId.value = row.id;
      try {
        await deleteLine(row.id);
        lines.value = lines.value.filter((item) => item.id !== row.id);
        message.success('产线及工位已删除');
      } finally {
        deletingId.value = undefined;
      }
    },
  });
}

function confirmDeleteWorkshop(row: Workshop) {
  Modal.confirm({
    title: '删除车间',
    content: `确定删除车间“${row.name}”吗？已有产线的车间无法删除。`,
    keyboard: true,
    okText: '删除',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      deletingId.value = row.id;
      try {
        await deleteWorkshop(row.id);
        workshops.value = workshops.value.filter((item) => item.id !== row.id);
        if (lineForm.workshop_id === row.id) lineForm.workshop_id = '';
        message.success('车间已删除');
      } finally {
        deletingId.value = undefined;
      }
    },
  });
}

async function saveWorkshopForm() {
  if (!workshopForm.name.trim()) {
    message.warning('请填写车间名称');
    return;
  }
  saving.value = true;
  try {
    const created = await saveWorkshop({ code: workshopForm.code.trim(), name: workshopForm.name.trim() }, workshopId.value);
    const result = await listWorkshops();
    workshops.value = result.items;
    if (quickWorkshop.value) lineForm.workshop_id = created.id;
    workshopOpen.value = false;
    message.success('车间已保存');
  } finally {
    saving.value = false;
  }
}

async function saveLineForm() {
  if (!lineForm.workshop_id || !lineForm.name.trim() || lineForm.station_count < 1) {
    message.warning('请填写产线资料和工位数量');
    return;
  }
  saving.value = true;
  try {
    await saveLine({ ...lineForm, code: lineForm.code.trim(), name: lineForm.name.trim(), station_names: Object.fromEntries(previewColumns.value.flat().map((station) => [station.position, stationName(station).trim()])) }, lineId.value);
    lineOpen.value = false;
    await refresh();
    message.success('产线与工位已保存');
  } finally {
    saving.value = false;
  }
}

onMounted(() => void refresh());
</script>

<template>
  <Page :title="tab === 'workshops' ? '车间管理' : '产线与工位'">
    <Tabs v-model:active-key="tab" :items="[{ key: 'lines', label: '产线与工位' }, { key: 'workshops', label: '车间' }]" />
    <template v-if="tab === 'lines'">
      <div class="mb-4 flex justify-end"><Button v-access:code="'esop:line:create'" type="primary" @click="editLine(undefined, $event)">新增产线</Button></div>
      <Table date-field="created_at" :columns="lineColumns" :data-source="lines" :loading="loading" :pagination="false" :scroll="{ x: 900 }" row-key="id">
        <template #bodyCell="{ column, record }">
          <span v-if="column.key === 'code'" class="line-code">{{ (record as ProductionLine).code }}</span>
          <strong v-else-if="column.key === 'name'" class="line-name">{{ (record as ProductionLine).name }}</strong>
          <span v-if="column.key === 'workshop'">{{ workshopNames.get((record as ProductionLine).workshop_id) || '—' }}</span>
          <div v-else-if="column.key === 'layout'" class="table-layout"><LineLayoutIcon :layout="(record as ProductionLine).layout" /><span>{{ (record as ProductionLine).layout === 'double' ? '双排' : '单排' }}</span></div>
          <template v-else-if="column.key === 'action'">
            <Button v-access:code="'esop:line:update'" type="link" @click="editLine(record as ProductionLine, $event)">编辑</Button>
            <Button v-access:code="'esop:device:bind'" type="link" @click="openBinding(record as ProductionLine, $event)">绑定设备</Button>
            <Button v-access:code="'esop:line:delete'" danger type="link" :loading="deletingId === record.id" :disabled="!!deletingId" @click="confirmDeleteLine(record as ProductionLine, $event)">删除</Button>
          </template>
        </template>
      </Table>
    </template>
    <template v-else>
      <div class="mb-4 flex justify-end"><Button v-access:code="'esop:workshop:create'" type="primary" @click="editWorkshop(undefined, $event)">新增车间</Button></div>
      <Table date-field="created_at" :columns="workshopColumns" :data-source="workshops" :loading="loading" :pagination="false" row-key="id">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'action'">
            <Button v-access:code="'esop:workshop:update'" type="link" @click="editWorkshop(record as Workshop, $event)">编辑</Button>
            <Button v-access:code="'esop:workshop:delete'" danger type="link" :loading="deletingId === record.id" :disabled="!!deletingId" @click="confirmDeleteWorkshop(record as Workshop)">删除</Button>
          </template>
        </template>
      </Table>
    </template>
    <StationDeviceBinding v-model:open="bindingOpen" :initial-line-id="bindingLineId" @bound="refreshBinding" @closed="restoreBindingFocus" />

    <Drawer :open="workshopOpen" :keyboard="true" :title="workshopId ? '编辑车间' : '新增车间'" width="min(960px, max(68vw, min(100vw, 640px)))" :z-index="3000" :mask-style="{ zIndex: 0 }" :content-wrapper-style="{ zIndex: 1 }" @close="closeWorkshop" @after-open-change="afterWorkshopOpenChange">
      <Form :model="workshopForm" layout="vertical">
        <Form.Item label="车间编码"><Input v-model:value="workshopForm.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
        <Form.Item label="车间名称" required><Input v-model:value="workshopForm.name" :maxlength="100" /></Form.Item>
      </Form>
      <template #footer>
        <Button class="mr-2" @click="closeWorkshop">取消</Button>
        <Button :loading="saving" type="primary" @click="saveWorkshopForm">保存</Button>
      </template>
    </Drawer>

    <Drawer :open="lineOpen" :keyboard="!workshopOpen" :title="lineId ? '编辑产线' : '新增产线'" width="min(1480px, max(78vw, min(100vw, 1080px)))" :mask-style="{ zIndex: 0 }" :content-wrapper-style="{ zIndex: 1 }" @close="closeLine" @after-open-change="afterLineOpenChange">
      <Form :model="lineForm" layout="vertical">
        <Form.Item label="所属车间" required>
          <div class="flex items-center gap-2">
            <Select v-model:value="lineForm.workshop_id" class="min-w-0 flex-1" :options="workshopOptions" placeholder="选择车间" />
            <Button v-access:code="'esop:workshop:create'" @click="editWorkshop(undefined, $event, true)"><IconifyIcon icon="lucide:plus" class="mr-1 inline-block size-4" />新建车间</Button>
          </div>
        </Form.Item>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Form.Item label="产线编码"><Input v-model:value="lineForm.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
          <Form.Item label="产线名称" required><Input v-model:value="lineForm.name" :maxlength="100" /></Form.Item>
          <Form.Item label="工位布局" required>
            <div class="layout-options" role="group" aria-label="工位布局">
              <button v-for="option in layoutOptions" :key="option.value" type="button" class="layout-option" :class="{ selected: lineForm.layout === option.value }" :aria-pressed="lineForm.layout === option.value" @click="lineForm.layout = option.value">
                <LineLayoutIcon :layout="option.value" /><span>{{ option.label }}</span>
              </button>
            </div>
          </Form.Item>
          <Form.Item label="工位总数" required><InputNumber v-model:value="lineForm.station_count" :min="1" :max="200" class="w-full" /></Form.Item>
          <Form.Item v-if="lineForm.layout === 'double'" label="工位编号方式" class="sm:col-span-2"><Select v-model:value="lineForm.numbering_mode" :options="numberingOptions" /></Form.Item>
        </div>
      </Form>
      <section aria-label="工位布局预览" class="station-preview">
        <div class="preview-heading"><h3>工位布局与名称</h3><span>共 {{ lineForm.station_count || 0 }} 个工位 · 已绑定 {{ boundCount }} 个 · 名称可直接修改，留空使用默认名称 · 可向右滑动查看</span></div>
        <div class="station-scroller" role="region" tabindex="0" aria-label="工位布局，可横向滚动">
          <div class="station-track">
            <div v-for="columnStations in previewColumns" :key="columnStations[0]!.position" class="station-column">
              <div v-for="station in columnStations" :key="station.position" class="station" :class="{ bound: station.terminal_code }">
              <IconifyIcon :icon="station.terminal_code ? 'lucide:monitor-check' : 'lucide:monitor'" class="size-5" aria-hidden="true" />
              <label :for="`station-name-${station.position}`">工位 {{ station.position }}</label>
              <Input :id="`station-name-${station.position}`" :value="stationName(station)" :aria-label="`工位 ${station.position} 名称`" :placeholder="`工位 ${station.position}`" :maxlength="100" size="small" @update:value="stationNames[station.position] = $event" />
              <span>{{ station.row }} 排 · {{ station.column }} 位</span>
              <span class="station-binding">{{ station.terminal_code ? '已绑定终端' : '未绑定终端' }}</span>
              <span v-if="station.terminal_code" class="terminal-code" :title="station.terminal_code">{{ station.terminal_code }}</span>
              <span v-else-if="station.pending" class="terminal-code">保存后可绑定</span>
              </div>
            </div>
          </div>
        </div>
      </section>
      <template #footer>
        <Button class="mr-2" @click="closeLine">取消</Button>
        <Button :loading="saving" type="primary" @click="saveLineForm">保存</Button>
      </template>
    </Drawer>
  </Page>
</template>

<style scoped>
.line-code { font-variant-numeric: tabular-nums; }
.line-name { font-weight: 600; }
.table-layout { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; font-size: 13px; }
.table-layout :deep(svg) { width: 56px; height: 26px; }
.layout-options { display: flex; gap: 12px; }
.layout-option { display: flex; flex: 1; flex-direction: column; align-items: center; gap: 4px; padding: 10px; border: 1px solid hsl(var(--border)); border-radius: 6px; background: hsl(var(--background)); cursor: pointer; }
.layout-option.selected { border-color: hsl(var(--primary)); outline: 1px solid hsl(var(--primary)); }
.layout-option:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: 3px; }
.station-preview { margin-top: 8px; }
.preview-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 16px; }
.preview-heading h3 { margin: 0; font-size: 16px; font-weight: 600; }
.preview-heading > span { color: hsl(var(--muted-foreground)); font-size: 12px; }
.station-scroller { overflow-x: auto; padding: 12px 0; border-top: 1px solid hsl(var(--border)); }
.station-scroller:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: 2px; }
.station-track { display: flex; width: max-content; gap: 8px; }
.station-column { display: flex; width: 156px; flex: none; flex-direction: column; gap: 8px; }
.station { display: flex; height: 150px; min-width: 0; flex-direction: column; align-items: center; gap: 3px; padding: 8px 4px; border: 1px solid hsl(var(--border)); border-radius: 6px; font-size: 12px; }
.station > svg { color: hsl(var(--muted-foreground)); }
.station > label { font-size: 13px; font-weight: 600; }
.station-binding { color: hsl(var(--muted-foreground)); }
.bound .station-binding, .bound > svg { color: #247b50; }
.terminal-code { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
@media (max-width: 640px) { .layout-options { gap: 8px; } }
</style>
