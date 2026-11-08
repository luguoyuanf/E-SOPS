<script setup lang="ts">
import { SelectableTable as Table } from '#/components/selectable-table';
import type { Operation } from '../../api/esop';
import type { ProductSopDetail, ProductSopVersion } from '../../api/product-sops';

import { computed, onMounted, ref } from 'vue';

import { formatDateTime } from '@vben/utils';
import { Page } from '@vben/common-ui';
import { Button, DatePicker, Drawer, Empty, Form, Input, message, Modal, Select, Spin, Tabs, TabPane, Tag } from 'ant-design-vue';
import { createdRangeQuery } from '#/utils/created-range';
import { approveProductSop, getProductSopVersion, listProductSopReviews, productSopStatusText, rejectProductSop } from '../../api/product-sops';
import ProductSopComparison from '../../components/product-sop-comparison.vue';
import OperationAttachmentsPreview from '../../components/operation-attachments-preview.vue';
import ProductSopPreview from '../../components/product-sop-preview.vue';
import { compareProductOperations } from '../../utils/product-sop-diff';

const rows = ref<ProductSopVersion[]>([]);
const loading = ref(false);
const failed = ref(false);
const activeTab = ref<'pending' | 'reviewed'>('pending');
const keyword = ref('');
const submittedRange = ref<[string, string]>();
const appliedSubmittedRange = ref<[string, string]>();
const reviewStatus = ref<'approved' | 'rejected'>();
const appliedKeyword = ref('');
const appliedStatus = ref<'approved' | 'rejected'>();
const statusColors = { pending: 'warning', approved: 'success', rejected: 'error' } as const;
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const detail = ref<ProductSopDetail>();
const open = ref(false);
const detailLoading = ref(false);
const reviewing = ref(false);
const rejectOpen = ref(false);
const reason = ref('');
const previewOpen = ref(false);
const attachmentsOpen = ref(false);
const attachmentsOperation = ref<Operation>();
const attachmentsVersion = ref<ProductSopVersion>();
const attachmentsTrigger = ref<HTMLElement>();
const previewVersion = ref<ProductSopVersion>();
const previewSide = ref<0 | 1>(1);
const previewTrigger = ref<HTMLElement>();
const changes = computed(() => detail.value ? compareProductOperations(detail.value.base_version?.operations ?? [], detail.value.version.operations).filter((item) => item.changes.length) : []);
const changedIds = computed(() => new Set(changes.value.map((item) => item.id)));
const beforeChanges = computed(() => detail.value?.base_version?.operations.filter((item) => changedIds.value.has(item.id)) ?? []);
const afterChanges = computed(() => detail.value?.version.operations.filter((item) => changedIds.value.has(item.id)) ?? []);
const previewOperations = computed(() => previewSide.value === 0 ? beforeChanges.value : afterChanges.value);
const previewPositions = computed(() => Object.fromEntries(previewOperations.value.map((item) => [item.id, (previewVersion.value?.operations.findIndex((operation) => operation.id === item.id) ?? -1) + 1])));
const previewLabels = computed(() => Object.fromEntries(changes.value.map((item) => [item.id, item.before && item.after ? '修改' : item.before ? '删除' : '新增'])));
let requestId = 0;
let detailRequest = 0;
let returnFocus: HTMLElement | undefined;
const columns = computed(() => [
  { title: '产品', dataIndex: 'product_name', key: 'product_name' },
  { title: '版本', key: 'version', width: 90 },
  { title: '状态', key: 'status', width: 100 },
  { title: '提交时间', key: 'submitted_at' },
  ...(activeTab.value === 'reviewed' ? [{ title: '审核人', key: 'reviewer_name', width: 140 }, { title: '审核时间', key: 'reviewed_at' }] : []),
  { title: '工序数', key: 'operations', width: 90 },
  { title: '操作', key: 'action', width: 140 },
]);
async function refresh() {
  const id = ++requestId;
  loading.value = true;
  failed.value = false;
  try { const range = createdRangeQuery(appliedSubmittedRange.value); const result = await listProductSopReviews(activeTab.value === 'pending' ? 'pending' : appliedStatus.value ?? 'reviewed', page.value, pageSize.value, appliedKeyword.value, range.created_from, range.created_to); if (id === requestId) { rows.value = result.items; total.value = result.total; } }
  catch { if (id === requestId) failed.value = true; }
  finally { if (id === requestId) loading.value = false; }
}
async function inspect(row: ProductSopVersion, event: Event) {
  returnFocus = event.currentTarget as HTMLElement;
  const id = ++detailRequest;
  open.value = true;
  detail.value = undefined;
  detailLoading.value = true;
  try { const result = await getProductSopVersion(row.id); if (id === detailRequest && open.value) detail.value = result; }
  finally { if (id === detailRequest) detailLoading.value = false; }
}
function close() { if (previewOpen.value || attachmentsOpen.value || rejectOpen.value) return; detailRequest++; open.value = false; }
function afterOpenChange(visible: boolean) { if (!visible) returnFocus?.focus(); }
function previewAttachments(operation: Operation, side: number, trigger: HTMLElement) {
  attachmentsTrigger.value = trigger;
  const version = side === 0 ? detail.value?.base_version : detail.value?.version;
  if (!version) return;
  attachmentsOperation.value = operation;
  attachmentsVersion.value = version;
  attachmentsOpen.value = true;
}
function preview(version: ProductSopVersion, side: 0 | 1, event: Event) { previewTrigger.value = event.currentTarget as HTMLElement; previewVersion.value = version; previewSide.value = side; previewOpen.value = true; }
async function approve() {
  if (!detail.value || reviewing.value) return;
  reviewing.value = true;
  try {
    await approveProductSop(detail.value.version.id);
    message.success('产品版本已审核通过');
    close();
    await refresh();
  } finally { reviewing.value = false; }
}
async function reject() {
  if (!detail.value || reviewing.value) return;
  if (!reason.value.trim()) { message.warning('请填写驳回原因'); return; }
  reviewing.value = true;
  try {
    const rejected = await rejectProductSop(detail.value.version.id, reason.value.trim());
    rejectOpen.value = false;
    message.success(rejected.base_version_id ? '已驳回，工序已恢复至上一审核通过版本' : '已驳回；首次提交没有上一审核通过版本，工序保留为草稿');
    close();
    await refresh();
  } finally { reviewing.value = false; }
}
function search() { appliedKeyword.value = keyword.value.trim(); appliedStatus.value = reviewStatus.value; appliedSubmittedRange.value = submittedRange.value ? [...submittedRange.value] : undefined; page.value = 1; void refresh(); }
function resetSearch() { keyword.value = ''; reviewStatus.value = undefined; submittedRange.value = undefined; search(); }
function changeTab() { page.value = 1; rows.value = []; total.value = 0; void refresh(); }
function changePage(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current ?? 1; pageSize.value = pagination.pageSize ?? 20; void refresh();
}
onMounted(() => void refresh());
</script>

