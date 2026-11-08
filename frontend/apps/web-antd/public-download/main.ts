import { translate } from './translate';
import type { VerificationHandle } from './captcha';

import { downloadOfficialTerminal, type TerminalArchitecture } from '../src/api/core/terminal-download';

type PackageInfo = {
  version: string;
  arm64Available: boolean;
  arm32Available: boolean;
  ubuntuArm64Available: boolean;
};

const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-architecture]')];
const status = document.querySelector<HTMLElement>('#status')!;
const retry = document.querySelector<HTMLButtonElement>('#retry')!;
let verification: VerificationHandle | undefined;
let info: PackageInfo | undefined;
let pending: TerminalArchitecture | undefined;
let trigger: HTMLButtonElement | undefined;
let downloading = false;

function notify(text: string, error = false) {
  status.textContent = text;
  status.dataset.error = String(error);
}

function updateButtons() {
  for (const button of buttons) {
    const architecture = button.dataset.architecture as TerminalArchitecture;
    const available = info?.[`${architecture}Available`];
    button.disabled = !available || downloading;
    button.textContent = available ? translate('验证并下载') : translate('暂未提供');
  }
}

async function loadPackages() {
  retry.hidden = true;
  try {
    const response = await fetch('/api/v1/homepage/downloads/public', {
      signal: AbortSignal.timeout(10_000),
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('Package information unavailable');
    const result = await response.json();
    info = result.data || result;
    notify(translate('当前版本：{version}', { version: info!.version }));
  } catch {
    notify(translate('暂时无法获取安装包信息，请重试。'), true);
    retry.hidden = false;
  }
  updateButtons();
}

async function captchaApi(path: string, data: unknown) {
  const response = await fetch(`/api/v1/system/captcha/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error('Captcha request failed');
  const result = await response.json();
  return result.data || result;
}

async function afterVerification({ captchaVerification }: { captchaVerification: string }) {
  const architecture = pending;
  if (!architecture) return;
  verification?.onClose();
  downloading = true;
  updateButtons();
  try {
    await downloadOfficialTerminal(architecture, info?.version, captchaVerification);
    notify(translate('已开始下载，请查看浏览器下载记录。'));
  } catch {
    notify(translate('下载失败，请重新完成验证后重试。'), true);
  } finally {
    downloading = false;
    updateButtons();
  }
}

for (const button of buttons) {
  button.addEventListener('click', async () => {
    trigger = button;
    pending = button.dataset.architecture as TerminalArchitecture;
    downloading = true;
    updateButtons();
    try {
      if (!verification) {
        notify(translate('正在加载安全验证…'));
        const { mountVerification } = await import('./captcha');
        verification = await mountVerification({
          getCaptchaApi: (data: unknown) => captchaApi('get', data),
          checkCaptchaApi: (data: unknown) => captchaApi('check', data),
          onOnSuccess: afterVerification,
          onOnClose: () => {
            pending = undefined;
            trigger?.focus();
          },
          onOnError: () => notify(translate('验证码加载或验证失败，请重试。'), true),
        });
      }
      verification.show();
      notify(translate('请完成安全验证。'));
    } catch {
      pending = undefined;
      notify(translate('安全验证加载失败，请重试。'), true);
    } finally {
      downloading = false;
      updateButtons();
    }
  });
}
retry.addEventListener('click', loadPackages);
void loadPackages();
