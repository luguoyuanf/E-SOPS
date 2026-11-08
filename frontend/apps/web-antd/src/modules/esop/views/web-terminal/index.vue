<script setup lang="ts">
import type { Alarm, Advertisement, Broadcast, OrderTask, ProductionPlan, Report, SipPlan, Staff, TerminalProfile, TerminalTask } from './client';
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, reactive, ref, toRefs, watch } from 'vue';
import IconifyIcon from './terminal-icon.vue';
import message from 'ant-design-vue/es/message';
import ConfigProvider from 'ant-design-vue/es/config-provider';
import antdEn from 'ant-design-vue/es/locale/en_US';
import antdFr from 'ant-design-vue/es/locale/fr_FR';
import antdDe from 'ant-design-vue/es/locale/de_DE';
import antdRu from 'ant-design-vue/es/locale/ru_RU';
import antdTh from 'ant-design-vue/es/locale/th_TH';
import antdVi from 'ant-design-vue/es/locale/vi_VN';
import antdZh from 'ant-design-vue/es/locale/zh_CN';
import antdZhTw from 'ant-design-vue/es/locale/zh_TW';
import TerminalMedia from './terminal-media.vue';
import { detectTerminalLocale, normalizeTerminalLocale, terminalLanguages, terminalText } from './locale';
import type { TerminalLocale } from './locale';
import terminalLogo from './esops-logo.png';
import './terminal.css';
import AdvertisementPanel from './advertisement-panel.vue';
import { probeTerminalServer, TerminalClient, TerminalError } from './client';
import { createAlarmHistory } from './alarm-history';
import { refreshTerminal } from './refresh';
import type { TaskEnvelope } from './refresh';

const props = defineProps<{ terminalId?: string }>();
const client = new TerminalClient(props.terminalId ?? location.pathname.split('/')[2] ?? '');
const InputNumber = defineAsyncComponent(() => import('ant-design-vue/es/input-number'));
const TextArea = defineAsyncComponent(() => import('ant-design-vue/es/input/TextArea'));
const Modal = defineAsyncComponent(() => import('ant-design-vue/es/modal'));
const Pagination = defineAsyncComponent(() => import('ant-design-vue/es/pagination'));
const Select = defineAsyncComponent(() => import('ant-design-vue/es/select'));
const Switch = defineAsyncComponent(() => import('ant-design-vue/es/switch'));
const profile = ref<TerminalProfile>();
const staff = ref<Staff>();
const tasks = ref<TerminalTask[]>([]);
const catalog = ref<TerminalTask[]>([]);
const orders = ref<OrderTask[]>([]);
const plans = ref<ProductionPlan[]>([]);
const sipPlans = ref<SipPlan[]>([]);
const sipTotal = ref(0);
const sipPage = ref(1);
const sipSelected = ref<SipPlan>();
const sipQuantity = ref(1);
const sipSearch = ref('');
const sipCategory = ref<'active' | 'completed'>('active');
const sipLoading = ref(false);
let sipRequestEpoch = 0;
const sipRequestId = ref<string>();
const sipRequestPayload = ref<{ releaseId: string; operationId: string; quantity: number }>();
watch(sipQuantity, (quantity) => {
  if (sipRequestPayload.value && quantity !== sipRequestPayload.value.quantity) {
    sipRequestId.value = undefined;
    sipRequestPayload.value = undefined;
  }
}, { flush: 'sync' });
const planTotal = ref(0);
const planPage = ref(1);
const planSearch = ref('');
const planCategory = ref<'active' | 'completed'>('active');
const planLoading = ref(false);
const planToSwitch = ref<ProductionPlan>();
let planRequestEpoch = 0;
const reports = ref<Report[]>([]);
const reportTotal = ref(0);
const reportPage = ref(1);
const alarmHistory = createAlarmHistory((page) => client.request<{ items: Alarm[]; total: number }>(
  `terminal/alarms?page=${page}&page_size=10${alarmStatus.value ? `&status=${alarmStatus.value}` : ''}${alarmFilterType.value ? `&type_code=${encodeURIComponent(alarmFilterType.value)}` : ''}`,
));
const { items: alarms, total: alarmTotal, page: alarmPage, loading: alarmsLoading, ended: alarmsEnded, error: alarmLoadError } = toRefs(alarmHistory.state);
const alarmList = ref<HTMLElement>();
const alarmStatus = ref<string>();
const alarmTypes = ref<{ code: string; name: string }[]>([]);
const broadcasts = ref<Broadcast[]>([]);
const advertisements = ref<Advertisement[]>([]);
const page = ref<'sop' | 'catalog' | 'plans' | 'sip' | 'reports' | 'alarms' | 'settings'>('sop');
const preview = ref<TerminalTask>();
const query = ref('');
const loading = ref(true);
const busy = ref(false);
const online = ref(false);
const browserOnline = ref(navigator.onLine);
const error = ref('');
let networkFailureShown = false;
const account = ref('');
const showPassword = ref(false);
const isFullscreen = ref(!!document.fullscreenElement);
function syncFullscreen() { isFullscreen.value = !!document.fullscreenElement; }
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { networkFailureShown = false; error.value = tr('当前浏览器无法进入全屏，请使用浏览器的全屏功能'); }
}
const serverOrigin = window.location.origin;
const screenResolution = `${window.screen.width} × ${window.screen.height}`;
const alarmFilterType = ref<string>();
const resolveAlarmId = ref<string>();
const password = ref('');
const settingsKey = `esop-web-terminal:${client.terminalId}:settings`;
let settings: { locale?: string; scale?: number; autoPages?: boolean; interval?: number } = {};
try { settings = JSON.parse(localStorage.getItem(settingsKey) ?? '{}'); } catch { /* Use defaults for display preferences only. */ }
const scale = ref(settings.scale ?? 1);
const locale = ref<TerminalLocale>(settings.locale
  ? normalizeTerminalLocale(settings.locale)
  : detectTerminalLocale(navigator.languages?.length ? navigator.languages : [navigator.language]));
