<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { ProductOption } from '../../api/esop';
import type { OrderProgress } from '../../api/operations';
import type { ApprovedProductOperation, ProductionOrder } from '../../api/production';

import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { formatDateTime } from '@vben/utils';

import { Button, Checkbox, Drawer, Dropdown, Form, Input, InputNumber, Menu, message, Modal, Progress, Select } from 'ant-design-vue';

import { listProducts } from '../../api/esop';
import { listOrderProgress } from '../../api/operations';
import { confirmOrderOperations, deleteOrder, exportOrders, getApprovedProductOperations, getOrderOperations, listApprovedProductVersions, listOrders, saveOrder } from '../../api/production';

const rows = ref<ProductionOrder[]>([]);
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const products = ref<ProductOption[]>([]);
const productSearchResults = ref<ProductOption[]>([]);
const progress = ref<OrderProgress[]>([]);
const defectOrder = ref<ProductionOrder>();
const progressOrder = ref<ProductionOrder>();
const loading = ref(false);
const exporting = ref(false);
const saving = ref(false);
const open = ref(false);
const editingId = ref<string>();
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const selectedIds = ref<string[]>([]);
const filters = reactive({ keyword: '', product_id: undefined as string | undefined, status: undefined as string | undefined,
  created_at_from: '', created_at_to: '', due_date_from: '', due_date_to: '' });
