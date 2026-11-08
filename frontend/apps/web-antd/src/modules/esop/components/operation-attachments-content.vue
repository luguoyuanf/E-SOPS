<script setup lang="ts">
import type { Operation } from '../api/esop';
import type { AttachmentCategory } from '../utils/operation-attachments';

import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Button, Empty, Spin } from 'ant-design-vue';
import { getProductSopFileAccess } from '../api/product-sops';
import { attachmentCategories, boundPreviewIndex, groupOperationAttachments, operationAttachmentPages } from '../utils/operation-attachments';

const ModelAttachmentViewer = defineAsyncComponent(() => import('./model-attachment-viewer.vue'));

const props = defineProps<{
  active: boolean;
  productId: string;
  operation?: Operation;
  orientation?: string;
  versionId?: string;
  initialFileId?: string;
  resolveFile?: (fileId: string) => Promise<{ url: string; expires_at: string }>;
  resolution?: string;
}>();
const emit = defineEmits<{ close: [] }>();
const category = ref<AttachmentCategory>('image');
const attachmentIndex = ref(0);
const pageIndex = ref(0);
const loading = ref(false);
const error = ref(false);
const downloading = ref(false);
const mediaUrl = ref('');
const mediaType = ref('');
const zoom = ref(100);
const canZoom = computed(() => !!mediaUrl.value && (mediaType.value.startsWith('image/') || mediaType.value === 'application/pdf'));
const pdfUrl = computed(() => `${mediaUrl.value.split('#')[0]}#zoom=${zoom.value}`);
function changeZoom(value: number) { zoom.value = Math.max(50, Math.min(300, value)); }
const resourceUrls = ref<Record<string, string>>({});
const video = ref<HTMLVideoElement>();
const mediaArea = ref<HTMLDivElement>();
const availableScreenHeight = ref(300);
let screenObserver: ResizeObserver | undefined;
const isModel = computed(() => ['cad', 'model3d'].includes(attachment.value?.kind ?? ''));
const portrait = computed(() => props.orientation === 'portrait');
const screenStyle = computed(() => ({
  '--terminal-screen-height': `${availableScreenHeight.value}px`,
  '--terminal-screen-ratio': portrait.value ? String(9 / 16) : String(16 / 9),
  '--terminal-screen-aspect': portrait.value ? '9 / 16' : '16 / 9',
  '--terminal-screen-native-width': `${Number(props.resolution?.split('x')[0]) || (portrait.value ? 1080 : 1920)}px`,
}));
function updateScreenSpace() {
  if (!mediaArea.value) return;
  const viewport = window.visualViewport?.height ?? window.innerHeight;
  availableScreenHeight.value = Math.max(80, viewport - mediaArea.value.getBoundingClientRect().top - 115 - (isModel.value ? 85 : 0));
}
type FileAccess = { url: string; expires_at: string };
const accessCache = new Map<string, Promise<FileAccess>>();
function fileAccess(fileId: string): Promise<FileAccess> {
  const cached = accessCache.get(fileId);
  if (cached) return cached.then((access) => {
    if (Date.parse(access.expires_at) > Date.now() + 30_000) return access;
    accessCache.delete(fileId);
    return fileAccess(fileId);
  });
  const pending = (props.resolveFile ? props.resolveFile(fileId) : getProductSopFileAccess(props.productId, fileId, props.versionId))
    .catch((cause: unknown) => { accessCache.delete(fileId); throw cause; });
  accessCache.set(fileId, pending);
  return pending;
}
let requestId = 0;
const operation = computed(() => props.operation);
const groups = computed(() => groupOperationAttachments(operation.value?.attachments ?? []));
const visibleCategories = computed(() => attachmentCategories.filter((item) => groups.value[item.key].length > 0));
const attachments = computed(() => groups.value[category.value]);
const attachment = computed(() => attachments.value[boundPreviewIndex(attachmentIndex.value, attachments.value.length)]);
const pages = computed(() => operationAttachmentPages(attachment.value));
const currentPage = computed(() => pages.value[boundPreviewIndex(pageIndex.value, pages.value.length)]);
const categoryLabel = computed(() => attachmentCategories.find((item) => item.key === category.value)!.label);

function clearMedia() {
  video.value?.pause();
  mediaUrl.value = '';
  resourceUrls.value = {};
}

