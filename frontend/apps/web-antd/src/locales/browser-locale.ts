import type { SupportedLanguagesType } from '@vben/locales';

export function detectBrowserLocale(
  languages: readonly string[] | undefined,
): SupportedLanguagesType {
  for (const language of languages ?? []) {
    const normalized = language.trim().toLowerCase().replaceAll('_', '-');
    if (normalized === 'zh-tw' || normalized === 'zh-hk' || normalized === 'zh-mo' || normalized.startsWith('zh-hant')) return 'zh-TW';
    if (normalized.startsWith('zh')) return 'zh-CN';
    if (normalized.startsWith('en')) return 'en-US';
    if (normalized.startsWith('th')) return 'th-TH';
    if (normalized.startsWith('vi')) return 'vi-VN';
    if (normalized.startsWith('fr')) return 'fr-FR';
    if (normalized.startsWith('de')) return 'de-DE';
    if (normalized.startsWith('ru')) return 'ru-RU';
  }
  return 'zh-CN';
}

const websiteLanguages = new Set<SupportedLanguagesType>([
  'zh-CN', 'zh-TW', 'en-US', 'th-TH', 'vi-VN', 'fr-FR', 'de-DE', 'ru-RU',
]);

/** Shared website/admin preference accepts only the eight exact supported codes. */
export function isSupportedWebsiteLocale(value: string | null): value is SupportedLanguagesType {
  return websiteLanguages.has(value as SupportedLanguagesType);
}

export function resolvePersistentLocale(
  storedLocale: string | null,
  browserLanguages: readonly string[] | undefined,
): SupportedLanguagesType {
  return isSupportedWebsiteLocale(storedLocale) ? storedLocale : detectBrowserLocale(browserLanguages);
}
