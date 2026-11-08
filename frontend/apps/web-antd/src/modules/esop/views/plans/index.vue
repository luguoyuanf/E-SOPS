<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import { stationLabel } from '../../utils/line-layout';
import type {
  ApprovedProductOperation,
  ApprovedProductVersion,
  PlanAssignment,
  ProductionLine,
  ProductionOrder,
  ProductionPlan,
  OrderAllocation,
  OrderSupplement,
  PlanTaskDetail,
  PlanStationProgress,
  PlanGroup,
} from '../../api/production';

import { computed, onActivated, onMounted, reactive, ref } from 'vue';
import { formatDateTime } from '@vben/utils';
import { useRoute } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import { Alert, Button, Checkbox, DatePicker, Drawer, Dropdown, Form, Input, InputNumber, message, Menu, Modal, Progress, Select, Spin, Tabs, Tag } from 'ant-design-vue';
import { listProducts } from '../../api/esop';
import { createdRangeQuery } from '#/utils/created-range';

import {
  getApprovedProductOperations,
  getPlan,
  getPlanTask,
  getOrderAllocation,
  getOrderOperations,
  listOrderSupplements,
  requestOrderSupplement,
  reviewOrderSupplement,
  cancelPlan,
  listApprovedProductVersions,
  listLines,
  listOrders,
  listPlans,
  listPlanGroups,
  pausePlan,
  pausePlanGroup,
  publishPlan,
  resumePlan,
  removeUnboundPlanStation,
  startPlanGroupNow,
  savePlan,
  savePlanGroup,
  deletePlanGroup,
} from '../../api/production';

const plans = ref<ProductionPlan[]>([]);
const { hasAccessByCodes } = useAccess();
const route = useRoute();
const pagePlans = ref<ProductionPlan[]>([]);
const planTotal = ref(0);
const planPage = ref(1);
const planPageSize = ref(20);
const planKeyword = ref('');
const planCreatedRange = ref<[string, string]>();
const planStatus = ref<ProductionPlan['status']>();
const activeTab = ref('plans');
const orders = ref<ProductionOrder[]>([]);
const products = ref<{ id: string; name: string }[]>([]);
const lines = ref<ProductionLine[]>([]);
const groups = ref<PlanGroup[]>([]);
const groupCreatedRange = ref<[string, string]>();
const selectedGroupIds = ref<string[]>([]);
const visibleGroups = computed(() => {
  const range = createdRangeQuery(groupCreatedRange.value);
  return groups.value.filter((group) => {
    const time = new Date(group.created_at).getTime();
    return (!range.created_from || time >= new Date(range.created_from).getTime())
      && (!range.created_to || time <= new Date(range.created_to).getTime());
  });
});
const approvedOperations = ref<ApprovedProductOperation[]>([]);
const productVersions = ref<ApprovedProductVersion[]>([]);
const loading = ref(false);
const versionLoading = ref(false);
const saving = ref(false);
const publishing = ref(false);
const draftOpen = ref(false);
const releaseOpen = ref(false);
const groupOpen = ref(false);
const groupDetailOpen = ref(false);
const selectedGroupId = ref<string>();
const editingGroupId = ref<string>();
const groupForm = reactive({ name: '', start_at: '', switch_mode: 'together' as 'together' | 'independent', plan_ids: [] as string[] });
const groupSaving = ref(false);
const draggingPlan = ref('');
const legacyPlan = ref(false);
const selectedTask = ref<PlanTaskDetail>();
const taskLoading = ref(false);
const selectedReleasePlanCode = ref('');
const editingId = ref<string>();
const savedPayload = ref('');
const form = reactive({ code: '', order_id: '', quantity: 0, line_id: '', product_sop_version_id: '', start_at: '', end_at: '', assignments: [] as PlanAssignment[] });
const allocation = ref<OrderAllocation>();
const supplementOpen = ref(false);
const supplementOrderId = ref('');
const supplements = ref<OrderSupplement[]>([]);
const supplementQuantity = ref(0);
const supplementReason = ref('');
let versionRequest = 0;
let editorRequest = 0;

const orderMap = computed(() => new Map(orders.value.map((item) => [item.id, item])));
const productMap = computed(() => new Map(products.value.map((item) => [item.id, item.name])));
const lineMap = computed(() => new Map(lines.value.map((item) => [item.id, item])));
const planMap = computed(() => new Map(plans.value.map((item) => [item.id, item])));
const selectedGroup = computed(() => groups.value.find((item) => item.id === selectedGroupId.value));
const groupDetailPlans = computed(() => selectedGroup.value?.plan_ids.map((id, index) => ({
  id, index: index + 1, plan: planMap.value.get(id), label: planLabel(id),
})) ?? []);
const operationMap = computed(() => new Map(approvedOperations.value.map((item) => [item.operation_id, item])));
const bottleneck = computed(() => selectedTask.value?.operations.filter((item) => item.is_assigned)
  .reduce<PlanTaskDetail['operations'][number] | undefined>((lowest, item) => !lowest || item.completion_rate < lowest.completion_rate ? item : lowest, undefined));
const selectedOrder = computed(() => orderMap.value.get(form.order_id));
const selectedLine = computed(() => lineMap.value.get(form.line_id));
const orderOptions = computed(() => orders.value.map((item) => ({ label: `${item.code} · ${productMap.value.get(item.product_id) || '产品'}`, value: item.id })));
const schedulableOrderOptions = computed(() => orders.value
  .filter((item) => item.production_status !== 'completed' || (editingId.value && item.id === form.order_id))
  .map((item) => ({
    label: `${item.code} · ${productMap.value.get(item.product_id) || '产品'}${item.production_status === 'completed' ? '（已完成）' : ''}`,
    value: item.id,
    disabled: item.production_status === 'completed',
  })));
const lineOptions = computed(() => lines.value.map((item) => ({ label: item.name, value: item.id })));
const readyToStart = computed(() => form.assignments.length > 0
  && !!form.product_sop_version_id
  && form.assignments.every((item) => operationMap.value.get(item.operation_id)?.sop_id === item.sop_id
    && lines.value.some((line) => line.stations.some((station) => station.id === item.station_id && station.terminal_active))));