async function loadMedia() {
  const id = ++requestId;
  clearMedia();
  error.value = false;
  if (!props.active || !currentPage.value || attachment.value?.kind === 'model_resource') { loading.value = false; return; }
  const page = currentPage.value;
  loading.value = true;
  try {
    const related = ['cad', 'model3d'].includes(attachment.value?.kind ?? '')
      ? operation.value?.attachments.filter((item) => item.kind === 'model_resource' || item.kind === 'image') ?? []
      : [];
    const names = related.map((item) => item.original_name || item.name);
    const unique = related.filter((_, index) => names.indexOf(names[index]!) === names.lastIndexOf(names[index]!));
    const [access, resourceAccess] = await Promise.all([
      fileAccess(page.id),
      Promise.all(unique.map(async (file) => [file.original_name || file.name, (await fileAccess(file.file_id)).url] as const)),
    ]);
    if (id !== requestId || !props.active) return;
    mediaType.value = page.type;
    resourceUrls.value = Object.fromEntries(resourceAccess);
    mediaUrl.value = access.url;
  } catch { if (id === requestId) error.value = true; }
  finally { if (id === requestId) loading.value = false; }
}

function changeAttachment(next: number) {
  clearMedia();
  pageIndex.value = 0;
  attachmentIndex.value = boundPreviewIndex(next, attachments.value.length);
}
function changePage(next: number) { pageIndex.value = boundPreviewIndex(next, pages.value.length); }
function selectCategory(next: AttachmentCategory) {
  if (category.value === next && attachmentIndex.value === 0 && pageIndex.value === 0) return;
  clearMedia();
  attachmentIndex.value = 0;
  pageIndex.value = 0;
  category.value = next;
}
function navigateCategory(event: KeyboardEvent, index: number) {
  let next = index;
  if (event.key === 'ArrowRight') next = (index + 1) % visibleCategories.value.length;
  else if (event.key === 'ArrowLeft') next = (index + visibleCategories.value.length - 1) % visibleCategories.value.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = visibleCategories.value.length - 1;
  else return;
  event.preventDefault();
  const item = visibleCategories.value[next]!;
  selectCategory(item.key);
  (event.currentTarget as HTMLElement).parentElement?.querySelector<HTMLButtonElement>(`[data-category="${item.key}"]`)?.focus();
}
async function downloadOriginal() {
  if (!attachment.value || downloading.value) return;
  downloading.value = true;
  const file = attachment.value;
  try {
    const access = await fileAccess(file.file_id);
    const response = await fetch(access.url, { credentials: 'omit' });
    if (!response.ok) throw new Error('原文件下载失败');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = file.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  } finally { downloading.value = false; }
}
function close() { clearMedia(); emit('close'); }
watch([() => props.active, () => props.operation, () => props.initialFileId], ([active]) => {
  clearMedia();
  attachmentIndex.value = 0;
  pageIndex.value = 0;
  const initial = operation.value?.attachments.find((file) => file.file_id === props.initialFileId);
  category.value = (initial?.kind as AttachmentCategory | undefined) ?? visibleCategories.value[0]?.key ?? 'image';
  if (initial) attachmentIndex.value = Math.max(0, groups.value[category.value].findIndex((file) => file.file_id === initial.file_id));
  if (!active) { requestId++; loading.value = false; }
}, { immediate: true });
watch([() => props.productId, () => props.versionId, () => props.resolveFile], () => accessCache.clear());
watch([() => props.active, () => props.productId, () => props.versionId, () => props.resolveFile, currentPage], () => {
  zoom.value = 100;
  void loadMedia();
}, { immediate: true });
watch([() => props.active, () => props.orientation, () => props.operation, isModel, canZoom], () => void nextTick(updateScreenSpace));
onMounted(() => {
  screenObserver = new ResizeObserver(updateScreenSpace);
  if (mediaArea.value) screenObserver.observe(mediaArea.value);
  window.addEventListener('resize', updateScreenSpace);
  window.visualViewport?.addEventListener('resize', updateScreenSpace);
  void nextTick(updateScreenSpace);
});
onBeforeUnmount(() => {
  requestId++; clearMedia(); screenObserver?.disconnect();
  window.removeEventListener('resize', updateScreenSpace);
  window.visualViewport?.removeEventListener('resize', updateScreenSpace);
});
</script>

