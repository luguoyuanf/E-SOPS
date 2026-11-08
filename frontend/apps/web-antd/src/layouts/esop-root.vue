<script lang="ts" setup>
import { useRoute } from 'vue-router';
import BasicLayout from './basic.vue';
import ProductHome from '#/views/_core/home/index.vue';

const route = useRoute();
</script>

<template>
  <ProductHome v-if="route.path === '/'" />
  <BasicLayout v-else />
</template>