function operationCapacity(operationId: string) {
  const row = allocation.value?.operations.find((item) => item.operation_id === operationId);
  const editingPlan = pagePlans.value.find((plan) => plan.id === editingId.value);
  return (row?.remaining_quantity ?? allocation.value?.order_quantity ?? 0)
    + (editingPlan?.assignments.some((item) => item.operation_id === operationId) ? editingPlan.quantity : 0);
}
function operationConflict(operationId: string) {
  return allocation.value?.operations.find((item) => item.operation_id === operationId)?.plan_codes.join('、') || '';
}
const maxPlanQuantity = computed(() => {
  const operations = [...new Set(form.assignments.map((item) => item.operation_id))];
  return operations.length ? Math.min(...operations.map(operationCapacity))
    : (allocation.value?.order_quantity ?? 0) + (allocation.value?.approved_supplement_quantity ?? 0);
});
const unchangedSinceSave = computed(() => !!editingId.value && savedPayload.value === JSON.stringify(payload()));

type PlanAction = 'edit' | 'start' | 'pause' | 'resume' | 'cancel' | 'view';
const planActionLabels: Record<PlanAction, string> = {
  edit: '编辑', start: '启动', pause: '暂停', resume: '恢复', cancel: '作废', view: '查看任务',
};
function planActions(plan: ProductionPlan): PlanAction[] {
  const actions: PlanAction[] = [];
  const canUpdate = hasAccessByCodes(['esop:plan:update']);
  const canPublish = hasAccessByCodes(['esop:plan:publish']);
  if (plan.status === 'draft' && canUpdate) actions.push('edit');
  if (plan.status === 'draft' && canPublish) actions.push('start');
  if (plan.status === 'published' && canPublish) actions.push('pause');
  if (plan.status === 'paused' && canPublish) actions.push('resume');
  if (['draft', 'paused', 'expired'].includes(plan.status) && canUpdate) actions.push('cancel');
  if (!['draft', 'cancelled'].includes(plan.status)) actions.push('view');
  return actions;
}
function runPlanAction(action: PlanAction, plan: ProductionPlan) {
  if (action === 'edit') edit(plan);
  else if (action === 'start') void publishPlan(plan.id).then(refresh);
  else if (action === 'pause' || action === 'resume') void changeStatus(plan.id, action);
  else if (action === 'cancel') confirmCancel(plan);
  else viewPlanRelease(plan);
}

const planColumns = [
  { title: '排产编号', dataIndex: 'code', key: 'code', width: 160 },
  { title: '生产订单', key: 'order', width: 220 },
  { title: '订单数量', key: 'quantity', width: 105 },
  { title: '排产数量', dataIndex: 'quantity', key: 'plan_quantity', width: 105 },
  { title: '产线', key: 'line', width: 120 },
  { title: '任务组', key: 'group', width: 140 },
  { title: '工位分配', key: 'count', width: 100 },
  { title: '完成度', key: 'completion', width: 150 },
  { title: '状态', key: 'status', width: 110 },
  { title: '投入数', dataIndex: 'input_total', key: 'input_total', width: 90 },
  { title: '末道良品', dataIndex: 'good_total', key: 'good_total', width: 100 },
  { title: '末道不良', dataIndex: 'bad_total', key: 'bad_total', width: 100 },
  { title: '操作', key: 'action', width: 130, fixed: 'right' as const },
];
function payload() {
  return {
    code: form.code.trim() || null,
    order_id: form.order_id, line_id: form.line_id, route_id: null,
    quantity: form.quantity,
    product_sop_version_id: form.product_sop_version_id || null,
    assignments: form.assignments.map((item) => ({ ...item })),
    start_at: form.start_at ? new Date(form.start_at).toISOString() : null,
    end_at: form.end_at ? new Date(form.end_at).toISOString() : null,
  };
}

async function refresh() {
  loading.value = true;
  try {
    const [pageResult, groupResult, allResult] = await Promise.all([
      listPlans({ page: planPage.value, page_size: planPageSize.value, keyword: planKeyword.value.trim() || undefined, status: planStatus.value, ...createdRangeQuery(planCreatedRange.value) }),
      listPlanGroups(),
      activeTab.value === 'groups' ? listPlans() : Promise.resolve(null),
    ]);
    if (allResult) plans.value = allResult.items;
    pagePlans.value = pageResult.items;
    planTotal.value = pageResult.total;
    groups.value = groupResult.items;
    selectedGroupIds.value = [];
  } finally { loading.value = false; }
}
function searchPlans() { planPage.value = 1; void refresh(); }
function changeTab(key: number | string) { activeTab.value = String(key); void refresh(); }
function changePlanPage(pagination: { current?: number; pageSize?: number }) {
  planPage.value = pagination.current || 1;
  planPageSize.value = pagination.pageSize || 20;
  void refresh();
}

async function loadVersionOperations(request: number) {
  const productId = selectedOrder.value?.product_id;
  if (!productId || !form.product_sop_version_id) { approvedOperations.value = []; form.assignments = []; return; }
  const result = selectedOrder.value?.operation_ids
    ? await getOrderOperations(form.order_id)
    : await getApprovedProductOperations(productId, form.product_sop_version_id);
  if (request !== versionRequest) return;
  approvedOperations.value = result.operations;
  form.assignments = form.assignments.filter((item) => result.operations.some((operation) => operation.operation_id === item.operation_id))
    .map((item) => ({ ...item, sop_id: result.operations.find((operation) => operation.operation_id === item.operation_id)!.sop_id }));
}

async function loadVersions() {
  const request = ++versionRequest;
  versionLoading.value = true;
  approvedOperations.value = [];
  productVersions.value = [];
  const productId = selectedOrder.value?.product_id;
  try {
    if (!productId) { form.product_sop_version_id = ''; form.assignments = []; return; }
    if (selectedOrder.value?.operation_ids) {
      const operations = await getOrderOperations(form.order_id);
      if (request !== versionRequest) return;
      form.product_sop_version_id = operations.product_sop_version_id;
      approvedOperations.value = operations.operations;
      form.assignments = form.assignments.filter((item) => operations.operations.some((operation) => operation.operation_id === item.operation_id));
      return;
    }
    const result = await listApprovedProductVersions(productId);
    if (request !== versionRequest) return;
    productVersions.value = result.items;
    form.product_sop_version_id = result.items[0]?.id ?? '';
    await loadVersionOperations(request);
  } finally { if (request === versionRequest) versionLoading.value = false; }
}

