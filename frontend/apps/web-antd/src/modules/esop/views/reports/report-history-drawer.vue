<script lang="ts" setup>
import type { ProductionReport, ReportRevision } from '../../api/operations';

import { nextTick, ref } from 'vue';

import { formatDateTime } from '@vben/utils';

import { Drawer, Empty, Spin, Table } from 'ant-design-vue';

import { listReportRevisions } from '../../api/operations';

const open = ref(false);
const loading = ref(false);
const target = ref<ProductionReport>();
const rows = ref<ReportRevision[]>([]);
let trigger: HTMLElement | null = null;
let loadVersion = 0;
const columns = [{ title: '字段', dataIndex: 'field', width: 88 }, { title: '修改前', dataIndex: 'before' }, { title: '修改后', dataIndex: 'after' }];
function changes(row: ReportRevision) {
  return [
    { field: '记录状态', before: row.before.is_deleted ? '已删除' : '有效', after: row.after.is_deleted ? '已删除' : '有效', changed: !!row.before.is_deleted !== !!row.after.is_deleted },
    { field: '报工员工', before: row.before.staff_name, after: row.after.staff_name, changed: row.before.staff_user_id !== row.after.staff_user_id },
    ...(['input_qty', 'good_qty', 'defect_qty'] as const).map((key) => ({ field: { input_qty: '投入数量', good_qty: '良品数量', defect_qty: '不良数量' }[key], before: row.before[key], after: row.after[key], changed: row.before[key] !== row.after[key] })),
  ].filter((item) => item.changed);
}
async function show(row: ProductionReport) {
  trigger = document.activeElement as HTMLElement;
  target.value = row;
  rows.value = [];
  open.value = true;
  loading.value = true;
  const version = ++loadVersion;
  try {
    const result = await listReportRevisions(row.id);
    if (version === loadVersion) rows.value = result.items;
  } finally { if (version === loadVersion) loading.value = false; }
}
function close() { ++loadVersion; open.value = false; }
async function restoreFocus(visible: boolean) { if (!visible) { await nextTick(); trigger?.focus(); } }
defineExpose({ show });
</script>

<template>
  <Drawer :open="open" title="报工修改记录" width="min(760px, 100vw)" :keyboard="true" @close="close" @after-open-change="restoreFocus">
    <div v-if="target" class="mb-4 text-muted-foreground">{{ target.order_code }} · {{ target.station_position }} 号工位 · {{ target.staff_name }}</div>
    <Spin :spinning="loading">
      <Empty v-if="!loading && !rows.length" description="暂无修改记录" />
      <section v-for="row in rows" :key="row.id" class="mb-6 rounded border border-border p-4">
        <div class="mb-2 font-medium">第 {{ row.revision }} 次修改 · {{ row.changed_by_name }}</div>
        <div class="mb-3 text-sm text-muted-foreground">修改时间：{{ formatDateTime(row.changed_at) }}</div>
        <div class="mb-3 whitespace-pre-wrap break-words">修改原因：{{ row.reason }}</div>
        <Table size="small" table-layout="fixed" class="revision-changes" :columns="columns" :data-source="changes(row)" :pagination="false" row-key="field" />
      </section>
    </Spin>
  </Drawer>
</template>

<style scoped>
.revision-changes :deep(.ant-table-cell) {
  overflow-wrap: anywhere;
}
</style>
