import { describe, expect, it } from 'vitest';

const packs = import.meta.glob<Record<string, string>>('./ui-copy/*.json', {
  eager: true,
  import: 'default',
});
const appPacks = import.meta.glob<Record<string, unknown>>('./langs/*/*.json', {
  eager: true,
  import: 'default',
});
const placeholders = (text: string) => [...text.matchAll(/\{[^{}]+\}/gu)]
  .map((match) => match[0]).sort();
function flatten(value: Record<string, unknown>, prefix = ''): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof entry === 'string') result[path] = entry;
    else if (entry && typeof entry === 'object') {
      Object.assign(result, flatten(entry as Record<string, unknown>, path));
    }
  }
  return result;
}

describe('legacy UI copy locales', () => {
  it('has complete eight-language coverage without changing placeholders', () => {
    const source = packs['./ui-copy/zh-TW.json'];
    expect(source).toBeDefined();
    const keys = Object.keys(source ?? {}).sort();
    for (const language of ['en', 'fr', 'de', 'ru', 'th', 'vi']) {
      const target = packs[`./ui-copy/${language}.json`];
      expect(target, language).toBeDefined();
      expect(Object.keys(target ?? {}).sort(), language).toEqual(keys);
      for (const key of keys) {
        const value = target?.[key] ?? '';
        expect(value.trim(), `${language}:${key}`).not.toBe('');
        expect(placeholders(value), `${language}:${key}`).toEqual(placeholders(key));
        expect(/[\u3400-\u9fff]/u.test(value), `${language}:${key}`).toBe(false);
      }
    }
  });

  it('keeps every admin language pack aligned with English', () => {
    const englishFiles = Object.entries(appPacks)
      .filter(([path]) => path.includes('/en-US/'));
    for (const [path, english] of englishFiles) {
      const baseline = flatten(english);
      for (const language of ['zh-CN', 'zh-TW', 'fr-FR', 'de-DE', 'ru-RU', 'th-TH', 'vi-VN']) {
        const translated = appPacks[path.replace('/en-US/', `/${language}/`)];
        expect(translated, `${language}:${path}`).toBeDefined();
        const target = flatten(translated ?? {});
        expect(Object.keys(target).sort(), `${language}:${path}`).toEqual(Object.keys(baseline).sort());
        for (const [key, value] of Object.entries(target)) {
          expect(value.trim(), `${language}:${key}`).not.toBe('');
          expect(placeholders(value), `${language}:${key}`).toEqual(placeholders(baseline[key] ?? ''));
        }
      }
    }
  });
});