<template>
  <Page title="SOP审核">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-muted-foreground">按产品审核整套工序和作业指导书，审核通过后方可用于排产发布。</p>
      <Button :loading="loading" @click="refresh">刷新</Button>
    </div>
    <Tabs v-model:active-key="activeTab" @change="changeTab"><TabPane key="pending" tab="待审核" /><TabPane key="reviewed" tab="审核记录" /></Tabs>
    <Form layout="inline" class="mb-4 flex flex-wrap gap-y-3">
      <Form.Item label="产品名称"><Input v-model:value="keyword" allow-clear placeholder="请输入产品名称" :maxlength="100" @press-enter="search" /></Form.Item>
      <Form.Item label="提交时间"><DatePicker.RangePicker v-model:value="submittedRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" /></Form.Item>
      <Form.Item v-if="activeTab === 'reviewed'" label="状态"><Select v-model:value="reviewStatus" allow-clear placeholder="全部状态" class="w-36" :options="[{ label: '已审核', value: 'approved' }, { label: '已驳回', value: 'rejected' }]" /></Form.Item>
      <Form.Item><div class="flex gap-2"><Button type="primary" @click="search" :loading="loading">查询</Button><Button @click="resetSearch">重置</Button></div></Form.Item>
    </Form>
    <p v-if="failed" class="mb-4">审核列表加载失败，请点击刷新重试。</p>
    <Table :columns="columns" :data-source="rows" :loading="loading" :pagination="{ current: page, pageSize, total, showSizeChanger: true }" @change="changePage" :scroll="{ x: 760 }" row-key="id">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'version'">V{{ record.version }}</span>
        <Tag v-else-if="column.key === 'status'" :color="statusColors[(record as ProductSopVersion).status]">{{ productSopStatusText[(record as ProductSopVersion).status] }}</Tag>
        <span v-else-if="column.key === 'operations'">{{ record.operations.length }}</span>
        <span v-else-if="column.key === 'submitted_at'">{{ formatDateTime(record.submitted_at) }}</span>
        <span v-else-if="column.key === 'reviewer_name'">{{ record.reviewer_name || '—' }}</span>
        <span v-else-if="column.key === 'reviewed_at'">{{ record.reviewed_at ? formatDateTime(record.reviewed_at) : '—' }}</span>
        <Button v-else-if="column.key === 'action'" type="link" @click="inspect(record as ProductSopVersion, $event)">{{ record.status === 'pending' ? '对比审核' : '查看记录' }}</Button>
      </template>
    </Table>
    <Drawer :open="open" :mask-style="{ zIndex: 0 }" :content-wrapper-style="{ zIndex: 1 }" :keyboard="!previewOpen && !attachmentsOpen && !rejectOpen" :title="detail ? `${detail.version.product_name} · V${detail.version.version} ${productSopStatusText[detail.version.status]}` : '产品版本审核'" width="min(1180px, 100vw)" :z-index="1100" @close="close" @after-open-change="afterOpenChange">
      <Spin :spinning="detailLoading">
        <template v-if="detail">
          <div class="mb-4 flex flex-wrap gap-2">
            <Button v-if="detail.base_version && beforeChanges.length" @click="preview(detail.base_version, 0, $event)">预览变更前（{{ beforeChanges.length }} 道）</Button>
            <Button v-if="afterChanges.length" @click="preview(detail.version, 1, $event)">预览本次变更（{{ afterChanges.length }} 道）</Button>
          </div>
          <p v-if="!detail.base_version" class="mb-4 text-sm text-muted-foreground">首次提交，没有已审核的原版本。</p>
          <ProductSopComparison :before="detail.base_version?.operations ?? []" :after="detail.version.operations" @preview="previewAttachments" />
          <p v-if="detail.version.review_note" class="mt-4 whitespace-pre-wrap">审核意见：{{ detail.version.review_note }}</p>
        </template>
        <Empty v-else-if="!detailLoading" description="版本加载失败，请关闭后重试" />
      </Spin>
      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <Button @click="close">关闭</Button>
          <template v-if="detail?.version.status === 'pending'">
            <Button v-access:code="'esop:sop:review'" :disabled="reviewing" danger @click="reason = ''; rejectOpen = true">驳回</Button>
            <Button v-access:code="'esop:sop:review'" :loading="reviewing" type="primary" @click="approve">审核通过</Button>
          </template>
        </div>
      </template>
      <OperationAttachmentsPreview v-if="attachmentsOperation && attachmentsVersion" v-model:open="attachmentsOpen" :product-id="attachmentsVersion.product_id" :title="`${attachmentsOperation.name} · V${attachmentsVersion.version} 附件预览`" :operations="[attachmentsOperation]" :version-id="attachmentsVersion.id" :trigger-element="attachmentsTrigger" />
      <ProductSopPreview v-if="previewVersion" v-model:open="previewOpen" :product-id="previewVersion.product_id" :title="`${previewVersion.product_name} · V${previewVersion.version} ${previewSide === 0 ? '变更前' : '本次变更'}预览`" :operations="previewOperations" :operation-positions="previewPositions" :operation-labels="previewLabels" :version-id="previewVersion.id" :trigger-element="previewTrigger" />
      <Modal :open="rejectOpen" title="驳回产品版本" :keyboard="true" :z-index="3200" ok-text="确认驳回" cancel-text="取消" :confirm-loading="reviewing" @cancel="rejectOpen = false" @ok="reject">
        <Form layout="vertical"><Form.Item label="驳回原因" required><Input.TextArea v-model:value="reason" :rows="4" :maxlength="500" placeholder="说明需要修改的内容" /></Form.Item></Form>
      </Modal>
    </Drawer>
  </Page>
</template>
