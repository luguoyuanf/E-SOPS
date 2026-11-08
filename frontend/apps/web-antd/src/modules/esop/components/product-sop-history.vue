<script setup lang="ts">
import type { ProductSopVersion } from '../api/product-sops';

import { computed, ref, watch } from 'vue';
import { formatDateTime } from '@vben/utils';
import { Button, Drawer, Empty, message, Modal, Spin, Table } from 'ant-design-vue';
import { getProductSopVersion, listProductSopVersions, productSopStatusText, rollbackProductSop } from '../api/product-sops';
import ProductSopPreview from './product-sop-preview.vue';

const props = defineProps<{ open: boolean; productId: string; productName: string; canRollback: boolean }>();
const emit = defineEmits<{ 'update:open': [boolean]; changed: [] }>();
const rows = ref<ProductSopVersion[]>([]);
const effectiveId = computed(() => rows.value.filter((row) => row.status === 'approved').sort((a, b) => b.version - a.version)[0]?.id);
const loading = ref(false);
const failed = ref(false);
const preview = ref<ProductSopVersion>();
const previewOpen = ref(false);
const loadingPreview = ref(false);
const previewTrigger = ref<HTMLElement>();
const confirming = ref(false);
const rollingBack = ref(false);
let requestId = 0;
let previewRequest = 0;
let returnFocus: HTMLElement | undefined;
const columns = [
  { title: '版本', key: 'version', width: 90 },
  { title: '状态', key: 'status', width: 100 },
  { title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at' },
  { title: '审核时间', dataIndex: 'reviewed_at', key: 'reviewed_at' },
  { title: '审核意见', dataIndex: 'review_note', key: 'review_note' },
  { title: '操作', key: 'action', width: 160, fixed: 'right' as const },
];

async function load() {
  const id = ++requestId;
  loading.value = true;
  failed.value = false;
  try {
    const result = await listProductSopVersions(props.productId);
    if (id === requestId && props.open) rows.value = result.items;
  } catch { if (id === requestId) failed.value = true; }
  finally { if (id === requestId) loading.value = false; }
}
async function showPreview(row: ProductSopVersion, event: Event) {
  previewTrigger.value = event.currentTarget as HTMLElement;
  const request = ++previewRequest;
  loadingPreview.value = true;
  try {
    const detail = await getProductSopVersion(row.id);
    if (request === previewRequest && props.open) { preview.value = detail.version; previewOpen.value = true; }
  } finally { if (request === previewRequest) loadingPreview.value = false; }
}
function rollback(row: ProductSopVersion) {
  confirming.value = true;
  Modal.confirm({
    title: `恢复 V${row.version} 为草稿`,
    content: '当前未提交的修改将被该版本替换。恢复后需重新提交审核；已发布到终端的内容不会改变。',
    keyboard: true, zIndex: 3000, okText: '恢复为草稿', cancelText: '取消',
    onCancel() { confirming.value = false; },
    afterClose() { confirming.value = false; },
    async onOk() {
      rollingBack.value = true;
      try {
        await rollbackProductSop(row.id);
        confirming.value = false;
        emit('changed');
        emit('update:open', false);
        message.success('已恢复为草稿，请确认后提交审核');
      } finally { rollingBack.value = false; }
    },
  });
}
function close() { if (!previewOpen.value && !confirming.value) emit('update:open', false); }
function afterOpenChange(open: boolean) { if (!open) returnFocus?.focus(); }
watch(() => props.open, (open) => {
  if (open) { returnFocus = document.activeElement as HTMLElement; rows.value = []; void load(); }
  else { requestId++; previewRequest++; loadingPreview.value = false; previewOpen.value = false; }
});
</script>

<template>
  <Drawer :open="open" :mask-style="{ zIndex: 0 }" :content-wrapper-style="{ zIndex: 1 }" :title="`${productName} · 历史版本`" width="min(1000px, 100vw)" :keyboard="!previewOpen && !confirming" :z-index="1100" @close="close" @after-open-change="afterOpenChange">
    <p class="mb-4 text-sm text-muted-foreground">每个版本包含整套产品工序、顺序和附件。回滚会生成工作草稿，需重新审核后才可用于后续发布。</p>
    <Spin :spinning="loading || rollingBack">
      <div v-if="failed"><p class="mb-3">历史版本加载失败</p><Button @click="load">重试</Button></div>
      <Empty v-else-if="!rows.length && !loading" description="还没有提交过产品版本" />
      <Table v-else :columns="columns" :data-source="rows" :pagination="false" :scroll="{ x: 760 }" row-key="id">
        <template #bodyCell="{ column, record }">
          <span v-if="column.key === 'version'">V{{ record.version }}</span>
          <span v-else-if="column.key === 'status'">{{ record.id === effectiveId ? '生效' : record.status === 'approved' ? '历史已审核' : productSopStatusText[(record as ProductSopVersion).status] }}</span>
          <div v-else-if="column.key === 'action'" class="flex items-center">
            <Button type="link" :disabled="loadingPreview" @click="showPreview(record as ProductSopVersion, $event)">预览</Button>
            <Button v-if="record.status === 'approved'" v-access:code="'esop:sop:update'" :disabled="!canRollback || rollingBack" type="link" @click="rollback(record as ProductSopVersion)">回滚</Button>
          </div>
          <span v-else-if="column.key === 'submitted_at' || column.key === 'reviewed_at'">{{ record[column.key] ? formatDateTime(record[column.key]) : '—' }}</span>
          <span v-else-if="column.key === 'review_note'">{{ record.review_note || '—' }}</span>
        </template>
      </Table>
    </Spin>
    <ProductSopPreview v-if="preview" v-model:open="previewOpen" :product-id="productId" :title="`${productName} · V${preview.version} 产品预览`" :operations="preview.operations" :version-id="preview.id" :trigger-element="previewTrigger" />
  </Drawer>
</template>
