<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Card, Table, message } from 'ant-design-vue';
import { listGoogleBindingsApi, type GoogleBindingRecord } from '#/api';

const rows = ref<GoogleBindingRecord[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
async function load(next = page.value, size = pageSize.value) {
  loading.value = true;
  try {
    const result = await listGoogleBindingsApi({ page: next, page_size: size });
    rows.value = result.items;
    total.value = result.total;
    page.value = result.page;
    pageSize.value = result.page_size;
  } catch { message.error('获取 Google 绑定记录失败'); }
  finally { loading.value = false; }
}
const columns = [
  { title: '企业标识', dataIndex: 'tenant_id', key: 'tenant_id' },
  { title: '管理员标识', dataIndex: 'user_id', key: 'user_id' },
  { title: '绑定时间', dataIndex: 'created_at', key: 'created_at' },
];
onMounted(() => void load());
</script>

<template>
  <Card title="Google 租户绑定记录" class="mb-4">
    <p class="mb-3">Google 登录仅供租户管理员使用。绑定记录不可解绑或删除。</p>
    <Table :data-source="rows" :columns="columns" :loading="loading" row-key="id" :scroll="{ x: 700 }" :pagination="{ current: page, pageSize, total, showSizeChanger: true, onChange: load }" />
  </Card>
</template>
