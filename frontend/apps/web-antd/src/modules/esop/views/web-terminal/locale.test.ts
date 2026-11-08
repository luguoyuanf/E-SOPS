import { describe, expect, it } from 'vitest';

import translations from './locales.json';
import { detectTerminalLocale, normalizeTerminalLocale, terminalLanguages, terminalText } from './locale';

describe('web terminal languages', () => {
  it('offers each supported locale and restores saved language codes', () => {
    expect(terminalLanguages.map(({ value }) => value)).toEqual([
      'zh', 'zh-TW', 'en', 'th', 'vi', 'fr', 'de', 'ru',
    ]);
    expect(normalizeTerminalLocale('zh-TW')).toBe('zh-TW');
    expect(normalizeTerminalLocale('fr-FR')).toBe('fr');
    expect(normalizeTerminalLocale('de_DE')).toBe('de');
    expect(normalizeTerminalLocale('ru-RU')).toBe('ru');
    expect(normalizeTerminalLocale('unsupported')).toBe('zh');
    expect(detectTerminalLocale(['zh-Hant-TW'])).toBe('zh-TW');
    expect(detectTerminalLocale(['fr-CA'])).toBe('fr');
    expect(detectTerminalLocale(['es-ES', 'de-DE'])).toBe('de');
  });

  it('provides every source key with real translated labels', () => {
    const packs = translations as Record<string, Record<string, string>>;
    const sourceKeys = Object.keys(translations.zh).sort();
    for (const { value } of terminalLanguages) {
      expect(Object.keys(packs[value] ?? {}).sort(), value).toEqual(sourceKeys);
      for (const key of sourceKeys) {
        expect(packs[value]?.[key]?.trim(), `${value}:${key}`).toBeTruthy();
      }
    }
    expect(terminalText('zh-TW', 'logout')).toBe('退出登入');
    expect(terminalText('fr', 'logout')).toBe('Déconnexion');
    expect(terminalText('de', 'logout')).toBe('Abmelden');
    expect(terminalText('ru', 'logout')).toBe('Выйти');
  });
});
