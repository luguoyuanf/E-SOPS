export type SupportedLanguagesType = 'de-DE' | 'en-US' | 'fr-FR' | 'ru-RU' | 'th-TH' | 'vi-VN' | 'zh-CN' | 'zh-TW';

export type ImportLocaleFn = () => Promise<{ default: Record<string, string> }>;

export type LoadMessageFn = (
  lang: SupportedLanguagesType,
) => Promise<Record<string, string> | undefined>;

export interface LocaleSetupOptions {
  /** Commit synchronous third-party locale state only after the selected messages load. */
  onLocaleChanged?: (lang: SupportedLanguagesType) => void;
  /**
   * Default language
   * @default zh-CN
   */
  defaultLocale?: SupportedLanguagesType;
  /**
   * Load message function
   * @param lang
   * @returns
   */
  loadMessages?: LoadMessageFn;
  /**
   * Whether to warn when the key is not found
   */
  missingWarn?: boolean;
}