async function loadAllocation() {
  if (!form.order_id) { allocation.value = undefined; return; }
  const orderId = form.order_id;
  const result = await getOrderAllocation(orderId);
  if (form.order_id !== orderId) return;
  allocation.value = result;
  if (!editingId.value) form.quantity = result.order_quantity;
}
async function changeOrder() { form.assignments = []; await Promise.all([loadVersions(), loadAllocation()]); }
function assign(operationId: string, stationId: string) {
  if (!lines.value.some((line) => line.stations.some((station) => station.id === stationId && station.terminal_active))) {
    message.warning('该工位未绑定启用的终端，不能分配工序');
    return;
  }
  const operation = operationMap.value.get(operationId);
  if (!operation) return;
  if (operationCapacity(operationId) <= 0) {
    message.warning(`${operation.name}已由排产 ${operationConflict(operationId)} 占用，不能重复分配`);
    return;
  }
  form.assignments = form.assignments.filter((item) => item.station_id !== stationId);
  form.assignments.push({ operation_id: operationId, station_id: stationId, sop_id: operation.sop_id });
}
function dropOperation(event: DragEvent, stationId: string) {
  event.preventDefault();
  assign(event.dataTransfer?.getData('text/plain') || '', stationId);
}
function dragOperation(event: DragEvent, operationId: string) { event.dataTransfer?.setData('text/plain', operationId); }
function assignmentFor(stationId: string) { return form.assignments.find((item) => item.station_id === stationId); }
function clearAssignment(stationId: string) {
  form.assignments = form.assignments.filter((item) => item.station_id !== stationId);
}
function localTime(value: null | string) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}
function openDateTimePicker(event: MouseEvent) {
  (event.currentTarget as HTMLInputElement).showPicker?.();
}
const statusLabels: Record<ProductionPlan['status'], string> = {
  draft: '未启动', published: '运行中', paused: '已暂停', expired: '到期未完成', completed: '已完成', cancelled: '已作废',
};
const statusColors: Record<ProductionPlan['status'], string> = {
  draft: 'default', published: 'processing', paused: 'warning', expired: 'error', completed: 'success', cancelled: 'default',
};
function planLabel(id: string) {
  const plan = planMap.value.get(id);
  const order = plan && orderMap.value.get(plan.order_id);
  return `${plan?.code || id} · ${order ? productMap.value.get(order.product_id) || '产品' : '产品'}`;
}
function completedPlans(group: PlanGroup) {
  return group.plan_ids.filter((id) => planMap.value.get(id)?.status === 'completed').length;
}
function groupStatus(group: PlanGroup) {
  const queued = group.plan_ids.map((id) => planMap.value.get(id));
  if (!queued.length) return { label: '未配置任务', color: 'default' };
  if (queued.some((plan) => !plan)) return { label: '任务异常', color: 'error' };
  if (queued.every((plan) => plan?.status === 'completed')) return { label: '已完成', color: 'success' };
  if (queued.some((plan) => plan?.status === 'expired')) return { label: '到期未完成', color: 'error' };
  if (group.is_paused) return { label: '自动续排已暂停', color: 'warning' };
  if (queued.some((plan) => plan?.status === 'paused')) return { label: '排产已暂停', color: 'warning' };
  if (queued.some((plan) => plan?.status === 'published')) return { label: '运行中', color: 'processing' };
  if (queued.some((plan) => plan?.status === 'completed')) return { label: '待续排', color: 'warning' };
  if (queued.every((plan) => plan?.status === 'cancelled')) return { label: '无可执行任务', color: 'default' };
  if (group.start_at && new Date(group.start_at).getTime() > Date.now()) return { label: '待启动', color: 'warning' };
  return { label: '未启动', color: 'default' };
}
function openGroupDetail(group: PlanGroup) {
  selectedGroupId.value = group.id;
  groupDetailOpen.value = true;
}
function canStartGroup(group: PlanGroup) {
  const queued = group.plan_ids.map((id) => plans.value.find((plan) => plan.id === id));
  if (queued.some((plan) => plan?.status === 'expired')) return false;
  if (group.is_paused) return queued.some((plan) => plan && ['draft', 'published', 'paused'].includes(plan.status));
  return queued.some((plan) => plan?.status === 'draft')
    && !queued.some((plan) => plan && ['published', 'paused'].includes(plan.status));
}
function canPauseGroup(group: PlanGroup) {
  return !group.is_paused && group.plan_ids.some((id) => {
    const plan = planMap.value.get(id);
    return plan && ['draft', 'published', 'paused'].includes(plan.status);
  });
}
function closeDraft() { editorRequest++; versionRequest++; draftOpen.value = false; versionLoading.value = false; }

function create() {
  editorRequest++; versionRequest++; versionLoading.value = false;
  editingId.value = undefined; savedPayload.value = ''; legacyPlan.value = false;
  form.code = ''; form.order_id = ''; form.quantity = 0; form.line_id = ''; form.product_sop_version_id = ''; form.start_at = ''; form.end_at = ''; form.assignments = [];
  allocation.value = undefined;
  approvedOperations.value = []; productVersions.value = [];
  draftOpen.value = true;
}

async function edit(row: ProductionPlan) {
  if (row.status !== 'draft') return;
  const request = ++editorRequest;
  const plan = await getPlan(row.id);
  if (request !== editorRequest) return;
  editingId.value = plan.id; form.code = plan.code; form.order_id = plan.order_id; form.quantity = plan.quantity; form.line_id = plan.line_id;
  form.assignments = plan.assignments.map((item) => ({ ...item }));
  form.start_at = localTime(plan.start_at); form.end_at = localTime(plan.end_at);
  legacyPlan.value = !plan.product_sop_version_id;
  await loadVersions();
  await loadAllocation();
  if (request !== editorRequest) return;
  legacyPlan.value = legacyPlan.value || form.product_sop_version_id !== plan.product_sop_version_id;
  savedPayload.value = !legacyPlan.value ? JSON.stringify(payload()) : '';
  draftOpen.value = true;
}

