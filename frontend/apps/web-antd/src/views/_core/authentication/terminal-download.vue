<script lang="ts" setup>
import { onMounted, ref } from 'vue';

import { Verification } from '@vben/common-ui';

import { Button, message, Spin } from 'ant-design-vue';

import { checkSliderCaptchaApi, getSliderCaptchaApi } from '#/api';
import { downloadOfficialTerminal } from '#/api/core/terminal-download';
import type { TerminalArchitecture } from '#/api/core/terminal-download';
import esopsLogo from '#/assets/esops-logo.png';

type PackageInfo = {
  version: string;
  arm64Available: boolean;
  arm32Available: boolean;
  ubuntuArm64Available: boolean;
};

const info = ref<PackageInfo>();
const loading = ref(true);
const downloading = ref(false);
const pending = ref<TerminalArchitecture>();
const verification = ref<InstanceType<typeof Verification>>();

async function loadPackages() {
  try {
    const response = await fetch('/api/v1/homepage/downloads/public');
    if (!response.ok) throw new Error('Unable to load terminal packages');
    const result = await response.json();
    info.value = result.data || result;
  } catch {
    message.error('暂时无法获取终端安装包');
  } finally {
    loading.value = false;
  }
}

function startDownload(architecture: TerminalArchitecture) {
  pending.value = architecture;
  verification.value?.show();
}

async function afterVerification({ captchaVerification }: { captchaVerification: string }) {
  if (!pending.value) return;
  const architecture = pending.value;
  verification.value?.onClose();
  pending.value = undefined;
  downloading.value = true;
  try {
    await downloadOfficialTerminal(architecture, info.value?.version, captchaVerification);
  } catch {
    message.error('下载失败，请重新完成验证后重试');
  } finally {
    downloading.value = false;
  }
}

onMounted(loadPackages);
</script>

<template>
  <div class="download-panel">
    <h1>下载 ESOPS 工位终端</h1>
    <p>选择与设备系统和处理器匹配的安装包。点击下载后请完成拖动验证码。</p>
    <Spin :spinning="loading || downloading">
      <div id="arm64" class="package-card">
        <strong>Android ARM64</strong>
        <span>适用于多数较新的 64 位工位终端</span>
        <Button type="primary" :disabled="!info?.arm64Available || downloading" @click="startDownload('arm64')">{{ info?.arm64Available ? '验证并下载' : '暂未提供' }}</Button>
      </div>
      <div id="arm32" class="package-card">
        <strong>Android ARM32</strong>
        <span>适用于 32 位处理器终端</span>
        <Button type="primary" :disabled="!info?.arm32Available || downloading" @click="startDownload('arm32')">{{ info?.arm32Available ? '验证并下载' : '暂未提供' }}</Button>
      </div>
      <div class="package-card">
        <strong>Windows x64</strong>
        <span>适用于 64 位 Windows 设备，安装包尚未发布</span>
        <Button disabled>暂未提供</Button>
      </div>
      <div class="package-card">
        <strong>Ubuntu ARM64</strong>
        <span>适用于 64 位 ARM 处理器的 Ubuntu 设备（DEB）</span>
        <Button type="primary" :disabled="!info?.ubuntuArm64Available || downloading" @click="startDownload('ubuntuArm64')">{{ info?.ubuntuArm64Available ? '验证并下载' : '暂未提供' }}</Button>
      </div>
      <p v-if="info?.version" class="version">当前版本：{{ info.version }}</p>
    </Spin>
    <p class="help">不确定设备架构时，请联系设备管理员。安装前请确认设备允许安装企业应用。</p>
    <p class="legal"><a href="/privacy" target="_blank">隐私权政策</a> · <a href="/terms" target="_blank">服务条款</a></p>
    <Verification ref="verification" :brand-logo="esopsLogo" :check-captcha-api="checkSliderCaptchaApi" :get-captcha-api="getSliderCaptchaApi" :img-size="{ width: '400px', height: '200px' }" mode="pop" @on-success="afterVerification" @on-close="pending = undefined" @on-error="message.error('验证码验证失败，请重试')" />
  </div>
</template>

<style scoped>
.download-panel{width:100%}.download-panel h1{font-size:28px;font-weight:700;margin:0 0 12px}.download-panel>p{color:#66746d;line-height:1.7;margin-bottom:24px}.package-card{display:grid;grid-template-columns:1fr auto;gap:4px 16px;align-items:center;padding:18px 0;border-bottom:1px solid #e4ebe6}.package-card strong{font-size:16px}.package-card span{color:#66746d;font-size:13px}.package-card button{grid-column:2;grid-row:1/3}.version{margin-top:16px;color:#66746d}.help{margin-top:28px;font-size:13px}.legal{font-size:13px}.legal a{color:#087f5b}@media(max-width:560px){.package-card{grid-template-columns:1fr}.package-card button{grid-column:1;grid-row:auto;margin-top:8px}}
</style>
