<script setup lang="ts">
import type { ECOption } from '@vben/plugins/echarts';
import type {
  DashboardCount,
  DashboardLine,
  DashboardReport,
  EsopDashboard,
} from '../../api/generated/types.gen';
import { computed, onMounted, ref, watch } from 'vue';
import { Button, DatePicker, Select, Spin, Tag } from 'ant-design-vue';
import dayjs from 'dayjs';
import { requestClient } from '#/api/request';
import DashboardChart from './dashboard-chart.vue';

const data = ref<EsopDashboard>();
const loading = ref(false);
const error = ref(false);
const workshopId = ref<string>();
const lineId = ref<string>();
const day = ref(dayjs().format('YYYY-MM-DD'));
const planState = ref('');
const deviceState = ref('');
let requestId = 0;
const colors: Record<string, string> = {
  online: '#079eaa',
  offline: '#f2ac28',
  completed: '#389e65',
  published: '#3186ef',
  draft: '#a2aab7',
  paused: '#dd971a',
  expired: '#d94f4f',
  cancelled: '#c4c9d2',
  waiting: '#98a2b3',
};
const lineLabels: Record<string, string> = {
  published: '运行中',
  paused: '已暂停',
  expired: '异常',
  waiting: '待产',
};
const statusColors: Record<string, string> = {
  published: 'blue',
  paused: 'orange',
  expired: 'red',
  waiting: 'default',
};
const number = (value: number | undefined) =>
  value === undefined ? '—' : value.toLocaleString('zh-CN');
const planTotal = computed(() =>
  data.value?.plan_counts.reduce((sum, row) => sum + row.count, 0),
);
const lineOptions = computed(
  () =>
    data.value?.line_options
      .filter(
        (line) => !workshopId.value || line.workshop_id === workshopId.value,
      )
      .map((line) => ({ value: line.id, label: line.name })) ?? [],
);
const terminalStates = computed(() => [
  { key: 'online', label: '在线', count: data.value?.terminal_online ?? 0 },
  {
    key: 'offline',
    label: '离线',
    count:
      (data.value?.terminal_total ?? 0) - (data.value?.terminal_online ?? 0),
  },
]);
const visibleLines = computed(() =>
  (data.value?.lines ?? []).filter(
    (line) =>
      (!planState.value || (line.plan_counts[planState.value] ?? 0) > 0) &&
      (!deviceState.value ||
        (deviceState.value === 'online'
          ? line.terminal_online > 0
          : line.terminal_total > line.terminal_online)),
  ),
);
const reports = computed(() => {
  const ids = new Set(visibleLines.value.map((line) => line.id));
  const rows = new Map<string, DashboardReport>();
  for (const row of data.value?.reports ?? []) {
    if (!ids.has(row.line_id)) continue;
    const existing = rows.get(row.operation_id);
    if (existing) {
      existing.input_qty += row.input_qty;
      existing.good_qty += row.good_qty;
      existing.defect_qty += row.defect_qty;
      existing.count += row.count;
    } else rows.set(row.operation_id, { ...row });
  }
  return [...rows.values()].sort((a, b) =>
    a.operation_name.localeCompare(b.operation_name, 'zh-CN'),
  );
});
const reportCount = computed(() =>
  reports.value.reduce((sum, row) => sum + row.count, 0),
);
const freshness = computed(() =>
  data.value ? dayjs(data.value.updated_at).format('HH:mm:ss') : '—',
);
const isToday = computed(() => day.value === dayjs().format('YYYY-MM-DD'));
const planTitle = computed(() =>
  isToday.value ? '今日排产计划' : '当日排产计划',
);

