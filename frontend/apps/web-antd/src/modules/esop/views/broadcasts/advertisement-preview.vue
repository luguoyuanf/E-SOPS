<script lang="ts" setup>
import type { AdvertisementInput } from '../../api/broadcast';
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { Button, Modal, Spin } from 'ant-design-vue';
import { getAdvertisementFileAccess } from '../../api/broadcast';

const props = defineProps<{ open: boolean; task?: AdvertisementInput }>();
const emit = defineEmits<{ 'update:open': [value: boolean]; closed: [] }>();
const index = ref(0);
const paused = ref(false);
const waiting = ref(false);
const seconds = ref(0);
const url = ref('');
const loading = ref(false);
const error = ref('');
const ready = ref(false);
const video = ref<HTMLVideoElement>();
let timer: ReturnType<typeof setInterval> | undefined;
let generation = 0;
let roundStarted = 0;
const media = computed(() => props.task?.media[index.value]);
const layout = computed(() => props.task?.layout ?? 'fullscreen');
const showAd = computed(() => !waiting.value);
const panes = computed(() => ({ flexDirection: ['top', 'bottom'].includes(layout.value) ? 'column' as const : 'row' as const }));
const adFirst = computed(() => ['left', 'top'].includes(layout.value));

async function load() {
  const current = ++generation;
  url.value = ''; error.value = ''; ready.value = false;
  seconds.value = media.value?.duration_seconds ?? 10;
  if (!media.value || media.value.kind === 'text') { loading.value = false; ready.value = true; return; }
  loading.value = true;
  try {
    if (!media.value.file_id) throw new Error('缺少素材文件');
    const access = await getAdvertisementFileAccess(media.value.file_id);
    if (current === generation && props.open) url.value = access.url;
  } catch { if (current === generation) error.value = '素材加载失败，请检查文件或重试'; }
  finally { if (current === generation) loading.value = false; }
}
function restart() {
  roundStarted = Date.now(); index.value = 0; waiting.value = false; paused.value = false;
  void load();
}
function advance() {
  if (!props.task) return;
  paused.value = false;
  if (index.value + 1 < props.task.media.length) { index.value++; void load(); return; }
  if (props.task.playback === 'continuous') { restart(); return; }
  const period = props.task.interval_minutes * 60_000;
  const elapsed = Date.now() - roundStarted;
  seconds.value = Math.ceil((period - elapsed % period) / 1000);
  waiting.value = true; ready.value = false; video.value?.pause();
}
function tick() {
  if (paused.value || loading.value || error.value) return;
  if (waiting.value || (ready.value && media.value?.kind !== 'video')) {
    seconds.value--;
    if (seconds.value <= 0) { if (waiting.value) restart(); else advance(); }
  }
}
function toggle() {
  paused.value = !paused.value;
  if (paused.value) video.value?.pause();
  else void video.value?.play().catch(() => { paused.value = true; });
}
function onVideoPause(event: Event) {
  const source = event.target as HTMLVideoElement;
  if (source === video.value && ready.value && !source.ended && !waiting.value) paused.value = true;
}
function videoReady() {
  ready.value = true;
  if (!paused.value) void video.value?.play().catch(() => { paused.value = true; });
}
function stop() { if (timer) clearInterval(timer); timer = undefined; generation++; video.value?.pause(); }
watch(() => props.open, async (open) => {
  stop();
  if (open) { restart(); await nextTick();
    if (props.open) {
      document.querySelector<HTMLButtonElement>('.advertisement-preview-modal .ant-modal-close')?.focus();
      timer = setInterval(tick, 1000);
    } }
}, { immediate: true });
onBeforeUnmount(stop);
</script>
<template>
  <Modal wrap-class-name="advertisement-preview-modal" :open="open" title="广告模拟预览" :width="1100" :keyboard="true" :mask-closable="false" :destroy-on-close="true" :footer="null" :style="{ maxWidth: 'calc(100vw - 24px)', top: '24px' }" @cancel="emit('update:open', false)" :after-close="() => emit('closed')">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2"><strong>{{ task?.title || '未命名广告' }}</strong><span class="text-sm text-muted-foreground">模拟预览，不受排期限制，不影响现场终端</span></div>
    <div class="preview-screen" :style="panes" aria-label="广告与 SOP 屏幕模拟">
      <div v-if="(layout !== 'fullscreen' || !showAd) && !adFirst" class="sop-pane"><strong>SOP 作业指导（示意）</strong><p>实际终端显示当前工位的作业指导</p></div>
      <div v-if="showAd" class="ad-pane">
        <Spin v-if="loading" tip="加载素材" />
        <div v-else-if="error" class="text-center"><p>{{ error }}</p><Button @click="load">重试</Button></div>
        <div v-else-if="media?.kind === 'text'" class="ad-text">{{ media.content }}</div>
        <img v-else-if="media?.kind === 'image' && url" :src="url" :alt="media.name" @load="ready = true" @error="error = '图片加载失败，请重试'" />
        <video v-else-if="media?.kind === 'video' && url" ref="video" :src="url" controls muted playsinline @canplay="videoReady" @ended="advance" @pause="onVideoPause" @play="paused = false" @error="error = '视频加载失败，请重试'" />
      </div>
      <div v-if="(layout !== 'fullscreen' || !showAd) && adFirst" class="sop-pane"><strong>SOP 作业指导（示意）</strong><p>实际终端显示当前工位的作业指导</p></div>
    </div>
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
      <div class="text-sm text-muted-foreground"><template v-if="waiting">本轮播放完成，{{ seconds }} 秒后再次播放；当前恢复 SOP</template><template v-else>素材 {{ index + 1 }} / {{ task?.media.length }} · {{ media?.kind === 'video' ? '视频完整播放后切换（预览默认静音）' : `${seconds} 秒后切换` }}</template></div>
      <div class="flex flex-wrap gap-2"><Button @click="toggle">{{ paused ? '继续' : '暂停' }}</Button><Button :disabled="waiting" @click="advance">下一素材</Button><Button @click="restart">重新播放一轮</Button><Button type="primary" @click="emit('update:open', false)">关闭预览</Button></div>
    </div>
  </Modal>
</template>
<style scoped>
.preview-screen { display: flex; aspect-ratio: 16 / 9; width: 100%; overflow: hidden; background: #000; border: 1px solid #d1d5db; }
.ad-pane, .sop-pane { display: flex; flex: 1 1 50%; box-sizing: border-box; min-width: 0; min-height: 0; align-items: center; justify-content: center; overflow: hidden; }
.ad-pane { color: white; background: black; }
.ad-pane img, .ad-pane video { width: 100%; height: 100%; object-fit: contain; }
.ad-text { max-height: 100%; overflow: auto; padding: 20px; white-space: pre-wrap; overflow-wrap: anywhere; text-align: center; font-size: clamp(16px, 2.5vw, 32px); }
.sop-pane { flex-direction: column; gap: 12px; padding: 16px; color: #374151; background: #f3f4f6; text-align: center; }
.sop-pane strong { font-size: clamp(14px, 2vw, 26px); }
.sop-pane p { font-size: clamp(11px, 1.2vw, 16px); }
</style>