async function save() {
  if (versionLoading.value || saving.value || publishing.value) return;
  if (!form.order_id || !form.line_id || !form.product_sop_version_id) { message.warning('请先选择生产订单、产线和已审核工序'); return; }
  if (!Number.isInteger(form.quantity) || form.quantity <= 0 || form.quantity > maxPlanQuantity.value) { message.warning(`排产数量必须大于零且不能超过所选工序的剩余可排数量 ${maxPlanQuantity.value}`); return; }
  if (form.start_at && form.end_at && form.start_at >= form.end_at) { message.warning('结束时间必须晚于开始时间'); return; }
  saving.value = true;
  const request = editorRequest;
  try {
    const plan = await savePlan(payload(), editingId.value);
    if (request === editorRequest) {
      editingId.value = plan.id; form.code = plan.code; legacyPlan.value = false; savedPayload.value = JSON.stringify(payload());
    }
    await refresh(); message.success('排产任务已保存');
  } finally { saving.value = false; }
}

async function publish() {
  if (versionLoading.value || saving.value || publishing.value) return;
  if (!editingId.value || !readyToStart.value || !unchangedSinceSave.value) { message.warning('请至少分配一道工序到工位，并保存排产'); return; }
  publishing.value = true;
  const request = editorRequest;
  try {
    await publishPlan(editingId.value);
    if (request === editorRequest) {
      const planId = editingId.value;
      closeDraft();
      await viewPlanRelease({ id: planId, code: form.code });
    }
    await refresh(); message.success('排产已启动，终端刷新后同步当前有效 SOP');
  } finally { publishing.value = false; }
}

function confirmPublish() {
  Modal.confirm({
    title: '确认启动排产',
    content: '启动后，关联产线的终端将显示当前有效 SOP。',
    keyboard: true, okText: '启动', cancelText: '取消',
    onOk: publish,
  });
}

async function viewPlanRelease(plan: Pick<ProductionPlan, 'id' | 'code'>) {
  taskLoading.value = true;
  selectedTask.value = undefined;
  selectedReleasePlanCode.value = plan.code;
  releaseOpen.value = true;
  try { selectedTask.value = await getPlanTask(plan.id); }
  finally { taskLoading.value = false; }
}

function confirmRemoveStation(station: PlanStationProgress) {
  const plan = selectedTask.value?.plan;
  if (!plan) return;
  Modal.confirm({
    title: `移除${station.station_name}的排产工序`,
    content: '移除后，联网终端下次同步即不再收到该工位任务；历史报工保留。若剩余工序已达目标，排产可能立即完成并接续下一任务。',
    keyboard: true, okText: '确认移除', cancelText: '取消',
    onOk: async () => {
      selectedTask.value = await removeUnboundPlanStation(plan.id, station.station_id);
      await refresh();
      message.success('工位工序已移除，终端下次同步生效');
    },
  });
}

async function changeStatus(id: string, action: 'pause' | 'resume') {
  if (action === 'pause') await pausePlan(id); else await resumePlan(id);
  await refresh();
}
function confirmCancel(plan: ProductionPlan) {
  Modal.confirm({ title: `作废排产 ${plan.code}`, content: '作废后会释放未报工的排产数量，任务无法恢复。', keyboard: true,
    onOk: async () => { await cancelPlan(plan.id); await refresh(); message.success('排产已作废'); },
  });
}
async function openSupplements(orderId: string) {
  supplementOrderId.value = orderId; supplementQuantity.value = 0; supplementReason.value = '';
  supplements.value = (await listOrderSupplements(orderId)).items;
  supplementOpen.value = true;
}
async function submitSupplement() {
  if (!Number.isInteger(supplementQuantity.value) || supplementQuantity.value <= 0 || !supplementReason.value.trim()) { message.warning('请填写补排数量和原因'); return; }
  await requestOrderSupplement({ order_id: supplementOrderId.value, quantity: supplementQuantity.value, reason: supplementReason.value.trim() });
  supplements.value = (await listOrderSupplements(supplementOrderId.value)).items;
  message.success('补排申请已提交');
}
async function reviewSupplement(row: OrderSupplement, approve: boolean) {
  const note = approve ? '' : window.prompt('请输入退回原因')?.trim();
  if (!approve && !note) return;
  await reviewOrderSupplement(row.id, approve, note);
  supplements.value = (await listOrderSupplements(supplementOrderId.value)).items;
  message.success(approve ? '补排已批准' : '补排已退回');
}
function createGroup() {
  editingGroupId.value = undefined;
  groupForm.name = ''; groupForm.start_at = ''; groupForm.switch_mode = 'together'; groupForm.plan_ids = [];
  groupOpen.value = true;
}
function editGroup(group: PlanGroup) {
  editingGroupId.value = group.id;
  groupForm.name = group.name; groupForm.start_at = localTime(group.start_at); groupForm.switch_mode = group.switch_mode ?? 'together';
  groupForm.plan_ids = [...group.plan_ids]; groupOpen.value = true;
}
function addToGroup(value: unknown) { const id = String(value); if (!groupForm.plan_ids.includes(id)) groupForm.plan_ids.push(id); }
function startGroupDrag(event: DragEvent, id: string) {
  draggingPlan.value = id;
  event.dataTransfer?.setData('text/plain', id);
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
}
function reorderGroup(target: string) {
  const from = groupForm.plan_ids.indexOf(draggingPlan.value);
  const to = groupForm.plan_ids.indexOf(target);
  if (from < 0 || to < 0 || from === to) return;
  const [item] = groupForm.plan_ids.splice(from, 1);
  if (item) groupForm.plan_ids.splice(to, 0, item);
}
async function saveGroup() {
  if (!groupForm.name.trim()) { message.warning('请输入任务组名称'); return; }
  groupSaving.value = true;
  try {
    await savePlanGroup({ name: groupForm.name.trim(), switch_mode: groupForm.switch_mode, start_at: groupForm.start_at ? new Date(groupForm.start_at).toISOString() : null, plan_ids: groupForm.plan_ids }, editingGroupId.value);
    groupOpen.value = false; await refresh(); message.success('任务组已保存');
  } finally { groupSaving.value = false; }
}
function removeGroup(group: PlanGroup) {
  Modal.confirm({ title: '删除任务组', content: '组内排产任务会保留，当前运行任务继续运行，后续自动接续停止。', keyboard: true,
    onOk: async () => { await deletePlanGroup(group.id); await refresh(); },
  });
}

