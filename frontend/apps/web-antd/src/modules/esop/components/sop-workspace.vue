<script lang="ts" setup>
import type { Operation, ProductOption, Sop, SopPage, SopStatus } from '../api/esop';

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import { Button, Drawer, Dropdown, Form, Input, Menu, message, Pagination, Select, Table, Tag } from 'ant-design-vue';

import { requestClient } from '#/api/request';

import {
  approveSop,
  createSop,
  getSop,
  getSopVersions,
  listOperations,
  listProducts,
  listSops,
  newSopVersion,
  rejectSop,
  rollbackSopVersion,
  submitSop,
  updateSop,
  uploadSopFile,
} from '../api/esop';

const props = defineProps<{ mode: 'manage' | 'review' }>();
const { hasAccessByCodes } = useAccess();
const rows = ref<Sop[]>([]);
const page = ref(1);
const total = ref(0);
const operations = ref<Operation[]>([]);
const products = ref<ProductOption[]>([]);
const loading = ref(false);
const saving = ref(false);
const activeUploads = ref(0);
const uploading = computed(() => activeUploads.value > 0);
const open = ref(false);
const rejectOpen = ref(false);
const historyOpen = ref(false);
const historyRows = ref<Sop[]>([]);
const rejectReason = ref('');
const current = ref<Sop>();
const editorSession = ref(0);
const filterStatus = ref<SopStatus | undefined>(props.mode === 'review' ? 'pending' : undefined);
const form = reactive({ product_id: '', operation_id: '', title: '', pages: [] as SopPage[] });
const previews = reactive<Record<string, string>>({});
const fileTypes = reactive<Record<string, string>>({});
const fileInput = ref<HTMLInputElement>();
const columns = [
  { title: 'SOP', dataIndex: 'title', key: 'title' },
  { title: '产品', key: 'product', width: 180 },
  { title: '工序', key: 'operation', width: 150 },
  { title: '版本', dataIndex: 'version', key: 'version', width: 75 },
  { title: '状态', key: 'status', width: 95 },
  { title: '操作', key: 'action', width: 120, fixed: 'right' as const },
];
const statusText: Record<SopStatus, string> = {
  approved: '正式',
  draft: '草稿',
  pending: '待审核',
  rejected: '已退回',
};
const productNames = computed(() => new Map(products.value.map((item) => [item.id, item.name])));
const operationNames = computed(() => new Map(operations.value.map((item) => [item.id, item.name])));
const productOptions = computed(() => products.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const operationOptions = computed(() => operations.value
  .filter((item) => !form.product_id || item.product_id === null || item.product_id === form.product_id)
  .map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const editable = computed(() => props.mode === 'manage' && (!current.value || current.value.status === 'draft' || current.value.status === 'rejected'));
const latestApprovedVersion = computed(() => Math.max(0, ...historyRows.value.filter((item) => item.status === 'approved').map((item) => item.version)));
const hasEditableVersion = computed(() => historyRows.value.some((item) => item.status !== 'approved'));

async function refresh() {
  loading.value = true;
  try {
    const result = await listSops({ status: filterStatus.value, page: page.value, page_size: 20 });
    rows.value = result.items;
    total.value = result.total;
  } finally {
    loading.value = false;
  }
}

async function loadProducts(keyword = '') {
  products.value = (await listProducts(keyword)).items;
}

function clearPreviews() {
  editorSession.value += 1;
  for (const url of Object.values(previews)) URL.revokeObjectURL(url);
  for (const key of Object.keys(previews)) delete previews[key];
  for (const key of Object.keys(fileTypes)) delete fileTypes[key];
}

function changeStatus() {
  page.value = 1;
  void refresh();
}

function close() {
  open.value = false;
  rejectOpen.value = false;
  rejectReason.value = '';
  clearPreviews();
}

function create() {
  clearPreviews();
  current.value = undefined;
  form.product_id = '';
  form.operation_id = '';
  form.title = '';
  form.pages = [];
  open.value = true;
}

async function openSop(row: Sop) {
  clearPreviews();
  current.value = await getSop(row.id);
  form.product_id = current.value.product_id;
  form.operation_id = current.value.operation_id;
  form.title = current.value.title;
  form.pages = current.value.pages.map((page) => ({ ...page }));
  if (!products.value.some((item) => item.id === current.value?.product_id)) {
    await loadProducts();
  }
  open.value = true;
  await Promise.all(form.pages.map((page) => loadPreview(current.value!.id, page.file_id)));
}

async function loadPreview(sopId: string, fileId: string) {
  const session = editorSession.value;
  try {
    const blob = await requestClient.get<Blob>(`/esop/sops/${sopId}/pages/${fileId}/preview`, { responseType: 'blob' });
    if (session !== editorSession.value) return;
    previews[fileId] = URL.createObjectURL(blob);
    fileTypes[fileId] = blob.type;
  } catch {
    // The page remains listed so a missing media file is visible during review.
  }
}

async function addFile(file: File) {
  if (!(file.type.startsWith('image/') || file.type === 'application/pdf')) {
    message.warning('只支持图片和 PDF');
    return;
  }
  activeUploads.value += 1;
  const session = editorSession.value;
  try {
    const stored = await uploadSopFile(file);
    if (session !== editorSession.value) return;
    previews[stored.id] = URL.createObjectURL(file);
    fileTypes[stored.id] = file.type;
    form.pages.push({ file_id: stored.id, sort: form.pages.length, caption: null });
    message.success('文件已上传');
  } finally {
    activeUploads.value -= 1;
  }
}

async function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  for (const file of Array.from(input.files ?? [])) await addFile(file);
  input.value = '';
}

function paste(event: ClipboardEvent) {
  if (!editable.value) return;
  const files = Array.from(event.clipboardData?.items ?? [])
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((item): item is File => item !== null);
  if (files.length === 0) return;
  event.preventDefault();
  for (const file of files) void addFile(file);
}

function drop(event: DragEvent) {
  if (!editable.value) return;
  for (const file of Array.from(event.dataTransfer?.files ?? [])) void addFile(file);
}

function move(index: number, direction: -1 | 1) {
  const next = index + direction;
  if (next < 0 || next >= form.pages.length) return;
  [form.pages[index], form.pages[next]] = [form.pages[next]!, form.pages[index]!];
  form.pages.forEach((page, position) => { page.sort = position; });
}

function remove(index: number) {
  form.pages.splice(index, 1);
  form.pages.forEach((page, position) => { page.sort = position; });
}

async function save() {
  if (!form.product_id || !form.operation_id || !form.title.trim() || form.pages.length === 0) {
    message.warning('请选择产品、工序并填写标题和内容');
    return;
  }
  saving.value = true;
  try {
    const pages = form.pages.map((page, sort) => ({ file_id: page.file_id, sort, caption: page.caption?.trim() || null }));
    const sop = current.value
      ? await updateSop(current.value.id, { title: form.title.trim(), pages })
      : await createSop({ product_id: form.product_id, operation_id: form.operation_id, title: form.title.trim(), pages });
    current.value = sop;
    await refresh();
    message.success('已保存为草稿');
    close();
  } finally {
    saving.value = false;
  }
}

async function submit(row: Sop) {
  await submitSop(row.id);
  await refresh();
  message.success('已提交审核');
  close();
}

async function approve() {
  if (!current.value) return;
  await approveSop(current.value.id);
  await refresh();
  message.success('审核通过，版本已正式生效');
  close();
}

async function reject() {
  if (!current.value || !rejectReason.value.trim()) {
    message.warning('请填写退回原因');
    return;
  }
  await rejectSop(current.value.id, rejectReason.value.trim());
  await refresh();
  message.success('已退回草稿');
  close();
}

async function createVersion(row: Sop) {
  const draft = await newSopVersion(row.id);
  await refresh();
  historyOpen.value = false;
  await openSop(draft);
}

async function openHistory(row: Sop) {
  historyRows.value = (await getSopVersions(row.id)).items;
  historyOpen.value = true;
}

async function rollback(row: Sop) {
  const draft = await rollbackSopVersion(row.id);
  await refresh();
  historyOpen.value = false;
  message.success(`已从 V${row.version} 创建 V${draft.version} 草稿，请提交审核后生效`);
  await openSop(draft);
}

onMounted(async () => {
  const [operationResult] = await Promise.all([listOperations(), loadProducts()]);
  operations.value = operationResult.items;
  await refresh();
});
onBeforeUnmount(clearPreviews);
</script>

<template>
  <Page :title="mode === 'review' ? 'SOP审核' : 'SOP列表'">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <Select
        v-if="mode === 'manage'"
        v-model:value="filterStatus"
        allow-clear
        class="w-40"
        placeholder="全部状态"
        :options="Object.entries(statusText).map(([value, label]) => ({ label, value }))"
        @change="changeStatus"
      />
      <span v-else>待审核 {{ total }} 份</span>
      <Button v-if="mode === 'manage'" v-access:code="'esop:sop:create'" type="primary" @click="create">新增 SOP</Button>
    </div>
    <Table :columns="columns" :data-source="rows" :loading="loading" :pagination="false" row-key="id">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'product'">{{ productNames.get((record as Sop).product_id) || '—' }}</span>
        <span v-else-if="column.key === 'operation'">{{ operationNames.get((record as Sop).operation_id) || '—' }}</span>
        <Tag v-else-if="column.key === 'status'" :color="(record as Sop).status === 'approved' ? 'green' : undefined">{{ statusText[(record as Sop).status] }}</Tag>
        <span v-else-if="column.key === 'action'" class="flex gap-1">
          <Dropdown v-if="mode === 'manage' && ['draft', 'rejected'].includes((record as Sop).status) && hasAccessByCodes(['esop:sop:submit'])" :trigger="['click']"><Button type="link">更多操作</Button><template #overlay><Menu>
            <Menu.Item @click="openSop(record as Sop)">查看</Menu.Item>
            <Menu.Item @click="submit(record as Sop)">提交</Menu.Item>
            <Menu.Item @click="openHistory(record as Sop)">版本管理</Menu.Item>
          </Menu></template></Dropdown>
          <template v-else>
            <Button type="link" @click="openSop(record as Sop)">{{ mode === 'review' ? '审核' : '查看' }}</Button>
            <Button v-if="mode === 'manage' && ['draft', 'rejected'].includes((record as Sop).status)" v-access:code="'esop:sop:submit'" type="link" @click="submit(record as Sop)">提交</Button>
            <Button v-if="mode === 'manage'" type="link" @click="openHistory(record as Sop)">版本管理</Button>
          </template>
        </span>
      </template>
    </Table>
    <Pagination v-if="total > 20" v-model:current="page" :total="total" :page-size="20" class="mt-4 text-right" @change="refresh" />

    <Drawer :open="historyOpen" :keyboard="true" title="SOP版本管理" width="min(680px, 100vw)" @close="historyOpen = false">
      <Table :columns="[{ title: '版本', dataIndex: 'version', key: 'version' }, { title: '标题', dataIndex: 'title', key: 'title' }, { title: '状态', key: 'status' }, { title: '操作', key: 'action', fixed: 'right', width: 120 }]" :data-source="historyRows" :pagination="false" row-key="id">
        <template #bodyCell="{ column, record }">
          <span v-if="column.key === 'status'">{{ statusText[(record as Sop).status] }}</span>
          <span v-else-if="column.key === 'action'" class="flex gap-1">
            <Button v-if="(record as Sop).status === 'approved' && (record as Sop).version === latestApprovedVersion && !hasEditableVersion" v-access:code="'esop:sop:create'" type="link" @click="createVersion(record as Sop)">新版本</Button>
            <Button v-if="(record as Sop).status === 'approved' && (record as Sop).version < latestApprovedVersion && !hasEditableVersion" v-access:code="'esop:sop:create'" type="link" @click="rollback(record as Sop)">回滚此版</Button>
          </span>
        </template>
      </Table>
      <p class="mt-4 text-sm text-[var(--vben-text-muted)]">回滚会复制旧版内容生成新草稿。审核通过后，新版本才可用于后续生产发布；既有发布记录保持原快照。</p>
    </Drawer>

    <Drawer :open="open" :keyboard="true" :title="current ? `${current.title} · V${current.version}` : '新增 SOP'" width="min(920px, 100vw)" @close="close">
      <Form :model="form" layout="vertical">
        <div class="grid grid-cols-1 gap-x-4 md:grid-cols-2">
          <Form.Item label="产品" required>
            <Select v-model:value="form.product_id" :disabled="!!current" show-search :filter-option="false" :options="productOptions" placeholder="搜索产品" @search="loadProducts" @change="form.operation_id = ''" />
          </Form.Item>
          <Form.Item label="工序" required>
            <Select v-model:value="form.operation_id" :disabled="!!current" :options="operationOptions" placeholder="选择工序" />
          </Form.Item>
        </div>
        <Form.Item label="SOP 标题" required><Input v-model:value="form.title" :disabled="!editable" :maxlength="160" /></Form.Item>
      </Form>

      <div v-if="editable" v-access:code="'esop:sop:upload'" class="mb-5 rounded bg-[var(--vben-bg-color)] p-4" tabindex="0" @paste="paste" @dragover.prevent @drop.prevent="drop">
        <div class="mb-2 font-medium">作业内容</div>
        <p class="mb-3 text-sm text-[var(--vben-text-muted)]">在此粘贴截图、拖入图片或 PDF，也可选择文件。上传后可调整顺序。</p>
        <input ref="fileInput" class="hidden" type="file" accept="image/*,application/pdf" multiple @change="chooseFiles" />
        <Button :loading="uploading" @click="fileInput?.click()">选择文件</Button>
      </div>

      <div v-if="form.pages.length === 0" class="py-10 text-center text-[var(--vben-text-muted)]">尚无作业内容</div>
      <ol v-else class="space-y-4" aria-label="SOP 页面">
        <li v-for="(page, index) in form.pages" :key="page.file_id" class="rounded bg-[var(--vben-bg-color)] p-3">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <strong>第 {{ index + 1 }} 页</strong>
            <span v-if="editable" class="flex gap-1">
              <Button size="small" :disabled="index === 0" @click="move(index, -1)">上移</Button>
              <Button size="small" :disabled="index === form.pages.length - 1" @click="move(index, 1)">下移</Button>
              <Button size="small" danger @click="remove(index)">移除</Button>
            </span>
          </div>
          <iframe v-if="previews[page.file_id] && fileTypes[page.file_id] === 'application/pdf'" :src="previews[page.file_id]" :title="`第 ${index + 1} 页 PDF 预览`" class="h-80 w-full bg-white"></iframe>
          <img v-else-if="previews[page.file_id]" :src="previews[page.file_id]" :alt="page.caption || `第 ${index + 1} 页`" class="max-h-96 max-w-full object-contain" />
          <div v-else class="py-8 text-center">预览加载失败，请核对文件</div>
          <Input :value="page.caption ?? ''" :disabled="!editable" class="mt-3" placeholder="页面说明（选填）" :maxlength="200" @update:value="page.caption = $event" />
        </li>
      </ol>

      <div v-if="rejectOpen" class="mt-5 rounded bg-[var(--vben-bg-color)] p-4">
        <label class="mb-2 block font-medium" for="sop-reject-reason">退回原因</label>
        <Input.TextArea id="sop-reject-reason" v-model:value="rejectReason" :rows="3" placeholder="填写退回原因" />
      </div>

      <template #footer>
        <Button class="mr-2" @click="close">关闭</Button>
        <Button v-if="mode === 'review' && current?.status === 'pending'" v-access:code="'esop:sop:review'" class="mr-2" @click="rejectOpen ? reject() : (rejectOpen = true)">{{ rejectOpen ? '确认退回' : '退回' }}</Button>
        <Button v-if="mode === 'review' && current?.status === 'pending' && !rejectOpen" v-access:code="'esop:sop:review'" type="primary" @click="approve">审核通过</Button>
        <Button v-if="editable" v-access:code="current ? 'esop:sop:update' : 'esop:sop:create'" :loading="saving || uploading" type="primary" @click="save">保存草稿</Button>
      </template>
    </Drawer>
  </Page>
</template>