const tr = (key: string) => terminalText(locale.value, key);
const tf = (key: string, values: Record<string, number | string>) => tr(key).replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? ''));
const antdLocale = computed(() => ({ zh: antdZh, 'zh-TW': antdZhTw, en: antdEn, th: antdTh, vi: antdVi, fr: antdFr, de: antdDe, ru: antdRu })[locale.value]);
const autoPages = ref(settings.autoPages ?? false);
const interval = ref(settings.interval ?? 10);
const reportOrder = ref<OrderTask>();
const reportForm = reactive({ inputQty: 0, goodQty: 0, defectQty: 0 });
const alarmOpen = ref(false);
const alarmCode = ref<string>();
const alarmReason = ref('');
const changeReport = ref<Report>();
const changeKind = ref<'edit' | 'delete'>('edit');
const changeForm = reactive({ input_qty: 0, good_qty: 0, defect_qty: 0, reason: '' });
const badgeOpen = ref(false);
const avatarFailed = ref(false);
const mediaViewer = ref<{ advancePage: () => void }>();
const selectedFileId = ref<string>();
const settingsSection = ref('system');
const connectionResult = ref<{ ok: boolean; detail: string }>();
const confirmReport = ref(false);
const submissionId = ref<string>();
const submissionPayload = ref<Record<string, unknown>>();
const collapsed = ref(false);
const logoutOpen = ref(false);
let pollTimer: ReturnType<typeof setInterval> | undefined;
let slideTimer: ReturnType<typeof setInterval> | undefined;
let polling = false;
let disposed = false;
let taskSelectionEpoch = 0;
const currentTask = computed(() => tasks.value[0]);
const filteredCatalog = computed(() => catalog.value.filter((task) =>
  `${task.productCode} ${task.productName} ${task.productModel ?? ''} ${task.productCategoryName ?? ''} ${task.operationName}`.toLowerCase().includes(query.value.toLowerCase()),
));
const pageTitle = computed(() => ({ sop: tr('电子作业指导书'), catalog: tr('作业指导书'), plans: tr('生产计划'), sip: tr('SIP 点检'), reports: tr('报工'), alarms: tr('快捷报警'), settings: tr('终端设置') }[page.value]));
const settingsSections = computed(() => [ ['system', tr('系统信息'), 'lucide:monitor'], ['binding', tr('设备绑定'), 'lucide:link'], ['connection', tr('平台连接'), 'lucide:network'], ['display', tr('语言与字体'), 'lucide:languages'], ['about', tr('关于应用'), 'lucide:info'] ] as const);
const catalogGroups = computed(() => {
  const groups = new Map<string, Map<string, TerminalTask[]>>();
  for (const task of filteredCatalog.value) {
    const category = task.productCategoryName || tr('未分类');
    if (!groups.has(category)) groups.set(category, new Map());
    const products = groups.get(category)!;
    if (!products.has(task.productId)) products.set(task.productId, []);
    products.get(task.productId)!.push(task);
  }
  return groups;
});
const activeOrder = computed(() => orders.value.find((item) => item.releaseId === currentTask.value?.releaseId));
const selectedReportOrder = computed(() => orders.value.find((item) => item.releaseId === reportOrder.value?.releaseId) ?? orders.value[0]);
const resolveFile = (id: string) => client.file(id);
const displayDate = (value?: null | string) => value ? new Intl.DateTimeFormat('sv-SE', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value)) : '—';
function clearError() { error.value = ''; networkFailureShown = false; }
function showError(cause: unknown) {
  const networkFailure = cause instanceof TerminalError && cause.status === 0;
  if (networkFailure && !navigator.onLine) { browserWentOffline(); return; }
  error.value = tr(cause instanceof Error ? cause.message : '操作失败，请重试');
  networkFailureShown = networkFailure;
}
function browserWentOffline() {
  browserOnline.value = false;
  online.value = false;
  if (networkFailureShown) clearError();
}
function browserWentOnline() {
  browserOnline.value = true;
  void (profile.value ? refresh() : initialize());
}
async function action(run: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; clearError();
  try { await run(); } catch (cause) { showError(cause); }
  finally { busy.value = false; }
}
async function initialize() {
  loading.value = true; clearError();
  if (!navigator.onLine) { browserWentOffline(); loading.value = false; return; }
  try { profile.value = await client.connect(); online.value = navigator.onLine; }
  catch (cause) { online.value = false; showError(cause); }
  finally { loading.value = false; }
}
async function refresh() {
  if (!navigator.onLine) { browserWentOffline(); return; }
  if (polling || !client.token) return;
  polling = true;
  const epoch = taskSelectionEpoch;
  try {
    await refreshTerminal(client, {
      profile(latest) {
        if (disposed || epoch !== taskSelectionEpoch) return;
        if (profile.value && latest.siteId !== profile.value.siteId) {
          preview.value = undefined; tasks.value = []; orders.value = []; client.releaseFiles();
        }
        profile.value = latest; online.value = navigator.onLine;
        if (error.value.startsWith(tr('终端连接'))) clearError();
      },
      tasks(result) {
        if (disposed || epoch !== taskSelectionEpoch) return;
        if (tasks.value[0]?.releaseId !== result.list[0]?.releaseId) selectedFileId.value = undefined;
        if (JSON.stringify(tasks.value) !== JSON.stringify(result.list)) tasks.value = result.list;
        broadcasts.value = result.broadcasts; advertisements.value = result.advertisements;
        if (error.value.startsWith(tr('作业数据'))) clearError();
      },
      orders(result) {
        if (disposed || epoch !== taskSelectionEpoch) return;
        if (reportOrder.value && reportOrder.value.releaseId !== result[0]?.releaseId) resetReport();
        orders.value = result;
        if (error.value.startsWith(tr('报工数据'))) clearError();
      },
      failure(area, cause) {
        if (disposed || epoch !== taskSelectionEpoch) return;
        if (area === 'heartbeat') {
          online.value = false;
          if (cause instanceof TerminalError && [401, 403].includes(cause.status)) {
            tasks.value = []; profile.value = undefined; staff.value = undefined; client.disconnect();
          }
        }
        const label = { heartbeat: tr('终端连接'), tasks: tr('作业数据'), orders: tr('报工数据') }[area];
        if (cause instanceof TerminalError && cause.status === 0 && !navigator.onLine) { browserWentOffline(); return; }
        error.value = tf('{area}加载失败：{detail}', { area: label, detail: tr(cause instanceof Error ? cause.message : '请稍后重试') });
        networkFailureShown = cause instanceof TerminalError && cause.status === 0;
      },
    });
    if (staff.value) {
      try {
        if (page.value === 'reports') await loadReports();
        if (page.value === 'plans') await loadPlans();
        if (page.value === 'sip') await loadSipPlans();
        if (alarmOpen.value && alarmPage.value <= 1 && !alarmsLoading.value) await loadAlarms();
      } catch (cause) {
        if (cause instanceof TerminalError && cause.status === 401) { staff.value = undefined; client.staff = undefined; }
        showError(cause);
      }
    }
  } finally { polling = false; }
}

