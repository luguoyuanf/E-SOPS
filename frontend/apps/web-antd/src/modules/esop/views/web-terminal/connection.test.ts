import { afterEach, describe, expect, it, vi } from 'vitest';

import { probeTerminalServer, TerminalError } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('web terminal server connection test', () => {
  it('checks the same-origin API and accepts a healthy response', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => true });
    vi.stubGlobal('fetch', fetcher);
    await expect(probeTerminalServer()).resolves.toBeUndefined();
    expect(fetcher).toHaveBeenCalledWith('/api/v1/utils/health-check', expect.objectContaining({
      cache: 'no-store', credentials: 'omit',
    }));
  });

  it('reports the actual HTTP status when the API is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(probeTerminalServer()).rejects.toMatchObject({ message: 'HTTP 503', status: 503 });
  });

  it('distinguishes network failure from an HTTP response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(probeTerminalServer()).rejects.toBeInstanceOf(TerminalError);
    await expect(probeTerminalServer()).rejects.toMatchObject({ status: 0, message: '网络连接失败，请检查网络后重试' });
  });
});
