<script setup lang="ts">
import { ref } from 'vue';
import { Button, message } from 'ant-design-vue';
import type { DataScreenLink } from '../../api/generated/types.gen';
import { requestClient } from '#/api/request';

const loading = ref(false);
async function openScreen() {
  if (loading.value) return;
  const tab = window.open('', '_blank');
  if (!tab) { message.warning('请允许浏览器打开新标签页后重试'); return; }
  tab.opener = null;
  tab.document.title = '正在打开数据大屏';
  loading.value = true;
  try {
    const link = await requestClient.post<DataScreenLink>('/esop/data-screen/link');
    tab.location.replace(new URL(link.path, window.location.origin).href);
  } catch {
    tab.close();
    message.error('大屏链接生成失败，请重试');
  } finally { loading.value = false; }
}
</script>
<template><Button size="small" :loading="loading" @click="openScreen">数据大屏</Button></template>