async function login() {
  await action(async () => {
    const username = account.value.trim() || document.querySelector<HTMLInputElement>('#web-terminal-account')?.value.trim() || '';
    const credential = password.value || document.querySelector<HTMLInputElement>('#web-terminal-password')?.value || '';
    if (!username || !credential) throw new Error(tr('请输入员工账号和密码'));
    const result = await client.request<Staff>('terminal/staff-login', 'POST', { username, password: credential });
    staff.value = result; client.staff = result; password.value = '';
    void refresh();
  });
}
function logout() {
  badgeOpen.value = false; alarmOpen.value = false; confirmReport.value = false; changeReport.value = undefined;
  staff.value = undefined; client.staff = undefined;
  reports.value = []; plans.value = []; sipPlans.value = []; sipTotal.value = 0; sipPage.value = 1; sipSelected.value = undefined; sipRequestId.value = undefined; sipRequestPayload.value = undefined; sipCategory.value = 'active'; sipRequestEpoch++; planTotal.value = 0; planRequestEpoch++; planLoading.value = false; planCategory.value = 'active'; planToSwitch.value = undefined; alarmHistory.clear(); preview.value = undefined; page.value = 'sop';
}
async function loadSipPlans() {
  const epoch = ++sipRequestEpoch;
  sipLoading.value = true;
  try {
    const result = await client.request<{ items: SipPlan[]; total: number }>(`terminal/sip/plans?category=${sipCategory.value}&page=${sipPage.value}&page_size=30&keyword=${encodeURIComponent(sipSearch.value.trim())}`);
    if (epoch !== sipRequestEpoch) return;
    sipPlans.value = result.items;
    sipTotal.value = result.total;
    if (sipSelected.value) sipSelected.value = result.items.find((item) => item.releaseId === sipSelected.value?.releaseId && item.operationId === sipSelected.value?.operationId);
  } finally { if (epoch === sipRequestEpoch) sipLoading.value = false; }
}
function searchSipPlans() { sipPage.value = 1; void loadSipPlans().catch(showError); }
function loadSipPage(value: number) { sipPage.value = value; void loadSipPlans().catch(showError); }
function switchSipCategory(category: 'active' | 'completed') {
  if (category === sipCategory.value) return;
  sipCategory.value = category;
  sipSelected.value = undefined;
  sipPlans.value = [];
  sipTotal.value = 0;
  sipPage.value = 1;
  void loadSipPlans().catch(showError);
}
function canRetrySip(plan: SipPlan) {
  return !!sipRequestId.value && sipRequestPayload.value?.releaseId === plan.releaseId && sipRequestPayload.value.operationId === plan.operationId;
}
let sipTrigger: HTMLElement | undefined;
function closeSip() {
  if (busy.value) return;
  sipSelected.value = undefined;
  void nextTick(() => sipTrigger?.focus());
}
function sipEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !sipSelected.value || document.querySelector('.ant-modal-wrap:not([style*="display: none"])')) return;
  event.preventDefault();
  event.stopPropagation();
  closeSip();
}
function beginSip(plan: SipPlan, event: MouseEvent) {
  sipTrigger = event.currentTarget as HTMLElement;
  sipSelected.value = plan;
  const pending = sipRequestPayload.value;
  sipQuantity.value = pending?.releaseId === plan.releaseId && pending.operationId === plan.operationId ? pending.quantity : 1;
  if (pending && (pending.releaseId !== plan.releaseId || pending.operationId !== plan.operationId)) {
    sipRequestId.value = undefined;
    sipRequestPayload.value = undefined;
  }
}
async function submitSip() {
  const plan = sipSelected.value;
  if (!plan || !Number.isInteger(sipQuantity.value) || sipQuantity.value < 1 || (sipQuantity.value > plan.availableQty && !sipRequestId.value)) return;
  sipRequestId.value ??= crypto.randomUUID();
  sipRequestPayload.value = { releaseId: plan.releaseId, operationId: plan.operationId, quantity: sipQuantity.value };
  await action(async () => {
    await client.request('terminal/sip/inspections', 'POST', {
      requestId: sipRequestId.value, releaseId: plan.releaseId, operationId: plan.operationId, quantity: sipQuantity.value,
    });
    sipRequestId.value = undefined;
    sipRequestPayload.value = undefined;
    sipSelected.value = undefined;
    message.success(tr('点检上报成功'));
    await loadSipPlans();
  });
}
async function loadPlans(force = false) {
  if (planLoading.value && !force) return;
  const epoch = ++planRequestEpoch;
  planLoading.value = true;
  try {
    const result = await client.productionPlans(planPage.value, planSearch.value.trim(), planCategory.value);
    if (epoch !== planRequestEpoch) return;
    plans.value = result.items;
    planTotal.value = result.total;
  } catch (cause) {
    if (epoch === planRequestEpoch) throw cause;
  } finally { if (epoch === planRequestEpoch) planLoading.value = false; }
}
function searchPlans() { planPage.value = 1; void action(loadPlans); }
function loadPlanPage(value: number) { planPage.value = value; void action(loadPlans); }
function switchPlanCategory(category: 'active' | 'completed') {
  if (category === planCategory.value) return;
  planCategory.value = category;
  planPage.value = 1;
  planTotal.value = 0;
  plans.value = [];
  planToSwitch.value = undefined;
  void loadPlans(true).catch(showError);
}
const planStatus = (status: string) => tr(({ draft: '待发布', published: '已发布', paused: '已暂停', expired: '已过期', completed: '已完成' } as Record<string, string>)[status] ?? status);
async function confirmPlanSwitch() {
  const selected = planToSwitch.value;
  if (planCategory.value !== 'active' || selected?.status !== 'published' || !selected.releaseId) return;
  await action(async () => {
    try { await client.selectProductionPlan(selected.releaseId!); }
    catch (cause) { await loadPlans(); throw cause; }
    taskSelectionEpoch++;
    planToSwitch.value = undefined;
    tasks.value = [];
    orders.value = [];
    reportOrder.value = undefined;
    resetReport();
    selectedFileId.value = undefined;
    const [result, latestOrders] = await Promise.all([
      client.request<TaskEnvelope>('terminal/tasks'),
      client.request<OrderTask[]>('terminal/orders'),
    ]);
    tasks.value = result.list;
    broadcasts.value = result.broadcasts;
    advertisements.value = result.advertisements;
    orders.value = latestOrders;
    reportOrder.value = latestOrders[0];
    page.value = 'sop';
    message.success(tr('已切换报工订单'));
  });
}
async function loadReports() {
  const [items, history] = await Promise.all([
    client.request<OrderTask[]>('terminal/orders'),
    client.request<{ items: Report[]; total: number }>(`terminal/reports?page=${reportPage.value}&page_size=10`),
  ]);
  orders.value = items; reports.value = history.items; reportTotal.value = history.total;
}
async function loadAlarms(reset = true) {
  if (reset && alarmList.value) alarmList.value.scrollTop = 0;
  await Promise.all([
    ...(reset ? [client.request<{ items: { code: string; name: string }[] }>('terminal/alarm-types').then((types) => { alarmTypes.value = types.items; })] : []),
    alarmHistory.load(reset),
  ]);
}
function scrollAlarms(event: Event) {
  const list = event.currentTarget as HTMLElement;
  if (list.scrollHeight - list.scrollTop - list.clientHeight < 120) void loadAlarms(false).catch(showError);
}

function selectReportOrder(value: unknown) {
  const order = orders.value.find((item) => item.releaseId === String(value));
  if (order) beginReport(order);
}
function resetReport() {
  changeReport.value = undefined;
  Object.assign(reportForm, { inputQty: 0, goodQty: 0, defectQty: 0 });
}
async function navigate(next: typeof page.value) {
  page.value = next; preview.value = undefined; selectedFileId.value = undefined;
  await action(async () => {
    if (next === 'catalog') catalog.value = (await client.request<{ list: TerminalTask[] }>('terminal/sop-catalog')).list;
    if (next === 'plans') { planPage.value = 1; await loadPlans(); }
    if (next === 'sip') { sipSelected.value = undefined; sipCategory.value = 'active'; sipPage.value = 1; await loadSipPlans(); }
    if (next === 'reports') { await loadReports(); reportOrder.value = orders.value[0]; }
    if (next === 'alarms') await loadAlarms();
  });
}
function beginReport(order: OrderTask) {
  reportOrder.value = order; submissionId.value = undefined; submissionPayload.value = undefined; Object.assign(reportForm, { inputQty: 0, goodQty: 0, defectQty: 0 });
}
async function submitReport() {
  await action(async () => {
    const order = selectedReportOrder.value;
    if (!order) return;
    submissionId.value ??= crypto.randomUUID();
    submissionPayload.value ??= { ...reportForm, requestId: submissionId.value, occurredAt: new Date().toISOString(), releaseId: order.releaseId, orderId: order.id, sopId: order.sopId };
    try { await client.report(submissionPayload.value); }
    catch (cause) {
      if (cause instanceof TerminalError && cause.status >= 400) { submissionId.value = undefined; submissionPayload.value = undefined; }
      throw cause;
    }
    confirmReport.value = false; submissionId.value = undefined; submissionPayload.value = undefined;
    Object.assign(reportForm, { inputQty: 0, goodQty: 0, defectQty: 0 });
    message.success(tr('报工成功')); await loadReports();
  });
}
async function quickAlarm() {
  await action(async () => { await loadAlarms(); alarmCode.value = undefined; alarmReason.value = ''; alarmOpen.value = true; });
}
async function submitAlarm() {
  await action(async () => {
    if (!alarmCode.value) throw new Error(tr('请选择报警类型'));
    await client.alarm({ requestId: crypto.randomUUID(), typeCode: alarmCode.value, reason: alarmReason.value });
    alarmCode.value = undefined; alarmReason.value = ''; message.success(tr('报警已提交')); await loadAlarms();
  });
}
function beginChange(row: Report, kind: 'edit' | 'delete') {
  changeReport.value = row; changeKind.value = kind;
  Object.assign(changeForm, { input_qty: row.input_qty, good_qty: row.good_qty, defect_qty: row.defect_qty, reason: '' });
}
async function submitChange() {
  await action(async () => {
    if (!changeReport.value || !changeForm.reason.trim()) throw new Error(tr('请填写申请原因'));
    await client.request(`terminal/reports/${changeReport.value.id}/${changeKind.value === 'edit' ? 'changes' : 'deletion'}`, 'POST', {
      ...changeForm, request_id: crypto.randomUUID(), expected_revision: changeReport.value.revision,
    });
    changeReport.value = undefined; message.success(tr('申请已提交，等待审核')); await loadReports();
  });
}
async function resolveAlarm(id: string) {
  await action(async () => { await client.request(`terminal/alarms/${id}/resolve`, 'POST'); await loadAlarms(); });
}
function saveSettings() {
  localStorage.setItem(settingsKey, JSON.stringify({ locale: settings.locale, scale: scale.value, autoPages: autoPages.value, interval: interval.value }));
  message.success(tr('终端设置已保存'));
}
function saveLanguage() {
  settings.locale = locale.value;
  saveSettings();
}
async function testServerConnection() {
  if (busy.value) return;
  busy.value = true;
  connectionResult.value = undefined;
  try {
    await probeTerminalServer();
    connectionResult.value = { ok: true, detail: tf('服务器连接成功：{address}', { address: serverOrigin }) };
  } catch (cause) {
    const detail = cause instanceof Error ? tr(cause.message) : tr('操作失败，请重试');
    connectionResult.value = { ok: false, detail: tf('服务器连接失败：{detail}', { detail }) };
  } finally { busy.value = false; }
}
function tickPages() {
  if (!autoPages.value || page.value !== 'sop' || document.hidden || document.querySelector('.ant-modal-wrap:not([style*="display: none"])')) return;
  mediaViewer.value?.advancePage();
}

