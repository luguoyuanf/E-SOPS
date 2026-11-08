<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { Advertisement, AdvertisementInput, PublicationFilters } from '../../api/broadcast';
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { formatDateTime } from '@vben/utils';
import { Button, Card, DatePicker, Drawer, Dropdown, Empty, Form, Input, InputNumber, Menu, message, Modal, Select, Switch, Tag, TimePicker } from 'ant-design-vue';
import { deleteAdvertisement, listAdvertisements, saveAdvertisement, uploadAdvertisementFile } from '../../api/broadcast';
import AdvertisementPreview from './advertisement-preview.vue';
import PublicationSearch from './publication-filters.vue';

const layouts = [{ value: 'fullscreen', label: '全屏广告' }, { value: 'left', label: '左右分屏 · 广告在左' }, { value: 'right', label: '左右分屏 · 广告在右' }, { value: 'top', label: '上下分屏 · 广告在上' }, { value: 'bottom', label: '上下分屏 · 广告在下' }];
const initial = (): AdvertisementInput => ({ title: '', layout: 'fullscreen', playback: 'continuous', interval_minutes: 30, starts_at: null, ends_at: null, daily_start: null, daily_end: null, media: [], is_active: true });
const rows = ref<Advertisement[]>([]);
const filters = ref<PublicationFilters>({ keyword: '' });
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const schedulePicker = ref<string>();
function dismissSchedulePicker(event: KeyboardEvent) {
  if (!schedulePicker.value) return;
  schedulePicker.value = undefined; event.stopPropagation(); event.preventDefault();
}
function pickerChanged(key: string, value: boolean) { schedulePicker.value = value ? key : undefined; }
function pickerContainer(trigger: HTMLElement) { return trigger.parentElement!; }
function search() { page.value = 1; void refresh(); }
function changePage(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current ?? 1; pageSize.value = pagination.pageSize ?? 20; void refresh();
}
const form = reactive(initial());
const open = ref(false);
const previewOpen = ref(false);
const previewTask = ref<AdvertisementInput>();
let previewOrigin: 'editor' | string = 'editor';
function preview(row?: Advertisement) {
  const task = row ?? form;
  if (!task.media.length || task.media.some((m) => m.kind === 'text' && !m.content.trim())) return message.warning('请先添加并填写预览素材');
  previewTask.value = JSON.parse(JSON.stringify(task));
  previewOrigin = row?.id ?? 'editor';
  previewOpen.value = true;
}
function closeEditor() { if (!previewOpen.value && !schedulePicker.value) open.value = false; }
function previewClosed() {
  if (previewOrigin === 'editor') void nextTick(() => document.querySelector<HTMLButtonElement>('[data-ad-preview]')?.focus());
  else restoreFocus(false, previewOrigin);
}
const editingId = ref<string>();
const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const busyId = ref<string>();
const fileInput = ref<HTMLInputElement>();
let editorSession = 0;
watch(open, (value) => { if (!value) editorSession++; });
const starts = ref<string>();
const ends = ref<string>();
const dailyStart = computed({ get: () => form.daily_start ?? undefined, set: (value: string | undefined) => { form.daily_start = value ?? null; } });
const dailyEnd = computed({ get: () => form.daily_end ?? undefined, set: (value: string | undefined) => { form.daily_end = value ?? null; } });
const columns = [{ title: '广告任务', dataIndex: 'title', key: 'title' }, { title: '播放安排', key: 'schedule' }, { title: '屏幕布局', key: 'layout' }, { title: '发布时间', key: 'created_at', width: 180 }, { title: '状态', key: 'status', width: 100 }, { title: '操作', key: 'actions', width: 120 }];
const previewStyle = computed(() => ({ flexDirection: ['top', 'bottom'].includes(form.layout) ? 'column' as const : 'row' as const }));
function localInput(value: null | string) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}
async function refresh() {
  loading.value = true;
  try {
    const result = await listAdvertisements(filters.value, page.value, pageSize.value);
    rows.value = result.items; total.value = result.total;
    if (!rows.value.length && page.value > 1) { page.value--; await refresh(); }
  } finally { loading.value = false; }
}
function edit(row?: Advertisement) {
  editorSession++;
  Object.assign(form, row ? JSON.parse(JSON.stringify(row)) : initial());
  editingId.value = row?.id;
  starts.value = localInput(form.starts_at);
  ends.value = localInput(form.ends_at);
  schedulePicker.value = undefined;
  open.value = true;
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  const session = editorSession;
  uploading.value = true;
  try {
    for (const file of files) {
      if (form.media.length >= 50) { message.warning('每个任务最多 50 个素材'); break; }
      const stored = await uploadAdvertisementFile(file);
      if (session !== editorSession) return;
      form.media.push({ kind: file.type.startsWith('video/') ? 'video' : 'image', file_id: stored.id, name: file.name, content: '', duration_seconds: 10 });
    }
  } finally { uploading.value = false; input.value = ''; }
}
function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= form.media.length) return;
  const item = form.media.splice(index, 1)[0];
  if (item) form.media.splice(target, 0, item);
}
async function save() {
  if (!form.title.trim() || !form.media.length) return message.warning('请填写广告名称并添加素材');
  if (form.media.some((m) => m.kind === 'text' && !m.content.trim())) return message.warning('请填写文字素材内容');
  const start = starts.value ? new Date(starts.value).toISOString() : null;
  const end = ends.value ? new Date(ends.value).toISOString() : null;
  if (end && new Date(end) <= new Date(start ?? Date.now())) return message.warning('结束时间必须晚于开始时间');
  saving.value = true;
  try {
    await saveAdvertisement({ ...form, title: form.title.trim(), starts_at: start, ends_at: end, daily_start: form.daily_start || null, daily_end: form.daily_end || null }, editingId.value);
    open.value = false;
    await refresh();
    message.success('广告任务已保存，终端下次同步后生效');
  } finally { saving.value = false; }
}
async function toggle(row: Advertisement) {
  busyId.value = row.id;
  try { await saveAdvertisement({ ...row, is_active: !row.is_active }, row.id); await refresh(); }
  finally { busyId.value = undefined; }
}
function restoreFocus(isOpen = false, id = editingId.value) {
  if (isOpen) return;
  const selector = id ? `[data-ad-action="${id}"]` : '[data-ad-create]';
  void nextTick(() => document.querySelector<HTMLButtonElement>(selector)?.focus());
}
function confirmRemove(row: Advertisement) {
  Modal.confirm({ title: `删除广告任务“${row.title}”？`, keyboard: true, afterClose: () => restoreFocus(false, row.id), onOk: () => remove(row) });
}
async function remove(row: Advertisement) {
  busyId.value = row.id;
  try { await deleteAdvertisement(row.id); await refresh(); } finally { busyId.value = undefined; }
}
function status(row: Advertisement) {
  if (!row.is_active) return '已暂停';
  if (row.ends_at && new Date(row.ends_at).getTime() <= Date.now()) return '已结束';
  if (row.starts_at && new Date(row.starts_at).getTime() > Date.now()) return '待开始';
  return '已发布';
}
onMounted(refresh);
</script>
<template>
  <Card title="发布多媒体广告" class="mb-5">
    <template #extra><Button v-access:code="'esop:broadcast:manage'" type="primary" data-ad-create @click="edit()">新增广告任务</Button></template>
    <p class="mb-4 text-sm text-muted-foreground">发布到本租户已绑定工位的终端；多个任务依创建顺序排队。全屏广告结束后自动恢复当前 SOP。</p>
  </Card>
  <Card title="多媒体广告发布记录">
    <PublicationSearch v-model="filters" :loading="loading" placeholder="搜索广告名称" :status-options="[{ value: 'active', label: '运行中' }, { value: 'paused', label: '已暂停' }, { value: 'scheduled', label: '待开始' }, { value: 'ended', label: '已结束' }]" @search="search" />
    <Table :data-source="rows" :columns="columns" :loading="loading" row-key="id" :scroll="{ x: 850 }" :pagination="{ current: page, pageSize, total, showSizeChanger: true, showTotal: (n: number) => `共 ${n} 条` }" @change="changePage">
      <template #emptyText><Empty description="暂无广告任务，可先添加文字、图片或视频" /></template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'title'"><div>{{ record.title }}</div><span class="text-xs text-muted-foreground">{{ record.media.length }} 个素材</span></template>
        <template v-else-if="column.key === 'schedule'">
          <div>{{ record.playback === 'interval' ? `每隔 ${record.interval_minutes} 分钟完整播放一轮` : '持续轮播' }}</div>
          <div class="text-xs text-muted-foreground">{{ record.starts_at ? formatDateTime(record.starts_at) : '立即开始' }} → {{ record.ends_at ? formatDateTime(record.ends_at) : '一直显示' }}</div>
          <div v-if="record.daily_start" class="text-xs text-muted-foreground">每日 {{ record.daily_start }}–{{ record.daily_end }}（北京时间）</div>
        </template>
        <template v-else-if="column.key === 'layout'">{{ layouts.find((item) => item.value === record.layout)?.label }}</template>
        <template v-else-if="column.key === 'created_at'">{{ formatDateTime(record.created_at) }}</template>
        <template v-else-if="column.key === 'status'"><Tag :color="record.is_active ? (status(record as Advertisement) === '待开始' ? 'processing' : status(record as Advertisement) === '已结束' ? 'default' : 'success') : 'warning'">{{ status(record as Advertisement) }}</Tag></template>
        <template v-else-if="column.key === 'actions'">
          <Dropdown :trigger="['click']">
            <Button size="small" :data-ad-action="record.id" :loading="busyId === record.id">更多操作</Button>
            <template #overlay><Menu>
              <Menu.Item @click="preview(record as Advertisement)">模拟预览</Menu.Item>
              <Menu.Item v-access:code="'esop:broadcast:manage'" @click="edit(record as Advertisement)">编辑</Menu.Item>
              <Menu.Item v-access:code="'esop:broadcast:manage'" @click="toggle(record as Advertisement)">{{ record.is_active ? '暂停' : '启动' }}</Menu.Item>
              <Menu.Item v-access:code="'esop:broadcast:manage'" danger @click="confirmRemove(record as Advertisement)">删除</Menu.Item>
            </Menu></template>
          </Dropdown>
        </template>
      </template>
    </Table>
  </Card>
  <Drawer :open="open" @close="closeEditor" :title="editingId ? '编辑广告任务' : '新增广告任务'" width="min(760px, 100vw)" :keyboard="true" :mask-closable="false" :destroy-on-close="true" @after-open-change="restoreFocus">
    <Form layout="vertical">
      <Form.Item label="广告名称" required><Input v-model:value="form.title" :maxlength="100" placeholder="如：车间安全宣传" /></Form.Item>
      <div class="grid gap-4 sm:grid-cols-2" @keydown.esc.capture="dismissSchedulePicker">
        <Form.Item label="开始时间"><DatePicker v-model:value="starts" show-time value-format="YYYY-MM-DDTHH:mm" format="YYYY-MM-DD HH:mm" class="w-full" placeholder="选择开始日期与时间" :open="schedulePicker === 'start'" :get-popup-container="pickerContainer" @open-change="pickerChanged('start', $event)" /><div class="text-xs text-muted-foreground">留空立即开始，使用当前浏览器时区</div></Form.Item>
        <Form.Item label="结束时间"><DatePicker v-model:value="ends" show-time value-format="YYYY-MM-DDTHH:mm" format="YYYY-MM-DD HH:mm" class="w-full" placeholder="选择结束日期与时间" :open="schedulePicker === 'end'" :get-popup-container="pickerContainer" @open-change="pickerChanged('end', $event)" /><div class="text-xs text-muted-foreground">留空一直显示，直到手动停止</div></Form.Item>
        <Form.Item label="每日开始（可选，北京时间）"><TimePicker v-model:value="dailyStart" value-format="HH:mm" format="HH:mm" class="w-full" placeholder="选择每日开始时间" :open="schedulePicker === 'daily-start'" :get-popup-container="pickerContainer" @open-change="pickerChanged('daily-start', $event)" /></Form.Item>
        <Form.Item label="每日结束（可跨午夜）"><TimePicker v-model:value="dailyEnd" value-format="HH:mm" format="HH:mm" class="w-full" placeholder="选择每日结束时间" :open="schedulePicker === 'daily-end'" :get-popup-container="pickerContainer" @open-change="pickerChanged('daily-end', $event)" /></Form.Item>
        <Form.Item label="播放方式"><Select v-model:value="form.playback" :options="[{ value: 'continuous', label: '持续轮播' }, { value: 'interval', label: '间隔播放' }]" /></Form.Item>
        <Form.Item v-if="form.playback === 'interval'" label="间隔（分钟）"><InputNumber v-model:value="form.interval_minutes" :min="1" :max="10080" :precision="0" /></Form.Item>
      </div>
      <p v-if="form.playback === 'interval'" class="mb-4 text-sm text-muted-foreground">首次到时播放完整一轮，之后每隔 X 分钟再次播放；一轮超过间隔时不重叠，顺延到下一个播放时点。</p>
      <Form.Item label="屏幕布局"><Select v-model:value="form.layout" :options="layouts" /></Form.Item>
      <div class="mb-5 flex h-32 overflow-hidden rounded border" :style="previewStyle" aria-label="屏幕布局预览">
        <div v-if="form.layout !== 'fullscreen' && ['bottom', 'right'].includes(form.layout)" class="flex flex-1 items-center justify-center bg-gray-100 text-gray-700">SOP 作业指导</div>
        <div class="flex flex-1 items-center justify-center bg-gray-800 text-white">广告</div>
        <div v-if="form.layout !== 'fullscreen' && ['top', 'left'].includes(form.layout)" class="flex flex-1 items-center justify-center bg-gray-100 text-gray-700">SOP 作业指导</div>
      </div>
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2"><span>播放素材（按列表顺序）</span><div class="flex gap-2"><Button :disabled="form.media.length >= 50" @click="form.media.push({ kind: 'text', content: '', name: '文字', duration_seconds: 10 })">添加文字</Button><Button :loading="uploading" @click="fileInput?.click()">上传图片 / 视频</Button></div></div>
      <input ref="fileInput" type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm" style="display: none" @change="upload" />
      <Empty v-if="!form.media.length" description="添加文字或上传图片、视频" />
      <div v-for="(item, index) in form.media" :key="index" class="mb-3 rounded border p-3">
        <div class="mb-2 flex items-center justify-between gap-2"><span class="min-w-0 break-all">{{ index + 1 }}. {{ item.kind === 'text' ? '文字' : item.name }}</span><div class="flex shrink-0 gap-2"><Button size="small" :disabled="index === 0" @click="move(index, -1)">上移</Button><Button size="small" :disabled="index === form.media.length - 1" @click="move(index, 1)">下移</Button><Button size="small" danger @click="form.media.splice(index, 1)">移除</Button></div></div>
        <Input.TextArea v-if="item.kind === 'text'" v-model:value="item.content" :maxlength="2000" :rows="3" placeholder="输入广告文字" />
        <div v-if="item.kind !== 'video'" class="mt-2 flex items-center gap-2"><span>显示时长</span><InputNumber v-model:value="item.duration_seconds" :min="1" :max="3600" :precision="0" /><span>秒</span></div>
        <p v-else class="text-sm text-muted-foreground">完整播放视频后切换下一素材</p>
      </div>
      <Form.Item label="发布到终端"><Switch v-model:checked="form.is_active" /></Form.Item>
    </Form>
    <template #footer><div class="flex justify-end gap-3"><Button @click="closeEditor">取消</Button><Button data-ad-preview :disabled="uploading" @click="preview()">模拟预览</Button><Button type="primary" :loading="saving" :disabled="uploading" @click="save">保存广告任务</Button></div></template>
  </Drawer>
  <AdvertisementPreview v-model:open="previewOpen" :task="previewTask" @closed="previewClosed" />
</template>
