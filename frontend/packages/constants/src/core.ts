/**
 * @zh_CN 登录页面 url 地址
 */
export const LOGIN_PATH = '/auth/login';

export interface LanguageOption {
  label: string;
  value: 'de-DE' | 'en-US' | 'fr-FR' | 'ru-RU' | 'th-TH' | 'vi-VN' | 'zh-CN' | 'zh-TW';
}

/**
 * Supported languages
 */
export const SUPPORT_LANGUAGES: LanguageOption[] = [
  {
    label: '简体中文',
    value: 'zh-CN',
  },
  { label: '繁體中文', value: 'zh-TW' },
  { label: 'English', value: 'en-US' },
  { label: 'ไทย', value: 'th-TH' },
  { label: 'Tiếng Việt', value: 'vi-VN' },
  { label: 'Français', value: 'fr-FR' },
  { label: 'Deutsch', value: 'de-DE' },
  { label: 'Русский', value: 'ru-RU' },
];
