import { expect, it, vi } from 'vitest';

import html from './index.html?raw';

const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

it('shows content before JavaScript and downloads after the shared captcha succeeds', async () => {
  document.body.innerHTML = html.match(/<body>([\s\S]*)<\/body>/)![1]!;
  expect(document.querySelector('h1')?.textContent).toContain('下载 ESOPS');
  expect(document.querySelectorAll('.package-card')).toHaveLength(4);
  const requests: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const path = String(input);
    requests.push(path);
    let data: unknown;
    if (path.endsWith('/public')) {
      data = { version: 'test', arm64Available: true, arm32Available: true, ubuntuArm64Available: true };
    } else if (path.endsWith('/get')) {
      data = { repCode: '0000', repData: { token: 'test-token', secretKey: '0123456789abcdef', originalImageBase64: '', jigsawImageBase64: '' } };
    } else if (path.endsWith('/check')) {
      data = { repCode: '0000' };
    } else {
      data = { url: 'https://download.esops.cc/test.deb' };
    }
    return { ok: true, json: async () => data } as Response;
  });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await import('./main');
  await flushPromises();
  const button = document.querySelector<HTMLButtonElement>('#ubuntuArm64 button')!;
  expect(button.disabled).toBe(false);
  button.click();
  await vi.waitFor(() => expect(document.querySelector('.verify-bar-area')).not.toBeNull());
  await flushPromises();
  const bar = document.querySelector<HTMLElement>('.verify-bar-area')!;
  vi.spyOn(bar, 'getBoundingClientRect').mockReturnValue({ width: 400, left: 0 } as DOMRect);
  const handle = document.querySelector<HTMLElement>('.verify-move-block')!;
  handle.setPointerCapture = vi.fn();
  handle.dispatchEvent(new PointerEvent('pointerdown', { clientX: 22, pointerId: 1, bubbles: true }));
  window.dispatchEvent(new PointerEvent('pointermove', { clientX: 142, pointerId: 1 }));
  window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 }));
  await flushPromises();
  expect(requests).toContain('/api/v1/homepage/download-links/ubuntuArm64');
  expect(click).toHaveBeenCalledOnce();
  expect(document.querySelector('#status')?.textContent).toContain('已开始下载');
  expect(button.disabled).toBe(false);
  (document.querySelector('#verification') as Element & { __vue_app__: { unmount(): void } }).__vue_app__.unmount();
  vi.restoreAllMocks();
});
