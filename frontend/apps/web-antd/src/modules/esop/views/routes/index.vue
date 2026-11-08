<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { Operation, ProcessRoute } from '../../api/esop';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Drawer, Form, Input, message, Select } from 'ant-design-vue';

import { listOperations, listRoutes, saveRoute } from '../../api/esop';

const rows = ref<ProcessRoute[]>([]);
const operations = ref<Operation[]>([]);
const loading = ref(false);
const saving = ref(false);
const open = ref(false);
const editingId = ref<string>();
const form = reactive({ code: '', name: '', operation_ids: [] as string[] });
const columns = [
  { title: '流程编码', dataIndex: 'code', key: 'code' },
  { title: '工艺流程', dataIndex: 'name', key: 'name' },
  { title: '工序数', key: 'count', width: 100 },
  { title: '操作', key: 'action', width: 100 },
];
const options = computed(() => operations.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const operationNames = computed(() => new Map(operations.value.map((item) => [item.id, item.name])));

async function refresh() {
  loading.value = true;
  try {
    const [routeResult, operationResult] = await Promise.all([listRoutes(), listOperations()]);
    rows.value = routeResult.items;
    operations.value = operationResult.items;
  } finally {
    loading.value = false;
  }
}

function edit(row?: ProcessRoute) {
  editingId.value = row?.id;
  form.code = row?.code ?? '';
  form.name = row?.name ?? '';
  form.operation_ids = [...(row?.operation_ids ?? [])];
  open.value = true;
}

function close() { open.value = false; }

function move(index: number, direction: -1 | 1) {
  const next = index + direction;
  if (next < 0 || next >= form.operation_ids.length) return;
  [form.operation_ids[index], form.operation_ids[next]] = [form.operation_ids[next]!, form.operation_ids[index]!];
}

async function save() {
  if (!form.name.trim() || form.operation_ids.length === 0) {
    message.warning('请填写流程并选择至少一道工序');
    return;
  }
  saving.value = true;
  try {
    await saveRoute({ code: form.code.trim(), name: form.name.trim(), operation_ids: form.operation_ids }, editingId.value);
    close();
    await refresh();
    message.success('工艺流程已保存');
  } finally {
    saving.value = false;
  }
}

onMounted(() => void refresh());
</script>

<template>
  <Page title="工艺流程">
    <div class="mb-4 flex items-center justify-end">
      <Button v-access:code="'esop:route:create'" type="primary" @click="edit()">新增流程</Button>
    </div>
    <Table date-field="created_at" :columns="columns" :data-source="rows" :loading="loading" :pagination="false" row-key="id">
      <template #bodyCell="{ column, record }">
        <span v-if="column.key === 'count'">{{ (record as ProcessRoute).operation_ids.length }}</span>
        <Button v-else-if="column.key === 'action'" v-access:code="'esop:route:update'" type="link" @click="edit(record as ProcessRoute)">编辑</Button>
      </template>
    </Table>

    <Drawer :open="open" :keyboard="true" :title="editingId ? '编辑工艺流程' : '新增工艺流程'" width="min(560px, 100vw)" @close="close">
      <Form :model="form" layout="vertical">
        <Form.Item label="流程编码"><Input v-model:value="form.code" placeholder="留空自动生成" :maxlength="64" /></Form.Item>
        <Form.Item label="流程名称" required><Input v-model:value="form.name" :maxlength="120" /></Form.Item>
        <Form.Item label="包含工序" required>
          <Select v-model:value="form.operation_ids" mode="multiple" :options="options" placeholder="选择工序后调整顺序" />
        </Form.Item>
      </Form>
      <ol class="space-y-2" aria-label="工序顺序">
        <li v-for="(id, index) in form.operation_ids" :key="id" class="flex items-center justify-between rounded bg-[var(--vben-bg-color)] px-3 py-2">
          <span>{{ operationNames.get(id) || id }}</span>
          <span class="flex gap-1">
            <Button size="small" :disabled="index === 0" :aria-label="`将${operationNames.get(id)}上移`" @click="move(index, -1)">上移</Button>
            <Button size="small" :disabled="index === form.operation_ids.length - 1" :aria-label="`将${operationNames.get(id)}下移`" @click="move(index, 1)">下移</Button>
          </span>
        </li>
      </ol>
      <template #footer>
        <Button class="mr-2" @click="close">取消</Button>
        <Button :loading="saving" type="primary" @click="save">保存</Button>
      </template>
    </Drawer>
  </Page>
</template>
