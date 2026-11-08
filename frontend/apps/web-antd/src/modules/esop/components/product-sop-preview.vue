<script setup lang="ts">
import type { Operation } from '../api/esop';

import { computed, ref, watch } from 'vue';
import { Button, Empty, Modal, Select, Tree } from 'ant-design-vue';
import OperationAttachmentsContent from './operation-attachments-content.vue';

const props = defineProps<{
  open: boolean;
  productId: string;
  title: string;
  operations: Operation[];
  operationPositions?: Record<string, number>;
  operationLabels?: Record<string, string>;
  versionId?: string;
  triggerElement?: HTMLElement;
}>();
const emit = defineEmits<{ 'update:open': [boolean] }>();
const operationId = ref('');
const resolution = ref('1920x1080');
const orientation = computed(() => Number(resolution.value.split('x')[0]) > Number(resolution.value.split('x')[1]) ? 'landscape' : 'portrait');
const resolutions = [
  { value: '1920x1080', label: '1920 × 1080 横屏' },
  { value: '1280x720', label: '1280 × 720 横屏' },
  { value: '1080x1920', label: '1080 × 1920 竖屏' },
  { value: '720x1280', label: '720 × 1280 竖屏' },
];
const mobileTreeOpen = ref(false);
let returnFocus: HTMLElement | undefined;
const operation = computed(() => props.operations.find((item) => item.id === operationId.value));
const nodes = computed(() => props.operations.map((item, index) => ({ key: item.id, title: `${props.operationPositions?.[item.id] ?? index + 1}. ${item.name}${props.operationLabels?.[item.id] ? ` · ${props.operationLabels[item.id]}` : ''}`, count: item.attachments.length })));
function close() { emit('update:open', false); }
function restoreFocus() { returnFocus?.focus(); }
function selectOperation(keys: (number | string)[]) {
  if (!keys.length) return;
  operationId.value = String(keys[0]);
  mobileTreeOpen.value = false;
}
watch(() => props.open, (open) => {
  if (open) {
    returnFocus = props.triggerElement ?? document.activeElement as HTMLElement;
    operationId.value = props.operations[0]?.id ?? '';
    mobileTreeOpen.value = false;
  }
}, { immediate: true });
</script>

<template>
  <Modal :open="open" :title="title" :keyboard="true" :z-index="3200" width="min(1380px, 96vw)" :style="{ top: '24px' }" :footer="null" :after-close="restoreFocus" @cancel="close">
    <template #title><span :title="title" class="line-clamp-2">{{ title }}</span></template>
    <div class="product-preview-layout grid min-w-0 gap-4">
      <aside class="min-w-0 md:border-r md:border-border md:pr-4" aria-label="产品工序">
        <div class="mb-3 hidden items-center justify-between md:flex"><span class="font-medium">工序</span><span class="text-sm text-muted-foreground">{{ operations.length }} 道</span></div>
        <Button class="operation-picker mb-3 w-full" :aria-expanded="mobileTreeOpen" @click="mobileTreeOpen = !mobileTreeOpen"><span class="block max-w-full truncate">{{ mobileTreeOpen ? '收起工序' : `选择工序：${operation?.name || '暂无工序'}` }}</span></Button>
        <div :class="mobileTreeOpen ? 'block' : 'hidden md:block'" class="operation-tree overflow-y-auto">
          <Tree v-if="nodes.length" :tree-data="nodes" :selected-keys="[operationId]" block-node :show-line="false" aria-label="预览工序树" @select="selectOperation">
            <template #title="node"><span class="flex min-w-0 items-start justify-between gap-2"><span class="min-w-0 break-words">{{ node.title }}</span><span class="shrink-0 text-xs text-muted-foreground">{{ node.count }} 附件</span></span></template>
          </Tree>
          <Empty v-else description="暂无工序" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
        </div>
      </aside>
      <section class="min-w-0" aria-label="工序附件">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span :title="operation?.name" class="min-w-0 flex-1 break-words font-medium">{{ operation?.name || '工序附件' }}</span>
          <Select v-model:value="resolution" :options="resolutions" class="w-48" aria-label="终端分辨率与方向" />
        </div>
        <OperationAttachmentsContent :active="open" :product-id="productId" :operation="operation" :version-id="versionId" :orientation="orientation" :resolution="resolution" @close="close" />
      </section>
    </div>
  </Modal>
</template>

<style scoped>
@media (min-width: 768px) { .operation-picker { display: none !important; } .product-preview-layout { grid-template-columns: 240px minmax(0, 1fr); } }
.operation-tree { max-height: calc(100dvh - 200px); }
@media (max-width: 767px) { .operation-tree { max-height: 120px; } }
:deep(.ant-tree-node-content-wrapper) { min-width: 0; }
:deep(.ant-tree-title) { display: block; }
</style>
