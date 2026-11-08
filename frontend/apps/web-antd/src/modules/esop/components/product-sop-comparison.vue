<script setup lang="ts">
import type { Operation } from '../api/esop';
import { computed } from 'vue';
import { Button, Empty, Tag } from 'ant-design-vue';
import { compareProductOperations } from '../utils/product-sop-diff';

const props = defineProps<{ before: Operation[]; after: Operation[] }>();
const emit = defineEmits<{ preview: [operation: Operation, side: number, trigger: HTMLElement] }>();
const differences = computed(() => compareProductOperations(props.before, props.after));
const changed = computed(() => differences.value.filter((item) => item.changes.length));
</script>

<template>
  <p class="mb-4 text-sm text-muted-foreground">本次变更 {{ changed.length }} 道工序；仅展示新增、删除、修改及顺序调整。附件以文件及排列顺序进行比较。</p>
  <Empty v-if="!changed.length" description="本次没有工序变更" />
  <div v-for="item in changed" :key="item.id" class="mb-4 rounded border border-border">
    <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
      <span class="font-medium">{{ item.after?.name ?? item.before?.name }}</span>
      <Tag v-for="change in item.changes" :key="change">{{ change }}</Tag>
    </div>
    <div class="grid grid-cols-1 divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
      <div v-for="(operation, side) in [item.before, item.after]" :key="side" class="min-w-0 p-4">
        <h4 class="mb-3 text-sm text-muted-foreground">{{ side === 0 ? '原版本' : '本次提交' }}</h4>
        <template v-if="operation">
          <p class="break-all font-medium">{{ operation.name }}</p>
          <p class="mt-1 text-sm text-muted-foreground">第 {{ (side === 0 ? before : after).findIndex((entry) => entry.id === operation.id) + 1 }} 道工序</p>
          <p class="mt-1 break-all text-sm">{{ operation.code }}</p>
          <p class="mt-2 whitespace-pre-wrap break-words text-sm">{{ operation.description || '无工序说明' }}</p>
          <div class="mt-3 flex items-center justify-between gap-2"><span class="text-sm text-muted-foreground">附件 {{ operation.attachments.length }} 个</span><Button size="small" type="link" @click="emit('preview', operation, side, $event.currentTarget as HTMLElement)">预览附件</Button></div>
          <ol class="mt-1 list-inside list-decimal text-sm">
            <li v-for="file in operation.attachments" :key="file.file_id" class="break-all">{{ file.name }}</li>
          </ol>
        </template>
        <p v-else class="text-sm text-muted-foreground">{{ side === 0 ? '原版本中不存在此工序' : '本次已删除此工序' }}</p>
      </div>
    </div>
  </div>
</template>
