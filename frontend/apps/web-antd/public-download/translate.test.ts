import { afterEach, expect, it } from 'vitest';

import { translate, translateCaptcha } from './translate';

afterEach(() => { document.body.replaceChildren(); });

function language(translations: Record<string, string>) {
  const config = document.createElement('script');
  config.id = 'public-language-data';
  config.type = 'application/json';
  config.textContent = JSON.stringify({ translations });
  document.body.append(config);
}

it('uses the current static page dictionary and preserves dynamic version values', () => {
  language({ '当前版本：{version}': 'Version: {version}', '验证并下载': 'Verify and download' });
  expect(translate('当前版本：{version}', { version: '0.2.4' })).toBe('Version: 0.2.4');
  expect(translate('验证并下载')).toBe('Verify and download');
  document.getElementById('public-language-data')!.textContent = JSON.stringify({ translations: { '验证并下载': 'Vérifier et télécharger' } });
  expect(translate('验证并下载')).toBe('Vérifier et télécharger');
});

it('keeps the standalone Chinese entry usable without localized configuration', () => {
  expect(translate('当前版本：{version}', { version: 'test' })).toBe('当前版本：test');
});

it('translates asynchronously rendered captcha copy and accessibility labels only in its own root', async () => {
  language({ '安全验证': 'Security verification', '关闭': 'Close', '验证通过': 'Verified', '滑动验证码背景': 'Puzzle background' });
  const outside = document.createElement('p'); outside.textContent = '安全验证'; document.body.append(outside);
  const root = document.createElement('div'); document.body.append(root); translateCaptcha(root);
  root.innerHTML = '<section aria-label="安全验证"><button aria-label="关闭">×</button><p>0.42s 验证通过</p><img alt="滑动验证码背景"></section>';
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(root.querySelector('section')?.getAttribute('aria-label')).toBe('Security verification');
  expect(root.querySelector('button')?.getAttribute('aria-label')).toBe('Close');
  expect(root.querySelector('p')?.textContent).toBe('0.42s Verified');
  expect(root.querySelector('img')?.getAttribute('alt')).toBe('Puzzle background');
  expect(outside.textContent).toBe('安全验证');
});
