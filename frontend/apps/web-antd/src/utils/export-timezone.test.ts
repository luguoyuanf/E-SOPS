import { afterEach, describe, expect, it, vi } from 'vitest';

const { getCurrentTimezone, post } = vi.hoisted(() => ({
  getCurrentTimezone: vi.fn(() => 'Asia/Taipei'),
  post: vi.fn(),
}));
vi.mock('@vben/utils', () => ({ getCurrentTimezone }));
vi.mock('@vben/hooks', () => ({ useAppConfig: () => ({ apiURL: '/api/v1' }) }));
vi.mock('@vben/stores', () => ({ useAccessStore: () => ({ accessToken: 'test-token' }) }));
vi.mock('#/api/request', () => ({ requestClient: { post } }));

import { downloadApi } from '#/api/core/download';
import { exportChannelKeys, exportAdminChannelKeys } from '#/modules/esop/api/channel';
import { exportActivationKeys } from '#/modules/esop/api/operations';
import { exportOrders } from '#/modules/esop/api/production';

describe('导出使用页面当前时区', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    post.mockReset();
  });

  it('所有 ESOP POST 导出读取实时页面时区', () => {
    getCurrentTimezone.mockReturnValue('Europe/London');
    exportOrders({ ids: [] });
    exportActivationKeys({});
    exportChannelKeys({ key_ids: [] });
    exportAdminChannelKeys('channel-1', { key_ids: [] });
    expect(post).toHaveBeenCalledTimes(4);
    for (const call of post.mock.calls) {
      expect(call[2].headers).toEqual({ 'X-Export-Timezone': 'Europe/London' });
    }
  });

  it('下载导出携带时区，普通文件下载不增加导出头', async () => {
    getCurrentTimezone.mockReturnValue('Asia/Tokyo');
    const fetch = vi.fn().mockResolvedValue({
      blob: async () => new Blob(['test']),
      headers: new Headers(),
      ok: true,
    });
    vi.stubGlobal('fetch', fetch);
    vi.stubGlobal('URL', {
      createObjectURL: () => 'blob:test',
      revokeObjectURL: () => {},
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await downloadApi('/erp/products/export?status=active', '产品列表.csv');
    await downloadApi('/files/file-1/download', '说明书.pdf');
    expect(fetch.mock.calls[0]?.[1]?.headers['X-Export-Timezone']).toBe('Asia/Tokyo');
    expect(fetch.mock.calls[1]?.[1]?.headers['X-Export-Timezone']).toBeUndefined();
  });
});
