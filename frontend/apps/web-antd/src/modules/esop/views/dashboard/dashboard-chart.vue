<script setup lang="ts">
import type { ECOption } from '@vben/plugins/echarts';
import type { EchartsUIType } from '@vben/plugins/echarts';
import { onMounted, ref, watch } from 'vue';
import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

const props = defineProps<{ option: ECOption }>();
const emit = defineEmits<{ select: [name: string] }>();
const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);
async function render() {
  const chart = await renderEcharts(props.option);
  chart?.off('click');
  chart?.on('click', (event) =>
    emit(
      'select',
      event.seriesName === '累计生效' ? event.name : event.seriesName || '',
    ),
  );
}
onMounted(render);
watch(() => props.option, render, { deep: true });
</script>
<template><EchartsUI ref="chartRef" /></template>
