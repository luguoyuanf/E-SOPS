<script setup lang="ts">
import type { OtaPackage } from '../../api/ota';
import DataScreenButton from '../data-screen/open-button.vue';

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Verification } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';
import { useAccessStore, useUserStore } from '@vben/stores';
import { Alert, Button, Dropdown, Menu, Modal, Spin, Tag, message } from 'ant-design-vue';

import { checkSliderCaptchaApi, getSliderCaptchaApi } from '#/api';
import { downloadOfficialTerminal } from '#/api/core/terminal-download';
import type { TerminalArchitecture } from '#/api/core/terminal-download';
import esopsLogo from '#/assets/esops-logo.png';

import { listHardwareModels, listOtaPackages, downloadOtaPackage } from '../../api/ota';
import { getWebTerminalAccess, listTerminals, openWebTerminal as requestWebTerminal } from '../../api/operations';
import { publishedTerminalDownloads, terminalPlatforms } from './terminal-downloads';
import type { TerminalPlatform } from './terminal-downloads';

const router = useRouter();
const accessStore = useAccessStore();
const userStore = useUserStore();
const open = ref(false);
const downloadOpen = ref(false);
const step = ref(0);
const loading = ref(false);
const downloading = ref<string>();
const openingWeb = ref(false);
const downloads = ref(new Map<TerminalPlatform, OtaPackage>());
const officialDownloads = ref<{ version: string; arm32Available: boolean; arm64Available: boolean; ubuntuArm64Available: boolean }>();
const officialVerification = ref<InstanceType<typeof Verification>>();
const pendingOfficial = ref<TerminalArchitecture>();
const officialDownloading = ref(false);
function officialDownloadAvailable(platform: TerminalPlatform) {
  if (platform === 'android32') return officialDownloads.value?.arm32Available;
  if (platform === 'android64') return officialDownloads.value?.arm64Available;
  if (platform === 'ubuntuArm64') return officialDownloads.value?.ubuntuArm64Available;
  return false;
}

function startOfficialDownload(platform: TerminalPlatform) {
  pendingOfficial.value = platform === 'android32' ? 'arm32' : platform === 'ubuntuArm64' ? 'ubuntuArm64' : 'arm64';
  officialVerification.value?.show();
}

async function afterOfficialVerification({ captchaVerification }: { captchaVerification: string }) {
  const architecture = pendingOfficial.value;
  officialVerification.value?.onClose();
  pendingOfficial.value = undefined;
  if (!architecture) return;
  officialDownloading.value = true;
  try {
    await downloadOfficialTerminal(architecture, officialDownloads.value?.version, captchaVerification);
  } catch {
    message.error('下载失败，请重新完成验证后重试');
  } finally {
    officialDownloading.value = false;
  }
}
const guideButton = ref<{ $el: HTMLButtonElement }>();
const downloadButton = ref<{ $el: HTMLButtonElement }>();
const steps = ['准备终端', '激活密钥', '设置产线', '绑定设备', '开始使用'];
const can = (code: string) => accessStore.accessCodes.includes(code);
const canManage = computed(() => ['esop:line:create', 'esop:device:bind', 'esop:device:key-list'].some(can));
const identity = computed(() => `${userStore.userInfo?.userId || 'unknown'}:${userStore.userInfo?.tenantId || 'default'}`);
const completedKey = computed(() => `esop:new-user-guide:v1:${identity.value}:complete`);
const progressKey = computed(() => `esop:new-user-guide:v1:${identity.value}:step`);
const dismissedKey = computed(() => `esop:new-user-guide:v1:${identity.value}:dismissed`);
const suppressedKey = computed(() => `esop:new-user-guide:v1:${identity.value}:suppressed`);

async function loadDownloads() {
  loading.value = true;
  try {
    const response = await fetch('/api/v1/homepage/downloads/public');
    if (!response.ok) throw new Error('Unable to load official terminal packages');
    const result = await response.json();
    officialDownloads.value = result.data || result;
    if (can('esop:ota:list')) {
      const [packages, models] = await Promise.all([listOtaPackages(), listHardwareModels()]);
      downloads.value = publishedTerminalDownloads(packages.items, models.items);
    }
  } catch {
    message.warning('安装包目录暂时无法加载，请稍后重试');
  } finally {
    loading.value = false;
  }
}