const form = reactive({ code: '', product_id: '', quantity: 1, due_date: '', product_sop_version_id: '' as string, operation_ids: [] as string[] });
const formOperations = ref<ApprovedProductOperation[]>([]);
const operationLoading = ref(false);
const confirmingLegacy = ref(false);
const legacyEditing = computed(() => !!editingId.value && !confirmingLegacy.value && !rows.value.find((row) => row.id === editingId.value)?.operation_ids);
let operationRequest = 0;
const canPublish = computed(() => hasAccessByCodes(['esop:plan:create']));
const canUpdate = computed(() => hasAccessByCodes(['esop:order:update']));
const productNames = computed(() => new Map(products.value.map((item) => [item.id, item.name])));
const productOptions = computed(() => products.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const editingProductOptions = computed(() => productSearchResults.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const progressMap = computed(() => new Map(progress.value.map((item) => [item.order_id, item])));
const defectProgress = computed(() => defectOrder.value && progressMap.value.get(defectOrder.value.id));
const selectedProgress = computed(() => progressOrder.value && progressMap.value.get(progressOrder.value.id));
const rowSelection = computed(() => ({ columnWidth: 48, selectedRowKeys: selectedIds.value, onChange: (keys: Array<number | string>) => { selectedIds.value = keys.map(String); } }));
const columns = [
  { title: '生产订单', dataIndex: 'code', key: 'code', width: 160 },
  { title: '产品', key: 'product', width: 150 },
  { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 80 },
  { title: '整单良品 / 目标', key: 'progress', width: 145 },
  { title: '工序不良', key: 'bad', width: 90 },
  { title: '完成度', key: 'completion', width: 90 },
  { title: '创建时间', key: 'created_at', width: 165 },
  { title: '交期', dataIndex: 'due_date', key: 'due_date', width: 120 },
  { title: '发布状态', key: 'status', width: 100 },
  { title: '生产状态', key: 'production_status', width: 100 },
  { title: '操作', key: 'action', width: 110 },
];

function queryParams() {
  return { keyword: filters.keyword.trim() || undefined, product_id: filters.product_id, is_published: filters.status === undefined ? undefined : filters.status === 'published',
    created_at_from: filters.created_at_from || undefined, created_at_to: filters.created_at_to || undefined,
    due_date_from: filters.due_date_from || undefined, due_date_to: filters.due_date_to || undefined };
}
const appliedFilters = ref<Partial<ReturnType<typeof queryParams>>>({});

function productionStatus(order: ProductionOrder) {
  return { completed: '已完成', in_progress: '生产中', waiting: '待开工', unplanned: '未排产' }[order.production_status];
}

async function loadOperations(row?: ProductionOrder) {
  const request = ++operationRequest;
  formOperations.value = [];
  form.operation_ids = row?.operation_ids?.slice() ?? [];
  form.product_sop_version_id = row?.product_sop_version_id ?? '';
  if (!form.product_id) return;
  operationLoading.value = true;
  try {
    const result = row
      ? await getOrderOperations(row.id)
      : await (async () => {
          const versions = await listApprovedProductVersions(form.product_id);
          return versions.items[0] ? getApprovedProductOperations(form.product_id, versions.items[0].id) : null;
        })();
    if (request !== operationRequest) return;
    if (!result) { message.warning('该产品尚无审核通过的工序版本'); return; }
    form.product_sop_version_id = result.product_sop_version_id;
    formOperations.value = result.operations;
  } finally { if (request === operationRequest) operationLoading.value = false; }
}

function allOperations(checked: boolean) {
  form.operation_ids = checked ? formOperations.value.map((item) => item.operation_id) : [];
}

function datesValid() {
  if (filters.created_at_from && filters.created_at_to && filters.created_at_from > filters.created_at_to) {
    message.warning('创建日期结束时间不能早于开始时间'); return false;
  }
  if (filters.due_date_from && filters.due_date_to && filters.due_date_from > filters.due_date_to) {
    message.warning('交期结束日期不能早于开始日期'); return false;
  }
  return true;
}

async function refresh() {
  loading.value = true;
  try {
    const [ordersResult, progressResult] = await Promise.all([
      listOrders({ ...appliedFilters.value, page: page.value, page_size: pageSize.value }), listOrderProgress(),
    ]);
    rows.value = ordersResult.items;
    total.value = ordersResult.total;
    progress.value = progressResult.items;
  } finally {
    loading.value = false;
  }
}

function search() { if (!datesValid()) return; appliedFilters.value = queryParams(); page.value = 1; selectedIds.value = []; void refresh(); }
function resetFilters() {
  filters.keyword = ''; filters.product_id = undefined; filters.status = undefined;
  filters.created_at_from = ''; filters.created_at_to = ''; filters.due_date_from = ''; filters.due_date_to = '';
  search();
}
function changePage(pagination: { current?: number; pageSize?: number }) {
  page.value = pagination.current || 1;
  pageSize.value = pagination.pageSize || 20;
  selectedIds.value = [];
  void refresh();
}
function openDatePicker(event: MouseEvent) { (event.currentTarget as HTMLInputElement).showPicker?.(); }
async function exportSelected() {
  if (!selectedIds.value.length || exporting.value) return;
  exporting.value = true;
  try {
    const blob = await exportOrders({ ...appliedFilters.value, ids: selectedIds.value });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = '生产订单.csv';
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  } finally { exporting.value = false; }
}

async function searchProducts(keyword = '') {
  productSearchResults.value = (await listProducts(keyword)).items;
  if (!keyword) products.value = productSearchResults.value;
}

function edit(row?: ProductionOrder, confirm = false) {
  editingId.value = row?.id;
  confirmingLegacy.value = confirm;
  form.code = row?.code ?? '';
  form.product_id = row?.product_id ?? '';
  form.quantity = row?.quantity ?? 1;
  form.due_date = row?.due_date?.slice(0, 10) ?? '';
  open.value = true;
  void loadOperations(row);
}

function remove(row: ProductionOrder) {
  Modal.confirm({
    title: '删除生产订单', content: `确认删除订单 ${row.code}？已有排产或报工记录的订单不能删除。`,
    keyboard: true, okText: '删除', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => { await deleteOrder(row.id); if (rows.value.length === 1 && page.value > 1) page.value--; selectedIds.value = []; await refresh(); message.success('订单已删除'); },
  });
}

async function save() {
  if (!form.product_id || !form.due_date || form.quantity < 1 || (!legacyEditing.value && (!form.product_sop_version_id || !form.operation_ids.length))) {
    message.warning('请填写产品、数量、交期，并至少选择一道工序');
    return;
  }
  saving.value = true;
  try {
    if (confirmingLegacy.value && editingId.value) {
      await confirmOrderOperations(editingId.value, { product_sop_version_id: form.product_sop_version_id, operation_ids: form.operation_ids });
    } else {
      await saveOrder({ ...form, code: form.code.trim(),
        product_sop_version_id: legacyEditing.value ? null : form.product_sop_version_id,
        operation_ids: legacyEditing.value ? null : form.operation_ids }, editingId.value);
    }
    open.value = false;
    selectedIds.value = [];
    await refresh();
    message.success(confirmingLegacy.value ? '订单工序已确认' : '订单已保存');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([refresh(), searchProducts()]);
});
</script>

<template>
  <Page title="生产订单">
    <form class="mb-4 flex flex-wrap items-end gap-3" @submit.prevent="search">
      <label class="flex flex-col gap-1 text-sm">订单号或产品名称<Input v-model:value="filters.keyword" class="w-48" allow-clear placeholder="搜索订单号或产品名称" /></label>
      <label class="flex flex-col gap-1 text-sm">产品<Select v-model:value="filters.product_id" class="w-48" show-search option-filter-prop="label" allow-clear :options="productOptions" placeholder="全部产品" /></label>
      <label class="flex flex-col gap-1 text-sm">发布状态<Select v-model:value="filters.status" class="w-32" allow-clear :options="[{ label: '待发布', value: 'unpublished' }, { label: '已发布', value: 'published' }]" placeholder="全部状态" /></label>
      <div class="flex flex-col gap-1 text-sm"><span>创建日期</span><div class="flex items-center gap-1"><Input v-model:value="filters.created_at_from" type="date" aria-label="创建开始日期" @click="openDatePicker" /><span>至</span><Input v-model:value="filters.created_at_to" type="date" aria-label="创建结束日期" @click="openDatePicker" /></div></div>
      <div class="flex flex-col gap-1 text-sm"><span>交期范围</span><div class="flex items-center gap-1"><Input v-model:value="filters.due_date_from" type="date" aria-label="交期开始日期" @click="openDatePicker" /><span>至</span><Input v-model:value="filters.due_date_to" type="date" aria-label="交期结束日期" @click="openDatePicker" /></div></div>
      <Button html-type="submit" :loading="loading">查询</Button><Button @click="resetFilters">重置</Button>
    </form>
    <div class="mb-4 flex items-center justify-between gap-2"><span class="text-sm text-muted-foreground">翻页、查询或重置时清空选择</span><div class="flex gap-2"><Button v-access:code="'esop:order:list'" :loading="exporting" :disabled="!selectedIds.length" @click="exportSelected">导出所选</Button><Button v-access:code="'esop:order:create'" type="primary" @click="edit()">新增订单</Button></div></div>
    <Table :columns="columns" :data-source="rows" :loading="loading" :row-selection="rowSelection" :pagination="{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'], showTotal: (count: number) => `共 ${count} 条` }" :scroll="{ x: 1358 }" table-layout="fixed" size="middle" row-key="id" @change="changePage">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'product'">{{ productNames.get((record as ProductionOrder).product_id) || '—' }}</span>
        <span v-else-if="column.key === 'progress'">{{ progressMap.get((record as ProductionOrder).id)?.good_total ?? 0 }} / {{ (record as ProductionOrder).quantity }}</span>
        <Button v-else-if="column.key === 'bad'" type="link" class="!px-0" :aria-label="`查看 ${(record as ProductionOrder).code} 各工序不良数`" @click="defectOrder = record as ProductionOrder">{{ progressMap.get((record as ProductionOrder).id)?.bad_total ?? 0 }}</Button>
        <Button v-else-if="column.key === 'completion'" type="link" class="!px-0" :aria-label="`查看 ${(record as ProductionOrder).code} 各工序完成度`" @click="progressOrder = record as ProductionOrder">{{ progressMap.get((record as ProductionOrder).id)?.completion_rate ?? 0 }}%</Button>
        <span v-else-if="column.key === 'created_at'">{{ formatDateTime((record as ProductionOrder).created_at) }}</span>
        <span v-else-if="column.key === 'status'">{{ (record as ProductionOrder).is_published ? '已发布' : '待发布' }}</span>
        <span v-else-if="column.key === 'production_status'">{{ productionStatus(record as ProductionOrder) }}</span>
        <span v-else-if="column.key === 'action'" class="inline-flex whitespace-nowrap">
          <Dropdown v-if="canUpdate" :trigger="['click']"><Button type="link">更多操作</Button><template #overlay><Menu>
            <Menu.Item v-if="canPublish" key="publish" @click="router.push({ path: '/esop/publish-center/plans', query: { order_id: (record as ProductionOrder).id } })">发布</Menu.Item>
            <Menu.Item key="edit" :disabled="(record as ProductionOrder).is_published" @click="edit(record as ProductionOrder)">编辑</Menu.Item>
            <Menu.Item key="delete" danger :disabled="(record as ProductionOrder).is_published" @click="remove(record as ProductionOrder)">删除</Menu.Item>
            <Menu.Item v-if="!(record as ProductionOrder).operation_ids" key="confirm" @click="edit(record as ProductionOrder, true)">确认工序并切换新规则</Menu.Item>
          </Menu></template></Dropdown>
          <Button v-else-if="canPublish" type="link" @click="router.push({ path: '/esop/publish-center/plans', query: { order_id: (record as ProductionOrder).id } })">发布</Button>
        </span>
      </template>
    </Table>

    <Modal :open="!!defectOrder" :title="`${defectOrder?.code ?? ''} · 工序不良明细`" :footer="null" :keyboard="true" @cancel="defectOrder = undefined">
      <p class="mb-3 text-sm text-muted-foreground">各工序报工的不良数量，合计按工序相加。</p>
      <table class="w-full text-sm"><thead><tr class="border-b text-left"><th class="py-2">工序</th><th class="py-2 text-right">不良数</th></tr></thead>
        <tbody><tr v-for="item in defectProgress?.operations ?? []" :key="item.operation_id" class="border-b last:border-0"><td class="py-2">{{ item.operation_name }}</td><td class="py-2 text-right">{{ item.bad_total }}</td></tr></tbody>
        <tfoot><tr class="font-medium"><td class="py-2">合计</td><td class="py-2 text-right">{{ defectProgress?.bad_total ?? 0 }}</td></tr></tfoot>
      </table>
    </Modal>

    <Modal :open="!!progressOrder" :title="`${progressOrder?.code ?? ''} · 工序完成度`" :footer="null" :keyboard="true" @cancel="progressOrder = undefined">
      <p class="mb-4 text-sm text-muted-foreground">每道工序按（良品＋不良）÷订单数量计算，上限 100%；订单完成度为各工序完成率的平均值。</p>
      <div v-for="item in selectedProgress?.operations ?? []" :key="item.operation_id" class="mb-4 last:mb-0">
        <div class="flex justify-between text-sm"><span>{{ item.operation_name }}</span><span>{{ item.completed_total }} / {{ selectedProgress?.quantity ?? 0 }}</span></div>
        <Progress :percent="item.completion_rate" size="small" />
      </div>
      <p v-if="!selectedProgress?.operations.length" class="text-sm text-muted-foreground">暂无工序进度。</p>
    </Modal>

    <Drawer :open="open" :keyboard="true" :title="confirmingLegacy ? '确认历史订单工序' : editingId ? '编辑生产订单' : '新增生产订单'" width="min(520px, 100vw)" @close="open = false">
      <Form :model="form" layout="vertical">
        <Form.Item label="订单编号"><Input v-model:value="form.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
        <Form.Item label="产品" required>
          <Select v-model:value="form.product_id" show-search :disabled="confirmingLegacy" :filter-option="false" :options="editingProductOptions" placeholder="搜索产品" @search="searchProducts" @change="() => loadOperations()" />
        </Form.Item>
        <Form.Item v-if="!legacyEditing" label="订单工序" required>
          <div v-if="operationLoading">正在读取工序…</div>
          <template v-else><Checkbox :checked="!!formOperations.length && form.operation_ids.length === formOperations.length" :disabled="!!editingId && !confirmingLegacy && !!rows.find((row) => row.id === editingId)?.operation_ids" @change="(event: any) => allOperations(event.target.checked)">全选工序</Checkbox>
          <Checkbox.Group v-model:value="form.operation_ids" class="mt-2 flex flex-col gap-2" :disabled="!!editingId && !confirmingLegacy && !!rows.find((row) => row.id === editingId)?.operation_ids" :options="formOperations.map((item) => ({ label: `${item.code} · ${item.name}`, value: item.operation_id }))" /></template>
          <p v-if="confirmingLegacy" class="mt-2 text-xs text-muted-foreground">确认后切换为全部工序完成判定；有效排产必须覆盖所选工序。</p>
        </Form.Item>
        <Form.Item label="生产数量" required><InputNumber v-model:value="form.quantity" :disabled="confirmingLegacy" :min="1" :precision="0" class="w-full" /></Form.Item>
        <Form.Item label="交期" required><Input v-model:value="form.due_date" :disabled="confirmingLegacy" type="date" @click="openDatePicker" /></Form.Item>
      </Form>
      <template #footer>
        <Button class="mr-2" @click="open = false">取消</Button>
        <Button :loading="saving" type="primary" @click="save">保存</Button>
      </template>
    </Drawer>
  </Page>
</template>
