<script setup lang="ts">
import type { Advertisement } from './client';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
const props = defineProps<{ items: Advertisement[]; resolveFile: (id: string) => Promise<{ url: string }> }>();
const now = ref(Date.now());
const index = ref(0);
const round = ref(0);
const elapsed = ref(0);
const url = ref('');
const failure = ref(false);
const ready = ref(false);
const paused = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
let generation = 0;
function eligible(item: Advertisement) {
  const date = new Date(now.value);
  if (item.startsAt && date < new Date(item.startsAt)) return false;
  if (item.endsAt && date >= new Date(item.endsAt)) return false;
  const time = date.toTimeString().slice(0, 8);
  if (item.dailyStart && item.dailyEnd) {
    return item.dailyStart <= item.dailyEnd
      ? time >= item.dailyStart && time <= item.dailyEnd
      : time >= item.dailyStart || time <= item.dailyEnd;
  }
  return true;
}
const ad = computed(() => props.items.find(eligible));
const media = computed(() => ad.value?.media[index.value]);
const waiting = computed(() => !ready.value && round.value > 0);
const shown = computed(() => ad.value && !waiting.value && !failure.value);
const vertical = computed(() => ['top', 'bottom'].includes(ad.value?.layout ?? ''));
const first = computed(() => ['left', 'top', 'fullscreen'].includes(ad.value?.layout ?? ''));
async function load() {
  const request = ++generation;
  ready.value = false; url.value = ''; failure.value = false; elapsed.value = 0;
  if (!media.value) return;
  if (media.value.kind === 'text') { ready.value = true; return; }
  try {
    if (!media.value.file_id) throw new Error('Missing media');
    const access = await props.resolveFile(media.value.file_id);
    if (request === generation) { url.value = access.url; ready.value = true; }
  } catch { if (request === generation) failure.value = true; }
}
function next() {
  if (!ad.value) return;
  if (index.value + 1 < ad.value.media.length) { index.value++; void load(); }
  else if (ad.value.playback === 'continuous') { index.value = 0; void load(); }
  else { round.value = Date.now(); ready.value = false; }
}
watch(() => ad.value?.id, () => { index.value = 0; round.value = 0; void load(); });
watch(() => JSON.stringify(ad.value?.media), () => { index.value = 0; round.value = 0; void load(); });
onMounted(() => {
  void load();
  timer = setInterval(() => {
    now.value = Date.now();
    if (paused.value || document.hidden) return;
    if (round.value) {
      if (Date.now() - round.value >= (ad.value?.intervalMinutes ?? 1) * 60_000) { round.value = 0; index.value = 0; void load(); }
    } else if (ready.value && media.value?.kind !== 'video' && ++elapsed.value >= (media.value?.duration_seconds ?? 10)) next();
  }, 1000);
});
onBeforeUnmount(() => { generation++; clearInterval(timer); });
</script>
<template>
  <div class="ad-workspace" :class="{ vertical, fullscreen: shown && ad?.layout === 'fullscreen' }">
    <div v-if="shown" class="ad-panel" :style="{ order: first ? 0 : 2 }">
      <p v-if="media?.kind === 'text'" class="ad-text">{{ media.content || media.text || ad?.title }}</p>
      <video v-else-if="url && media?.kind === 'video'" :src="url" controls autoplay muted playsinline @ended="next" @pause="paused = true" @play="paused = false" @error="failure = true" />
      <img v-else-if="url" :src="url" :alt="ad?.title" @error="failure = true" />
    </div>
    <div v-show="!shown || ad?.layout !== 'fullscreen'" class="sop-panel"><slot /></div>
  </div>
</template>
<style scoped>
.ad-workspace{height:100%;min-height:0;display:flex;gap:12px;align-items:stretch}.ad-workspace.vertical{flex-direction:column}.ad-panel{flex:1;min-width:0;display:grid;place-items:center;background:#f1f6fa}.ad-panel video,.ad-panel img{width:100%;max-height:65vh;object-fit:contain}.ad-text{padding:24px;font-size:28px;white-space:pre-wrap}.sop-panel{flex:1;min-width:0;min-height:0;height:100%}.fullscreen .ad-panel{min-height:55vh}@media(max-width:600px){.ad-workspace{flex-direction:column}}
</style>
