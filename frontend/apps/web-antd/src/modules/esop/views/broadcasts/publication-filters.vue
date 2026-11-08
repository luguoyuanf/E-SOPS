<script lang="ts" setup>
import type { PublicationFilters, PublicationStatus } from '../../api/broadcast';
import { Button, DatePicker, Input, Select } from 'ant-design-vue';
const filters = defineModel<PublicationFilters>({ required: true });
withDefaults(defineProps<{ loading: boolean; placeholder: string; statusOptions?: { value: PublicationStatus; label: string }[] }>(), {
  statusOptions: () => [{ value: 'active', label: '运行中' }, { value: 'paused', label: '已暂停' }],
});
const emit = defineEmits<{ search: [] }>();
function reset() { filters.value = { keyword: '' }; emit('search'); }
</script>
<template>
  <div class="mb-4 flex flex-wrap items-end gap-3">
    <label class="flex flex-col gap-1"><span class="text-sm">关键词</span><Input v-model:value="filters.keyword" :placeholder="placeholder" allow-clear style="width: 220px; max-width: 100%" @press-enter="emit('search')" /></label>
    <label class="flex flex-col gap-1"><span class="text-sm">状态</span><Select v-model:value="filters.status" :options="statusOptions" allow-clear placeholder="全部状态" style="width: 140px" /></label>
    <div class="flex min-w-0 flex-col gap-1"><span class="text-sm">发布时间</span><DatePicker.RangePicker v-model:value="filters.created_range" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" style="max-width: 100%" /></div>
    <Button type="primary" :loading="loading" @click="emit('search')">查询</Button><Button :disabled="loading" @click="reset">重置</Button>
  </div>
</template>