async function refresh() {
  const id = ++requestId;
  loading.value = true;
  error.value = false;
  try {
    const result = await requestClient.get<EsopDashboard>('/esop/dashboard', {
      params: {
        day: day.value,
        workshop_id: workshopId.value,
        line_id: lineId.value,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
    });
    if (id === requestId) data.value = result;
  } catch {
    if (id === requestId) {
      error.value = true;
      data.value = undefined;
    }
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(workshopId, () => {
  lineId.value = undefined;
});
watch(
  [workshopId, lineId, day],
  () => {
    planState.value = '';
    deviceState.value = '';
    refresh();
  },
  { flush: 'post' },
);
onMounted(refresh);
function selectLine(line: DashboardLine) {
  lineId.value = line.id;
}
function reset() {
  workshopId.value = undefined;
  lineId.value = undefined;
  day.value = dayjs().format('YYYY-MM-DD');
  planState.value = '';
  deviceState.value = '';
}
function selectMonth(month: string) {
  const end = dayjs(`${month}-01`).endOf('month');
  day.value = (end.isAfter(dayjs()) ? dayjs() : end).format('YYYY-MM-DD');
}
const trendOption = computed<ECOption>(() => ({
  animationDuration: 250,
  color: ['#079eaa'],
  tooltip: {
    trigger: 'axis',
    confine: true,
    valueFormatter: (value) => `${value} 份`,
  },
  grid: { left: 40, right: 22, top: 32, bottom: 53 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: data.value?.sop_trend.map((row) => row.month) ?? [],
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#d9e0e8' } },
    axisLabel: {
      color: '#667085',
      formatter: (value: string) => `${Number(value.slice(5))}月`,
    },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    name: '数量（份）',
    nameTextStyle: { color: '#667085' },
    axisLabel: { color: '#667085' },
    splitLine: { lineStyle: { color: '#e7edf2', type: 'dashed' } },
  },
  dataZoom: [
    { type: 'inside', filterMode: 'none' },
    {
      type: 'slider',
      height: 12,
      bottom: 4,
      borderColor: 'transparent',
      showDetail: false,
    },
  ],
  series: [
    {
      name: '累计生效',
      type: 'line',
      smooth: false,
      symbolSize: 7,
      label: { show: true, color: '#344054', position: 'top' },
      data: data.value?.sop_trend.map((row) => row.count) ?? [],
    },
  ],
}));
function barOption(rows: DashboardCount[]): ECOption {
  return {
    animationDuration: 250,
    tooltip: {
      trigger: 'item',
      confine: true,
      valueFormatter: (value) => `${value}`,
    },
    grid: { left: 0, right: 0, top: 4, bottom: 4 },
    xAxis: {
      type: 'value',
      show: false,
      max: Math.max(
        1,
        rows.reduce((sum, row) => sum + row.count, 0),
      ),
    },
    yAxis: { type: 'category', show: false, data: ['数量'] },
    series: rows.map((row) => ({
      name: row.key,
      type: 'bar',
      stack: 'total',
      barWidth: 20,
      data: [row.count],
      itemStyle: { color: colors[row.key] },
      emphasis: { focus: 'series' },
      tooltip: { formatter: `${row.label}：${row.count}` },
    })),
  };
}
const terminalOption = computed(() => barOption(terminalStates.value));
const planOption = computed(() => barOption(data.value?.plan_counts ?? []));
const selectedPlanLabel = computed(
  () =>
    data.value?.plan_counts.find((row) => row.key === planState.value)?.label,
);
</script>

<template>
  <main class="sop-dashboard">
    <header class="dashboard-header">
      <h1>仪表盘</h1>
      <div class="filters">
        <Select
          v-model:value="workshopId"
          aria-label="车间筛选"
          placeholder="全部车间"
          allow-clear
          :options="
            data?.workshops.map((row) => ({ value: row.id, label: row.name }))
          "
        />
        <Select
          v-model:value="lineId"
          aria-label="产线筛选"
          placeholder="全部产线"
          allow-clear
          show-search
          option-filter-prop="label"
          :options="lineOptions"
        />
        <DatePicker
          v-model:value="day"
          aria-label="统计日期"
          value-format="YYYY-MM-DD"
          :allow-clear="false"
          :disabled-date="(value) => value.isAfter(dayjs(), 'day')"
        />
        <Button @click="reset">重置</Button>
      </div>
      <div class="freshness">
        更新于 {{ freshness }}
        <Button :loading="loading" size="small" @click="refresh">刷新</Button>
      </div>
    </header>
    <div v-if="error" class="error-notice" role="alert">
      统计数据加载失败，请刷新重试。
    </div>
    <Spin :spinning="loading">
      <div class="metrics">
        <section class="metric">
          <span>有效 SOP 数</span>
          <div class="metric-value">
            {{ number(data?.effective_sop) }} <small>份</small>
          </div>
          <p>截至所选日期 · 按产品计数，工序与换版不重复</p>
        </section>
        <section class="metric">
          <span>有效工序数</span>
          <div class="metric-value">
            {{ number(data?.effective_operations) }} <small>道</small>
          </div>
          <p>当前有效产品 SOP 中的工序</p>
        </section>
        <section class="metric">
          <span>产线统计</span>
          <div class="metric-content">
            <div class="metric-value">
              {{ number(data?.lines.length) }} <small>条</small>
            </div>
            <div class="mini-states">
              <span v-for="state in data?.line_counts" :key="state.key"
                ><i :style="{ background: colors[state.key] }"></i
                >{{ state.label }} <b>{{ state.count }}</b></span
              >
            </div>
          </div>
        </section>
        <section class="metric">
          <span>终端设备统计</span>
          <div class="metric-content">
            <div class="metric-value">
              {{ number(data?.terminal_total) }} <small>台</small>
            </div>
            <div class="mini-states">
              <span v-for="state in terminalStates" :key="state.key"
                ><i :style="{ background: colors[state.key] }"></i
                >{{ state.label }}
                <b :style="{ color: colors[state.key] }">{{
                  state.count
                }}</b></span
              ><span
                >未绑定 <b>{{ number(data?.terminal_unbound) }}</b></span
              >
            </div>
          </div>
          <p>当前心跳 · 120 秒内为在线</p>
        </section>
        <section class="metric">
          <span>{{ planTitle }}</span>
          <div class="metric-content">
            <div class="metric-value">
              {{ number(planTotal) }} <small>单</small>
            </div>
            <div class="mini-states plan-mini">
              <span v-for="state in data?.plan_counts" :key="state.key"
                ><i :style="{ background: colors[state.key] }"></i
                >{{ state.label }} <b>{{ state.count }}</b></span
              >
            </div>
          </div>
        </section>
      </div>
      <div v-if="planState || deviceState" class="linked-notice">
        产线与日报联动：{{ selectedPlanLabel }}
        {{
          deviceState === 'online'
            ? '有在线终端'
            : deviceState === 'offline'
              ? '有离线终端'
              : ''
        }}<Button
          size="small"
          @click="
            planState = '';
            deviceState = '';
          "
          >清除状态筛选</Button
        >
      </div>
      <div class="work-grid">
        <section class="panel dispatch-panel">
          <div class="panel-heading">
            <h2>产线调度</h2>
            <span>点击产线查看该线统计 · {{ visibleLines.length }} 条</span>
          </div>
          <div class="table-scroll dispatch-scroll">
            <table>
              <thead>
                <tr>
                  <th>产线编号</th>
                  <th>产线名称</th>
                  <th>终端在线 / 总数</th>
                  <th>当日计划（单）</th>
                  <th>运行状态</th>
                  <th>当前产品 / SOP 版本</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="line in visibleLines"
                  :key="line.id"
                  :class="{ 'selected-row': line.id === lineId }"
                >
                  <td>
                    <button class="line-button" @click="selectLine(line)">
                      {{ line.code }}
                    </button>
                  </td>
                  <td>{{ line.name }}</td>
                  <td>
                    <strong class="teal">{{ line.terminal_online }}</strong> /
                    {{ line.terminal_total }}
                  </td>
                  <td>{{ line.plan_total }}</td>
                  <td>
                    <Tag :color="statusColors[line.status]">{{
                      lineLabels[line.status]
                    }}</Tag>
                  </td>
                  <td class="sop-names" :title="line.current_sop.join('；')">
                    {{ line.current_sop.join('；') || '—' }}
                  </td>
                </tr>
                <tr v-if="!visibleLines.length">
                  <td colspan="6" class="empty">
                    {{ loading ? '正在加载产线…' : '当前筛选下暂无产线' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="panel-footnote">
            运行状态依据所选日期内的排产任务；终端与当前 SOP 展示实时状态。
          </p>
        </section>
        <aside class="status-panels">
          <section class="panel terminal-panel">
            <div class="panel-heading">
              <h2>终端设备状态</h2>
              <span>实时</span>
            </div>
            <div class="status-total">
              总数 <strong>{{ number(data?.terminal_total) }}</strong
              ><small>台</small>
            </div>
            <DashboardChart
              class="status-chart"
              :option="terminalOption"
              @select="(key) => (deviceState = deviceState === key ? '' : key)"
            />
            <div class="status-legend">
              <button
                v-for="state in terminalStates"
                :key="state.key"
                :class="{ active: deviceState === state.key }"
                :aria-pressed="deviceState === state.key"
                @click="
                  deviceState = deviceState === state.key ? '' : state.key
                "
              >
                <i :style="{ background: colors[state.key] }"></i
                >{{ state.label }}
                <b :style="{ color: colors[state.key] }">{{ state.count }}</b
                ><small>{{
                  data?.terminal_total
                    ? `${((state.count / data.terminal_total) * 100).toFixed(2)}%`
                    : '—'
                }}</small>
              </button>
            </div>
            <p class="unbound">
              其中未绑定 <b>{{ number(data?.terminal_unbound) }}</b
              ><small>台 · 与在线状态独立统计</small>
            </p>
          </section>
          <section class="panel plan-panel">
            <div class="panel-heading">
              <h2>当日计划状态</h2>
              <span>点击状态联动</span>
            </div>
            <div class="status-total">
              总数 <strong>{{ number(planTotal) }}</strong
              ><small>单</small>
            </div>
            <DashboardChart
              class="status-chart"
              :option="planOption"
              @select="(key) => (planState = planState === key ? '' : key)"
            />
            <div class="status-legend plan-legend">
              <button
                v-for="state in data?.plan_counts"
                :key="state.key"
                :class="{ active: planState === state.key }"
                :aria-pressed="planState === state.key"
                @click="planState = planState === state.key ? '' : state.key"
              >
                <i :style="{ background: colors[state.key] }"></i
                >{{ state.label }} <b>{{ state.count }}</b>
              </button>
            </div>
          </section>
        </aside>
      </div>
      <div class="bottom-grid">
        <section class="panel trend-panel">
          <div class="panel-heading">
            <h2>SOP 累计生效趋势</h2>
            <span>近 6 个月 · 按产品首次生效计数</span>
          </div>
          <div class="trend-content">
            <DashboardChart
              class="trend-chart"
              :option="trendOption"
              @select="selectMonth"
            />
            <div class="trend-summary">
              <span>累计首次生效</span
              ><strong class="teal"
                >{{ number(data?.cumulative_sop) }} <small>份</small></strong
              ><span>当前有效</span
              ><strong
                >{{ number(data?.effective_sop) }} <small>份</small></strong
              >
            </div>
          </div>
          <p class="panel-footnote">
            点击月份查看当月末统计；拖动底部滑块缩放。车间 /
            产线筛选按曾排产产品统计。
          </p>
        </section>
        <section class="panel report-panel">
          <div class="panel-heading">
            <h2>日工序报工</h2>
            <span>{{ day }}</span>
          </div>
          <div class="table-scroll report-scroll">
            <table>
              <thead>
                <tr>
                  <th>工序</th>
                  <th>投入（件）</th>
                  <th>良品（件）</th>
                  <th>不良（件）</th>
                  <th>报工（笔）</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in reports" :key="row.operation_id">
                  <td>{{ row.operation_name }}</td>
                  <td>{{ number(row.input_qty) }}</td>
                  <td>{{ number(row.good_qty) }}</td>
                  <td>{{ number(row.defect_qty) }}</td>
                  <td>{{ row.count }}</td>
                </tr>
                <tr v-if="!reports.length">
                  <td colspan="5" class="empty">
                    {{ loading ? '正在加载报工…' : '当日暂无有效报工记录' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <footer class="report-footer">
            <span>工序数量不汇总为成品产量</span
            ><span
              >合计报工
              <strong class="teal">{{ number(reportCount) }}</strong> 笔</span
            >
          </footer>
        </section>
      </div>
    </Spin>
  </main>
</template>

<style scoped>
.sop-dashboard {
  --ink: #182230;
  --muted: #667085;
  --border: #e5eaf0;
  --teal: #079eaa;
  background: #f5f7fa;
  color: var(--ink);
  padding: 20px;
  min-height: 100%;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.dashboard-header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.dashboard-header h1 {
  font-size: 24px;
  font-weight: 650;
  margin: 0;
  margin-right: auto;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.filters :deep(.ant-select) {
  width: 155px;
}
.freshness {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
}
.metrics {
  display: grid;
  grid-template-columns: 0.8fr 0.8fr 1.2fr 1.35fr 1.6fr;
  gap: 14px;
  margin-bottom: 16px;
}
.metric,
.panel {
  background: white;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.metric {
  padding: 14px 16px;
  min-height: 116px;
}
.metric > span {
  font-size: 16px;
  font-weight: 550;
}
.metric-value {
  font-size: 32px;
  line-height: 1.2;
  font-weight: 600;
  white-space: nowrap;
  margin-top: 8px;
}
.metric-value small {
  font-size: 14px;
  font-weight: 400;
}
.metric p {
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.metric-content {
  display: flex;
  align-items: center;
  gap: 18px;
  justify-content: space-between;
}
.mini-states {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 10px;
  max-width: 220px;
  font-size: 12px;
  color: var(--muted);
}
.mini-states span {
  white-space: nowrap;
}
.mini-states b {
  margin-left: 4px;
  color: var(--ink);
}
i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}
.work-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(290px, 1fr);
  gap: 16px;
}
.panel {
  padding: 14px;
}
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.panel-heading h2 {
  line-height: 1.5;
  font-size: 17px;
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
}
.panel-heading > span {
  font-size: 12px;
  color: var(--muted);
}
.table-scroll {
  overflow: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th {
  background: #f8fafc;
  color: var(--muted);
  font-weight: 500;
  white-space: nowrap;
}
th,
td {
  text-align: center;
  padding: 11px 10px;
  border-bottom: 1px solid #ecf0f4;
}
tbody tr:hover {
  background: #f7fbfc;
}
.dispatch-scroll {
  max-height: 280px;
  min-height: 180px;
}
.dispatch-scroll table {
  min-width: 720px;
}
.dispatch-scroll th {
  position: sticky;
  top: 0;
  z-index: 1;
}
.sop-names {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.line-button {
  color: #147da6;
  background: none;
  border: 0;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.selected-row {
  background: #eaf8f8;
}
.teal {
  color: var(--teal);
}
.status-panels {
  display: grid;
  gap: 12px;
  grid-template-rows: auto auto;
}
.status-total {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--muted);
}
.status-total strong {
  font-size: 27px;
  color: var(--ink);
  font-weight: 600;
}
.status-total small {
  font-size: 12px;
}
.status-chart {
  height: 28px !important;
  width: 100%;
}
.status-legend {
  display: flex;
  gap: 8px 12px;
  flex-wrap: wrap;
}
.status-legend button {
  line-height: 1.4;
  background: none;
  border: 1px solid transparent;
  padding: 4px 5px;
  color: var(--muted);
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 5px;
}
.status-legend button i {
  margin-right: 0;
}
.status-legend button b {
  font-size: 16px;
  color: var(--ink);
}
.status-legend button small {
  font-size: 11px;
}
.status-legend button:hover,
.status-legend button.active {
  background: #edf8f9;
  border-color: #bee3e6;
}
.unbound {
  border-top: 1px solid var(--border);
  padding-top: 10px;
  margin: 9px 0 0;
  color: var(--muted);
}
.unbound b {
  color: var(--ink);
  margin-left: 7px;
}
.unbound small {
  font-size: 11px;
  margin-left: 8px;
}
.plan-legend {
  gap: 0 8px;
}
.plan-legend button {
  font-size: 12px;
}
.plan-legend button b {
  font-size: 14px;
}
.bottom-grid {
  display: grid;
  grid-template-columns: 1.08fr 1fr;
  gap: 16px;
  margin-top: 16px;
}
.trend-content {
  display: flex;
  align-items: center;
}
.trend-chart {
  height: 180px !important;
  min-width: 0;
  flex: 1;
}
.trend-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-left: 1px solid var(--border);
  padding-left: 20px;
  margin-left: 10px;
  min-width: 122px;
}
.trend-summary span {
  font-size: 14px;
}
.trend-summary strong {
  font-size: 30px;
  font-weight: 600;
  margin-bottom: 8px;
}
.trend-summary small {
  font-size: 13px;
  font-weight: 400;
}
.panel-footnote {
  font-size: 11px;
  color: var(--muted);
  margin: 12px 0 0;
}
.report-scroll {
  height: 170px;
}
.report-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding-top: 16px;
  color: var(--muted);
  font-size: 12px;
}
.report-footer strong {
  font-size: 24px;
  margin: 0 7px;
}
.empty {
  height: 110px;
  color: var(--muted);
  text-align: center;
}
.linked-notice {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0 16px;
  color: #087f8b;
}
.error-notice {
  padding: 12px;
  color: #a12c2c;
  background: #fff1f0;
  margin-bottom: 16px;
}
@media (min-width: 1800px) {
  .dispatch-scroll {
    max-height: 360px;
    min-height: 220px;
  }
  th,
  td {
    padding: 14px 12px;
  }
  .trend-chart {
    height: 220px !important;
  }
  .report-scroll {
    height: 210px;
  }
}
@media (max-width: 1250px) {
  .metrics {
    grid-template-columns: 1fr 1fr;
  }
  .dashboard-header h1 {
    width: 100%;
    margin-right: 0;
  }
  .metric {
    min-height: 128px;
  }
  .work-grid {
    grid-template-columns: minmax(0, 1.8fr) minmax(280px, 1fr);
  }
  .bottom-grid {
    grid-template-columns: 1fr;
  }
  .report-scroll {
    height: auto;
    max-height: 280px;
  }
}
@media (max-width: 800px) {
  .sop-dashboard {
    padding: 14px;
  }
  .work-grid {
    grid-template-columns: 1fr;
  }
  .status-panels {
    grid-template-columns: 1fr 1fr;
  }
  .metric-value {
    font-size: 30px;
  }
  .metric {
    padding: 14px;
  }
  .metric-content {
    gap: 8px;
    align-items: flex-start;
    flex-direction: column;
  }
  .mini-states {
    margin-top: 0;
  }
  .filters :deep(.ant-select) {
    width: 135px;
  }
  .trend-summary {
    min-width: 100px;
    padding-left: 12px;
  }
  .panel-heading {
    align-items: flex-start;
  }
  .panel-heading > span {
    max-width: 150px;
    text-align: right;
  }
}
@media (max-width: 560px) {
  .filters {
    gap: 8px;
    width: 100%;
  }
  .filters :deep(.ant-select) {
    width: calc(50% - 4px);
  }
  .metrics {
    gap: 10px;
  }
  .status-panels {
    grid-template-columns: 1fr;
  }
  .panel {
    padding: 14px;
  }
  .panel-heading h2 {
    font-size: 16px;
  }
  .trend-content {
    flex-direction: column;
    align-items: stretch;
  }
  .trend-summary {
    border-left: 0;
    border-top: 1px solid var(--border);
    padding: 12px 0 0;
    margin: 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .trend-summary strong {
    font-size: 24px;
    grid-row: 2;
  }
  .trend-summary span:nth-of-type(2) {
    grid-column: 2;
    grid-row: 1;
  }
  .report-scroll table {
    min-width: 450px;
  }
  .report-footer {
    align-items: flex-start;
    flex-direction: column;
  }
  .dispatch-scroll {
    height: 300px;
  }
  .freshness {
    margin-left: auto;
  }
  .linked-notice {
    flex-wrap: wrap;
  }
}
</style>
