<script lang="ts" setup>
import { onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Select, Spin } from 'ant-design-vue';

import { requestClient } from '#/api/request';

type HomepageContent = {
  locales: Record<string, Record<string, string>>;
  media: Record<string, string>;
};
type DownloadConfig = { version: string; arm64Key: string; arm32Key: string; windows64Key: string; ubuntuArm64Key: string };
type LegalDocument = {
  title: string;
  effective: string;
  intro: string;
  sections: Array<{ heading: string; body: string }>;
};
type LegalSlug = 'privacy' | 'terms';

const router = useRouter();
const userStore = useUserStore();
const loading = ref(true);
const saving = ref(false);
const locale = ref('zh-CN');
const content = reactive<HomepageContent>({ locales: {}, media: {} });
const form = reactive<Record<string, string>>({});
const media = reactive({ backendImage: '', terminalImage: '' });
const downloads = reactive<DownloadConfig>({ version: '', arm64Key: '', arm32Key: '', windows64Key: '', ubuntuArm64Key: '' });
const legalSlug = ref<LegalSlug>('privacy');
const legalDocuments = reactive<Record<LegalSlug, LegalDocument>>({
  privacy: { title: '', effective: '', intro: '', sections: [] },
  terms: { title: '', effective: '', intro: '', sections: [] },
});
const localeOptions = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en-US', label: 'English' },
  { value: 'th-TH', label: 'ไทย' },
  { value: 'vi-VN', label: 'Tiếng Việt' },
  { value: 'fr-FR', label: 'Français' },
  { value: 'de-DE', label: 'Deutsch' },
  { value: 'ru-RU', label: 'Русский' },
];
const labels: Record<string, string> = {
  siteTitle: '页面标题（SEO）', siteDescription: '页面描述（SEO）',
  freeHeadline: '免费 ESOP 主标题', freeIntro: '免费 ESOP 介绍',
  showcaseTitle: '界面展示标题', showcaseIntro: '界面展示介绍',
  backendTitle: '后台展示标题', backendDesc: '后台展示说明',
  terminalTitle: '终端展示标题', terminalDesc: '终端展示说明',
  faqTitle: '常见问题标题', faqQ1: '问题 1', faqA1: '回答 1',
  faqQ2: '问题 2', faqA2: '回答 2', faqQ3: '问题 3', faqA3: '回答 3',
};

function fillForm() {
  for (const key of Object.keys(form)) delete form[key];
  Object.assign(form, content.locales[locale.value] || {});
}

watch(locale, fillForm);

async function loadContent() {
  loading.value = true;
  try {
    const [result, packages, privacy, terms] = await Promise.all([
      requestClient.get<HomepageContent>('/homepage/public'),
      requestClient.get<DownloadConfig>('/homepage/downloads/config'),
      requestClient.get<LegalDocument>('/homepage/legal/privacy'),
      requestClient.get<LegalDocument>('/homepage/legal/terms'),
    ]);
    content.locales = result.locales;
    content.media = result.media;
    media.backendImage = result.media.backendImage || '';
    media.terminalImage = result.media.terminalImage || '';
    Object.assign(downloads, packages);
    legalDocuments.privacy = privacy;
    legalDocuments.terms = terms;
    fillForm();
  } finally {
    loading.value = false;
  }
}

async function saveLocale() {
  saving.value = true;
  try {
    const result = await requestClient.put<HomepageContent>(
      `/homepage/locales/${locale.value}`,
      { values: { ...form } },
    );
    content.locales = result.locales;
    message.success('首页文案已保存');
  } finally {
    saving.value = false;
  }
}

async function saveMedia() {
  saving.value = true;
  try {
    const result = await requestClient.put<HomepageContent>('/homepage/media', { ...media });
    content.media = result.media;
    message.success('展示图片已保存');
  } finally {
    saving.value = false;
  }
}

async function saveDownloads() {
  saving.value = true;
  try {
    Object.assign(downloads, await requestClient.put<DownloadConfig>('/homepage/downloads/config', { ...downloads }));
    message.success('终端安装包配置已保存');
  } finally {
    saving.value = false;
  }
}

async function saveLegal() {
  saving.value = true;
  try {
    legalDocuments[legalSlug.value] = await requestClient.put<LegalDocument>(
      `/homepage/legal/${legalSlug.value}`,
      legalDocuments[legalSlug.value],
    );
    message.success('公开法律页面已保存');
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  if (!userStore.userInfo?.roles?.includes('super')) {
    void router.replace('/basic-settings/settings');
    return;
  }
  void loadContent();
});
</script>

