<script lang="ts" setup>
import type { BroadcastInput, BroadcastPosition, BroadcastRecord, PublicationFilters } from '../../api/broadcast';
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { formatDateTime } from '@vben/utils';
import { Button, Card, Dropdown, Form, Input, InputNumber, Menu, message, Modal, Switch, Tag } from 'ant-design-vue';
import { SelectableTable as Table } from '#/components/selectable-table';
import { deleteBroadcastRecord, listBroadcastRecords, saveBroadcastRecord } from '../../api/broadcast';
import PublicationSearch from './publication-filters.vue';
const props = defineProps<{ position: BroadcastPosition }>();
const title = computed(() => props.position === 'top' ? '顶部广播' : '底部广播');
const initial = (): BroadcastInput => ({ content: '', font_size: 24, background_color: '#12304A', font_color: '#FFFFFF', is_active: true });
const form = reactive(initial());
const editingId = ref<string>();
const filters = ref<PublicationFilters>({ keyword: '' });
const rows = ref<BroadcastRecord[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const saving = ref(false);
const busyId = ref<string>();
const columns = [{ title: '广播内容', dataIndex: 'content', key: 'content', width: 360 }, { title: '发布时间', key: 'created_at', width: 180 }, { title: '更新时间', key: 'updated_at', width: 180 }, { title: '状态', key: 'status', width: 100 }, { title: '操作', key: 'actions', width: 120 }];
async function refresh() {
  loading.value = true;
  try {
    const result = await listBroadcastRecords(props.position, filters.value, page.value, pageSize.value);
    rows.value = result.items; total.value = result.total;
    if (!rows.value.length && page.value > 1) { page.value--; await refresh(); }
  } finally { loading.value = false; }
}
function search() { page.value = 1; void refresh(); }
function changePage(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current ?? 1; pageSize.value = pagination.pageSize ?? 20; void refresh();
}
function reset() { editingId.value = undefined; Object.assign(form, initial()); }
function edit(row: BroadcastRecord) {
  editingId.value = row.id;
  Object.assign(form, { content: row.content, font_size: row.font_size, background_color: row.background_color, font_color: row.font_color, is_active: row.is_active });
  void nextTick(() => document.querySelector<HTMLTextAreaElement>(`[data-ticker-editor="${props.position}"]`)?.focus());
}
async function save() {
  if (!form.content.trim()) return message.warning('请填写广播内容');
  saving.value = true;
  try { await saveBroadcastRecord(props.position, { ...form, content: form.content.trim() }, editingId.value); reset(); page.value = 1; await refresh(); message.success('广播记录已保存'); }
  finally { saving.value = false; }
}
async function toggle(row: BroadcastRecord) {
  busyId.value = row.id;
  try { await saveBroadcastRecord(props.position, { ...row, is_active: !row.is_active }, row.id); await refresh(); if (editingId.value === row.id) form.is_active = !row.is_active; }
  finally { busyId.value = undefined; }
}
function remove(row: BroadcastRecord) {
  Modal.confirm({ title: '删除广播记录', content: '删除后不能恢复；运行中的内容将从终端撤下。', keyboard: true,
    afterClose: () => void nextTick(() => document.querySelector<HTMLButtonElement>(`[data-ticker-action="${row.id}"]`)?.focus()),
    onOk: async () => {
      busyId.value = row.id;
      try { await deleteBroadcastRecord(props.position, row.id); if (editingId.value === row.id) reset(); await refresh(); }
      finally { busyId.value = undefined; }
    } });
}
onMounted(refresh);
</script>
<template>
  <Card v-access:code="'esop:broadcast:manage'" :title="`${editingId ? '编辑' : '发布'}${title}`" class="mb-5">
    <p class="mb-4 text-sm text-muted-foreground">同一位置只显示一条广播；启动另一条时，自动暂停原内容。保存后的记录可在下方查询和管理。</p>
    <Form layout="vertical">
      <Form.Item label="滚动内容" required><Input.TextArea v-model:value="form.content" :data-ticker-editor="position" :maxlength="500" :rows="3" show-count placeholder="输入终端展示的广播内容" /></Form.Item>
      <div class="grid gap-4 sm:grid-cols-3">
        <Form.Item label="字号（px）"><InputNumber v-model:value="form.font_size" :min="12" :max="72" :precision="0" class="w-full" /></Form.Item>
        <Form.Item label="背景颜色"><input v-model="form.background_color" type="color" class="h-9 w-full cursor-pointer" /></Form.Item>
        <Form.Item label="字体颜色"><input v-model="form.font_color" type="color" class="h-9 w-full cursor-pointer" /></Form.Item>
      </div>
      <div class="mb-4 flex items-center gap-3"><span>发布后启动</span><Switch v-model:checked="form.is_active" /></div>
      <div class="mb-4 overflow-hidden rounded px-4 py-3" :style="{ backgroundColor: form.background_color, color: form.font_color, fontSize: `${form.font_size}px` }" aria-label="广播文字预览">{{ form.content || `${title}预览` }}</div>
      <div class="flex justify-end gap-3"><Button v-if="editingId" @click="reset">取消编辑</Button><Button type="primary" :loading="saving" @click="save">{{ editingId ? '保存修改' : '发布广播' }}</Button></div>
    </Form>
  </Card>
  <Card :title="`${title}发布记录`">
    <PublicationSearch v-model="filters" :loading="loading" placeholder="搜索广播内容" @search="search" />
    <Table :data-source="rows" :columns="columns" :loading="loading" row-key="id" :scroll="{ x: 960 }" :pagination="{ current: page, pageSize, total, showSizeChanger: true, showTotal: (n: number) => `共 ${n} 条` }" @change="changePage">
      <template #emptyText>暂无广播发布记录</template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'content'"><div class="whitespace-pre-wrap break-all">{{ record.content }}</div></template>
        <template v-else-if="column.key === 'created_at' || column.key === 'updated_at'">{{ formatDateTime(record[column.key]) }}</template>
        <template v-else-if="column.key === 'status'"><Tag :color="record.is_active ? 'success' : 'warning'">{{ record.is_active ? '运行中' : '已暂停' }}</Tag></template>
        <template v-else-if="column.key === 'actions'"><Dropdown v-access:code="'esop:broadcast:manage'" :trigger="['click']"><Button size="small" :loading="busyId === record.id" :data-ticker-action="record.id">更多操作</Button><template #overlay><Menu><Menu.Item @click="toggle(record as BroadcastRecord)">{{ record.is_active ? '暂停' : '启动' }}</Menu.Item><Menu.Item @click="edit(record as BroadcastRecord)">编辑</Menu.Item><Menu.Item danger @click="remove(record as BroadcastRecord)">删除</Menu.Item></Menu></template></Dropdown></template>
      </template>
    </Table>
  </Card>
</template>
