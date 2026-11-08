<script setup lang="ts">
import type { Object3D } from 'three';

import { nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue';
import { Button, message, Spin } from 'ant-design-vue';
import { AmbientLight, Box3, Color, DirectionalLight, PerspectiveCamera, Scene, Vector3, WebGLRenderer } from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { disposeModel, explosionParts, fetchModelBytes, loadModelData } from '../utils/model-loader';

const props = withDefaults(defineProps<{
  url?: string;
  data?: ArrayBuffer;
  fileName: string;
  active?: boolean;
  resourceUrls?: Record<string, string>;
  translate?: (key: string) => string;
}>(), { active: true, resourceUrls: () => ({}) });
const t = (key: string) => props.translate?.(key) ?? key;
const host = ref<HTMLDivElement>();
const canvasHost = ref<HTMLDivElement>();
const loading = ref(false);
const error = ref('');
const warning = ref('');
const partCount = ref(0);
const amount = ref(0);
const playing = ref(false);
let renderer: WebGLRenderer | undefined;
let controls: OrbitControls | undefined;
let scene: Scene | undefined;
let camera: PerspectiveCamera | undefined;
let model: Object3D | undefined;
let parts: ReturnType<typeof explosionParts> = [];
let observer: ResizeObserver | undefined;
let request = 0;
let controller: AbortController | undefined;
let frame = 0;
let phase = 0;
let lastTime = 0;
function render() { if (renderer && scene && camera && props.active && !document.hidden) renderer.render(scene, camera); }
function resize() {
  if (!canvasHost.value || !renderer || !camera) return;
  const { width, height } = canvasHost.value.getBoundingClientRect();
  if (!width || !height) return;
  const previousAspect = camera.aspect;
  renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  if (model && Math.abs(previousAspect - camera.aspect) > 0.01) fit(playing.value ? playbackBounds() : undefined);
  else render();
}
function applyAmount(value: number) {
  amount.value = value;
  for (const part of parts) part.object.position.copy(part.origin).addScaledVector(part.direction, value);
  render();
}
function animate(time: number) {
  if (!playing.value || !props.active || document.hidden) { frame = 0; return; }
  if (lastTime) phase += Math.min((time - lastTime) / 1000, 0.1) * Math.PI / 3;
  lastTime = time;
  applyAmount((1 - Math.cos(phase)) / 2);
  frame = requestAnimationFrame(animate);
}
function stop() { playing.value = false; cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
function togglePlay() {
  if (playing.value) { stop(); return; }
  if (!parts.length || !props.active) return;
  fit(playbackBounds());
  playing.value = true; phase = Math.acos(1 - amount.value * 2); lastTime = 0; frame = requestAnimationFrame(animate);
}
function playbackBounds() {
  const current = amount.value;
  applyAmount(0);
  const bounds = new Box3().setFromObject(model!);
  applyAmount(1);
  bounds.union(new Box3().setFromObject(model!));
  applyAmount(current);
  return bounds;
}
function setAmount(value: number) { stop(); applyAmount(value); }
function expand() { setAmount(1); fit(); }
function fit(bounds?: Box3) {
  if (!model || !camera || !controls) return;
  const box = bounds ?? new Box3().setFromObject(model); const center = box.getCenter(new Vector3());
  const radius = Math.max(box.getSize(new Vector3()).length() / 2, 0.001);
  const distance = radius / Math.sin(camera.fov * Math.PI / 360) * Math.max(1, 1 / camera.aspect) * 1.25;
  camera.position.copy(center).add(new Vector3(0.9, -1.2, 0.9).normalize().multiplyScalar(distance));
  camera.up.set(0, 0, 1); camera.near = Math.max(radius / 1000, 0.000001); camera.far = distance + radius * 100;
  camera.updateProjectionMatrix(); controls.target.copy(center); controls.update(); render();
}
function reset() { setAmount(0); fit(); }
async function fullscreen() {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await host.value?.requestFullscreen(); }
  catch { message.warning(t('当前浏览器暂不能进入全屏，可继续在预览窗口查看')); }
}
function clearModel() {
  stop();
  if (model) { scene?.remove(model); disposeModel(model); model = undefined; }
  parts = []; warning.value = ''; partCount.value = 0; amount.value = 0;
}
async function load() {
  const id = ++request; controller?.abort(); clearModel(); error.value = '';
  if (!props.active || !renderer || (!props.url && !props.data)) { loading.value = false; return; }
  controller = new AbortController(); const signal = controller.signal;
  loading.value = true;
  try {
    const bytes = props.data ? props.data.slice(0) : await fetchModelBytes(props.url!, signal);
    const result = await loadModelData(bytes, props.fileName, props.resourceUrls, signal);
    if (id !== request || !props.active) { disposeModel(result); return; }
    model = result; warning.value = result.userData.previewWarning ?? ''; scene!.add(result); result.updateMatrixWorld(true); parts = explosionParts(result); partCount.value = parts.length;
    resize(); fit();
  } catch (cause) {
    if (id === request && !signal.aborted) error.value = cause instanceof Error && /[\u3400-\u9fff]/u.test(cause.message) ? cause.message : '模型解析失败，请检查文件格式或配套资源';
  } finally { if (id === request) loading.value = false; }
}
function visibilityChanged() { if (document.hidden) stop(); else render(); }
onMounted(async () => {
  await nextTick();
  try {
    scene = new Scene(); scene.background = new Color(0xf1f5f9);
    camera = new PerspectiveCamera(40, 1, 0.001, 100000);
    renderer = new WebGLRenderer({ antialias: true, alpha: false }); renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.setAttribute('aria-label', t('CAD 与三维模型交互画布')); renderer.domElement.tabIndex = 0;
    canvasHost.value!.append(renderer.domElement);
    controls = new OrbitControls(camera, renderer.domElement); controls.addEventListener('change', render);
    scene.add(new AmbientLight(0xffffff, 2));
    const light = new DirectionalLight(0xffffff, 3); light.position.set(4, -6, 10); scene.add(light);
    observer = new ResizeObserver(resize); observer.observe(canvasHost.value!);
    document.addEventListener('visibilitychange', visibilityChanged);
    document.addEventListener('fullscreenchange', resize);
    await load();
  } catch { error.value = '当前设备无法启动三维显示，请检查浏览器 WebGL 支持'; loading.value = false; }
});
watchEffect(() => { renderer?.domElement.setAttribute('aria-label', t('CAD 与三维模型交互画布')); });
watch([() => props.active, () => props.url, () => props.data, () => props.fileName, () => props.resourceUrls], () => void load());
onBeforeUnmount(() => {
  request++; controller?.abort(); clearModel(); observer?.disconnect(); controls?.removeEventListener('change', render); controls?.dispose();
  renderer?.dispose(); renderer?.forceContextLoss(); renderer?.domElement.remove();
  document.removeEventListener('visibilitychange', visibilityChanged); document.removeEventListener('fullscreenchange', resize);
});
</script>

<template>
  <div ref="host" class="model-viewer flex min-h-0 w-full flex-col bg-slate-100 text-slate-900">
    <div class="model-toolbar flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-2">
      <Button size="small" :disabled="loading || !partCount" @click="expand">{{ t('展开') }}</Button>
      <Button size="small" :disabled="loading || !partCount" @click="setAmount(0)">{{ t('合拢') }}</Button>
      <Button size="small" :disabled="loading || !partCount" @click="togglePlay">{{ playing ? t('暂停') : t('自动播放') }}</Button>
      <Button size="small" :disabled="loading || !!error" @click="reset">{{ t('复位') }}</Button>
      <Button size="small" @click="fullscreen">{{ t('全屏') }}</Button>
      <input v-if="partCount" type="range" min="0" max="1" step="0.01" :value="amount" :aria-label="t('部件展开程度')" class="model-slider min-w-0 flex-1" @input="setAmount(Number(($event.target as HTMLInputElement).value))" />
    </div>
    <div ref="canvasHost" class="model-screen relative mx-auto min-h-0 shrink-0 overflow-hidden" :aria-label="t('模型显示区域')">
      <Spin v-if="loading" :tip="t('正在读取并解析模型')" class="absolute inset-0 z-10 flex items-center justify-center bg-white/80" />
      <div v-if="error" role="alert" class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white p-4 text-center"><p>{{ t(error) }}</p><Button size="small" @click="load">{{ t('重新加载') }}</Button></div>
    </div>
    <p v-if="warning" role="status" class="model-warning shrink-0 px-2 text-xs text-amber-800">{{ t(warning) }}</p>
    <p class="model-help shrink-0 border-t border-slate-200 px-2 py-1 text-xs text-slate-600">{{ t('拖动旋转 · 右键拖动平移 · 滚轮或双指缩放') }}<span v-if="!loading && !error">{{ partCount ? ` · ${t('{count} 个独立部件').replace('{count}', String(partCount))}` : ` · ${t('单体模型或图形，没有独立部件可展开')}` }}</span></p>
  </div>
</template>

<style scoped>
.model-viewer { display: flex; flex-direction: column; min-width: 0; min-height: 0; width: 100%; background: #f1f5f9; color: #0f172a; }
.model-toolbar { display: flex; flex: 0 0 auto; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px; border-bottom: 1px solid #e2e8f0; background: #fff; }
.model-slider { flex: 1; min-width: 0; }
.model-warning, .model-help { flex-shrink: 0; padding: 4px 8px; font-size: 12px; }
.model-warning { color: #92400e; }
.model-help { border-top: 1px solid #e2e8f0; color: #475569; }
:deep(canvas) { display: block; width: 100%; height: 100%; touch-action: none; }
.model-screen {
  width: min(100%, var(--terminal-screen-native-width, 1920px), calc(var(--terminal-screen-height, 400px) * var(--terminal-screen-ratio, 1.7777778)));
  aspect-ratio: var(--terminal-screen-aspect, 16 / 9);
}
.model-viewer:fullscreen { width: 100vw; height: 100dvh; }
.model-viewer:fullscreen .model-screen { width: min(100vw, calc((100dvh - 90px) * var(--terminal-screen-ratio, 1.7777778))); }
</style>
