<script setup lang="ts">
import type { TerminalAttachment, TerminalTask } from './client';
import type { TerminalLocale } from './locale';
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue';
import IconifyIcon from './terminal-icon.vue';
import terminalLogo from './esops-logo.png';
import { terminalText } from './locale';
const ModelViewer = defineAsyncComponent(() => import('../../components/model-attachment-viewer.vue'));
const props = defineProps<{
  task?: TerminalTask; locale?: TerminalLocale; selectedId?: string; catalog?: boolean; stationLabel: string;
  resolveFile: (id: string) => Promise<{ url: string }>;
}>();
const tr = (key: string) => terminalText(props.locale ?? 'zh', key);
const index = ref(0);
const chosenId = ref<string>();
const kind = ref<string>();
const loading = ref(false);
const error = ref('');
const url = ref('');
const resources = ref<Record<string, string>>({});
const host = ref<HTMLElement>();
const zoom = ref(100);
let generation = 0;
const kindLabels = computed<Record<string, string>>(() => ({ image: tr('图片'), pdf: 'PDF', word: 'Word', excel: 'Excel', ppt: 'PPT', video: tr('视频'), cad: 'CAD', model3d: tr('3D模型') }));
const files = computed<TerminalAttachment[]>(() => props.task?.attachments?.length ? props.task.attachments : (props.task?.pages ?? []).map((page, i) => ({ id: page.fileId, name: tr('指导书 {number}').replace('{number}', String(i + 1)), kind: 'image', mimeType: 'image/png', size: 0, pages: [page] })));
const kinds = computed(() => [...new Set(files.value.map((file) => file.kind))]);
const visibleFiles = computed(() => props.catalog && kind.value ? files.value.filter((file) => file.kind === kind.value) : files.value);
const selected = computed(() => files.value.find((file) => file.id === (props.catalog ? chosenId.value : props.selectedId)) ?? visibleFiles.value[0]);
const pages = computed(() => selected.value?.pages?.length ? selected.value.pages : selected.value ? [{ fileId: selected.value.id, url: '' }] : []);
const isModel = computed(() => ['cad', 'model3d', '3d', 'model'].includes(selected.value?.kind ?? ''));
async function load() {
  const request = ++generation;
  url.value = ''; error.value = ''; resources.value = {};
  if (!selected.value) { loading.value = false; return; }
  if (isModel.value && !props.catalog) return;
  loading.value = true;
  try {
    const file = pages.value[index.value];
    if (!file) return;
    const result = await props.resolveFile(file.fileId);
    const related: Record<string, string> = {};
    if (isModel.value) for (const item of props.task?.resources ?? []) related[item.name] = (await props.resolveFile(item.id)).url;
    if (request === generation) { url.value = result.url; resources.value = related; }
  } catch (cause) { if (request === generation) error.value = tr(cause instanceof Error ? cause.message : '文件加载失败'); }
  finally { if (request === generation) loading.value = false; }
}
function changePage(next: number) { index.value = Math.max(0, Math.min(next, pages.value.length - 1)); }
function advancePage() { if (!loading.value && selected.value?.kind !== 'video' && pages.value.length > 1) index.value = (index.value + 1) % pages.value.length; }
function selectKind(value: string) { kind.value = value; chosenId.value = files.value.find((file) => file.kind === value)?.id; }
function fullscreen() { void host.value?.requestFullscreen(); }
watch(() => props.task?.sopId, () => { chosenId.value = undefined; kind.value = undefined; index.value = 0; zoom.value = 100; });
watch(() => selected.value?.id, () => { index.value = 0; });
watch([() => selected.value?.id, index], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; });
defineExpose({ advancePage });
</script>
<template>
  <div ref="host" class="terminal-media" :class="{ 'catalog-media': catalog }">
    <template v-if="catalog && task">
      <div class="catalog-media-heading"><strong>{{ task.productName || task.productCode }} / {{ task.operationName }}</strong><button class="terminal-text-button" @click="fullscreen"><IconifyIcon icon="lucide:maximize" />{{ tr('全屏查看') }}</button></div>
      <div class="file-kind-tabs"><button v-for="item in kinds" :key="item" :class="{ selected: selected?.kind === item }" @click="selectKind(item)">{{ kindLabels[item] || item }}　{{ files.filter((file) => file.kind === item).length }}</button></div>
      <div class="file-name-tabs"><button v-for="file in visibleFiles" :key="file.id" :class="{ selected: selected?.id === file.id }" @click="chosenId = file.id">{{ file.name }}</button></div>
    </template>
    <div v-if="!task && !catalog" class="terminal-waiting">
      <span class="waiting-circle top" /><span class="waiting-circle bottom" />
      <div class="waiting-content"><img :src="terminalLogo" alt="ESOPS" /><i /><strong>{{ tr('tagline') }}</strong><p class="waiting-title">{{ tr('waitingWorkDispatch') }}</p><p>{{ tr('waitingWorkDispatchHint') }}</p><p class="waiting-station">{{ stationLabel }}</p></div>
    </div>
    <div v-else-if="!task" class="media-empty">{{ tr('请从左侧选择产品工序查看作业指导书') }}</div>
    <template v-else>
      <div class="document-stage">
        <div v-if="loading" class="media-empty">{{ tr('正在加载…') }}</div>
        <div v-else-if="error" class="media-empty"><p>{{ error }}</p><button class="terminal-outline-button" @click="load">{{ tr('重新加载') }}</button></div>
        <div v-else-if="isModel && !catalog" class="media-empty">{{ tr('此文件暂不支持在终端查看') }}</div>
        <ModelViewer class="terminal-model-viewer" v-else-if="isModel && url" :url="url" :file-name="selected?.name || ''" :resource-urls="resources" :active="true" :translate="tr" />
        <video v-else-if="selected?.kind === 'video' && url" :key="url" :src="url" autoplay controls loop playsinline />
        <div v-else-if="url" class="document-scroll"><div class="document-zoom" :style="{ width: `${zoom}%`, height: `${zoom}%` }"><img :src="url" :alt="selected?.name" /></div></div>
        <div v-else class="media-empty">{{ tr('当前工序暂无可展示的指导书页面') }}</div>
      </div>
      <footer v-if="selected?.kind !== 'video' && !isModel" class="document-pagination"><button class="terminal-outline-button" :disabled="index <= 0" @click="changePage(index - 1)"><IconifyIcon icon="lucide:chevron-left" />{{ tr('上一页') }}</button><span>{{ pages.length ? index + 1 : 0 }} / {{ pages.length }}</span><button class="terminal-outline-button" :disabled="index >= pages.length - 1" @click="changePage(index + 1)"><IconifyIcon icon="lucide:chevron-right" />{{ tr('下一页') }}</button><template v-if="catalog"><button class="terminal-text-button" :aria-label="tr('缩小')" @click="zoom = Math.max(25, zoom - 25)">−</button><span>{{ zoom }}%</span><button class="terminal-text-button" :aria-label="tr('放大')" @click="zoom = Math.min(300, zoom + 25)">＋</button></template></footer>
    </template>
  </div>
