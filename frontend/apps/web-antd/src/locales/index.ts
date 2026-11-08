import type { Locale } from 'ant-design-vue/es/locale';

import type { App } from 'vue';

import type { LocaleSetupOptions, SupportedLanguagesType } from '@vben/locales';

import { ref } from 'vue';

import {
  $t,
  setupI18n as coreSetup,
  loadLocalesMapFromDir,
} from '@vben/locales';
import { preferences } from '@vben/preferences';

import antdEnLocale from 'ant-design-vue/es/locale/en_US';
import antdDefaultLocale from 'ant-design-vue/es/locale/zh_CN';
import antdDeLocale from 'ant-design-vue/es/locale/de_DE';
import antdFrLocale from 'ant-design-vue/es/locale/fr_FR';
import antdRuLocale from 'ant-design-vue/es/locale/ru_RU';
import antdThLocale from 'ant-design-vue/es/locale/th_TH';
import antdViLocale from 'ant-design-vue/es/locale/vi_VN';
import antdZhTwLocale from 'ant-design-vue/es/locale/zh_TW';
import dayjs from 'dayjs';

import { installUiCopyTranslation } from './ui-copy';

const antdLocale = ref<Locale>(antdDefaultLocale);

const modules = import.meta.glob('./langs/**/*.json');

const localesMap = loadLocalesMapFromDir(
  /\.\/langs\/([^/]+)\/(.*)\.json$/,
  modules,
);
/**
 * 加载应用特有的语言包
 * 这里也可以改造为从服务端获取翻译数据
 * @param lang
 */
async function loadMessages(lang: SupportedLanguagesType) {
  const [appLocaleMessages] = await Promise.all([
    localesMap[lang]?.(),
    loadDayjsLocale(lang),
  ]);
  return appLocaleMessages?.default;
}

/**
 * 加载dayjs的语言包
 * @param lang
 */
async function loadDayjsLocale(lang: SupportedLanguagesType) {
  let locale;
  switch (lang) {
    case 'en-US': {
      locale = await import('dayjs/locale/en');
      break;
    }
    case 'zh-CN': {
      locale = await import('dayjs/locale/zh-cn');
      break;
    }
    case 'zh-TW': { locale = await import('dayjs/locale/zh-tw'); break; }
    case 'th-TH': { locale = await import('dayjs/locale/th'); break; }
    case 'vi-VN': { locale = await import('dayjs/locale/vi'); break; }
    case 'fr-FR': { locale = await import('dayjs/locale/fr'); break; }
    case 'de-DE': { locale = await import('dayjs/locale/de'); break; }
    case 'ru-RU': { locale = await import('dayjs/locale/ru'); break; }
    // 默认使用英语
    default: {
      locale = await import('dayjs/locale/en');
    }
  }
  if (!locale) {
    console.error(`Failed to load dayjs locale for ${lang}`);
  }
}

/**
 * 加载antd的语言包
 * @param lang
 */
async function loadAntdLocale(lang: SupportedLanguagesType) {
  switch (lang) {
    case 'en-US': {
      antdLocale.value = antdEnLocale;
      break;
    }
    case 'zh-CN': {
      antdLocale.value = antdDefaultLocale;
      break;
    }
    case 'zh-TW': { antdLocale.value = antdZhTwLocale; break; }
    case 'th-TH': { antdLocale.value = antdThLocale; break; }
    case 'vi-VN': { antdLocale.value = antdViLocale; break; }
    case 'fr-FR': { antdLocale.value = antdFrLocale; break; }
    case 'de-DE': { antdLocale.value = antdDeLocale; break; }
    case 'ru-RU': { antdLocale.value = antdRuLocale; break; }
  }
}

async function setupI18n(app: App, options: LocaleSetupOptions = {}) {
  await coreSetup(app, {
    defaultLocale: preferences.app.locale,
    loadMessages,
    onLocaleChanged: (lang) => {
      void loadAntdLocale(lang);
      dayjs.locale({ 'zh-CN': 'zh-cn', 'zh-TW': 'zh-tw', 'en-US': 'en', 'th-TH': 'th', 'vi-VN': 'vi', 'fr-FR': 'fr', 'de-DE': 'de', 'ru-RU': 'ru' }[lang]);
    },
    missingWarn: !import.meta.env.PROD,
    ...options,
  });
  installUiCopyTranslation();
}

export { $t, antdLocale, setupI18n };
