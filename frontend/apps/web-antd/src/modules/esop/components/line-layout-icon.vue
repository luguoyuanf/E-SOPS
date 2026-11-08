<script setup lang="ts">
defineProps<{ layout: 'double' | 'single' }>();
</script>

<template>
  <svg viewBox="0 0 132 54" fill="none" aria-hidden="true" class="line-layout-icon">
    <path d="M8 27h114m-6-4 6 4-6 4" stroke="currentColor" stroke-width="2" />
    <g v-for="x in [22, 51, 80, 109]" :key="x" stroke="currentColor" stroke-width="1.5">
      <rect :x="x - 8" y="5" width="16" height="12" rx="2" />
      <path :d="`M${x} 17v4m-5 0h10`" />
      <template v-if="layout === 'double'">
        <rect :x="x - 8" y="34" width="16" height="12" rx="2" />
        <path :d="`M${x} 46v4m-5 0h10`" />
      </template>
    </g>
  </svg>
</template>

<style scoped>
.line-layout-icon { display: block; width: 132px; height: 54px; max-width: 100%; }
</style>
