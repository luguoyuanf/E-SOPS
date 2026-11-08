<script setup lang="ts">
import glyphs from './material-icons.json';
defineProps<{ icon: string }>();
</script>
<template><span class="terminal-material-icon" aria-hidden="true">{{ glyphs[icon as keyof typeof glyphs] || glyphs['lucide:file'] }}</span></template>
<style scoped>
@font-face{font-family:TerminalMaterialIcons;src:url('./MaterialIcons.woff2') format('woff2');font-display:block}.terminal-material-icon{font-family:TerminalMaterialIcons!important;font-weight:normal;font-style:normal;font-size:20px;line-height:1;letter-spacing:normal;text-transform:none;white-space:nowrap;word-wrap:normal;direction:ltr;display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;flex-shrink:0;-webkit-font-smoothing:antialiased}
</style>
