import { afterEach, expect, it, vi } from 'vitest';

import { downloadOfficialTerminal } from './terminal-download';

afterEach(() => vi.restoreAllMocks());

it('requests only a fixed link and hands the R2 download to the browser', async () => {
  const url = 'https://download.esops.cc/app.apk';
  const blob = vi.fn();
  const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: true, json: async () => ({ url }), blob,
  } as unknown as Response);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.href).toBe(url);
    expect(this.referrerPolicy).toBe('origin');
  });
  await downloadOfficialTerminal('arm64', '1', 'test-proof');
  expect(request).toHaveBeenCalledOnce();
  expect(request.mock.calls[0]?.[0]).toBe('/api/v1/homepage/download-links/arm64');
  expect(click).toHaveBeenCalledOnce();
  expect(blob).not.toHaveBeenCalled();
});

it('does not navigate when link issuance fails', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false } as Response);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click');
  await expect(downloadOfficialTerminal('arm32', '1', 'invalid')).rejects.toThrow('Download failed');
  expect(click).not.toHaveBeenCalled();
});
