import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  access: { accessToken: '', loginExpired: false, setAccessToken: vi.fn(), setAccessCodes: vi.fn(), setLoginExpired: vi.fn() },
  user: { setUserInfo: vi.fn() },
  usage: vi.fn(), warning: vi.fn(),
}));
vi.mock('@vben/stores', () => ({ resetAllStores: vi.fn(), useAccessStore: () => mocks.access, useUserStore: () => mocks.user }));
vi.mock('pinia', () => ({ defineStore: (_name: string, setup: () => unknown) => setup }));
vi.mock('vue-router', () => ({ useRouter: () => ({ currentRoute: { value: { query: {} } }, push: vi.fn() }) }));
vi.mock('@vben/preferences', () => ({ preferences: { app: { defaultHomePath: '/' } } }));
vi.mock('ant-design-vue', () => ({ Modal: { warning: mocks.warning }, notification: { success: vi.fn() } }));
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
vi.mock('#/api', () => ({
  loginApi: async () => ({ accessToken: 'test-session' }),
  getUserInfoApi: async () => ({ realName: 'Test' }),
  getAccessCodesApi: async () => [],
  getCurrentStorageUsageApi: mocks.usage,
}));
import { useAuthStore } from './auth';

describe('login storage reminder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.access.accessToken = '';
    mocks.access.setAccessToken.mockImplementation((token: string) => { mocks.access.accessToken = token; });
  });
  it('shows capacity and expansion advice after successful login with <=10% remaining', async () => {
    mocks.usage.mockResolvedValue({ used_bytes: 90, limit_bytes: 100, remaining_bytes: 10, warning: true });
    await useAuthStore().authLogin({});
    await vi.waitFor(() => expect(mocks.warning).toHaveBeenCalledOnce());
    expect(mocks.warning).toHaveBeenCalledWith(expect.objectContaining({
      keyboard: true, closable: true, title: '存储空间即将用完', content: expect.stringContaining('购买存储扩容包'),
    }));
  });
  it('does not remind when capacity is sufficient', async () => {
    mocks.usage.mockResolvedValue({ used_bytes: 89, limit_bytes: 100, remaining_bytes: 11, warning: false });
    await useAuthStore().authLogin({});
    expect(mocks.warning).not.toHaveBeenCalled();
  });
  it('does not fail login when storage lookup fails', async () => {
    const log = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mocks.usage.mockRejectedValue(new Error('unavailable'));
    await expect(useAuthStore().authLogin({})).resolves.toMatchObject({ userInfo: { realName: 'Test' } });
    expect(mocks.warning).not.toHaveBeenCalled();
    log.mockRestore();
  });
});
