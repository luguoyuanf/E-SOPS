<script lang="ts" setup>
import type { WebReportInput, WebReportOptions } from '../../api/operations';

import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';

import { Alert, Button, Drawer, Form, InputNumber, message, Select, Spin } from 'ant-design-vue';

import { getWebReportOptions, submitWebReport } from '../../api/operations';

const emit = defineEmits<{ success: [] }>();
const open = ref(false);
const loading = ref(false);
const saving = ref(false);
const openSelect = ref('');
const options = ref<WebReportOptions>({ can_select_staff: false, current_user_id: '', staff: [], tasks: [] });
const form = reactive({ release_id: '', station_id: '', staff_user_id: '', input_qty: 0, good_qty: 0, defect_qty: 0 });
let trigger: HTMLElement | null = null;
let pending: WebReportInput | undefined;
const releaseOptions = computed(() => [...new Map(options.value.tasks.map((task) => [task.release_id, {
  value: task.release_id, label: `${task.plan_code} · ${task.order_code} · ${task.line_name}`,
}])).values()]);
const stationOptions = computed(() => [...new Map(options.value.tasks.filter((task) => task.release_id === form.release_id).map((task) => [task.station_id, {
  value: task.station_id, label: task.station_name,
}])).values()]);
const selectedTask = computed(() => options.value.tasks.find((task) => task.release_id === form.release_id && task.station_id === form.station_id));
watch(() => form.release_id, () => { form.station_id = ''; });

async function loadOptions() {
  loading.value = true;
  try {
    options.value = await getWebReportOptions();
    if (!form.staff_user_id || !options.value.can_select_staff) form.staff_user_id = options.value.current_user_id;
  } finally {
    loading.value = false;
  }
}

async function show() {
  if (saving.value) return;
  trigger = document.activeElement as HTMLElement;
  Object.assign(form, { release_id: '', station_id: '', staff_user_id: options.value.current_user_id, input_qty: 0, good_qty: 0, defect_qty: 0 });
  pending = undefined;
  openSelect.value = '';
  open.value = true;
  await loadOptions();
}

function selectVisibility(name: string, visible: boolean) {
  if (visible) openSelect.value = name;
  else if (openSelect.value === name) openSelect.value = '';
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && openSelect.value) {
    openSelect.value = '';
    event.stopPropagation();
  }
}

function close() {
  openSelect.value = '';
  open.value = false;
}

async function restoreFocus(visible: boolean) {
  if (!visible) { await nextTick(); trigger?.focus(); }
}

async function save() {
  if (saving.value) return;
  const task = selectedTask.value;
  if (!task || !form.staff_user_id) { message.warning('请选择排产、工位和员工'); return; }
  if (![form.input_qty, form.good_qty, form.defect_qty].every((value) => Number.isInteger(value) && value >= 0)) {
    message.warning('请填写非负整数数量'); return;
  }
  if (!Number.isInteger(form.input_qty) || form.input_qty <= 0) { message.warning('请填写大于零的投入数量'); return; }
  if (form.good_qty + form.defect_qty !== form.input_qty) { message.warning('良品数量与不良数量之和必须等于投入数量'); return; }
  const data = { ...form, operation_id: task.operation_id, sop_id: task.sop_id };
  // Reuse the key when retrying the same payload after an uncertain network outcome.
  if (!pending || JSON.stringify({ ...pending, request_id: undefined }) !== JSON.stringify({ ...data, request_id: undefined })) pending = { ...data, request_id: crypto.randomUUID() };
  saving.value = true;
  try {
    await submitWebReport(pending);
    open.value = false;
    pending = undefined;
    message.success('报工已保存');
    emit('success');
    await loadOptions();
  } finally {
    saving.value = false;
  }
}

onMounted(loadOptions);
defineExpose({ show });
</script>

<template>
  <Drawer :open="open" title="新增报工" width="min(560px, 100vw)" :keyboard="true" @close="close" @after-open-change="restoreFocus">
    <Spin :spinning="loading">
      <Alert v-if="!loading && !options.tasks.length" class="mb-4" type="info" show-icon message="暂无可报工排产，请先启动排产并分配工位与工序。" />
      <Form :model="form" layout="vertical" :disabled="saving || loading" @keydown.capture="handleEscape">
        <Form.Item label="排产任务" name="release_id" required><Select v-model:value="form.release_id" :open="openSelect === 'release_id'" @dropdown-visible-change="(visible) => selectVisibility('release_id', visible)" :options="releaseOptions" placeholder="选择运行中的排产任务" /></Form.Item>
        <Form.Item label="工位" name="station_id" required><Select v-model:value="form.station_id" :open="openSelect === 'station_id'" @dropdown-visible-change="(visible) => selectVisibility('station_id', visible)" :disabled="!form.release_id" :options="stationOptions" placeholder="选择工位" /></Form.Item>
        <Form.Item label="工序"><span>{{ selectedTask?.operation_name || '选择工位后自动关联' }}</span></Form.Item>
        <Form.Item label="当前 SOP"><span>{{ selectedTask ? `${selectedTask.sop_title} V${selectedTask.sop_version}` : '选择工位后显示' }}</span></Form.Item>
        <Form.Item label="报工员工" name="staff_user_id" required><Select v-model:value="form.staff_user_id" :open="openSelect === 'staff_user_id'" @dropdown-visible-change="(visible) => selectVisibility('staff_user_id', visible)" :disabled="!options.can_select_staff" :options="options.staff" /></Form.Item>
        <div class="grid grid-cols-1 gap-x-4 sm:grid-cols-3">
          <Form.Item label="投入数量" name="input_qty" required><InputNumber v-model:value="form.input_qty" :min="0" :precision="0" class="w-full" /></Form.Item>
          <Form.Item label="良品数量" name="good_qty" required><InputNumber v-model:value="form.good_qty" :min="0" :precision="0" class="w-full" /></Form.Item>
          <Form.Item label="不良数量" name="defect_qty" required><InputNumber v-model:value="form.defect_qty" :min="0" :precision="0" class="w-full" /></Form.Item>
        </div>
      </Form>
    </Spin>
    <template #footer>
      <div class="flex justify-end gap-2">
        <Button @click="close">取消</Button>
        <Button type="primary" :loading="saving" :disabled="loading || !options.tasks.length" @click="save">提交报工</Button>
      </div>
    </template>
  </Drawer>
</template>