onMounted(() => {
  document.addEventListener('keydown', sipEscape);
  document.addEventListener('fullscreenchange', syncFullscreen);
  window.addEventListener('offline', browserWentOffline);
  window.addEventListener('online', browserWentOnline);
  void initialize();
  pollTimer = setInterval(() => { void refresh(); }, 10_000);
  let elapsed = 0;
  slideTimer = setInterval(() => { if (++elapsed >= interval.value) { elapsed = 0; tickPages(); } }, 1000);
});
onBeforeUnmount(() => { document.removeEventListener('keydown', sipEscape); document.removeEventListener('fullscreenchange', syncFullscreen); window.removeEventListener('offline', browserWentOffline); window.removeEventListener('online', browserWentOnline); disposed = true; clearInterval(pollTimer); clearInterval(slideTimer); client.releaseFiles(); });
</script>

<template>
  <ConfigProvider :locale="antdLocale">
  <main class="web-terminal" :class="{ 'settings-page': page === 'settings', 'reports-page': page === 'reports' }" :style="{ '--terminal-font-scale': scale }">
    <div v-if="loading" class="terminal-loading" role="status">{{ tr('正在连接 Web 终端…') }}</div>
    <template v-else-if="!profile"><div class="terminal-unavailable"><h1>{{ browserOnline ? tr('Web终端暂不可用') : tr('离线') }}</h1><p v-if="error">{{ error }}</p><button class="terminal-filled-button" @click="initialize">{{ tr('重新连接') }}</button></div></template>
    <template v-else-if="!staff && page !== 'settings'">
      <section class="terminal-login" :class="{ 'login-large-text': scale > 1.5 }">
        <header class="login-header">
          <div class="login-brand"><img :src="terminalLogo" alt="ESOPS" /><span>{{ tr('电子作业指导书') }}</span></div>
          <div class="login-actions">
            <label class="login-language"><span>{{ tr('language') }}</span><select v-model="locale" :aria-label="tr('language')" @change="saveLanguage"><option v-for="language in terminalLanguages" :key="language.value" :value="language.value">{{ language.label }}</option></select></label>
            <button class="terminal-text-button login-settings" type="button" :disabled="busy" @click="page = 'settings'"><IconifyIcon icon="lucide:settings" />{{ tr('设备设置') }}</button>
            <button class="terminal-text-button login-fullscreen" type="button" @click="toggleFullscreen"><IconifyIcon icon="lucide:maximize" />{{ isFullscreen ? tr('退出全屏') : tr('全屏') }}</button>
          </div>
        </header>
        <div class="login-content">
          <aside class="login-introduction">
            <p class="login-introduction-note">{{ tr('从作业标准，到每一个生产现场') }}</p>
            <div class="login-introduction-main"><img :src="terminalLogo" alt="ESOPS" /><h2>{{ tr('统一作业标准，') }}<br />{{ tr('连接生产现场。') }}</h2><p>{{ tr('查看作业指导书，完成生产报工。') }}</p></div>
            <p class="login-tagline">{{ tr('tagline') }}</p>
          </aside>
          <form class="login-form" @submit.prevent="login">
            <h1>{{ tr('员工登录') }}</h1>
            <p class="login-instruction">{{ tr('使用员工账号或工号，进入作业终端。') }}</p>
            <p v-if="profile.tenantName" class="login-tenant"><span>{{ tr('所属租户') }}</span> {{ profile.tenantName }}</p>
            <p v-if="profile.lineName || profile.siteName" class="login-station">{{ [profile.lineName, profile.siteName].filter(Boolean).join(' · ') }}</p>
            <label class="login-field"><span>{{ tr('员工账号或工号') }}</span><div class="login-input"><IconifyIcon icon="lucide:user-round" /><input id="web-terminal-account" v-model="account" :disabled="busy" autocomplete="username" :placeholder="tr('请输入员工账号或工号')" :aria-label="tr('员工账号或工号')" /></div></label>
            <label class="login-field"><span>{{ tr('密码') }}</span><div class="login-input"><IconifyIcon icon="lucide:lock-keyhole" /><input id="web-terminal-password" v-model="password" :disabled="busy" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" :placeholder="tr('请输入密码')" :aria-label="tr('密码')" /><button type="button" :aria-label="showPassword ? tr('隐藏密码') : tr('显示密码')" @click="showPassword = !showPassword"><IconifyIcon :icon="showPassword ? 'lucide:eye-off' : 'lucide:eye'" /></button></div></label>
            <p v-if="error" class="form-error" role="alert">{{ error }}</p>
            <button class="terminal-filled-button login-submit" type="submit" :disabled="busy">{{ busy ? tr('登录中…') : tr('登录') }}</button>
            <small>{{ tr('服务器') }}　{{ serverOrigin }}</small>
          </form>
        </div>
        <footer class="login-footer">Copyright © {{ new Date().getFullYear() }} ESOPS</footer>
      </section>
    </template>
    <template v-else>
      <header v-if="page === 'settings'" class="settings-header"><button :aria-label="tr('返回')" @click="page = 'sop'"><IconifyIcon icon="lucide:arrow-left" /></button><h1>{{ tr('终端设置') }}</h1><button class="settings-fullscreen" :aria-label="isFullscreen ? tr('退出全屏') : tr('全屏')" @click="toggleFullscreen"><IconifyIcon icon="lucide:maximize" /></button><span>{{ tr('已激活') }} · {{ profile.siteName }}</span></header>
      <header v-else class="terminal-header">
        <img v-if="page === 'sop'" :src="terminalLogo" alt="ESOPS" class="header-logo" />
        <button v-else class="header-back" :aria-label="tr('返回当前排产')" @click="navigate('sop')"><IconifyIcon icon="lucide:arrow-left" /></button>
        <span class="header-title">{{ pageTitle }}</span>
        <div class="header-station"><span><IconifyIcon icon="lucide:factory" :title="tr('产线')" />{{ profile.lineName || tr('未绑定') }}</span><span><IconifyIcon icon="lucide:monitor" :title="tr('工位')" />{{ profile.siteName || tr('未绑定') }}</span></div>
        <div class="header-actions">
          <template v-if="page === 'catalog'"><button class="terminal-text-button" @click="page = 'settings'"><IconifyIcon icon="lucide:settings" />{{ tr('设置') }}</button><button class="terminal-text-button" @click="navigate('sop')"><IconifyIcon icon="lucide:clipboard-list" />{{ tr('返回当前排产') }}</button></template>
          <button class="terminal-text-button" :disabled="busy" @click="page === 'catalog' ? navigate('catalog') : action(refresh)"><IconifyIcon icon="lucide:rotate-cw" />{{ page === 'catalog' ? tr('强制刷新') : tr('刷新') }}</button>
          <button class="terminal-text-button" :aria-label="isFullscreen ? tr('退出全屏') : tr('全屏')" @click="toggleFullscreen"><IconifyIcon icon="lucide:maximize" />{{ isFullscreen ? tr('退出全屏') : tr('全屏') }}</button>
          <span class="connection-state"><i :class="{ offline: !online }" />{{ online ? tr('在线') : tr('离线') }}</span>
          <button class="terminal-text-button staff-badge" @click="badgeOpen = true"><IconifyIcon icon="lucide:user-round" />{{ staff?.name || tr('未登录') }}</button>
          <template v-if="page === 'sop'"><button class="terminal-text-button" @click="page = 'settings'"><IconifyIcon icon="lucide:settings" />{{ tr('设置') }}</button><button class="terminal-text-button" :disabled="busy" @click="logoutOpen = true"><IconifyIcon icon="lucide:log-out" />{{ tr('logout') }}</button></template>
        </div>
      </header>
      <div v-if="error" class="terminal-error" role="alert">{{ error }}<button :aria-label="tr('关闭错误提示')" @click="clearError()">×</button></div>
      <div v-for="(broadcast, index) in broadcasts.filter((item) => item.position === 'top')" v-show="page === 'sop'" :key="`top-${index}`" class="terminal-broadcast" :style="{ color: broadcast.fontColor, backgroundColor: broadcast.backgroundColor, fontSize: `${broadcast.fontSize}px` }"><span>{{ broadcast.content }}</span></div>
      <section v-if="page === 'sop'" class="terminal-workspace">
        <AdvertisementPanel :items="advertisements" :resolve-file="resolveFile">
          <TerminalMedia ref="mediaViewer" :task="currentTask" :locale="locale" :selected-id="selectedFileId" :station-label="[profile.lineName, profile.siteName].filter(Boolean).join(' · ')" :resolve-file="resolveFile" />
        </AdvertisementPanel>
        <aside v-if="!collapsed" class="job-rail">
          <div class="job-rail-scroll"><div class="rail-title"><h2>{{ tr('当前排产') }}</h2><button :aria-label="tr('收起操作栏')" @click="collapsed = true"><IconifyIcon icon="lucide:chevron-right" /></button></div>
          <dl><dt>{{ tr('工序') }}</dt><dd>{{ currentTask?.operationName || '—' }}</dd><dt>{{ tr('产品') }}</dt><dd>{{ currentTask?.productName || '—' }}</dd><dt>{{ tr('型号') }}</dt><dd>{{ currentTask?.productModel || '—' }}</dd><dt>{{ tr('订单') }}</dt><dd>{{ currentTask?.orderCode || '—' }}</dd><dt>{{ tr('计划') }}</dt><dd>{{ currentTask?.planQty ?? 0 }}</dd><dt>{{ tr('已完成') }}</dt><dd>{{ (activeOrder?.operationGoodQty ?? 0) + (activeOrder?.operationDefectQty ?? 0) }}</dd></dl>
          <hr /><h2 class="files-heading">{{ tr('全部文件') }}</h2>
          <p v-if="!currentTask?.attachments?.length" class="rail-empty">{{ tr('当前数据未提供完整文件列表。可在左侧翻看已加载的指导书页面。') }}</p>
          <button v-for="(file, index) in currentTask?.attachments ?? []" :key="file.id" class="rail-file" :class="{ selected: file.id === (selectedFileId || currentTask?.attachments[0]?.id) }" @click="selectedFileId = file.id"><IconifyIcon icon="lucide:file" /><span>{{ file.name || tf('文件 {number}', { number: index + 1 }) }}</span></button></div>
          <div class="rail-actions"><button class="terminal-outline-button plan-action" @click="navigate('plans')"><IconifyIcon icon="lucide:calendar-days" />{{ tr('生产计划') }}</button><button class="terminal-outline-button sip-action" @click="navigate('sip')"><IconifyIcon icon="lucide:clipboard-check" />{{ tr('SIP 点检') }}</button><button class="terminal-outline-button" @click="navigate('catalog')">{{ tr('作业指导书') }}</button><button class="terminal-outline-button danger" @click="quickAlarm">{{ tr('快捷报警') }}</button><button class="terminal-filled-button report-action" @click="navigate('reports')">{{ tr('报工') }}</button></div>
        </aside>
        <aside v-else class="rail-collapsed"><button :aria-label="tr('展开操作栏')" @click="collapsed = false"><IconifyIcon icon="lucide:chevron-left" /></button></aside>
      </section>
      <section v-else-if="page === 'catalog'" class="catalog-workspace">
        <aside class="catalog-sidebar"><div class="catalog-search"><IconifyIcon icon="lucide:search" /><input v-model="query" :placeholder="tr('搜索产品或工序')" :aria-label="tr('搜索产品或工序')" /></div><div class="catalog-tree"><details v-for="[category, products] in catalogGroups" :key="category" :open="!!query"><summary><IconifyIcon icon="lucide:folder" />{{ category }}</summary><details v-for="[productId, operations] in products" :key="productId" :open="!!query"><summary><IconifyIcon icon="lucide:package" /><span>{{ operations[0]?.productName }}<small>{{ operations[0]?.productCode }}</small></span></summary><button v-for="task in operations" :key="task.operationId" :class="{ selected: preview?.operationId === task.operationId }" @click="preview = task"><IconifyIcon icon="lucide:file-text" />{{ task.operationName }}</button></details></details><p v-if="!filteredCatalog.length">{{ tr('没有匹配的作业指导书') }}</p></div></aside>
        <TerminalMedia :task="preview" :locale="locale" catalog :station-label="''" :resolve-file="resolveFile" />
      </section>
      <section v-else-if="page === 'plans'" class="plans-workspace">
        <div class="plans-tabs" role="tablist" :aria-label="tr('生产计划')"><button role="tab" :aria-selected="planCategory === 'active'" :class="{ selected: planCategory === 'active' }" @click="switchPlanCategory('active')">{{ tr('排产中') }}</button><button role="tab" :aria-selected="planCategory === 'completed'" :class="{ selected: planCategory === 'completed' }" @click="switchPlanCategory('completed')">{{ tr('已完成') }}</button></div>
        <form class="plans-toolbar" @submit.prevent="searchPlans"><label><IconifyIcon icon="lucide:search" /><input v-model="planSearch" :placeholder="tr('搜索生产订单、排产编号或产品')" :aria-label="tr('搜索生产订单、排产编号或产品')" /></label><button class="terminal-outline-button" :disabled="busy || planLoading" type="submit">{{ tr('搜索') }}</button><span>{{ tf('共 {total} 项排产', { total: planTotal }) }}</span></form>
        <div class="plans-list"><p v-if="!planLoading && !plans.length" class="panel-empty">{{ tr(planCategory === 'completed' ? '暂无已完成排产' : '本工位暂无排产任务') }}</p><article v-for="plan in plans" :key="`${plan.planId}:${plan.operationId}`" class="plan-card"><header><strong>{{ plan.orderCode }} · {{ plan.productName }}</strong><span class="plan-status" :class="plan.status">{{ planStatus(plan.status) }}</span><span v-if="plan.isCurrent" class="plan-current">{{ tr('当前报工') }}</span></header><p>{{ plan.planCode }} · {{ plan.operationName }}<span v-if="plan.productModel"> · {{ plan.productModel }}</span></p><p v-if="plan.groupName">{{ tr('任务组') }}：{{ plan.groupName }}</p><div class="plan-meta"><div><span>{{ tr('订单总量') }}</span><strong>{{ plan.orderQty }}</strong></div><div><span>{{ tr('交期') }}</span><strong>{{ plan.dueDate || '—' }}</strong></div><div><span>{{ tr('排产开始') }}</span><strong>{{ displayDate(plan.startAt) }}</strong></div><div><span>{{ tr('排产结束') }}</span><strong>{{ displayDate(plan.endAt) }}</strong></div></div><div class="plan-progress"><span>{{ tr('计划') }} {{ plan.planQty }}　{{ tr('已完成') }} {{ plan.completedQty }}</span><progress :value="Math.min(plan.completedQty, plan.planQty)" :max="Math.max(1, plan.planQty)" /><button v-if="planCategory === 'active'" class="terminal-filled-button" :disabled="busy || !plan.canSwitch || plan.isCurrent" @click="planToSwitch = plan">{{ plan.isCurrent ? tr('当前任务') : tr('切换报工') }}</button></div></article></div>
        <Pagination v-if="planTotal > 30" v-model:current="planPage" :total="planTotal" :page-size="30" :disabled="planLoading" @change="loadPlanPage" />
      </section>
      <section v-else-if="page === 'sip'" class="plans-workspace sip-workspace">
        <div class="plans-tabs" role="tablist" :aria-label="tr('SIP 点检')"><button role="tab" :aria-selected="sipCategory === 'active'" :class="{ selected: sipCategory === 'active' }" @click="switchSipCategory('active')">{{ tr('排产中') }}</button><button role="tab" :aria-selected="sipCategory === 'completed'" :class="{ selected: sipCategory === 'completed' }" @click="switchSipCategory('completed')">{{ tr('已完成') }}</button></div>
        <form class="plans-toolbar" @submit.prevent="searchSipPlans"><label><IconifyIcon icon="lucide:search" /><input v-model="sipSearch" :placeholder="tr('搜索生产订单、排产编号或产品')" :aria-label="tr('搜索生产订单、排产编号或产品')" /></label><button class="terminal-outline-button" type="submit" :disabled="sipLoading">{{ tr('搜索') }}</button><span>{{ tf('共 {total} 项排产', { total: sipTotal }) }}</span></form>
        <div class="plans-list"><p v-if="!sipLoading && !sipPlans.length" class="panel-empty">{{ tr(sipCategory === 'completed' ? '暂无已完成排产' : '本工位暂无可点检排产') }}</p><article v-for="plan in sipPlans" :key="`${plan.releaseId}:${plan.operationId}`" class="plan-card"><header><strong>{{ plan.orderCode }} · {{ plan.productName }}</strong><span class="plan-status" :class="plan.status">{{ planStatus(plan.status) }}</span></header><p>{{ plan.planCode }} · {{ plan.operationName }}</p><div class="sip-quantities"><span>{{ tr('计划') }} <strong>{{ plan.planQty }}</strong></span><span>{{ tr('已报工') }} <strong>{{ plan.reportedQty }}</strong><small>{{ tr('良品') }} {{ plan.goodQty }} + {{ tr('不良') }} {{ plan.badQty }}</small></span><span>{{ tr('已点检') }} <strong>{{ plan.inspectedQty }}</strong></span><span>{{ tr('可点检') }} <strong>{{ plan.availableQty }}</strong></span></div><div class="plan-progress"><progress :value="Math.min(plan.reportedQty, plan.planQty)" :max="Math.max(1, plan.planQty)" /><button class="terminal-filled-button" :disabled="busy || (plan.availableQty < 1 && !canRetrySip(plan))" @click="beginSip(plan, $event)">{{ tr('点检上报') }}</button></div></article></div>
        <Pagination v-if="sipTotal > 30" v-model:current="sipPage" :total="sipTotal" :page-size="30" :disabled="sipLoading" @change="loadSipPage" />
        <article v-if="sipSelected" class="terminal-panel sip-entry"><header><h2>{{ sipSelected.orderCode }} · {{ tr('点检上报') }}</h2><button class="terminal-text-button" :disabled="busy" @click="closeSip">{{ tr('关闭') }}</button></header><p>{{ sipSelected.planCode }} · {{ sipSelected.operationName }}</p><p>{{ tr('已报工') }} {{ sipSelected.reportedQty }}　{{ tr('已点检') }} {{ sipSelected.inspectedQty }}　{{ tr('可点检') }} {{ sipSelected.availableQty }}</p><label>{{ tr('本次点检数量') }} <InputNumber v-model:value="sipQuantity" :min="1" :max="sipRequestId ? Math.max(sipSelected.availableQty, sipQuantity) : sipSelected.availableQty" :precision="0" :disabled="busy" /></label><footer><button class="terminal-outline-button" :disabled="busy" @click="closeSip">{{ tr('取消') }}</button><button class="terminal-filled-button" :disabled="busy || sipQuantity < 1 || (sipQuantity > sipSelected.availableQty && !sipRequestId) || !Number.isInteger(sipQuantity)" @click="submitSip">{{ tr('确认上报') }}</button></footer></article>
      </section>
      <section v-else-if="page === 'reports'" class="report-workspace">
        <article class="terminal-panel report-entry"><h2>{{ changeReport && changeKind === 'edit' ? tr('修改报工') : tr('报工录入') }}</h2><div class="panel-scroll entry-scroll">
          <template v-if="changeReport && changeKind === 'edit'"><strong>{{ changeReport.order_code }}</strong><p>{{ changeReport.product_name }}</p></template>
          <template v-else-if="selectedReportOrder"><div class="task-information"><h3>{{ tr('排产任务信息') }}</h3><Select :value="selectedReportOrder.releaseId" class="task-select" :disabled="!!submissionId" :options="orders.map((item) => ({ value: item.releaseId, label: item.orderCode }))" @change="selectReportOrder" /><strong>{{ selectedReportOrder.productName }}</strong><p>{{ tr('型号：') }}{{ selectedReportOrder.productModel || '—' }}</p><p>{{ tr('订单：') }}{{ selectedReportOrder.orderCode }}</p><p>{{ tr('工序：') }}{{ selectedReportOrder.operationName }}</p><p>{{ tr('计划数量：') }}{{ selectedReportOrder.planQty }}</p><p>{{ tr('本工序已完成：') }}{{ selectedReportOrder.operationGoodQty + selectedReportOrder.operationDefectQty }}</p><p>{{ tr('待完成：') }}{{ Math.max(0, selectedReportOrder.planQty - selectedReportOrder.operationGoodQty - selectedReportOrder.operationDefectQty) }}</p><div class="progress-label">{{ tr('本工序进度') }} <strong>{{ selectedReportOrder.completionRate }}%</strong></div><progress :value="selectedReportOrder.completionRate" max="100" /><small>{{ tr('本工序良品与不良合计达到计划数量后停止报工') }}</small></div></template>
          <p v-else>{{ tr('暂无可报工任务，请先在后台启动排产。') }}</p>
          <template v-if="changeReport && changeKind === 'edit'"><label class="report-quantity">{{ tr('投入数量') }}<InputNumber v-model:value="changeForm.input_qty" :min="1" :precision="0" /></label><label class="report-quantity">{{ tr('良品数量') }}<InputNumber v-model:value="changeForm.good_qty" :min="0" :precision="0" /></label><label class="report-quantity">{{ tr('不良数量') }}<InputNumber v-model:value="changeForm.defect_qty" :min="0" :precision="0" /></label><label>{{ tr('修改原因') }}<TextArea v-model:value="changeForm.reason" :maxlength="500" /></label></template>
          <template v-else><label class="report-quantity">{{ tr('投入数量') }}<InputNumber v-model:value="reportForm.inputQty" :disabled="!!submissionId" :min="1" :precision="0" :placeholder="tr('必填')" /></label><label class="report-quantity">{{ tr('良品数量') }}<InputNumber v-model:value="reportForm.goodQty" :disabled="!!submissionId" :min="0" :precision="0" /></label><label class="report-quantity">{{ tr('不良数量') }}<InputNumber v-model:value="reportForm.defectQty" :disabled="!!submissionId" :min="0" :precision="0" /></label></template>
        </div><footer class="entry-footer"><p>{{ changeReport && changeKind === 'edit' ? tr('审核通过前，原数据保持有效') : tr('二次确认后立即生效') }}</p><div><button class="terminal-outline-button" :disabled="busy || !!submissionId" @click="resetReport">{{ changeReport ? tr('取消修改') : tr('重置') }}</button><button class="terminal-filled-button" :disabled="busy || (changeReport ? !changeForm.reason.trim() || changeForm.input_qty <= 0 : !selectedReportOrder || reportForm.inputQty <= 0 || selectedReportOrder.status === 'COMPLETED')" @click="confirmReport = true">{{ submissionId ? tr('重试提交') : changeReport ? tr('提交修改审核') : tr('提交报工') }}</button></div></footer></article>
        <article class="terminal-panel report-history"><h2>{{ tr('报工记录 · 当前用户') }}</h2><div class="panel-scroll"><p v-if="!reports.length" class="panel-empty">{{ tr('暂无报工记录，提交后在这里查看。') }}</p><article v-for="row in reports" :key="row.id" class="report-card" :class="{ selected: changeReport?.id === row.id }"><header><strong>{{ row.order_code }} · {{ displayDate(row.occurred_at) }}</strong><span :class="row.change_status === 'pending' ? 'pending-status' : row.change_status === 'rejected' ? 'form-error' : 'effective-status'">{{ row.change_status === 'pending' ? tr('待审核 · 原数据有效') : row.change_status === 'rejected' ? tr('修改已退回 · 原数据有效') : tr('已生效') }}</span></header><p>{{ row.product_name }} · {{ row.staff_name }}</p><div class="report-card-quantities"><strong>{{ tr('投入') }}　{{ row.input_qty }}</strong><strong>{{ tr('良品') }}　{{ row.good_qty }}</strong><strong>{{ tr('不良') }}　{{ row.defect_qty }}</strong><button class="terminal-outline-button blue" :disabled="row.change_status === 'pending' || !!submissionId" @click="beginChange(row, 'edit')">{{ row.change_status === 'pending' ? tr('待审核') : tr('修改') }}</button><button class="terminal-outline-button danger" :disabled="row.change_status === 'pending' || !!submissionId" @click="beginChange(row, 'delete')">{{ tr('申请删除') }}</button></div></article><p v-if="reports.length" class="history-end">{{ tf('已显示 {shown} / {total} 条记录', { shown: reports.length, total: reportTotal }) }}</p></div><Pagination v-if="reportTotal > 10" v-model:current="reportPage" :total="reportTotal" :page-size="10" @change="action(loadReports)" /></article>
      </section>
      <section v-else-if="page === 'settings'" class="settings-workspace"><aside class="settings-sidebar"><div class="settings-brand"><strong>ESOPS</strong><span>{{ tr('终端管理') }}</span></div><nav><button v-for="[key, label, icon] in settingsSections" :key="key" :class="{ selected: settingsSection === key }" @click="settingsSection = key"><IconifyIcon :icon="icon" />{{ label }}</button></nav><small>{{ tr('设备编号') }}　{{ profile.serialNumber }}</small></aside><div class="settings-detail"><h2>{{ settingsSections.find((item) => item[0] === settingsSection)?.[1] }}</h2><p class="settings-subtitle">{{ ({ system: tr('设备、系统及当前工位的运行信息'), binding: tr('查看设备与租户、工位的绑定状态'), connection: tr('终端连接的 ESOP 平台地址'), display: tr('设置终端字号与作业展示'), about: tr('应用版本与产品说明') } as Record<string, string>)[settingsSection] }}</p>
        <article v-if="settingsSection === 'system'" class="settings-card"><h3>{{ tr('当前设备') }}</h3><button class="terminal-text-button" @click="action(refresh)"><IconifyIcon icon="lucide:rotate-cw" />{{ tr('刷新设备信息') }}</button><dl><dt>{{ tr('设备编号') }}</dt><dd>{{ profile.serialNumber }}</dd><dt>{{ tr('设备名称') }}</dt><dd>{{ profile.deviceName }}</dd><dt>{{ tr('激活状态') }}</dt><dd>{{ tr('已激活') }}</dd><dt>{{ tr('所属租户') }}</dt><dd>{{ profile.tenantName }}</dd><dt>{{ tr('租户编码') }}</dt><dd>{{ profile.tenantCode || '—' }}</dd><dt>{{ tr('产线') }}</dt><dd>{{ profile.lineName || '—' }}</dd><dt>{{ tr('工位') }}</dt><dd>{{ profile.siteName || tr('待后台绑定') }}</dd><dt>{{ tr('服务器') }}</dt><dd>{{ serverOrigin }}</dd><dt>{{ tr('屏幕分辨率') }}</dt><dd>{{ screenResolution }}</dd><dt>{{ tr('应用版本') }}</dt><dd>{{ tr('Web版') }}</dd></dl></article>
        <article v-else-if="settingsSection === 'binding'" class="settings-card"><h3>{{ tr('设备已激活') }}</h3><dl><dt>{{ tr('设备编号') }}</dt><dd>{{ profile.serialNumber }}</dd><dt>{{ tr('设备名称') }}</dt><dd>{{ profile.deviceName }}</dd><dt>{{ tr('所属租户') }}</dt><dd>{{ profile.tenantName }}</dd><dt>{{ tr('租户编码') }}</dt><dd>{{ profile.tenantCode || '—' }}</dd><dt>{{ tr('产线') }}</dt><dd>{{ profile.lineName || '—' }}</dd><dt>{{ tr('工位') }}</dt><dd>{{ profile.siteName || tr('待后台绑定') }}</dd></dl><button class="terminal-outline-button" @click="action(refresh)">{{ tr('刷新绑定信息') }}</button></article>
        <article v-else-if="settingsSection === 'connection'" class="settings-card"><h3>{{ tr('远程维护组网') }}</h3><p>{{ tr('Web 终端的组网由所在设备的操作系统管理，浏览器无法检测 Tailscale 连接状态。') }}</p><dl><dt>{{ tr('组网服务地址') }}</dt><dd>https://mesh.esops.cc</dd><dt>{{ tr('开机自动组网') }}</dt><dd>{{ tr('请在操作系统中配置 Tailscale 开机自动连接。') }}</dd></dl><p>{{ tr('在所在设备安装 Tailscale，使用上述服务地址和管理员私下提供的终端入网密钥接入；请勿公开分享密钥。') }}</p><p>{{ tr('Android 和 Ubuntu 原生终端支持激活认证后自动入网；浏览器无法自动设置所在设备的系统网络。') }}</p><h3>{{ tr('平台连接') }}</h3><p>{{ tr('当前地址：') }}{{ serverOrigin }}</p><button class="terminal-filled-button" :disabled="busy" @click="testServerConnection">{{ tr('检测服务器连接') }}</button><p v-if="connectionResult" class="settings-connection-result" :class="connectionResult.ok ? 'success' : 'failure'" role="status">{{ connectionResult.detail }}</p></article>
        <article v-else-if="settingsSection === 'display'" class="settings-card"><h3>{{ tr('language') }}</h3><label v-for="language in terminalLanguages" :key="language.value" class="settings-radio"><input v-model="locale" type="radio" :value="language.value" @change="saveLanguage" />{{ language.label }}</label><h3>{{ tr('字号大小') }}</h3><p>{{ tr('在屏幕自动适配的基础上调整；选择后立即应用，并在下次启动时保留。') }}</p><label v-for="[value, label] in [[1, tr('标准')], [1.25, tr('较大')], [1.5, tr('大')], [2, tr('特大')]]" :key="value" class="settings-radio"><input v-model="scale" type="radio" :value="value" @change="saveSettings" />{{ label }} · {{ Number(value) * 100 }}%</label><h3>{{ tr('自动翻页') }}</h3><label class="settings-switch">{{ tr('自动翻页') }}<Switch v-model:checked="autoPages" @change="saveSettings" /></label><label>{{ tr('翻页间隔（秒）') }}<InputNumber v-model:value="interval" :min="3" :max="120" @change="saveSettings" /></label></article>
        <article v-else class="settings-card"><h3>ESOPS {{ tr('电子作业指导书') }}</h3><p>{{ tr('工位终端应用') }}</p><dl><dt>{{ tr('当前版本') }}</dt><dd>{{ tr('Web版') }}</dd></dl><p>{{ tr('用于查看已发布的作业指导书、接收当前工位排产并记录现场报工。') }}</p></article>
      </div></section>
      <div v-for="(broadcast, index) in broadcasts.filter((item) => item.position === 'bottom')" v-show="page === 'sop'" :key="`bottom-${index}`" class="terminal-broadcast" :style="{ color: broadcast.fontColor, backgroundColor: broadcast.backgroundColor, fontSize: `${broadcast.fontSize}px` }"><span>{{ broadcast.content }}</span></div>
    </template>
    <Modal v-if="planToSwitch" :open="!!planToSwitch" wrap-class-name="esop-terminal-modal" :closable="false" :title="tr('切换报工订单')" :keyboard="true" :confirm-loading="busy" :ok-text="tr('确认切换')" :cancel-text="tr('取消')" @cancel="planToSwitch = undefined" @ok="confirmPlanSwitch"><p v-if="error" class="form-error" role="alert">{{ error }}</p><p>{{ planToSwitch.orderCode }} · {{ planToSwitch.productName }}</p><p>{{ planToSwitch.planCode }} · {{ planToSwitch.operationName }}</p><p>{{ tr('切换后，作业指导书和报工对象将一起更新。原任务进度保留。') }}</p></Modal>
    <Modal v-if="confirmReport" v-model:open="confirmReport" wrap-class-name="esop-terminal-modal" :closable="false" :title="changeReport ? tr('确认提交修改审核') : tr('确认提交报工')" :keyboard="true" :confirm-loading="busy" :ok-text="tr('确认提交')" :cancel-text="tr('返回修改')" @ok="changeReport ? submitChange().then(() => { if (!error) confirmReport = false; }) : submitReport()"><p v-if="error" class="form-error" role="alert">{{ error }}</p><dl><dt>{{ tr('生产单号') }}</dt><dd>{{ changeReport?.order_code || selectedReportOrder?.orderCode }}</dd><dt>{{ tr('产品名称') }}</dt><dd>{{ changeReport?.product_name || selectedReportOrder?.productName }}</dd><dt>{{ tr('投入') }}</dt><dd>{{ changeReport ? changeForm.input_qty : reportForm.inputQty }}</dd><dt>{{ tr('良品') }}</dt><dd>{{ changeReport ? changeForm.good_qty : reportForm.goodQty }}</dd><dt>{{ tr('不良') }}</dt><dd>{{ changeReport ? changeForm.defect_qty : reportForm.defectQty }}</dd></dl><p>{{ changeReport ? tr('审核通过前，原数据保持有效') : tr('提交后立即生效，请确认数量无误。') }}</p></Modal>
    <Modal v-if="alarmOpen" v-model:open="alarmOpen" wrap-class-name="esop-terminal-modal alarm-dialog" :closable="false" :title="tr('快捷报警')" :keyboard="true" :width="'94vw'" :footer="null"><p v-if="error" class="form-error" role="alert">{{ error }}</p><div class="alarm-workspace"><article class="terminal-panel"><h2>{{ tr('报警提交') }}</h2><div class="panel-scroll alarm-entry"><label v-for="type in alarmTypes" :key="type.code" class="alarm-radio"><input v-model="alarmCode" type="radio" :value="type.code" />{{ type.name }}</label><label class="alarm-reason">{{ tr('说明（选填）') }}<TextArea v-model:value="alarmReason" :maxlength="500" :rows="4" :placeholder="tr('请填写报警情况')" /></label></div><footer><button class="terminal-filled-button" :disabled="busy || !alarmCode" @click="submitAlarm">{{ busy ? tr('提交中…') : tr('确认报警') }}</button></footer></article><article class="terminal-panel"><h2>{{ tr('当前用户的报警记录') }}</h2><div class="alarm-filters"><Select v-model:value="alarmFilterType" allow-clear :placeholder="tr('全部类型')" :options="alarmTypes.map((item) => ({ value: item.code, label: item.name }))" @change="loadAlarms().catch(showError)" /><Select v-model:value="alarmStatus" allow-clear :placeholder="tr('全部状态')" :options="[{ value: 'unresolved', label: tr('未解除') }, { value: 'resolved', label: tr('已解除') }]" @change="loadAlarms().catch(showError)" /></div><div class="alarm-count alarm-history-tools"><span>{{ tf('共 {total} 条', { total: alarmTotal }) }}</span><button class="terminal-text-button" :disabled="alarmsLoading" @click="loadAlarms().catch(showError)">{{ tr('刷新') }}</button></div><div ref="alarmList" class="panel-scroll" @scroll="scrollAlarms"><p v-if="!alarmsLoading && !alarmLoadError && !alarms.length" class="panel-empty">{{ tr('暂无报警记录') }}</p><article v-for="row in alarms" :key="row.id" class="alarm-card"><header><strong>{{ row.type_name || tr('报警') }}</strong><span>{{ row.resolved_at ? tr('已解除') : tr('未解除') }}</span></header><p v-if="row.plan_code">{{ tr('排产编号：') }}{{ row.plan_code }}</p><p v-if="row.order_code">{{ tr('生产单号') }}：{{ row.order_code }}</p><p>{{ row.reason }}</p><footer><span>{{ displayDate(row.occurred_at) }}</span><button v-if="!row.resolved_at" class="terminal-outline-button" :disabled="busy" @click="resolveAlarmId = row.id">{{ tr('解除报警') }}</button></footer></article><p v-if="alarmsLoading" class="history-end" role="status">{{ tr('加载中…') }}</p><p v-else-if="alarmLoadError" class="history-end"><button class="terminal-text-button" @click="loadAlarms(alarmPage === 0).catch(showError)">{{ tr(alarmLoadError) }} · {{ tr('点击重试') }}</button></p><p v-else-if="alarmsEnded && alarms.length" class="history-end">{{ tr('没有更多记录') }}</p></div></article></div><div class="alarm-close"><button class="terminal-text-button" @click="alarmOpen = false">{{ tr('关闭') }}</button></div></Modal>
    <Modal v-if="resolveAlarmId" :open="!!resolveAlarmId" wrap-class-name="esop-terminal-modal" :closable="false" :title="tr('解除报警')" :keyboard="true" :confirm-loading="busy" :ok-text="tr('确认解除')" :cancel-text="tr('取消')" @cancel="resolveAlarmId = undefined" @ok="resolveAlarm(resolveAlarmId!).then(() => { if (!error) resolveAlarmId = undefined; })"><p>{{ tr('确认解除此条报警？') }}</p></Modal>
    <Modal v-if="changeReport && changeKind === 'delete'" :open="true" wrap-class-name="esop-terminal-modal" :closable="false" :title="tr('申请删除报工')" :keyboard="true" :confirm-loading="busy" :ok-button-props="{ disabled: !changeForm.reason.trim() }" :ok-text="tr('提交删除申请')" :cancel-text="tr('取消')" @cancel="changeReport = undefined" @ok="submitChange"><p v-if="error" class="form-error" role="alert">{{ error }}</p><p>{{ tr('生产单号') }}：{{ changeReport?.order_code }}</p><p>{{ tr('产品名称') }}：{{ changeReport?.product_name }}</p><label>{{ tr('删除原因') }}<TextArea v-model:value="changeForm.reason" :maxlength="500" /></label><p>{{ tr('审核通过前，原数据保持有效') }}</p></Modal>
    <Modal v-if="logoutOpen" v-model:open="logoutOpen" wrap-class-name="esop-terminal-modal" :closable="false" :title="tr('logout')" :keyboard="true" :ok-text="tr('确认')" :cancel-text="tr('取消')" @ok="logout(); logoutOpen = false"><p>{{ tr('logoutConfirm') }}</p></Modal>
    <Modal v-if="badgeOpen" v-model:open="badgeOpen" wrap-class-name="esop-terminal-modal staff-badge-dialog" :closable="false" :width="560" :keyboard="true" :footer="null"><div class="badge-heading"><strong>{{ tr('上岗证') }}</strong><button @click="logoutOpen = true">{{ tr('logout') }}</button><button :aria-label="tr('关闭上岗证')" @click="badgeOpen = false">×</button></div><div class="badge-content"><div class="badge-avatar"><img v-if="staff?.avatar && !avatarFailed" :src="staff.avatar" :alt="tr('员工头像')" @error="avatarFailed = true" /><IconifyIcon v-else icon="lucide:user-round" /></div><dl><dt>{{ tr('姓名') }}</dt><dd>{{ staff?.name || '--' }}</dd><dt>{{ tr('工号') }}</dt><dd>{{ staff?.username || '--' }}</dd><dt>{{ tr('岗位') }}</dt><dd>{{ staff?.post || '--' }}</dd><dt>{{ tr('电话') }}</dt><dd>{{ staff?.phoneNumber || '--' }}</dd><dt>{{ tr('入职日期') }}</dt><dd>{{ staff?.hiredate || '--' }}</dd></dl></div></Modal>
  </main>
  </ConfigProvider>
</template>
