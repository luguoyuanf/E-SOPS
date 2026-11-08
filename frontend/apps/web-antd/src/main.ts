import { initPreferences, preferences, updateCustomPreferences, updatePreferences } from '@vben/preferences';
import { watch } from 'vue';
import { unmountGlobalLoading } from '@vben/utils';

import { publicEntries } from './router/generated-public-entries';

import { detectBrowserLocale, isSupportedWebsiteLocale, resolvePersistentLocale } from './locales/browser-locale';
import { buildManifest } from './modules/build-manifest';
import { overridesPreferences, preferencesExtension } from './preferences';

/**
 * 应用初始化完成之后再进行页面加载渲染
 */
async function initApplication() {
  const publicEntry = publicEntries.find((entry) => location.pathname.startsWith(entry.prefix));
  if (publicEntry) {
    await (await publicEntry.load()).bootstrap();
    unmountGlobalLoading();
    return;
  }
  // name用于指定项目唯一标识
  // 用于区分不同项目的偏好设置以及存储数据的key前缀以及其他一些需要隔离的数据
  const env = import.meta.env.PROD ? 'prod' : 'dev';
  const appVersion = import.meta.env.VITE_APP_VERSION;
  const namespace = `${import.meta.env.VITE_APP_NAMESPACE}-${appVersion}-${env}`;

  // app偏好设置初始化
  await initPreferences({
    extension: preferencesExtension,
    namespace,
    overrides: {
      ...overridesPreferences,
      app: {
        ...overridesPreferences.app,
        locale: detectBrowserLocale(navigator.languages?.length ? navigator.languages : [navigator.language]),
      },
    },
  });

  // ESOPS public pages and authenticated screens share one persistent choice.
  // Resolve it after legacy cached preferences, before i18n renders the first screen.
  if (buildManifest.edition === 'esop') {
    let storedLocale: string | null = null;
    try { storedLocale = localStorage.getItem('esops-site-language'); } catch {}
    updatePreferences({ app: { name: 'ESOPS', locale: resolvePersistentLocale(
      storedLocale, navigator.languages?.length ? navigator.languages : [navigator.language],
    ) } });
    watch(() => preferences.app.locale, (locale) => {
      if (isSupportedWebsiteLocale(locale)) {
        try { localStorage.setItem('esops-site-language', locale); } catch {}
      }
    }, { immediate: true, flush: 'sync' });
  }

  // Brand assets must supersede logo URLs saved by earlier app versions.
  updatePreferences({
    logo: { source: '/esops-icon.png', sourceDark: '/esops-icon.png' },
  });

  const visualDefaultsKey = `${namespace}:visual-defaults:20261101`;
  if (!localStorage.getItem(visualDefaultsKey)) {
    updatePreferences({
      theme: {
        builtinType: 'deep-green',
        colorPrimary: 'hsl(181 84% 32%)',
      },
    });
    updateCustomPreferences({ tenantMode: 'single' });
    localStorage.setItem(visualDefaultsKey, '1');
  }

  // Apply the agreed layout once to existing profiles; later user choices remain editable.
  const layoutDefaultsKey = `${namespace}:layout-defaults:20261025`;
  if (!localStorage.getItem(layoutDefaultsKey)) {
    updatePreferences({
      app: { layout: 'header-mixed-nav' },
      sidebar: {
        collapsed: true,
        collapsedShowTitle: true,
        collapseWidth: 80,
        expandOnHover: false,
        width: 164,
      },
      theme: {
        mode: 'light',
        semiDarkHeader: true,
        semiDarkSidebar: true,
        semiDarkSidebarSub: true,
      },
    });
    localStorage.setItem(layoutDefaultsKey, '1');
  }

  // 启动应用并挂载
  // vue应用主要逻辑及视图
  const { bootstrap } = await import('./bootstrap');
  await bootstrap(namespace);

  // 移除并销毁loading
  unmountGlobalLoading();
}

initApplication();