<template>
  <div class="attachment-content min-w-0">
    <div v-if="visibleCategories.length" role="tablist" aria-label="附件类型" class="mb-2 flex flex-wrap border-b border-border">
      <button v-for="(item, index) in visibleCategories" :key="item.key" type="button" role="tab" :aria-selected="category === item.key" :tabindex="category === item.key ? 0 : -1" :data-category="item.key" class="min-w-20 border-b-2 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px]" :class="category === item.key ? 'border-primary font-medium text-primary' : 'border-transparent text-muted-foreground'" @click="selectCategory(item.key)" @keydown="navigateCategory($event, index)">{{ item.label }}</button>
    </div>
    <div class="mb-2 flex items-center justify-between gap-2">
      <Button :disabled="attachmentIndex <= 0" aria-label="上一个附件" @click="changeAttachment(attachmentIndex - 1)">上一附件</Button>
      <span class="shrink-0 text-sm" aria-live="polite">{{ attachments.length ? `附件 ${attachmentIndex + 1} / ${attachments.length}` : '附件 0 / 0' }}</span>
      <Button :disabled="attachmentIndex >= attachments.length - 1" aria-label="下一个附件" @click="changeAttachment(attachmentIndex + 1)">下一附件</Button>
    </div>
    <p :title="attachment?.name" class="mb-2 h-6 truncate text-sm">{{ attachment?.name || '当前工序暂无附件' }}</p>
    <div v-if="canZoom" role="group" aria-label="预览缩放" class="mb-2 flex flex-wrap items-center justify-end gap-2">
      <Button :disabled="zoom <= 50" aria-label="缩小预览" @click="changeZoom(zoom - 25)">缩小</Button>
      <span class="min-w-12 text-center text-sm" aria-live="polite">{{ zoom }}%</span>
      <Button :disabled="zoom >= 300" aria-label="放大预览" @click="changeZoom(zoom + 25)">放大</Button>
      <Button :disabled="zoom === 100" aria-label="还原预览比例" @click="changeZoom(100)">还原</Button>
    </div>
    <div ref="mediaArea" role="tabpanel" :aria-label="`${categoryLabel}附件预览`" :style="screenStyle" :class="{ 'attachment-model-stage': isModel }" class="attachment-media relative mx-auto flex items-center justify-center overflow-hidden rounded bg-neutral-950 text-white">
      <Spin v-if="loading" class="absolute inset-0 flex items-center justify-center" />
      <div v-else-if="error" class="p-6 text-center"><p class="mb-3">附件预览加载失败</p><Button @click="loadMedia">重新加载</Button></div>
      <Empty v-else-if="!attachment" description="当前工序暂无附件" :image="Empty.PRESENTED_IMAGE_SIMPLE" class="attachment-empty" />
      <div v-else-if="!currentPage" class="p-6 text-center"><p>此文件尚未生成可预览内容</p><p class="mt-2 text-sm text-neutral-300">可下载原文件查看；工作草稿可生成预览后再打开。</p></div>
      <p v-else-if="attachment.kind === 'model_resource'" class="p-6 text-center">此文件为模型配套资源，请切换到对应的 CAD 或 3D 模型查看。</p>
      <ModelAttachmentViewer v-else-if="mediaUrl && ['cad', 'model3d'].includes(attachment.kind)" :key="attachment.file_id" :url="mediaUrl" :file-name="attachment.original_name || attachment.name" :active="active" :resource-urls="resourceUrls" />
      <div v-else-if="mediaUrl && mediaType.startsWith('image/')" class="h-full w-full overflow-auto" aria-label="可滚动的缩放预览">
        <div class="attachment-zoom-content" :style="{ width: `${zoom}%`, height: `${zoom}%` }">
          <img :src="mediaUrl" :alt="attachment.name" class="h-full w-full object-contain" @error="error = true" />
        </div>
      </div>
      <video v-else-if="mediaUrl && mediaType.startsWith('video/')" ref="video" :key="mediaUrl" :src="mediaUrl" controls playsinline preload="metadata" class="h-full w-full object-contain" @error="error = true" />
      <iframe v-else-if="mediaUrl && mediaType === 'application/pdf'" :src="pdfUrl" :title="attachment.name" class="h-full w-full border-0 bg-white" />
      <p v-else class="p-6">该文件暂不支持在线预览，请下载原文件查看</p>
    </div>
    <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <Button :disabled="pageIndex <= 0" @click="changePage(pageIndex - 1)">上一页</Button>
        <span class="text-sm" aria-live="polite">{{ pages.length ? `文档页 ${pageIndex + 1} / ${pages.length}` : '文档页 0 / 0' }}</span>
        <Button :disabled="pageIndex >= pages.length - 1" @click="changePage(pageIndex + 1)">下一页</Button>
      </div>
      <div class="flex gap-2">
        <Button :disabled="!attachment" :loading="downloading" @click="downloadOriginal">下载原文件</Button>
        <Button @click="close">关闭</Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attachment-media {
  width: min(100%, var(--terminal-screen-native-width), calc(var(--terminal-screen-height) * var(--terminal-screen-ratio)));
  aspect-ratio: var(--terminal-screen-aspect);
}
.attachment-model-stage { width: 100%; min-height: 120px; aspect-ratio: auto; background: transparent; }
.attachment-zoom-content { margin-inline: auto; }
:deep(.attachment-empty .ant-empty-description) { color: #d4d4d4; }
</style>
