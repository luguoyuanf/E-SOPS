<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { DataScreenDashboard } from '../../api/generated/types.gen';

const props = defineProps<{ accessKey: string }>();
const themes = [{ value: 'tech', label: '深色科技' }, { value: 'light', label: '浅色简洁' }, { value: 'business', label: '深蓝商务' }];
const theme = ref('tech');
const root = ref<HTMLElement>();
const lineBody = ref<HTMLElement>();
const orderBody = ref<HTMLElement>();
const data = ref<DataScreenDashboard>();
const workshop = ref('');
const line = ref('');
const loading = ref(false);
const error = ref(false);
const notice = ref('');
const fullscreen = ref(false);
const mobilePanel = ref('orders');
const linePage = ref(0);
const orderPage = ref(0);
const lineSize = ref(3);
const orderSize = ref(3);
let refreshTimer: ReturnType<typeof setInterval> | undefined;
let pageTimer: ReturnType<typeof setInterval> | undefined;
let observer: ResizeObserver | undefined;
let sequence = 0;
const labels: Record<string, string> = { published: '运行中', paused: '已暂停', expired: '异常', waiting: '待产' };
const lines = computed(() => data.value?.lines ?? []);
const orders = computed(() => data.value?.running_orders ?? []);
const linePages = computed(() => Math.max(1, Math.ceil(lines.value.length / lineSize.value)));
const orderPages = computed(() => Math.max(1, Math.ceil(orders.value.length / orderSize.value)));
const visibleLines = computed(() => lines.value.slice(linePage.value * lineSize.value, (linePage.value + 1) * lineSize.value));
const visibleOrders = computed(() => orders.value.slice(orderPage.value * orderSize.value, (orderPage.value + 1) * orderSize.value));
const options = computed(() => data.value?.line_options.filter(item => !workshop.value || item.workshop_id === workshop.value) ?? []);
const progress = computed(() => new Map(data.value?.line_progress.map(item => [item.line_id, item]) ?? []));
const number = (value: number | undefined) => (value ?? 0).toLocaleString('zh-CN');
const fraction = (good: number, planned: number) => planned > 0 ? `${(good / planned * 100).toFixed(1)}%` : '—';
const cards = computed(() => [
  { label: '订单总数', value: data.value?.order_total, unit: '单' },
  { label: '在产订单', value: data.value?.order_running, unit: '单' },
  { label: '已完成订单', value: data.value?.order_completed, unit: '单' },
  { label: '逾期未完成', value: data.value?.order_overdue, unit: '单' },
  { label: '今日完工良品', value: lines.value.reduce((n, item) => n + (item.finished_qty ?? 0), 0), unit: '件' },
  { label: '未处理报警', value: lines.value.reduce((n, item) => n + (item.unresolved_alarms ?? 0), 0), unit: '条' },
]);
const updated = computed(() => data.value ? new Date(data.value.updated_at).toLocaleString('zh-CN', { hour12: false }) : '等待更新');
const latePlans = computed(() => data.value?.plan_counts.find(item => item.key === 'expired')?.count ?? 0);
function measure() {
  for (const [element, size, page, pages] of [[lineBody.value, lineSize, linePage, linePages], [orderBody.value, orderSize, orderPage, orderPages]] as const) {
    if (!element || element.clientHeight === 0) continue;
    const head = element.querySelector('thead')?.getBoundingClientRect().height ?? 30;
    const row = element.querySelector('.data-row')?.getBoundingClientRect().height ?? 42;
    size.value = Math.max(1, Math.floor((element.clientHeight - head - 2) / row));
    page.value = Math.min(page.value, pages.value - 1);
  }
}
function move(kind: 'lines' | 'orders', offset: number) {
  const page = kind === 'lines' ? linePage : orderPage;
  const total = kind === 'lines' ? linePages : orderPages;
  page.value = (page.value + offset + total.value) % total.value;
}
async function refresh() {
  const id = ++sequence;
  loading.value = true;
  try {
    if (!props.accessKey) throw new Error('缺少大屏密钥，请从后台重新打开数据大屏');
    const params = new URLSearchParams({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
    if (workshop.value) params.set('workshop_id', workshop.value);
    if (line.value) params.set('line_id', line.value);
    const response = await fetch(`/api/v1/esop/data-screen/data?${params}`, {
      headers: { 'X-Data-Screen-Key': props.accessKey },
      credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error(response.status === 403
      ? '大屏链接无效、已过期或所属用户已无权限，请从后台重新打开'
      : '数据加载失败，请点击刷新重试');
    const result: DataScreenDashboard = await response.json();
    if (id === sequence) { data.value = result; error.value = false; await nextTick(); measure(); }
  } catch (cause) {
    if (id === sequence) { error.value = true; data.value = undefined; notice.value = cause instanceof Error ? cause.message : '数据加载失败，请重试'; }
  } finally { if (id === sequence) loading.value = false; }
}
function filterChanged() { linePage.value = 0; orderPage.value = 0; refresh(); }
function changeWorkshop() { line.value = ''; filterChanged(); }
function syncFullscreen() { fullscreen.value = document.fullscreenElement === root.value; }
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement === root.value) await document.exitFullscreen();
    else await root.value?.requestFullscreen();
  } catch { notice.value = '当前浏览器暂不支持全屏，请使用浏览器全屏功能'; }
}
watch(theme, value => { try { localStorage.setItem('esop-data-screen-theme', value); } catch { /* Use in-memory preference. */ } });
watch([lineBody, orderBody], () => {
  observer?.disconnect();
  for (const element of [lineBody.value, orderBody.value]) if (element) observer?.observe(element);
  measure();
}, { flush: 'post' });
watch(mobilePanel, async () => { await nextTick(); measure(); });
onMounted(() => {
  try { const stored = localStorage.getItem('esop-data-screen-theme'); if (themes.some(item => item.value === stored)) theme.value = stored!; } catch { /* Use default theme. */ }
  if (typeof ResizeObserver !== 'undefined') observer = new ResizeObserver(measure);
  window.addEventListener('resize', measure);
  document.addEventListener('fullscreenchange', syncFullscreen);
  refresh();
  refreshTimer = setInterval(() => { if (!document.hidden && !loading.value) refresh(); }, 30_000);
  pageTimer = setInterval(() => { if (!document.hidden) { move('lines', 1); move('orders', 1); } }, 10_000);
});
onBeforeUnmount(() => { ++sequence; clearInterval(refreshTimer); clearInterval(pageTimer); observer?.disconnect(); window.removeEventListener('resize', measure); document.removeEventListener('fullscreenchange', syncFullscreen); });
</script>

<template>
  <main ref="root" class="data-screen" :data-theme="theme" :aria-busy="loading">
    <header class="screen-header">
      <div class="heading"><p class="eyebrow">ESOPS · PRODUCTION MONITOR</p><h1>生产数据大屏</h1><p class="muted">{{ updated }} · 数据每 30 秒更新</p></div>
      <div class="controls">
        <select v-model="workshop" aria-label="车间筛选" @change="changeWorkshop"><option value="">全部车间</option><option v-for="item in data?.workshops" :key="item.id" :value="item.id">{{ item.name }}</option></select>
        <select v-model="line" aria-label="产线筛选" @change="filterChanged"><option value="">全部产线</option><option v-for="item in options" :key="item.id" :value="item.id">{{ item.name }}</option></select>
        <select v-model="theme" aria-label="大屏主题"><option v-for="item in themes" :key="item.value" :value="item.value">{{ item.label }}</option></select>
        <button :disabled="loading" @click="refresh">{{ loading ? '更新中…' : '刷新' }}</button><button @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '全屏' }}</button>
      </div>
    </header>
    <div v-if="error" role="alert" class="error">{{ notice }}</div>
    <template v-else-if="data">
      <section class="metrics" aria-label="订单与生产概况"><article v-for="card in cards" :key="card.label"><p class="muted">{{ card.label }}</p><strong>{{ number(card.value) }}</strong><span>{{ card.unit }}</span></article></section>
      <div class="body-grid">
        <div class="tables" :data-mobile-panel="mobilePanel">
          <div class="panel-tabs" role="group" aria-label="切换大屏数据"><button :aria-pressed="mobilePanel === 'orders'" @click="mobilePanel = 'orders'">在产订单</button><button :aria-pressed="mobilePanel === 'lines'" @click="mobilePanel = 'lines'">产线进度</button></div>
          <section class="panel lines-panel">
            <h2>产线计划良品进度 <small>{{ lines.length }} 条产线</small></h2>
            <div ref="lineBody" class="table-body"><table class="line-table"><colgroup><col style="width:30%"><col style="width:14%"><col style="width:17%"><col style="width:26%"><col style="width:13%"></colgroup><thead><tr><th>产线 / 当前 SOP</th><th>状态</th><th>今日良品</th><th>累计良品 / 计划数</th><th>在线设备</th></tr></thead><tbody><tr v-for="item in visibleLines" :key="item.id" class="data-row"><td :title="`${item.name} · ${item.current_sop.join('、')}`"><b>{{ item.name }}</b><p class="muted ellipsis">{{ item.current_sop.join('、') || '暂无发布 SOP' }}</p></td><td><span class="status" :class="item.status">{{ labels[item.status] || item.status }}</span></td><td>{{ number(item.finished_qty) }}</td><td><div class="progress-caption"><b>{{ number(progress.get(item.id)?.good_qty) }} / {{ number(progress.get(item.id)?.planned_qty) }}</b><span>{{ fraction(progress.get(item.id)?.good_qty ?? 0, progress.get(item.id)?.planned_qty ?? 0) }}</span></div><progress :value="progress.get(item.id)?.good_qty" :max="progress.get(item.id)?.planned_qty || 1" /></td><td>{{ item.terminal_online }} / {{ item.terminal_total }}</td></tr></tbody></table><p v-if="!lines.length" class="empty">当前范围暂无产线</p></div>
            <div class="pager"><span>跨日累计 · 按最新发布版本</span><div><button aria-label="上一页产线" :disabled="linePages === 1" @click="move('lines', -1)">‹</button><span>{{ linePage + 1 }} / {{ linePages }}</span><button aria-label="下一页产线" :disabled="linePages === 1" @click="move('lines', 1)">›</button></div></div>
          </section>
          <section class="panel orders-panel">
            <h2>正在生产的订单 <small>{{ data.order_running }} 单 · {{ orders.length }} 条排产</small></h2>
            <div ref="orderBody" class="table-body"><table class="order-table"><colgroup><col style="width:31%"><col style="width:18%"><col style="width:32%"><col style="width:19%"></colgroup><thead><tr><th>订单 / 产品</th><th>产线</th><th>本排产累计良品 / 数量</th><th>订单交期</th></tr></thead><tbody><tr v-for="item in visibleOrders" :key="item.plan_code" class="data-row"><td :title="`${item.order_code} · ${item.product_name}`"><b>{{ item.order_code }}</b><p class="muted ellipsis">{{ item.product_name }}</p></td><td :title="item.line_name">{{ item.line_name }}</td><td :title="`排产 ${item.plan_code}`"><div class="progress-caption"><b>{{ number(item.good_qty) }} / {{ number(item.plan_quantity) }}</b><span>{{ fraction(item.good_qty, item.plan_quantity) }}</span></div><progress :value="item.good_qty" :max="item.plan_quantity || 1" /></td><td :class="{ overdue: item.due_date < data.day }">{{ item.due_date }}</td></tr></tbody></table><p v-if="!orders.length" class="empty">当前范围暂无正在生产的订单</p></div>
            <div class="pager"><span>每 10 秒自动翻页 · 同一订单可分多条排产</span><div><button aria-label="上一页订单" :disabled="orderPages === 1" @click="move('orders', -1)">‹</button><span>{{ orderPage + 1 }} / {{ orderPages }}</span><button aria-label="下一页订单" :disabled="orderPages === 1" @click="move('orders', 1)">›</button></div></div>
          </section>
        </div>
        <aside>
          <section class="panel device-panel"><h2>终端连接</h2><div class="device"><strong>{{ data.terminal_online }}</strong><span class="muted">在线 / {{ data.terminal_total }} 台</span></div><progress :value="data.terminal_online" :max="data.terminal_total || 1"/><p class="muted">离线 {{ data.terminal_total - data.terminal_online }} · 未绑定 {{ data.terminal_unbound }}</p></section>
          <section class="panel alerts-panel"><h2>计划关注</h2><div class="alert-row"><span>今日覆盖计划</span><b>{{ data.plan_counts.reduce((n, item) => n + item.count, 0) }}</b></div><div class="alert-row"><span>逾期计划</span><strong>{{ latePlans }}</strong></div><p class="muted">订单逾期按交期判断</p></section>
          <section class="panel states-panel"><h2>今日计划状态</h2><div class="states"><div v-for="item in data.plan_counts" :key="item.key" class="state-row"><span>{{ item.label }}</span><b>{{ item.count }}</b></div></div></section>
        </aside>
      </div>
      <footer><b>计划良品进度</b>＝今日覆盖计划最新发布版本的累计末道工序良品 ÷ 这些计划的排产数量。<span>订单总数按当前范围统计；在产订单指当前有效发布、未完成且处于计划时段的订单。</span></footer>
    </template>
    <p v-else class="empty loading-message">正在读取生产数据…</p>
  </main>
