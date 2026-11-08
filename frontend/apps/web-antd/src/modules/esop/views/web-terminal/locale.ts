import translations from './locales.json';

import { detectBrowserLocale } from '../../../../locales/browser-locale';

export const terminalLanguages = [
  { value: 'zh', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en', label: 'English' },
  { value: 'th', label: 'ไทย' },
  { value: 'vi', label: 'Tiếng Việt' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'ru', label: 'Русский' },
] as const;

export type TerminalLocale = (typeof terminalLanguages)[number]['value'];

export function detectTerminalLocale(languages: readonly string[] | undefined): TerminalLocale {
  return normalizeTerminalLocale(detectBrowserLocale(languages));
}

export function normalizeTerminalLocale(value: unknown): TerminalLocale {
  if (typeof value !== 'string') return 'zh';
  const normalized = value.trim().toLowerCase().replace('_', '-');
  if (normalized === 'zh-tw' || normalized === 'zh-hant') return 'zh-TW';
  const language = normalized.split('-')[0];
  return terminalLanguages.find((entry) => entry.value === language)?.value ?? 'zh';
}

export function terminalText(locale: TerminalLocale, key: string): string {
  const packs = translations as Record<string, Record<string, string>>;
  return packs[locale]?.[key] ?? packs.zh?.[key] ?? key;
}
