<script lang="ts" setup>
import { ref } from 'vue';
import { Page } from '@vben/common-ui';
import { Tabs } from 'ant-design-vue';
import Advertisements from './advertisements.vue';
import TickerPublications from './ticker-publications.vue';
const activeTab = ref('media');
</script>
<template>
  <Page title="广播发布">
    <Tabs v-model:active-key="activeTab">
      <Tabs.TabPane key="media" tab="多媒体广告任务"><Advertisements /></Tabs.TabPane>
      <Tabs.TabPane key="top" tab="顶部广播"><TickerPublications position="top" /></Tabs.TabPane>
      <Tabs.TabPane key="bottom" tab="底部广播"><TickerPublications position="bottom" /></Tabs.TabPane>
    </Tabs>
  </Page>
</template>
