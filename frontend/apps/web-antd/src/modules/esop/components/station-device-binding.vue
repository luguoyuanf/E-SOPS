<script lang="ts" setup>
import type { Terminal } from '../api/operations';
import type { ProductionLine, Station } from '../api/production';

import { computed, ref, watch } from 'vue';

import { IconifyIcon } from '@vben/icons';

import { Button, message, Modal, Select } from 'ant-design-vue';

import { bindTerminal, listTerminals } from '../api/operations';
import { listLines } from '../api/production';
import { buildStationColumns, stationLabel } from '../utils/line-layout';

const props = defineProps<{
  open: boolean;
  initialLineId?: string;
  initialTerminalId?: string;
}>();
const emit = defineEmits<{
  'update:open': [value: boolean];
  bound: [];
  closed: [];
}>();

const lines = ref<ProductionLine[]>([]);
const terminals = ref<Terminal[]>([]);
const lineId = ref<string>();
const terminalId = ref<string>();
const loading = ref(false);
const saving = ref(false);
const selectedLine = computed(() => lines.value.find((line) => line.id === lineId.value));
const selectedTerminal = computed(() => terminals.value.find((terminal) => terminal.id === terminalId.value));
const currentBinding = computed(() => {
  const stationId = selectedTerminal.value?.station_id;
  if (!stationId) return;
  for (const line of lines.value) {
    const station = line.stations.find((item) => item.id === stationId);
    if (station) return `${line.name} · ${stationLabel(station)}`;
  }
  return '工位已不可用';
});
const columns = computed(() => selectedLine.value
  ? buildStationColumns(selectedLine.value.layout, selectedLine.value.station_count, selectedLine.value.stations, selectedLine.value.numbering_mode)
  : []);
const lineOptions = computed(() => lines.value.map((line) => ({ label: `${line.name} (${line.code})`, value: line.id })));
const terminalOptions = computed(() => terminals.value.filter((terminal) => terminal.is_active).map((terminal) => ({ label: terminal.device_name ? `${terminal.device_name} (${terminal.serial_number})` : terminal.serial_number, value: terminal.id })));

watch(() => props.open, async (open) => {
  if (!open) return;
  lineId.value = props.initialLineId;
  terminalId.value = props.initialTerminalId;
  loading.value = true;
  try {
    const [lineResult, terminalResult] = await Promise.all([listLines(), listTerminals()]);
    if (!props.open) return;
    lines.value = lineResult.items;
    terminals.value = terminalResult.items;
    if (!lineId.value && selectedTerminal.value?.station_id) {
      lineId.value = lines.value.find((line) => line.stations.some((station) => station.id === selectedTerminal.value?.station_id))?.id;
    }
  } finally {
    loading.value = false;
  }
});

function occupant(station: Station) {
  return terminals.value.find((terminal) => terminal.is_active && terminal.station_id === station.id);
}

async function bind(stationId: null | string) {
  if (!terminalId.value || saving.value) {
    if (!terminalId.value) message.warning('请先选择设备');
    return;
  }
  saving.value = true;
  try {
    await bindTerminal(terminalId.value, stationId);
    message.success(stationId ? '设备已绑定到工位' : '设备已解绑');
    emit('update:open', false);
    emit('bound');
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal :open="open" :title="initialTerminalId ? '绑定工位' : '绑定设备'" :footer="null" :keyboard="true" width="min(920px, 96vw)" @cancel="emit('update:open', false)" @after-close="emit('closed')">
    <div class="binding-filters">
      <label>设备<Select v-model:value="terminalId" show-search option-filter-prop="label" :options="terminalOptions" :loading="loading" placeholder="选择设备" /></label>
      <label>产线<Select v-model:value="lineId" show-search option-filter-prop="label" :options="lineOptions" :loading="loading" placeholder="选择产线" /></label>
    </div>
    <p v-if="currentBinding" class="current-binding">当前绑定：{{ currentBinding }}</p>
    <p v-if="!selectedLine" class="binding-hint">请选择产线，查看工位位置。</p>
    <template v-else>
      <p class="binding-hint">{{ selectedLine.layout === 'double' ? '双排' : '单排' }} · {{ selectedLine.station_count }} 个工位 · 点击空闲工位绑定所选设备</p>
      <div class="station-scroller" role="region" tabindex="0" aria-label="产线工位布局，可横向滚动">
        <div class="station-track">
          <div v-for="columnStations in columns" :key="columnStations[0]!.position" class="station-column">
            <button v-for="station in columnStations" :key="station.id" type="button" class="station" :class="{ occupied: !!occupant(station), current: selectedTerminal?.station_id === station.id }" :disabled="loading || saving || !!occupant(station) && occupant(station)?.id !== terminalId" :aria-label="`${stationLabel(station)}，${station.row} 排 ${station.column} 位，${occupant(station) ? `${occupant(station)?.serial_number}，${occupant(station)?.device_name || '未命名'}` : '空闲'}`" @click="bind(station.id)">
              <IconifyIcon :icon="occupant(station) ? 'lucide:monitor-check' : 'lucide:monitor'" class="size-5" aria-hidden="true" />
              <strong>{{ stationLabel(station) }}</strong>
              <span>{{ station.row }} 排 · {{ station.column }} 位</span>
              <span>{{ occupant(station)?.serial_number || '空闲' }}</span>
              <span v-if="occupant(station)">{{ occupant(station)?.device_name || '未命名' }}</span>
            </button>
          </div>
        </div>
      </div>
    </template>
    <div class="binding-footer">
      <Button v-if="selectedTerminal?.station_id" :loading="saving" @click="bind(null)">解除当前绑定</Button>
      <Button @click="emit('update:open', false)">取消</Button>
    </div>
  </Modal>
</template>

<style scoped>
.binding-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.binding-filters label { display: grid; gap: 6px; font-weight: 500; }
.binding-filters :deep(.ant-select) { width: 100%; }
.binding-hint, .current-binding { margin: 16px 0 8px; color: hsl(var(--muted-foreground)); }
.station-scroller { overflow-x: auto; padding: 12px 0; border-top: 1px solid hsl(var(--border)); }
.station-track { display: flex; width: max-content; gap: 8px; }
.station-column { display: flex; width: 156px; flex: none; flex-direction: column; gap: 8px; }
.station { display: flex; min-height: 128px; width: 100%; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding: 8px; border: 1px solid hsl(var(--border)); border-radius: 6px; background: hsl(var(--background)); cursor: pointer; }
.station:hover:not(:disabled), .station:focus-visible { border-color: hsl(var(--primary)); outline: 1px solid hsl(var(--primary)); }
.station:disabled { cursor: not-allowed; opacity: .65; }
.station.occupied { color: #247b50; }
.station.current { border-color: #247b50; }
.station span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.binding-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
@media (max-width: 640px) { .binding-filters { grid-template-columns: 1fr; } }
</style>
