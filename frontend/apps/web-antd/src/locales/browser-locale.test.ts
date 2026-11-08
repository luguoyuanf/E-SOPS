import { expect, it } from 'vitest';

import { detectBrowserLocale, isSupportedWebsiteLocale, resolvePersistentLocale } from './browser-locale';

it('restores all eight exact stored choices ahead of a different browser language', () => {
  for (const locale of ['zh-CN','zh-TW','en-US','th-TH','vi-VN','fr-FR','de-DE','ru-RU']) {
    expect(isSupportedWebsiteLocale(locale)).toBe(true);
    expect(resolvePersistentLocale(locale, ['en-US'])).toBe(locale);
  }
});

it('rejects invalid stored values and uses browser language on the first visit', () => {
  for (const locale of [null,'','fr','fr-fr',' en-US','<script>','ja-JP']) {
    expect(isSupportedWebsiteLocale(locale)).toBe(false);
    expect(resolvePersistentLocale(locale, ['fr-FR'])).toBe('fr-FR');
  }
});

it('keeps a manual choice when the browser language changes on a later visit', () => {
  expect(resolvePersistentLocale('de-DE',['fr-FR'])).toBe('de-DE');
  expect(resolvePersistentLocale('fr-FR',['zh-CN'])).toBe('fr-FR');
});

it('detects the first supported browser language and traditional Chinese variants', () => {
  expect(detectBrowserLocale(['ja-JP','fr-CA','en-US'])).toBe('fr-FR');
  expect(detectBrowserLocale(['zh-Hant-HK'])).toBe('zh-TW');
  expect(detectBrowserLocale(undefined)).toBe('zh-CN');
});
