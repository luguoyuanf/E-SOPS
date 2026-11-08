<script lang="ts" setup>
import type { ProductionReport, ReportFilterOption } from '../../api/operations';

import { computed, nextTick, reactive, ref } from 'vue';

import { Button, Drawer, Form, Input, InputNumber, message, Select } from 'ant-design-vue';

import { correctReport } from '../../api/operations';

const props = defineProps<{ staff: ReportFilterOption[] }>();
const emit = defineEmits<{ success: [] }>();
const open = ref(false);
const saving = ref(false);
const staffOpen = ref(false);
const target = ref<ProductionReport>();
const form = reactive({ staff_user_id: '', input_qty: 0, good_qty: 0, defect_qty: 0, reason: '' });
let trigger: HTMLElement | null = null;
const staffOptions = computed(() => {
  const result: (ReportFilterOption & { disabled?: boolean })[] = [...props.staff];
  const row = target.value;
  if (row && !result.some((option) => option.value === row.staff_user_id)) result.unshift({ value: row.staff_user_id, label: row.staff_name, disabled: true });
  return result;
});

function show(row: ProductionReport) {
  if (saving.value) return;
  trigger = document.activeElement as HTMLElement;
  target.value = row;
  Object.assign(form, { staff_user_id: row.staff_user_id, input_qty: row.input_qty, good_qty: row.good_qty, defect_qty: row.defect_qty, reason: '' });
  staffOpen.value = false;
  open.value = true;
}

function close() { staffOpen.value = false; open.value = false; }
function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && staffOpen.value) { staffOpen.value = false; event.stopPropagation(); }
}
async function restoreFocus(visible: boolean) {
  if (!visible) {
    await nextTick();
    const button = trigger?.isConnected ? trigger : document.querySelector<HTMLElement>(`[data-report-edit="${target.value?.id}"]`);
    button?.focus();
  }
}
async function save() {
  const row = target.value;
  if (!row || saving.value) return;
  if (!form.reason.trim()) { message.warning('请填写修改原因'); return; }
  if (!form.staff_user_id || ![form.input_qty, form.good_qty, form.defect_qty].every((value) => Number.isInteger(value) && value >= 0)) {
    message.warning('请选择员工并填写非负整数数量'); return;
  }
  if (form.staff_user_id === row.staff_user_id && form.input_qty === row.input_qty && form.good_qty === row.good_qty && form.defect_qty === row.defect_qty) { message.warning('未修改报工内容'); return; }
  if (!Number.isInteger(form.input_qty) || form.input_qty <= 0) { message.warning('请填写大于零的投入数量'); return; }
  if (form.good_qty + form.defect_qty !== form.input_qty) { message.warning('良品数量与不良数量之和必须等于投入数量'); return; }
  saving.value = true;
  try {
    await correctReport(row.id, { ...form, reason: form.reason.trim(), expected_revision: row.revision });
    close();
    message.success('报工已修改，修改记录已保存');
    emit('success');
  } finally { saving.value = false; }
}
defineExpose({ show });
</script>

<template>
  <Drawer :open="open" title="修改报工" width="min(560px, 100vw)" :keyboard="true" @close="close" @after-open-change="restoreFocus">
    <div v-if="target" class="mb-4 text-muted-foreground">{{ target.order_code }} · {{ target.station_position }} 号工位 · {{ target.sop_title }} V{{ target.sop_version }}</div>
    <Form name="report-correction" :model="form" layout="vertical" :disabled="saving" @keydown.capture="handleEscape">
      <Form.Item label="报工员工" name="staff_user_id" required><Select v-model:value="form.staff_user_id" :open="staffOpen" :options="staffOptions" @dropdown-visible-change="(visible) => { staffOpen = visible; }" /></Form.Item>
      <div class="grid grid-cols-1 gap-x-4 sm:grid-cols-3">
        <Form.Item label="投入数量" name="input_qty" required><InputNumber v-model:value="form.input_qty" :min="0" :precision="0" :style="{ width: '100%' }" /></Form.Item>
        <Form.Item label="良品数量" name="good_qty" required><InputNumber v-model:value="form.good_qty" :min="0" :precision="0" :style="{ width: '100%' }" /></Form.Item>
        <Form.Item label="不良数量" name="defect_qty" required><InputNumber v-model:value="form.defect_qty" :min="0" :precision="0" :style="{ width: '100%' }" /></Form.Item>
      </div>
      <Form.Item label="修改原因" name="reason" required><Input.TextArea v-model:value="form.reason" :maxlength="500" :rows="4" show-count placeholder="请说明本次修改原因" /></Form.Item>
    </Form>
    <template #footer><div class="flex justify-end gap-2"><Button @click="close">取消</Button><Button type="primary" :loading="saving" @click="save">保存修改</Button></div></template>
  </Drawer>
</template>
