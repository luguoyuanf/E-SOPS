<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { Button, Input, Table, Tabs, message } from 'ant-design-vue';

import { requestClient } from '#/api/request';

interface SipPlan {
  releaseId: string;
  operationId: string;
  orderCode: string;
  planCode: string;
  productName: string;
  operationName: string;
  stationName: string;
  stationId: string;
  planQty: number;
  goodQty: number;
  badQty: number;
  reportedQty: number;
  inspectedQty: number;
  availableQty: number;
}

interface SipInspection {
  id: string;
  releaseId: string;
  operationId: string;
  stationId: string;
  quantity: number;
  staffUserId: string;
  createdAt: string;
}

const tab = ref('active');
const keyword = ref('');
const loading = ref(false);
const plans = ref<SipPlan[]>([]);
const inspections = ref<SipInspection[]>([]);
const selected = ref<SipPlan>();
const page = ref(1);
const total = ref(0);
const historyPage = ref(1);
const historyTotal = ref(0);
const columns = [
  { title: '订单', dataIndex: 'orderCode', key: 'orderCode' },
  { title: '排产', dataIndex: 'planCode', key: 'planCode' },
  { title: '产品 / 工序', key: 'task' },
  { title: '工位', dataIndex: 'stationName', key: 'stationName' },
  { title: '计划', dataIndex: 'planQty', key: 'planQty' },
  { title: '良品', dataIndex: 'goodQty', key: 'goodQty' },
  { title: '不良', dataIndex: 'badQty', key: 'badQty' },
  { title: '已报工', dataIndex: 'reportedQty', key: 'reportedQty' },
  { title: '已点检', dataIndex: 'inspectedQty', key: 'inspectedQty' },
  { title: '可点检', dataIndex: 'availableQty', key: 'availableQty' },
  { title: '记录', key: 'records' },
];
const historyColumns = [
  { title: '点检时间', dataIndex: 'createdAt', key: 'createdAt' },
  { title: '点检数量', dataIndex: 'quantity', key: 'quantity' },
  { title: '员工编号', dataIndex: 'staffUserId', key: 'staffUserId' },
];

async function load() {
  loading.value = true;
  try {
    const response = await requestClient.get<{ items: SipPlan[]; total: number }>('/esop/sip/plans', {
      params: { category: tab.value, keyword: keyword.value.trim(), page: page.value },
    });
    plans.value = response.items;
    total.value = response.total;
  } catch {
    message.error('点检排产加载失败');
  } finally {
    loading.value = false;
  }
}

async function showRecords(plan: SipPlan) {
  selected.value = plan;
  historyPage.value = 1;
  await loadRecords();
}

async function loadRecords() {
  const plan = selected.value;
  if (!plan) return;
  try {
    const response = await requestClient.get<{ items: SipInspection[]; total: number }>('/esop/sip/inspections', {
      params: { release_id: plan.releaseId, operation_id: plan.operationId, station_id: plan.stationId, page: historyPage.value },
    });
    inspections.value = response.items;
    historyTotal.value = response.total;
  } catch {
    message.error('点检记录加载失败');
  }
}

function changeTab(value: number | string) {
  tab.value = String(value);
  page.value = 1;
  selected.value = undefined;
  void load();
}

onMounted(load);
</script>

<template>
  <Page title="SIP 点检" description="按订单排产查看成片报工与分次点检数量。良品和不良品均计入可点检数量。">
    <div class="rounded-lg bg-white p-5">
      <Tabs :active-key="tab" @change="changeTab">
        <Tabs.TabPane key="active" tab="排产中" />
        <Tabs.TabPane key="completed" tab="已完成" />
      </Tabs>
      <div class="mb-4 flex gap-2">
        <Input v-model:value="keyword" placeholder="搜索订单、排产或产品" @press-enter="load" />
        <Button type="primary" @click="page = 1; load()">查询</Button>
      </div>
      <Table :columns="columns" :data-source="plans" :loading="loading" :pagination="{ current: page, total, pageSize: 30, onChange: (value: number) => { page = value; load(); } }" :row-key="(row: SipPlan) => `${row.releaseId}-${row.operationId}-${row.stationId}`">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'task'">{{ record.productName }} · {{ record.operationName }}</template>
          <template v-else-if="column.key === 'records'"><Button type="link" @click="showRecords(record as SipPlan)">查看记录</Button></template>
        </template>
      </Table>
      <div v-if="selected" class="mt-6">
        <h3 class="mb-2 text-lg font-semibold">{{ selected.orderCode }} · {{ selected.operationName }} · 点检记录</h3>
        <Table :columns="historyColumns" :data-source="inspections" :pagination="{ current: historyPage, total: historyTotal, pageSize: 30, onChange: (value: number) => { historyPage = value; loadRecords(); } }" row-key="id" />
      </div>
    </div>
  </Page>
</template>
