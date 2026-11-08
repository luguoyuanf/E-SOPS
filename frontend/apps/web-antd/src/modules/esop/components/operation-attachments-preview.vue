<script setup lang="ts">
import type { Operation } from '../api/esop';

import { computed, ref, watch } from 'vue';
import { Modal, Select } from 'ant-design-vue';
import OperationAttachmentsContent from './operation-attachments-content.vue';

const props = defineProps<{
  open: boolean;
  productId: string;
  title: string;
  operations: Operation[];
  versionId?: string;
  triggerElement?: HTMLElement;
  initialFileId?: string;
  resolveFile?: (fileId: string) => Promise<{ url: string; expires_at: string }>;
}>();
const emit = defineEmits<{ 'update:open': [boolean] }>();
const operationId = ref('');
const operation = computed(() => props.operations.find((item) => item.id === operationId.value));
const operationOptions = computed(() => props.operations.map((item, index) => ({ value: item.id, label: `${index + 1}. ${item.name}` })));
let returnFocus: HTMLElement | undefined;
function close() { emit('update:open', false); }
function restoreFocus() { returnFocus?.focus(); }
watch(() => props.open, (open) => {
  if (open) {
    returnFocus = props.triggerElement ?? document.activeElement as HTMLElement;
    operationId.value = (props.operations.find((item) => item.attachments.some((file) => file.file_id === props.initialFileId)) ?? props.operations[0])?.id ?? '';
  }
}, { immediate: true });
</script>

<template>
  <Modal :open="open" :title="title" :keyboard="true" :z-index="3200" width="min(1060px, 96vw)" :style="{ top: '24px' }" :footer="null" :after-close="restoreFocus" @cancel="close">
    <template #title><span :title="title" class="line-clamp-2">{{ title }}</span></template>
    <Select v-if="operations.length > 1" v-model:value="operationId" :options="operationOptions" class="mb-3 w-full" aria-label="选择附件所属工序" />
    <OperationAttachmentsContent :active="open" :product-id="productId" :operation="operation" :version-id="versionId" :initial-file-id="initialFileId" :resolve-file="resolveFile" @close="close" />
  </Modal>
</template>