function start() {
  step.value = Number(localStorage.getItem(progressKey.value) || 0);
  if (!Number.isInteger(step.value) || step.value < 0 || step.value > 4) step.value = 0;
  open.value = true;
  void loadDownloads();
}

function openDownloads() {
  downloadOpen.value = true;
  void loadDownloads();
}

function dismiss() {
  open.value = false;
  sessionStorage.setItem(dismissedKey.value, '1');
}

function suppress(period: 'today' | 'week' | 'forever') {
  if (period === 'forever') {
    localStorage.setItem(suppressedKey.value, 'forever');
  } else {
    const until = new Date();
    if (period === 'today') until.setHours(24, 0, 0, 0);
    else {
      until.setHours(0, 0, 0, 0);
      until.setDate(until.getDate() + ((8 - until.getDay()) % 7 || 7));
    }
    localStorage.setItem(suppressedKey.value, String(until.getTime()));
  }
  open.value = false;
  message.success(period === 'today' ? '今天不再自动提示' : period === 'week' ? '本周不再自动提示' : '已关闭自动提示');
}

function advance() {
  step.value = Math.min(step.value + 1, 4);
  localStorage.setItem(progressKey.value, String(step.value));
}

function selectStep(index: number) {
  step.value = index;
  localStorage.setItem(progressKey.value, String(index));
}

function finish() {
  localStorage.setItem(completedKey.value, '1');
  localStorage.removeItem(progressKey.value);
  open.value = false;
}

function navigate(path: string) {
  open.value = false;
  void router.push(path);
}

async function download(row?: OtaPackage) {
  if (!row) return;
  downloading.value = row.id;
  try {
    const response = await downloadOtaPackage(row.id);
    const url = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = url;
    link.download = row.file_name;
    link.click();
    URL.revokeObjectURL(url);
  } finally {
    downloading.value = undefined;
  }
}

async function openWebTerminal() {
  const tab = window.open('about:blank', '_blank');
  if (tab) tab.opener = null;
  openingWeb.value = true;
  try {
    const [access, terminals] = await Promise.all([getWebTerminalAccess(), listTerminals()]);
    const terminal = terminals.items.find((item) => item.device_code === 'WEB' && item.is_active);
    if (!access.allowed || !terminal) {
      tab?.close();
      message.warning('当前账号无法打开 Web 终端，请到终端管理查看');
      return;
    }
    const result = await requestWebTerminal(terminal.id);
    if (tab) tab.location.href = result.path;
    else window.location.assign(result.path);
  } catch {
    tab?.close();
    message.error('Web 终端打开失败，请到终端管理重试');
  } finally {
    openingWeb.value = false;
  }
}

onMounted(() => {
  if (!canManage.value) return;
  const suppressed = localStorage.getItem(suppressedKey.value);
  if (suppressed === 'forever' || (suppressed && Number(suppressed) > Date.now())) return;
  if (!localStorage.getItem(completedKey.value) && !sessionStorage.getItem(dismissedKey.value)) start();
});
</script>