</template>

<style scoped>
.data-screen{--bg:#081421;--panel:#102338;--ink:#e6f3ff;--muted:#9db2c8;--border:#26435e;--accent:#47d6d0;--gap:clamp(6px,1.3vh,16px);--row-height:clamp(34px,4.5vh,52px);height:100vh;height:100dvh;width:100%;padding:clamp(8px,1.5vw,24px);display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;gap:var(--gap);overflow:hidden;background:var(--bg);color:var(--ink);font-variant-numeric:tabular-nums;font-size:clamp(11px,.85vw,15px)}
.data-screen[data-theme='light']{--bg:#f2f5f8;--panel:#fff;--ink:#162c40;--muted:#536b80;--border:#d8e2ec;--accent:#007f7c}.data-screen[data-theme='business']{--bg:#142145;--panel:#1c3057;--ink:#f2f5ff;--muted:#b1bfdc;--border:#3a5076;--accent:#a9c9ff}.data-screen:fullscreen{width:100vw;height:100dvh;overflow:hidden}
.screen-header{display:flex;justify-content:space-between;gap:12px;align-items:center;min-width:0}h1{font-size:clamp(18px,2vw,30px);font-weight:650;margin:3px 0}h2{font-size:clamp(12px,1vw,17px);font-weight:600;margin:0;display:flex;justify-content:space-between;gap:8px;align-items:center;min-width:0}small{font-size:10px;color:var(--muted);font-weight:400;white-space:nowrap}.eyebrow{font-size:9px;letter-spacing:2px;color:var(--accent)}.muted,footer{color:var(--muted);font-size:clamp(10px,.73vw,12px)}.controls{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;min-width:0}select,button{border:1px solid var(--border);background:var(--panel);color:var(--ink);border-radius:5px;padding:6px 9px;font-size:12px;max-width:170px;min-width:0}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:var(--gap);min-width:0}.metrics article,.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:clamp(8px,1.2vh,16px);min-width:0;min-height:0}.metrics strong{font-size:clamp(20px,3.3vh,42px);color:var(--accent);display:inline-block;margin:5px 6px 0 0;line-height:1.1}.metrics span{color:var(--muted);font-size:11px}.body-grid{display:grid;grid-template-columns:minmax(0,1fr) clamp(190px,20vw,300px);gap:var(--gap);min-height:0;min-width:0}.tables{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr);gap:var(--gap);min-height:0;min-width:0}.tables>.panel{display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:6px}.panel-tabs{display:none}.table-body{min-height:0;min-width:0;overflow:hidden}table{width:100%;table-layout:fixed;border-collapse:collapse;text-align:left;white-space:nowrap;font-size:inherit}thead{height:28px}th{color:var(--muted);font-size:10px;font-weight:500}td,th{padding:4px 6px;border-bottom:1px solid var(--border);overflow:hidden;text-overflow:ellipsis}.data-row{height:var(--row-height)}td b{font-weight:600}.ellipsis{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}.progress-caption{display:flex;justify-content:space-between;gap:6px;font-size:clamp(10px,.8vw,13px)}.progress-caption span{color:var(--accent)}progress{display:block;width:100%;height:5px;margin:5px 0 0;accent-color:var(--accent)}.status{padding:3px 5px;border-radius:4px;border:1px solid currentColor;color:var(--muted);font-size:10px}.status.published{color:var(--accent)}.status.expired,.overdue{color:#e27a6a}.status.paused{color:#dba653}.pager{display:flex;align-items:center;justify-content:space-between;gap:6px;font-size:10px;color:var(--muted);min-width:0}.pager>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pager>div{display:flex;align-items:center;gap:8px;flex-shrink:0}.pager button{padding:0 8px;line-height:20px}
aside{display:grid;grid-template-rows:repeat(3,minmax(0,1fr));gap:var(--gap);min-height:0}.device-panel,.alerts-panel,.states-panel{display:flex;flex-direction:column;justify-content:space-between;gap:4px}.device{display:flex;align-items:baseline;gap:8px}.device strong{font-size:clamp(24px,4.5vh,52px);color:var(--accent);line-height:1}.alert-row,.state-row{display:flex;justify-content:space-between;gap:8px;font-size:clamp(10px,.85vw,14px)}.alert-row strong{color:#dba653}.states{display:grid;grid-template-columns:1fr;gap:clamp(2px,.6vh,10px)}footer{line-height:1.5;min-width:0}footer span{margin-left:10px}footer b{color:var(--ink);font-weight:500}.empty{padding:12px;text-align:center;color:var(--muted)}.loading-message,.error{grid-row:2/5;align-self:center}.error{border:1px solid #d56b6b;padding:20px;color:#e88b8b}
@media(max-width:1100px),(max-height:650px){.body-grid{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr)}aside{grid-row:1;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:1fr}.tables{grid-row:2;grid-template-columns:1fr 1fr;grid-template-rows:minmax(0,1fr)}.states{grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 10px}.device strong{font-size:24px}.device-panel,.alerts-panel,.states-panel{padding:8px}.device-panel progress{display:none}.screen-header .eyebrow{display:none}.metrics article{padding:7px}.metrics strong{font-size:24px}.metrics strong{margin-top:3px}.progress-caption{flex-wrap:wrap;gap:0 4px}.progress-caption span{font-size:10px}.line-table col:first-child{width:26%!important}footer{font-size:10px}.pager{gap:3px}.pager>span{max-width:55%}}
@media(max-width:760px){.screen-header{flex-wrap:wrap;gap:6px}.heading{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.heading h1{font-size:20px}.controls{justify-content:flex-start;width:100%;gap:4px}select,button{padding:4px 6px;font-size:11px;max-width:140px}.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.metrics article{padding:5px 7px}.metrics strong{font-size:22px}.tables{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr);gap:5px}.panel-tabs{display:flex;gap:6px}.panel-tabs button[aria-pressed='true']{color:var(--accent);border-color:var(--accent)}.tables[data-mobile-panel='orders'] .lines-panel,.tables[data-mobile-panel='lines'] .orders-panel{display:none}.tables>.panel{grid-row:2}.states{font-size:10px;gap:2px 6px}.states .state-row{gap:3px;font-size:10px}aside h2{font-size:11px}.device{gap:4px;flex-wrap:wrap}.device strong{font-size:21px}.device-panel,.alerts-panel,.states-panel{padding:6px}.alerts-panel .muted{display:none}.pager>span{max-width:60%}footer span{display:block;margin-left:0}.progress-caption{font-size:11px}.data-screen{padding:8px}.line-table col:first-child{width:28%!important}}
@media(max-height:480px){.data-screen{padding:5px;gap:4px;--gap:4px;--row-height:32px}.screen-header{flex-wrap:nowrap}.heading .muted{display:none}h1{font-size:17px}.metrics{grid-template-columns:repeat(6,minmax(0,1fr))}.metrics article{padding:4px 6px}.metrics strong{font-size:19px}.metrics .muted{font-size:10px}aside .panel{padding:4px 7px}.device strong{font-size:18px}.device-panel .muted,.alerts-panel .muted{font-size:9px}.body-grid{grid-template-rows:auto minmax(0,1fr)}.tables>.panel{padding:5px;gap:3px}h2{font-size:11px}.table-body td{font-size:10px;padding:2px 4px}.table-body th{font-size:9px}thead{height:22px}.pager{font-size:9px}.pager button{line-height:16px}footer{line-height:1.2;font-size:9px}.heading{gap:4px}.controls{width:auto}.progress-caption{font-size:10px}}
@media(min-width:761px) and (max-width:1100px) and (min-height:651px){.tables{grid-template-columns:1fr;grid-template-rows:minmax(0,1fr) minmax(0,1fr)}}
</style>
