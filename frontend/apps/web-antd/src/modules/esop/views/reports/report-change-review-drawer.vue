<script lang="ts" setup>
import type { ReportChange } from '../../api/operations';
import { nextTick, ref } from 'vue';
import { formatDateTime } from '@vben/utils';
import { Button, Drawer, Empty, Input, Modal, Pagination, Select, Spin, message } from 'ant-design-vue';
import { listReportChanges, reviewReportChange } from '../../api/operations';

const emit = defineEmits<{ success: [] }>();
const open = ref(false);
const loading = ref(false);
const rows = ref<ReportChange[]>([]);
const total = ref(0);
const page = ref(1);
const status = ref('pending');
const target = ref<ReportChange>();
const approving = ref(true);
const reviewing = ref(false);
const note = ref('');
const reviewOpen = ref(false);
let trigger: HTMLElement | null = null;
let reviewTrigger: HTMLElement | null = null;
const fields = [{ label: '投入', key: 'input_qty' }, { label: '良品', key: 'good_qty' }, { label: '不良', key: 'defect_qty' }];
async function load() {
  loading.value = true;
  try {
    const result = await listReportChanges({ status: status.value, page: page.value, page_size: 20 });
    rows.value = result.items;
    total.value = result.total;
  } finally { loading.value = false; }
}
async function show() {
  trigger = document.activeElement as HTMLElement;
  open.value = true;
  page.value = 1;
  await load();
}
function confirm(row: ReportChange, approve: boolean, event: MouseEvent) {
  reviewTrigger = event.currentTarget as HTMLElement;
  target.value = row;
  approving.value = approve;
  note.value = '';
  reviewOpen.value = true;
}
async function review() {
  if (!target.value || reviewing.value) return;
  if (!approving.value && !note.value.trim()) { message.warning('请填写退回原因'); return; }
  reviewing.value = true;
  try {
    await reviewReportChange(target.value.id, { approve: approving.value, note: note.value.trim() });
    reviewOpen.value = false;
    message.success(approving.value ? (target.value.kind === 'delete' ? '审核通过，报工已删除并回滚统计' : '审核通过，修改已生效') : '申请已退回，原数据保持有效');
    emit('success');
    await load();
  } finally { reviewing.value = false; }
}
function close() { if (!reviewing.value && !reviewOpen.value) open.value = false; }
async function restoreFocus(visible: boolean) { if (!visible) { await nextTick(); trigger?.focus(); } }
async function restoreReviewFocus() { await nextTick(); if (reviewTrigger?.isConnected) reviewTrigger.focus(); }
defineExpose({ show });
</script>
<template>
  <Drawer :open="open" title="报工修改/删除审核" width="min(920px, 100vw)" :keyboard="true" :mask-closable="!reviewOpen" @close="close" @after-open-change="restoreFocus">
    <div class="mb-4 flex items-center gap-3">
      <Select v-model:value="status" aria-label="审核状态" :options="[{value:'pending',label:'待审核'},{value:'approved',label:'已通过'},{value:'rejected',label:'已退回'}]" style="width:140px" @change="page = 1; load()" />
      <Button :loading="loading" @click="load">刷新</Button>
      <span class="text-muted-foreground">审核修改或删除申请，新增报工提交后立即生效。</span>
    </div>
    <Spin :spinning="loading">
      <Empty v-if="!rows.length" description="暂无审核申请" />
      <article v-for="row in rows" :key="row.id" class="mb-4 rounded-lg border p-4">
        <div class="mb-2 flex flex-wrap justify-between gap-2"><strong>{{ row.order_code }} · {{ row.sop_title }}</strong><span>{{ row.requested_by_name }} · {{ formatDateTime(row.requested_at) }}</span></div>
        <div class="my-3 flex flex-wrap gap-8"><strong>{{ row.kind === 'delete' ? '删除申请' : '修改申请' }}</strong><div v-for="field in fields" :key="field.key"><span class="text-muted-foreground">{{ field.label }}：</span>{{ row.before[field.key] }}<template v-if="row.kind !== 'delete'"> → <strong>{{ row.after[field.key] }}</strong></template></div></div>
        <p v-if="row.kind === 'delete'" class="mb-3">审核通过后删除本条报工，回滚上述数量及完成进度；保留审批追溯。</p>
        <p class="mb-3 whitespace-pre-wrap">{{ row.kind === 'delete' ? '删除原因' : '修改原因' }}：{{ row.reason }}</p>
        <div v-if="status === 'pending'" class="flex justify-end gap-2"><Button @click="confirm(row, false, $event)">退回申请</Button><Button type="primary" @click="confirm(row, true, $event)">审核通过</Button></div>
        <p v-else class="text-muted-foreground">{{ status === 'approved' ? '已通过' : '已退回' }} · {{ row.reviewed_by_name }}{{ row.review_note ? ` · ${row.review_note}` : '' }}</p>
      </article>
    </Spin>
    <Pagination v-model:current="page" :total="total" :page-size="20" :show-size-changer="false" @change="load" />
    <Modal v-model:open="reviewOpen" :title="approving ? '确认审核通过' : '退回申请'" :keyboard="true" :confirm-loading="reviewing" :mask-closable="!reviewing" :cancel-button-props="{ disabled: reviewing }" :ok-text="approving ? '确认通过' : '确认退回'" cancel-text="取消" @ok="review" @after-close="restoreReviewFocus">
      <p class="mb-4">{{ approving ? (target?.kind === 'delete' ? '通过后删除报工并回滚统计，保留审批追溯。' : '通过后将替换原报工数量，并保留修改记录。') : '退回后原报工数据保持有效。' }}</p>
      <Input.TextArea v-model:value="note" aria-label="审核意见" :disabled="reviewing" :maxlength="500" :rows="3" :placeholder="approving ? '审核意见（选填）' : '请填写退回原因'" />
    </Modal>
  </Drawer>
</template>