<template>
  <DataScreenButton v-if="can('dashboard:view')" />
  <Button v-if="canManage" ref="guideButton" size="small" @click="start">新手引导</Button>
  <Button ref="downloadButton" type="text" shape="circle" size="small" class="!text-white/80 hover:!text-white" aria-label="下载客户端" title="下载客户端" @click="openDownloads"><IconifyIcon icon="lucide:download" class="size-4" aria-hidden="true" /></Button>
  <Modal :open="downloadOpen" :keyboard="true" :footer="null" :width="660" title="下载终端客户端" @cancel="downloadOpen = false" @after-close="downloadButton?.$el.focus()">
    <p class="guide-note">选择与设备系统和处理器架构匹配的版本。Android 安装包与官网同步；其他平台仅展示当前租户有权访问且已发布的安装包。</p>
    <Spin :spinning="loading">
      <div class="download-grid">
        <div v-for="platform in terminalPlatforms" :key="platform.key" class="download-card">
          <div><strong>{{ platform.label }}</strong><small>{{ platform.detail }}</small></div>
          <template v-if="platform.key === 'android32' || platform.key === 'android64' || platform.key === 'ubuntuArm64'">
            <Button v-if="officialDownloadAvailable(platform.key)" size="small" :loading="officialDownloading" :disabled="officialDownloading" @click="startOfficialDownload(platform.key)">下载</Button>
            <Tag v-else>暂未提供</Tag>
          </template>
          <Button v-else-if="downloads.get(platform.key)" size="small" :loading="downloading === downloads.get(platform.key)?.id" @click="download(downloads.get(platform.key))">下载</Button>
          <Tag v-else>暂未提供</Tag>
        </div>
      </div>
    </Spin>
    <Button v-if="can('esop:ota:list')" type="link" class="!px-0" @click="downloadOpen = false; navigate('/esop/services/ota')">查看全部安装包</Button>
  </Modal>
  <Modal :open="open" :keyboard="true" :footer="null" :width="820" :destroy-on-close="true" title="欢迎使用 ESOPS" @cancel="dismiss" @after-close="guideButton?.$el.focus()">
    <p class="guide-intro">按下面的顺序准备终端和产线。可以随时关闭，之后从右上角的新手引导按钮重新打开。</p>
    <nav class="guide-steps" aria-label="新手引导步骤">
      <button v-for="(title, index) in steps" :key="title" type="button" :class="{ active: step === index, done: step > index }" :aria-current="step === index ? 'step' : undefined" @click="selectStep(index)">
        <span>{{ index + 1 }}</span>{{ title }}
      </button>
    </nav>
    <section v-if="step === 0" class="guide-body">
      <h3>选择终端</h3>
      <p>实体设备安装对应系统与架构的客户端；也可以先打开租户自带的 Web 终端体验。Web 终端无需激活密钥。</p>
      <div class="guide-actions">
        <Button :loading="openingWeb" :disabled="!can('esop:device:list')" type="primary" @click="openWebTerminal">打开 Web 终端</Button>
        <Button :disabled="!can('esop:device:list')" @click="navigate('/esop/resources/terminals')">终端管理</Button>
      </div>
      <h4>下载实体终端客户端</h4>
      <Spin :spinning="loading">
        <div class="download-grid">
          <div v-for="platform in terminalPlatforms" :key="platform.key" class="download-card">
            <div><strong>{{ platform.label }}</strong><small>{{ platform.detail }}</small></div>
            <template v-if="platform.key === 'android32' || platform.key === 'android64' || platform.key === 'ubuntuArm64'">
              <Button v-if="officialDownloadAvailable(platform.key)" size="small" :loading="officialDownloading" :disabled="officialDownloading" @click="startOfficialDownload(platform.key)">下载</Button>
              <Tag v-else>暂未提供</Tag>
            </template>
            <Button v-else-if="downloads.get(platform.key)" size="small" :loading="downloading === downloads.get(platform.key)?.id" @click="download(downloads.get(platform.key))">下载</Button>
            <Tag v-else>暂未提供</Tag>
          </div>
        </div>
      </Spin>
      <p class="guide-note">Android 安装包与官网同步；其他平台仅展示当前租户有权访问且已发布的安装包。下载前请核对设备架构。</p>
      <Button v-if="can('esop:ota:list')" type="link" class="!px-0" @click="navigate('/esop/services/ota')">查看全部安装包</Button>
    </section>
    <section v-else-if="step === 1" class="guide-body">
      <h3>激活实体终端</h3>
      <p>在实体终端输入属于本租户的激活密钥。注册赠送的免费密钥可在“激活密钥”页面查看；需要更多设备时可查看购买页面。Web 终端可跳过此步。</p>
      <div class="guide-actions">
        <Button :disabled="!can('esop:device:key-list')" type="primary" @click="navigate('/esop/services/activation-keys')">查看免费密钥</Button>
        <Button :disabled="!can('esop:purchase:list')" @click="navigate('/esop/services/purchase')">购买密钥</Button>
      </div>
    </section>
    <section v-else-if="step === 2" class="guide-body">
      <h3>快速设置产线</h3>
      <p>先建立车间，再创建产线并设置工位数量与布局。产线保存后即可在工位图上绑定终端。</p>
      <div class="guide-actions"><Button :disabled="!can('esop:line:list')" type="primary" @click="navigate('/esop/resources/lines')">去设置产线</Button></div>
    </section>
    <section v-else-if="step === 3" class="guide-body">
      <h3>绑定设备到工位</h3>
      <p>终端激活后，在“终端管理”选择“绑定工位”；也可从产线的工位布局中选择设备。Web 终端同样需要绑定工位才能查看对应作业。</p>
      <div class="guide-actions"><Button :disabled="!can('esop:device:list')" type="primary" @click="navigate('/esop/resources/terminals')">去绑定设备</Button></div>
    </section>
    <section v-else class="guide-body">
      <Alert type="success" show-icon message="设备准备就绪后，开始配置作业内容" />
      <p class="!mt-4">依次配置产品、编写并审核 SOP、创建生产订单，最后创建排产并发布到产线，终端即可显示当前作业指导。</p>
      <div class="guide-actions">
        <Button :disabled="!can('esop:product:list')" @click="navigate('/erp/product/products')">配置产品</Button>
        <Button :disabled="!can('esop:sop:list')" @click="navigate('/esop/basic/operations')">配置 SOP</Button>
        <Button :disabled="!can('esop:order:list')" @click="navigate('/esop/order-center/orders')">创建订单</Button>
        <Button :disabled="!can('esop:plan:list')" @click="navigate('/esop/publish-center/plans')">创建排产</Button>
      </div>
    </section>
    <footer class="guide-footer">
      <div class="guide-actions !mt-0">
        <Button @click="dismiss">稍后继续</Button>
        <Dropdown :trigger="['click']">
          <Button>不再显示</Button>
          <template #overlay><Menu>
            <Menu.Item @click="suppress('today')">今天不提示</Menu.Item>
            <Menu.Item @click="suppress('week')">本周不提示</Menu.Item>
            <Menu.Item @click="suppress('forever')">永久关闭</Menu.Item>
          </Menu></template>
        </Dropdown>
      </div>
      <div class="guide-actions">
        <Button v-if="step > 0" @click="selectStep(step - 1)">上一步</Button>
        <Button v-if="step < 4" type="primary" @click="advance">下一步</Button>
        <Button v-else type="primary" @click="finish">完成引导</Button>
      </div>
    </footer>
  </Modal>
  <Verification ref="officialVerification" :brand-logo="esopsLogo" :check-captcha-api="checkSliderCaptchaApi" :get-captcha-api="getSliderCaptchaApi" :img-size="{ width: '400px', height: '200px' }" mode="pop" @on-success="afterOfficialVerification" @on-close="pendingOfficial = undefined" @on-error="message.error('验证码验证失败，请重试')" />
