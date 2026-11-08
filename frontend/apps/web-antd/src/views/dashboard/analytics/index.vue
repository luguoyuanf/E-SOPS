<script lang="ts" setup>
import type { Component } from 'vue';
import { defineAsyncComponent } from 'vue';
import { buildManifest } from '#/modules/build-manifest';
import { modulePageMap } from '#/router/generated-module-pages';

const esopPage = modulePageMap['../modules/esop/views/dashboard/index.vue'];
const dashboard = defineAsyncComponent(
  buildManifest.modules.some((module) => String(module.code) === 'esop') && esopPage
    ? (esopPage as () => Promise<Component>)
    : () => import('./platform-analytics.vue'),
);
</script>
<template><component :is="dashboard" /></template>