</template>
<style scoped>
.document-stage :deep(.model-viewer) { height: 100%; overflow: hidden; }
.document-stage :deep(.model-screen) { flex: 1 1 0; position: relative; min-height: 0; width: 100%; aspect-ratio: auto; overflow: hidden; }
.document-stage :deep(.model-viewer.terminal-model-viewer:fullscreen .model-screen) { width: 100%; }
.document-stage :deep(.model-screen > .ant-spin), .document-stage :deep(.model-screen > [role="alert"]) { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: #fff; }

.terminal-media{display:flex;flex-direction:column;min-width:0;min-height:0;height:100%;background:#f4f1eb}.terminal-media:fullscreen{background:#fff;width:100vw;height:100vh}.terminal-waiting{height:100%;position:relative;overflow:hidden;display:grid;place-items:center;background:linear-gradient(135deg,#f7f4ee,#ecfdf5,#f4f1eb)}.waiting-circle{position:absolute;border-radius:50%;pointer-events:none}.waiting-circle.top{width:220px;height:220px;right:-40px;top:-30px;background:#0596690f}.waiting-circle.bottom{width:260px;height:260px;left:-50px;bottom:-60px;background:#d977060d}.waiting-content{max-width:480px;width:100%;padding:0 36px;text-align:center;z-index:1}.waiting-content img{width:400px;max-width:100%;height:166px;object-fit:contain;margin:0 auto}.waiting-content i{display:block;width:36px;height:3px;background:#059669;margin:14px auto 18px}.waiting-content strong{display:block;color:#047857;font-size:calc(18px * var(--terminal-text-scale,1));font-weight:600;letter-spacing:1.2px}.waiting-content p{font-size:calc(13px * var(--terminal-text-scale,1));color:#737373;line-height:1.4;margin:10px 32px 0}.waiting-content .waiting-title{margin:28px 0 0;font-size:calc(15px * var(--terminal-text-scale,1));letter-spacing:2px}.waiting-content .waiting-station{margin-top:20px}.document-stage{flex:1;min-height:0;position:relative}.document-scroll{overflow:auto;width:100%;height:100%}.document-zoom{margin-inline:auto}.document-scroll img{width:100%;height:100%;max-width:none;display:block;object-fit:contain}.document-stage video{width:100%;height:100%;object-fit:contain;background:#000}.media-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;height:100%;color:#737373}.document-pagination{height:58px;flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:24px;font-size:calc(18px * var(--terminal-text-scale,1))}.catalog-media{background:#fff}.catalog-media-heading{display:flex;justify-content:space-between;align-items:center;padding:12px 18px 0;font-size:calc(20px * var(--terminal-text-scale,1))}.file-kind-tabs,.file-name-tabs{display:flex;align-items:center;gap:8px;overflow:auto;white-space:nowrap;flex-shrink:0;padding:8px;height:52px}.file-kind-tabs button,.file-name-tabs button{border:1px solid #879398;border-radius:8px;padding:7px 12px;font-size:calc(14px * var(--terminal-text-scale,1));color:#182334}.file-kind-tabs button.selected{background:#008d93;color:#fff;border-color:#008d93}.file-name-tabs button.selected{background:#ddf7f7;color:#007b80;border-color:#007b80}
</style>
