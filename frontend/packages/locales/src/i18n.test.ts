import { createApp } from 'vue';
import { expect, it, vi } from 'vitest';

import { i18n, loadLocaleMessages, setupI18n } from './i18n';

it('preloads fallback messages without activating them when refreshing traditional Chinese', async () => {
  const committed = vi.fn();
  await setupI18n(createApp({}), {
    defaultLocale: 'zh-TW',
    loadMessages: async locale => ({ test: locale }),
    onLocaleChanged: committed,
  });
  expect(committed.mock.calls).toEqual([['zh-TW']]);
  expect(i18n.global.locale.value).toBe('zh-TW');
  expect(document.documentElement.lang).toBe('zh-TW');
  expect(i18n.global.t('test')).toBe('zh-TW');
});

it('keeps the last selection even when an earlier language finishes loading later', async () => {
  let releaseFrench!: () => void;
  const french = new Promise<void>(resolve => { releaseFrench = resolve; });
  const committed = vi.fn();
  await setupI18n(createApp({}), {
    defaultLocale: 'zh-TW',
    loadMessages: async locale => {
      if (locale === 'fr-FR') await french;
      return { test: locale };
    },
    onLocaleChanged: committed,
  });
  committed.mockClear();
  const earlier = loadLocaleMessages('fr-FR');
  const latest = loadLocaleMessages('de-DE');
  await latest;
  releaseFrench(); await earlier;
  expect(committed.mock.calls).toEqual([['de-DE']]);
  expect(i18n.global.locale.value).toBe('de-DE');
  expect(document.documentElement.lang).toBe('de-DE');
  expect(i18n.global.t('test')).toBe('de-DE');
});

it('cancels a pending load when the user switches back to the currently active language', async () => {
  let releaseFrench!: () => void;
  const french = new Promise<void>(resolve => { releaseFrench = resolve; });
  await setupI18n(createApp({}), {
    defaultLocale: 'zh-TW',
    loadMessages: async locale => { if (locale === 'fr-FR') await french; return {}; },
  });
  const earlier = loadLocaleMessages('fr-FR');
  await loadLocaleMessages('zh-TW');
  releaseFrench(); await earlier;
  expect(i18n.global.locale.value).toBe('zh-TW');
  expect(document.documentElement.lang).toBe('zh-TW');
});
