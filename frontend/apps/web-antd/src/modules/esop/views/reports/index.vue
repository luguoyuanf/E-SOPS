<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { ProductionReport, ReportCorrectionOptions, ReportFilterOptions } from '../../api/operations';

import { computed, onMounted, reactive, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';
import { formatDateTime } from '@vben/utils';
import { useAccess } from '@vben/access';

import { Button, Input, Select } from 'ant-design-vue';

import { downloadApi } from '#/api';

import { getReportCorrectionOptions, listReportFilterOptions, listReports } from '../../api/operations';
import WebReportDrawer from './web-report-drawer.vue';
import ReportCorrectionDrawer from './report-correction-drawer.vue';
import ReportHistoryDrawer from './report-history-drawer.vue';
import ReportChangeReviewDrawer from './report-change-review-drawer.vue';
import OperationAttachmentsPreview from '../../components/operation-attachments-preview.vue';
import type { Operation } from '../../api/esop';
import { getReportSopPreview, getReportSopFileAccess } from '../../api/operations';

const sopPreviewOpen = ref(false);
const sopPreviewLoading = ref('');
const sopPreview = ref<{ reportId: string; productId: string; title: string; operation: Operation; trigger: HTMLElement }>();
async function previewSop(record: ProductionReport, event: MouseEvent) {
  const trigger = event.currentTarget as HTMLElement;
  sopPreviewLoading.value = record.id;
  try {
    const result = await getReportSopPreview(record.id);
    sopPreview.value = {
      reportId: record.id, productId: result.product_id, title: `${record.sop_title} V${record.sop_version} · 当时 SOP`, trigger,
      operation: { id: result.operation_id, code: '', name: result.title, product_id: result.product_id, sort_order: 0, attachments: result.attachments },
    };
    sopPreviewOpen.value = true;
  } finally {
    sopPreviewLoading.value = '';
  }
}
function resolveSopFile(fileId: string) {
  return getReportSopFileAccess(sopPreview.value!.reportId, fileId);
}

const { hasAccessByCodes } = useAccess();
const correctionOptions = ref<ReportCorrectionOptions>({ can_edit: false, staff: [] });
const correctionDrawer = ref<InstanceType<typeof ReportCorrectionDrawer>>();
const reviewDrawer = ref<InstanceType<typeof ReportChangeReviewDrawer>>();
const historyDrawer = ref<InstanceType<typeof ReportHistoryDrawer>>();
const reportDrawer = ref<InstanceType<typeof WebReportDrawer>>();
const canCreate = computed(() => hasAccessByCodes(['esop:report:create']));
const rows = ref<ProductionReport[]>([]);
const options = ref<ReportFilterOptions>({ orders: [], lines: [], stations: [], staff: [] });
const loading = ref(false);
const exporting = ref(false);
const filters = reactive({ order_id: '', line_id: '', station_id: '', staff_user_id: '', start_date: '', end_date: '' });
const stationOptions = computed(() => options.value.stations.filter(
  (station) => !filters.line_id || station.line_id === filters.line_id,
));
watch(() => filters.line_id, () => { filters.station_id = ''; });
const columns = [
  { title: '订单', dataIndex: 'order_code', key: 'order_code', width: 170 },
  { title: '员工', dataIndex: 'staff_name', key: 'staff_name', width: 130 },
  { title: '工位', key: 'station', width: 100 },
  { title: '当时 SOP', key: 'sop', width: 200, ellipsis: true },
  { title: '投入', dataIndex: 'input_qty', key: 'input_qty', width: 80 },
  { title: '良品', dataIndex: 'good_qty', key: 'good_qty', width: 80 },
  { title: '不良', dataIndex: 'defect_qty', key: 'defect_qty', width: 80 },
  { title: '来源', key: 'source', width: 80 },
  { title: '报工时间', dataIndex: 'occurred_at', key: 'occurred_at', width: 190 },
  { title: '操作', key: 'actions', width: 200, fixed: 'right' as const },
];

function openDatePicker(event: MouseEvent) {
  (event.target as HTMLInputElement).showPicker?.();
}

function params() {
  return {
    order_id: filters.order_id || undefined,
    line_id: filters.line_id || undefined,
    station_id: filters.station_id || undefined,
    staff_user_id: filters.staff_user_id || undefined,
    start_at: filters.start_date ? new Date(`${filters.start_date}T00:00:00`).toISOString() : undefined,
    end_at: filters.end_date ? new Date(`${filters.end_date}T23:59:59`).toISOString() : undefined,
  };
}

async function refresh() {
  loading.value = true;
  try {
    const result = await listReports(params());
    rows.value = result.items;
  } finally {
    loading.value = false;
  }
}

async function exportCsv() {
  exporting.value = true;
  try {
    const query = new URLSearchParams(
      Object.entries(params()).filter((item): item is [string, string] => item[1] !== undefined),
    ).toString();
    await downloadApi(`/esop/reports/export${query ? `?${query}` : ''}`, '报工记录.csv');
  } finally {
    exporting.value = false;
  }
}

function clearFilters() {
  filters.order_id = '';
  filters.line_id = '';
  filters.station_id = '';
  filters.staff_user_id = '';
  filters.start_date = '';
  filters.end_date = '';
  void refresh();
}

onMounted(() => {
  void refresh();
  void getReportCorrectionOptions().then((result) => { correctionOptions.value = result; });
  void listReportFilterOptions().then((result) => { options.value = result; });
});
</script>

<template>
  <Page title="员工报工与追溯">
    <form class="report-filters mb-4" @submit.prevent="refresh()">
      <div class="report-filter">
        <label for="report-order">生产订单</label>
        <Select id="report-order" v-model:value="filters.order_id" allow-clear :options="options.orders" placeholder="请选择生产订单" />
      </div>
      <div class="report-filter">
        <label for="report-line">产线</label>
        <Select id="report-line" v-model:value="filters.line_id" allow-clear :options="options.lines" placeholder="请选择产线" />
      </div>
      <div class="report-filter">
        <label for="report-station">工位</label>
        <Select id="report-station" v-model:value="filters.station_id" allow-clear :options="stationOptions" placeholder="请选择工位" />
      </div>
      <div class="report-filter">
        <label for="report-staff">员工</label>
        <Select id="report-staff" v-model:value="filters.staff_user_id" allow-clear :options="options.staff" placeholder="请选择员工" />
      </div>
      <div class="report-filter report-date-filter" role="group" aria-labelledby="report-date-label">
        <span id="report-date-label">报工日期</span>
        <div class="report-date-range">
          <Input v-model:value="filters.start_date" aria-label="开始日期" type="date" @click="openDatePicker" />
          <span>至</span>
          <Input v-model:value="filters.end_date" aria-label="结束日期" type="date" @click="openDatePicker" />
        </div>
      </div>
      <div class="report-actions">
        <Button v-if="canCreate" type="primary" @click="reportDrawer?.show()">新增报工</Button>
        <Button v-if="correctionOptions.can_edit" @click="reviewDrawer?.show()">报工修改/删除审核</Button>
        <Button html-type="submit" :loading="loading">查询</Button>
        <Button @click="clearFilters">重置</Button>
        <Button v-access:code="'esop:report:export'" :loading="exporting" @click="exportCsv">导出 CSV</Button>
      </div>
    </form>
    <Table table-layout="fixed" :scroll="{ x: 1400 }" :columns="columns" :data-source="rows" :loading="loading" :pagination="false" row-key="id">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'actions'" class="inline-flex gap-2">
          <Button v-if="correctionOptions.can_edit" type="link" :data-report-edit="record.id" @click="correctionDrawer?.show(record as ProductionReport)">修改</Button>
          <Button type="link" @click="historyDrawer?.show(record as ProductionReport)">修改记录{{ record.revision ? ` (${record.revision})` : '' }}</Button>
        </span>
        <span v-else-if="column.key === 'source'">{{ (record as ProductionReport).submitted_by ? '后台' : '终端' }}</span>
        <span v-else-if="column.key === 'station'">{{ (record as ProductionReport).station_position }} 号工位</span>
        <Button v-else-if="column.key === 'sop'" type="link" class="sop-preview-link" :title="`${record.sop_title} V${record.sop_version}`" :loading="sopPreviewLoading === record.id" :disabled="!!sopPreviewLoading" @click="previewSop(record as ProductionReport, $event)">{{ record.sop_title }} V{{ record.sop_version }}</Button>
        <span v-else-if="column.key === 'occurred_at'">{{ (record as ProductionReport).occurred_at ? formatDateTime((record as ProductionReport).occurred_at) : '—' }}</span>
      </template>
    </Table>
    <ReportCorrectionDrawer v-if="correctionOptions.can_edit" ref="correctionDrawer" :staff="correctionOptions.staff" @success="refresh" />
    <ReportHistoryDrawer ref="historyDrawer" />
    <ReportChangeReviewDrawer v-if="correctionOptions.can_edit" ref="reviewDrawer" @success="refresh" />
    <WebReportDrawer v-if="canCreate" ref="reportDrawer" @success="refresh" />
    <OperationAttachmentsPreview v-if="sopPreview" v-model:open="sopPreviewOpen" :product-id="sopPreview.productId" :title="sopPreview.title" :operations="[sopPreview.operation]" :resolve-file="resolveSopFile" :trigger-element="sopPreview.trigger" />
  </Page>
</template>

<style scoped>
.sop-preview-link {
  max-width: 100%;
  padding-inline: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.report-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
}

.report-filter,
.report-date-range,
.report-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.report-filter > label,
.report-date-filter > span {
  flex-shrink: 0;
  white-space: nowrap;
}

.report-filter :deep(.ant-select) {
  width: 180px;
}

.report-date-range {
  min-width: 0;
  flex-wrap: nowrap;
}

.report-date-range :deep(.ant-input) {
  width: 150px;
  min-width: 0;
}

@media (max-width: 575px) {
  .report-date-filter { width: 100%; }
  .report-date-range { flex: 1; }
  .report-date-range :deep(.ant-input) { width: 0; flex: 1; }
}
</style>