<template>
  <Page title="官网首页内容">
    <Spin :spinning="loading">
      <div class="mx-auto max-w-4xl space-y-6 pb-8">
        <div class="flex items-center justify-between">
          <Button @click="router.push('/basic-settings/settings')">返回参数设置</Button>
          <a href="/" target="_blank" rel="noopener noreferrer">查看官网首页</a>
        </div>
        <section class="rounded-lg bg-white p-6 shadow-sm">
          <h2 class="mb-2 text-lg font-semibold">多语言文案</h2>
          <p class="mb-4 text-gray-500">编辑后保存当前语言。标题、描述与常见问题也用于官网搜索展示。</p>
          <Select v-model:value="locale" class="mb-6 w-48" :options="localeOptions" />
          <div class="grid gap-4 md:grid-cols-2">
            <label v-for="(_, key) in form" :key="key" class="block">
              <span class="mb-1 block text-sm font-medium">{{ labels[key] || key }}</span>
              <Input.TextArea v-if="key.endsWith('Desc') || key.endsWith('Intro') || key.startsWith('faqA') || key.startsWith('desc')" v-model:value="form[key]" :rows="3" />
              <Input v-else v-model:value="form[key]" />
            </label>
          </div>
          <Button class="mt-6" type="primary" :loading="saving" @click="saveLocale">保存当前语言</Button>
        </section>
        <section class="rounded-lg bg-white p-6 shadow-sm">
          <h2 class="mb-4 text-lg font-semibold">界面展示图片</h2>
          <p class="mb-4 text-gray-500">填写 HTTPS 图片地址或本站以 / 开头的图片路径。</p>
          <label class="mb-4 block"><span class="mb-1 block text-sm font-medium">管理后台截图</span><Input v-model:value="media.backendImage" /></label>
          <label class="block"><span class="mb-1 block text-sm font-medium">工位终端截图</span><Input v-model:value="media.terminalImage" /></label>
          <Button class="mt-6" type="primary" :loading="saving" @click="saveMedia">保存图片地址</Button>
        </section>
        <section class="rounded-lg bg-white p-6 shadow-sm">
          <h2 class="mb-4 text-lg font-semibold">终端安装包</h2>
          <p class="mb-4 text-gray-500">安装包保存在专用下载存储中。填写对象路径后，下载页会在拖动验证码通过后直接下载文件。</p>
          <label class="mb-4 block"><span class="mb-1 block text-sm font-medium">版本号</span><Input v-model:value="downloads.version" placeholder="0.1.93" /></label>
          <label class="mb-4 block"><span class="mb-1 block text-sm font-medium">ARM64 安装包对象路径</span><Input v-model:value="downloads.arm64Key" placeholder="releases/esops-arm64.apk" /></label>
          <label class="block"><span class="mb-1 block text-sm font-medium">ARM32 安装包对象路径</span><Input v-model:value="downloads.arm32Key" placeholder="releases/esops-arm32.apk" /></label>
          <label class="mt-4 block"><span class="mb-1 block text-sm font-medium">Windows x64 安装包对象路径</span><Input v-model:value="downloads.windows64Key" placeholder="releases/esops-windows-x64.exe" /></label>
          <label class="mt-4 block"><span class="mb-1 block text-sm font-medium">Ubuntu ARM64 安装包对象路径</span><Input v-model:value="downloads.ubuntuArm64Key" placeholder="releases/esops-ubuntu-arm64.deb" /></label>
          <Button class="mt-6" type="primary" :loading="saving" @click="saveDownloads">保存安装包</Button>
        </section>
        <section class="rounded-lg bg-white p-6 shadow-sm">
          <h2 class="mb-2 text-lg font-semibold">隐私权政策与服务条款</h2>
          <p class="mb-4 text-gray-500">公开页面供应用商店和用户访问。修改时请核对实际的数据处理、套餐及联系方式。</p>
          <Select v-model:value="legalSlug" class="mb-6 w-48" :options="[{ value: 'privacy', label: '隐私权政策' }, { value: 'terms', label: '服务条款' }]" />
          <div class="space-y-4">
            <label class="block"><span class="mb-1 block text-sm font-medium">标题</span><Input v-model:value="legalDocuments[legalSlug].title" /></label>
            <label class="block"><span class="mb-1 block text-sm font-medium">生效日期</span><Input v-model:value="legalDocuments[legalSlug].effective" /></label>
            <label class="block"><span class="mb-1 block text-sm font-medium">简介</span><Input.TextArea v-model:value="legalDocuments[legalSlug].intro" :rows="4" /></label>
            <div v-for="(section, index) in legalDocuments[legalSlug].sections" :key="index" class="rounded border p-4">
              <label class="mb-3 block"><span class="mb-1 block text-sm font-medium">第 {{ index + 1 }} 节标题</span><Input v-model:value="section.heading" /></label>
              <label class="block"><span class="mb-1 block text-sm font-medium">正文</span><Input.TextArea v-model:value="section.body" :rows="5" /></label>
            </div>
          </div>
          <div class="mt-5 flex items-center gap-5"><Button type="primary" :loading="saving" @click="saveLegal">保存公开页面</Button><a :href="`/${legalSlug}`" target="_blank" rel="noopener noreferrer">查看页面</a></div>
        </section>
      </div>
    </Spin>
  </Page>
</template>