onMounted(async () => {
  const [ordersResult, linesResult, productsResult] = await Promise.all([listOrders(), listLines(), listProducts()]);
  orders.value = ordersResult.items; lines.value = linesResult.items; products.value = productsResult.items;
  await refresh();
  await openOrderFromQuery();
});
async function openOrderFromQuery() {
  const orderId = route.query.order_id;
  const order = typeof orderId === 'string' ? orders.value.find((item) => item.id === orderId) : undefined;
  if (order?.production_status === 'completed') { message.warning('该生产订单已完成，不能再排产'); return; }
  if (order) {
    activeTab.value = 'plans'; create(); form.order_id = order.id; await changeOrder();
  }
}
onActivated(() => { if (orders.value.length) void openOrderFromQuery(); });

</script>

<template>
  <Page title="排产发布">
    <Tabs v-model:active-key="activeTab" @change="changeTab">
      <Tabs.TabPane key="plans" tab="排产发布">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <Input v-model:value="planKeyword" class="w-56" placeholder="搜索排产编号或订单号" allow-clear @press-enter="searchPlans" />
            <Select v-model:value="planStatus" class="w-32" allow-clear placeholder="全部状态" :options="Object.entries(statusLabels).map(([value, label]) => ({ value, label }))" @change="searchPlans" />
            <DatePicker.RangePicker v-model:value="planCreatedRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" @change="searchPlans" />
            <Button @click="searchPlans">查询</Button>
          </div>
          <div class="flex items-center gap-2"><Select v-model:value="supplementOrderId" class="w-48" show-search option-filter-prop="label" :options="orderOptions" placeholder="选择补排订单" /><Button v-access:code="'esop:plan:list'" :disabled="!supplementOrderId" @click="openSupplements(supplementOrderId)">补排申请</Button><Button v-access:code="'esop:plan:create'" type="primary" @click="create">新建排产</Button></div>
        </div>
        <div class="mx-auto w-full" style="max-width: 1680px">
        <Table :columns="planColumns" :data-source="pagePlans" :loading="loading" :pagination="{ current: planPage, pageSize: planPageSize, total: planTotal, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'], showTotal: (total: number) => `共 ${total} 条` }" :scroll="{ x: 1680 }" size="middle" row-key="id" @change="changePlanPage">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'order'" class="mx-auto max-w-[196px] overflow-hidden" :title="`${orderMap.get((record as ProductionPlan).order_id)?.code || '—'} · ${productMap.get(orderMap.get((record as ProductionPlan).order_id)?.product_id || '') || '产品'}`">
              <div class="truncate">{{ orderMap.get((record as ProductionPlan).order_id)?.code || '—' }}</div>
              <div class="truncate text-muted-foreground">{{ productMap.get(orderMap.get((record as ProductionPlan).order_id)?.product_id || '') || '产品' }}</div>
            </div>
            <span v-else-if="column.key === 'quantity'">{{ orderMap.get((record as ProductionPlan).order_id)?.quantity ?? '—' }}</span>
            <span v-else-if="column.key === 'plan_quantity'">{{ (record as ProductionPlan).quantity }}</span>
            <span v-else-if="column.key === 'line'">{{ [...new Set((record as ProductionPlan).assignments.map((item) => lines.find((line) => line.stations.some((station) => station.id === item.station_id))?.name).filter(Boolean))].join('、') || lineMap.get((record as ProductionPlan).line_id)?.name || '—' }}</span>
            <span v-else-if="column.key === 'group'">{{ groups.find((group) => group.id === (record as ProductionPlan).group_id)?.name || '独立任务' }}</span>
            <span v-else-if="column.key === 'count'">{{ (record as ProductionPlan).assignments.length }}</span>
            <Progress v-else-if="column.key === 'completion'" :percent="(record as ProductionPlan).completion_rate" :format="(percent) => `${percent}%`" size="small" title="每道已分配工序的（良品数＋不良数）÷排产数量，取最低值；有工序未报工时可能为 0%" />
            <Tag v-else-if="column.key === 'status'" :color="statusColors[(record as ProductionPlan).status]">{{ statusLabels[(record as ProductionPlan).status] }}</Tag>
            <div v-else-if="column.key === 'action'" class="flex items-center justify-center whitespace-nowrap">
              <Dropdown v-if="planActions(record as ProductionPlan).length >= 3" :trigger="['click']">
                <Button type="link">更多操作</Button>
                <template #overlay><Menu>
                  <Menu.Item v-for="action in planActions(record as ProductionPlan)" :key="action" :danger="action === 'cancel'" @click="runPlanAction(action, record as ProductionPlan)">{{ planActionLabels[action] }}</Menu.Item>
                </Menu></template>
              </Dropdown>
              <template v-else>
                <Button v-for="action in planActions(record as ProductionPlan)" :key="action" type="link" :danger="action === 'cancel'" @click="runPlanAction(action, record as ProductionPlan)">{{ planActionLabels[action] }}</Button>
              </template>
            </div>
          </template>
        </Table>
        </div>
      </Tabs.TabPane>
      <Tabs.TabPane key="groups" tab="任务组">
        <div class="mx-auto w-full" style="max-width: 1280px">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3"><div class="flex flex-wrap items-center gap-2"><span class="text-sm text-muted-foreground">创建时间</span><DatePicker.RangePicker v-model:value="groupCreatedRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" @change="selectedGroupIds = []" /><span class="text-sm text-muted-foreground">已选 {{ selectedGroupIds.length }} 项</span></div><Button v-access:code="'esop:plan:create'" type="primary" @click="createGroup">新建任务组</Button></div>
        <div v-if="loading" class="py-10 text-center"><Spin /></div>
        <div v-else-if="visibleGroups.length === 0" class="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">暂无任务组，可将多个未启动任务加入同一组顺序执行。</div>
        <div v-for="group in loading ? [] : visibleGroups" :key="group.id" class="mb-3 rounded-lg border border-border bg-background p-4">
          <div class="flex flex-wrap items-start gap-3">
            <Checkbox class="mt-1" :checked="selectedGroupIds.includes(group.id)" @change="selectedGroupIds = $event.target.checked ? [...selectedGroupIds, group.id] : selectedGroupIds.filter((id) => id !== group.id)" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2"><button type="button" class="text-base font-semibold text-primary hover:underline" @click="openGroupDetail(group)">{{ group.name }}</button><Tag>{{ group.switch_mode === 'independent' ? '工位独立切换' : '整线一起切换' }}</Tag><Tag :color="groupStatus(group).color">{{ groupStatus(group).label }}</Tag></div>
              <div class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground"><span>最早开始：{{ group.start_at ? formatDateTime(group.start_at) : '未设置' }}</span><span>已完成 {{ completedPlans(group) }} / {{ group.plan_ids.length }} 项</span></div>
              <div class="mt-3 flex flex-wrap items-center gap-2 text-xs"><span v-for="(id, index) in group.plan_ids.slice(0, 4)" :key="id" class="rounded bg-[var(--vben-bg-color)] px-2 py-1">{{ index + 1 }}. {{ planLabel(id) }}</span><span v-if="group.plan_ids.length > 4" class="text-muted-foreground">还有 {{ group.plan_ids.length - 4 }} 项</span><span v-if="!group.plan_ids.length" class="text-muted-foreground">尚未加入任务</span></div>
            </div>
            <div class="flex flex-wrap items-center justify-end gap-1"><Button v-access:code="'esop:plan:publish'" :type="group.is_paused ? 'primary' : 'link'" :disabled="!canStartGroup(group)" :title="canStartGroup(group) ? '立即启动或恢复任务组排产' : '已有运行中的排产，或没有待启动排产'" @click="startPlanGroupNow(group.id).then(refresh)">立即启动</Button><Button v-access:code="'esop:plan:update'" type="link" :disabled="!canPauseGroup(group)" :title="canPauseGroup(group) ? '当前排产继续运行，暂停后续自动接续' : '任务组已暂停或没有可暂停的排产'" @click="pausePlanGroup(group.id).then(refresh)">暂停</Button><Dropdown v-access:code="'esop:plan:update'" :trigger="['click']">
            <Button type="link">更多</Button>
            <template #overlay><Menu>
              <Menu.Item key="edit" @click="editGroup(group)">配置</Menu.Item>
              <Menu.Item key="delete" danger @click="removeGroup(group)">删除组</Menu.Item>
            </Menu></template>
          </Dropdown></div>
          </div>
        </div>
        </div>
      </Tabs.TabPane>
    </Tabs>

    <Drawer :open="draftOpen" :keyboard="true" title="排产与工位分配" width="min(920px, 100vw)" @close="closeDraft">
      <Alert v-if="legacyPlan" class="mb-4" type="info" show-icon message="请核对历史排产的工位分配并重新保存。" />
      <Form :model="form" layout="vertical">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Form.Item label="排产编号"><input v-model="form.code" maxlength="50" placeholder="留空自动生成" class="w-full rounded border border-border px-3 py-2" /></Form.Item>
          <Form.Item label="生产订单" required><Select v-model:value="form.order_id" :disabled="saving || publishing" :options="schedulableOrderOptions" show-search option-filter-prop="label" placeholder="搜索未完成的订单号或产品名称" @change="changeOrder" /></Form.Item>
          <Form.Item label="本任务排产数量" required><InputNumber v-model:value="form.quantity" class="w-full" :min="1" :precision="0" :max="maxPlanQuantity" /><div v-if="allocation" class="mt-1 text-xs text-muted-foreground">订单 {{ allocation.order_quantity }}，批准补排 {{ allocation.approved_supplement_quantity }}；每道工序分别计算可排数量，当前已选工序最多可排 {{ maxPlanQuantity }}</div></Form.Item>
          <Form.Item label="查看产线" required><Select v-model:value="form.line_id" :disabled="saving || publishing" :options="lineOptions" placeholder="选择产线查看工位" /></Form.Item>
          <Form.Item label="开始时间"><input v-model="form.start_at" type="datetime-local" class="w-full rounded border border-border px-3 py-2" @click="openDateTimePicker" /></Form.Item>
          <Form.Item label="结束时间"><input v-model="form.end_at" type="datetime-local" class="w-full rounded border border-border px-3 py-2" @click="openDateTimePicker" /></Form.Item>
        </div>
      </Form>
      <Spin :spinning="versionLoading">
        <div class="mb-3 font-medium">工序与工位</div>
        <div v-if="selectedOrder && approvedOperations.length === 0" class="rounded bg-[var(--vben-bg-color)] p-6 text-center">该产品暂无审核通过的完整工序版本，请先在 SOP 列表提交并完成审核。</div>
        <div v-if="approvedOperations.length" class="mb-4 flex flex-wrap gap-2">
          <button v-for="operation in approvedOperations" :key="operation.operation_id" type="button" :draggable="operationCapacity(operation.operation_id) > 0" :disabled="operationCapacity(operation.operation_id) <= 0" :title="operationCapacity(operation.operation_id) <= 0 ? `${operation.name}已排产：${operationConflict(operation.operation_id)}` : `可排 ${operationCapacity(operation.operation_id)} 件`" class="rounded border border-border px-3 py-2 text-sm" :class="operationCapacity(operation.operation_id) <= 0 ? 'cursor-not-allowed bg-[var(--vben-bg-color)] text-muted-foreground opacity-60' : 'cursor-grab'" @dragstart="dragOperation($event, operation.operation_id)">{{ operation.name }}<span v-if="operationCapacity(operation.operation_id) <= 0" class="ml-2">已排产 {{ operationConflict(operation.operation_id) }}</span></button>
        </div>
        <div v-if="selectedLine" class="overflow-x-auto pb-2">
          <div class="grid w-max gap-3" :style="{ gridTemplateColumns: `repeat(${selectedLine.layout === 'single' ? selectedLine.station_count : Math.ceil(selectedLine.station_count / 2)}, minmax(180px, 220px))` }">
          <div v-for="station in selectedLine.stations" :key="station.id" class="min-h-28 rounded border border-border p-3" :class="!station.terminal_active ? 'bg-[var(--vben-bg-color)] opacity-70' : ''" :style="{ gridColumn: station.column, gridRow: station.row }" @dragover.prevent @drop="dropOperation($event, station.id)">
            <div class="mb-2 font-medium">{{ stationLabel(station) }} <span class="text-xs text-muted-foreground">第 {{ station.row }} 排 · 第 {{ station.column }} 位</span></div>
            <div class="mb-2 text-xs" :class="station.terminal_active ? 'text-green-600' : 'text-orange-600'">{{ station.terminal_active ? `终端 ${station.terminal_code}` : '未绑定启用终端，不能排产' }}</div>
            <Select class="w-full" size="small" :disabled="!station.terminal_active" :value="assignmentFor(station.id)?.operation_id" :options="approvedOperations.map((item) => ({ label: operationCapacity(item.operation_id) <= 0 ? `${item.name}（已排产 ${operationConflict(item.operation_id)}）` : item.name, value: item.operation_id, disabled: operationCapacity(item.operation_id) <= 0 }))" placeholder="选择或拖入工序" allow-clear @change="assign(String($event), station.id)" @clear="clearAssignment(station.id)" />
          </div>
          </div>
        </div>
      </Spin>
      <template #footer>
        <Button class="mr-2" @click="closeDraft">关闭</Button>
        <Button v-access:code="editingId ? 'esop:plan:update' : 'esop:plan:create'" :disabled="versionLoading || publishing" :loading="saving" class="mr-2" @click="save">保存排产</Button>
        <Button v-if="editingId" v-access:code="'esop:plan:publish'" :disabled="versionLoading || saving || !readyToStart || !unchangedSinceSave" :loading="publishing" type="primary" @click="confirmPublish">启动</Button>
      </template>
    </Drawer>
    <Drawer :open="releaseOpen" :keyboard="true" title="排产任务进度" width="min(980px, 100vw)" @close="releaseOpen = false">
      <Spin :spinning="taskLoading">
        <div v-if="selectedTask" class="space-y-5">
          <Alert v-if="selectedTask.operations.some((operation) => operation.stations.some((station) => station.is_assigned && !station.terminal_active))" type="warning" show-icon message="有工位未绑定启用终端" description="该工位无法接收任务。可在下方移除分配；历史报工仍保留。" />
          <div class="rounded border border-border p-5">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div><div class="text-lg font-semibold">{{ selectedReleasePlanCode }} · {{ productMap.get(orderMap.get(selectedTask.release.order_id)?.product_id || '') || '产品' }}</div><div class="mt-1 text-sm text-muted-foreground">订单 {{ orderMap.get(selectedTask.release.order_id)?.code || '—' }} · 目标 {{ selectedTask.release.quantity }} · 交期 {{ selectedTask.release.due_date }}</div></div>
              <Tag :color="statusColors[selectedTask.plan.status]">{{ statusLabels[selectedTask.plan.status] }}</Tag>
            </div>
            <div class="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
              <div><div class="text-muted-foreground">整体完成度</div><div class="mt-1 text-xl font-semibold">{{ selectedTask.plan.completion_rate }}%</div></div>
              <div><div class="text-muted-foreground">当前瓶颈</div><div class="mt-1 font-semibold">{{ bottleneck?.operation_name || '—' }}</div></div>
              <div><div class="text-muted-foreground">末道良品 / 不良</div><div class="mt-1 font-semibold">{{ selectedTask.plan.good_total }} / {{ selectedTask.plan.bad_total }}</div></div>
              <div><div class="text-muted-foreground">良品缺口</div><div class="mt-1 font-semibold">{{ Math.max(0, selectedTask.release.quantity - selectedTask.plan.good_total) }}</div></div>
              <div><div class="text-muted-foreground">发布于</div><div class="mt-1">{{ formatDateTime(selectedTask.release.published_at) }}</div></div>
            </div>
            <Progress class="mt-3" :percent="selectedTask.plan.completion_rate" size="small" />
            <p class="mt-2 text-xs text-muted-foreground">整体进度取所有当前工序的最低完成比例；末道产出与当前工位产出可能不同。工序完成数 = 良品 + 不良。</p>
          </div>
          <div class="space-y-3">
            <div class="font-semibold">工序进度 <span class="text-sm font-normal text-muted-foreground">按本排产发布记录统计，多个工位执行同一工序时合并计算</span></div>
            <div v-for="operation in selectedTask.operations" :key="operation.operation_id" class="rounded border border-border p-4">
              <div class="flex flex-wrap items-center justify-between gap-2"><div class="font-semibold">{{ operation.operation_name }} <Tag v-if="!operation.is_assigned" color="default">已移出排产</Tag><Tag v-else-if="operation.completed_total > selectedTask.release.quantity" color="orange">超目标 {{ operation.completed_total - selectedTask.release.quantity }}</Tag></div><div class="text-lg font-semibold">{{ operation.completed_total }} / {{ selectedTask.release.quantity }} <span class="ml-1 text-sm text-muted-foreground">{{ operation.completion_rate }}%</span></div></div>
              <Progress class="mt-2" :percent="operation.completion_rate" :status="operation.is_assigned && operation.stations.some((station) => !station.terminal_active) ? 'exception' : 'normal'" size="small" />
              <div class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm"><span>投入 {{ operation.input_total }}</span><span>良品 {{ operation.good_total }}</span><span>不良 {{ operation.bad_total }}</span><span>待完成 {{ operation.remaining_qty }}</span></div>
              <div v-for="station in operation.stations" :key="station.station_id" class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-sm">
                <div><strong>{{ station.station_name }}</strong><span class="ml-2 text-muted-foreground">{{ station.is_assigned ? (station.terminal_active ? `终端 ${station.terminal_code}` : '无启用终端') : '已移出排产' }}</span><div class="mt-1 text-xs text-muted-foreground">投入 {{ station.input_total }} · 良品 {{ station.good_total }} · 不良 {{ station.bad_total }} · 最近报工 {{ station.last_report_at ? formatDateTime(station.last_report_at) : '暂无' }}</div></div>
                <Button v-if="station.is_assigned && !station.terminal_active && ['published', 'paused'].includes(selectedTask.plan.status)" v-access:code="'esop:plan:publish'" danger type="link" @click="confirmRemoveStation(station)">移除无终端工位</Button>
              </div>
            </div>
          </div>
        </div>
      </Spin>
      <template #footer><Button class="mr-2" :loading="taskLoading" :disabled="!selectedTask" @click="selectedTask && viewPlanRelease(selectedTask.plan)">刷新进度</Button><Button @click="releaseOpen = false">关闭</Button></template>
    </Drawer>
    <Drawer :open="groupDetailOpen" :keyboard="true" :title="selectedGroup?.name || '任务组进度'" width="min(900px, 100vw)" @close="groupDetailOpen = false">
      <div v-if="selectedGroup" class="space-y-5">
        <div class="rounded-lg border border-border p-4">
          <div class="flex flex-wrap items-center gap-2"><Tag>{{ selectedGroup.switch_mode === 'independent' ? '工位独立切换' : '整线一起切换' }}</Tag><Tag :color="groupStatus(selectedGroup).color">{{ groupStatus(selectedGroup).label }}</Tag></div>
          <div class="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3"><div><div class="text-muted-foreground">任务总数</div><strong>{{ selectedGroup.plan_ids.length }}</strong></div><div><div class="text-muted-foreground">已完成</div><strong>{{ completedPlans(selectedGroup) }}</strong></div><div><div class="text-muted-foreground">最早开始</div><strong>{{ selectedGroup.start_at ? formatDateTime(selectedGroup.start_at) : '未设置' }}</strong></div></div>
        </div>
        <div class="font-semibold">按执行顺序查看任务</div>
        <div v-for="item in groupDetailPlans" :key="item.id" class="rounded-lg border border-border p-4">
          <div class="flex flex-wrap items-center justify-between gap-2"><div class="font-medium">{{ item.index }}. {{ item.label }}</div><Tag v-if="item.plan" :color="statusColors[item.plan.status]">{{ statusLabels[item.plan.status] }}</Tag><Tag v-else>任务不存在</Tag></div>
          <template v-if="item.plan"><div class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground"><span>排产数量 {{ item.plan.quantity }}</span><span>末道良品 {{ item.plan.good_total }}</span><span>末道不良 {{ item.plan.bad_total }}</span><span>工位 {{ item.plan.assignments.length }} 个</span></div><Progress class="mt-3" :percent="item.plan.completion_rate" :format="(percent) => `${percent}%`" size="small" /></template>
        </div>
        <div v-if="!groupDetailPlans.length" class="rounded border border-dashed border-border p-6 text-center text-muted-foreground">任务组尚未加入排产任务</div>
      </div>
      <template #footer><Button class="mr-2" @click="refresh">刷新进度</Button><Button @click="groupDetailOpen = false">关闭</Button></template>
    </Drawer>
    <Drawer :open="groupOpen" :keyboard="true" title="任务组配置" width="min(680px, 100vw)" @close="groupOpen = false">
      <Form layout="vertical">
        <Form.Item label="任务组名称" required><input v-model="groupForm.name" maxlength="100" class="w-full rounded border border-border px-3 py-2" /></Form.Item>
        <Form.Item label="切换方式" required><Select v-model:value="groupForm.switch_mode" :options="[{ value: 'together', label: '一起切换：全部工序完成后整线进入下一排产' }, { value: 'independent', label: '独立切换：各工位完成后进入下一排产' }]" /></Form.Item>
        <Form.Item label="最早开始时间"><input v-model="groupForm.start_at" type="datetime-local" class="w-full rounded border border-border px-3 py-2" @click="openDateTimePicker" /></Form.Item>
      </Form>
      <div class="mb-2 font-medium">按顺序执行 <span class="text-sm font-normal text-muted-foreground">拖动任务调整执行顺序</span></div>
      <div v-for="(id, index) in groupForm.plan_ids" :key="id" draggable="true" class="mb-2 flex cursor-grab select-none items-center justify-between rounded border border-border p-3" @dragstart="startGroupDrag($event, id)" @dragover.prevent @drop.prevent="reorderGroup(id)" @dragend="draggingPlan = ''">
        <span>{{ index + 1 }}. {{ planLabel(id) }}</span><Button type="link" @click="groupForm.plan_ids.splice(index, 1)">移出</Button>
      </div>
      <Select class="mt-3 w-full" :options="plans.filter((plan) => plan.status === 'draft' && (!plan.group_id || plan.group_id === editingGroupId) && !groupForm.plan_ids.includes(plan.id)).map((plan) => ({ label: planLabel(plan.id), value: plan.id }))" placeholder="添加未启动的排产" @select="addToGroup" />
      <template #footer><Button class="mr-2" @click="groupOpen = false">取消</Button><Button v-access:code="editingGroupId ? 'esop:plan:update' : 'esop:plan:create'" type="primary" :loading="groupSaving" @click="saveGroup">保存任务组</Button></template>
    </Drawer>
    <Drawer :open="supplementOpen" :keyboard="true" title="生产订单补排申请" width="min(620px, 100vw)" @close="supplementOpen = false">
      <div class="mb-4 text-sm">订单 {{ orderMap.get(supplementOrderId)?.code || '—' }}。已排额度用尽且所有排产完成后，可按良品缺口申请补排；经理提交，租户管理员审批。</div>
      <Form layout="vertical">
        <Form.Item label="补排数量"><InputNumber v-model:value="supplementQuantity" class="w-full" :min="1" :precision="0" /></Form.Item>
        <Form.Item label="补排原因"><Input v-model:value="supplementReason" :maxlength="500" /></Form.Item>
        <Button v-access:code="'esop:plan:create'" type="primary" @click="submitSupplement">提交申请</Button>
      </Form>
      <div class="mt-6 font-medium">申请记录</div>
      <div v-for="row in supplements" :key="row.id" class="mt-3 rounded border border-border p-3 text-sm">
        <div class="flex justify-between"><strong>{{ row.quantity }} 件</strong><Tag :color="row.status === 'approved' ? 'green' : row.status === 'rejected' ? 'red' : 'orange'">{{ row.status === 'approved' ? '已批准' : row.status === 'rejected' ? '已退回' : '待审批' }}</Tag></div>
        <div class="mt-1">{{ row.reason }}</div>
        <div v-if="row.review_note" class="mt-1 text-muted-foreground">审批意见：{{ row.review_note }}</div>
        <div v-if="row.status === 'pending'" class="mt-2"><Button v-access:code="'esop:plan:publish'" size="small" type="primary" @click="reviewSupplement(row, true)">批准</Button><Button v-access:code="'esop:plan:publish'" size="small" class="ml-2" @click="reviewSupplement(row, false)">退回</Button></div>
      </div>
      <div v-if="!supplements.length" class="mt-3 text-sm text-muted-foreground">暂无申请</div>
    </Drawer>
  </Page>
</template>