</template>

<style scoped>
.guide-intro, .guide-body p, .guide-note { color: hsl(var(--muted-foreground)); }
.guide-steps { display: flex; gap: 8px; margin: 22px 0; overflow-x: auto; }
.guide-steps button { display: flex; align-items: center; gap: 7px; flex: 1; min-width: max-content; padding: 9px; border-radius: 8px; color: hsl(var(--muted-foreground)); text-align: left; }
.guide-steps button.active { color: hsl(var(--primary)); background: hsl(var(--primary) / 10%); font-weight: 600; }
.guide-steps button.done { color: hsl(var(--primary)); }
.guide-steps span { display: inline-grid; place-items: center; width: 22px; height: 22px; border: 1px solid currentColor; border-radius: 50%; font-size: 12px; }
.guide-body { min-height: 240px; max-height: min(48vh, 450px); overflow-y: auto; padding: 2px 4px 8px 0; }
.guide-body h3 { font-size: 18px; font-weight: 650; }
.guide-body h4 { margin: 22px 0 10px; font-weight: 600; }
.guide-body p { margin-top: 10px; line-height: 1.65; }
.guide-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 16px; }
.download-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.download-card { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 10px 12px; border: 1px solid hsl(var(--border)); border-radius: 8px; }
.download-card strong, .download-card small { display: block; }
.download-card small { margin-top: 2px; color: hsl(var(--muted-foreground)); }
.guide-note { font-size: 12px; }
.guide-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid hsl(var(--border)); padding-top: 16px; }
@media (max-width: 640px) { .guide-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); overflow: visible; } .guide-steps button { min-width: 0; font-size: 12px; } .download-grid { grid-template-columns: 1fr; } }
</style>
