import { generateAccessible } from '@vben/access';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({
  manifest: vi.fn(), menus: vi.fn(), close: vi.fn(), loading: vi.fn(), warning: vi.fn(),
}));
vi.mock('@vben/access', () => ({ generateAccessible: vi.fn() }));
vi.mock('@vben/preferences', () => ({ preferences: { app: { accessMode: 'backend' } } }));
vi.mock('ant-design-vue', () => ({ message: { loading: mock.loading, warning: mock.warning } }));
vi.mock('#/api', () => ({ getAllMenusApi: mock.menus, getBuildManifestApi: mock.manifest }));
vi.mock('#/layouts', () => ({ BasicLayout: {}, IFrameView: {} }));
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
vi.mock('./generated-module-pages', () => ({ modulePageMap: {} }));
vi.mock('#/modules/manifest-compatibility', () => {
  class ManifestMismatchError extends Error {}
  return {
    ManifestMismatchError,
    assertManifestCompatibility: (manifest: { compatible: boolean }) => {
      if (!manifest.compatible) throw new ManifestMismatchError('incompatible');
    },
  };
});
import { generateAccess, loadBackendMenus } from './access';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe('menu initialization', () => {
  beforeEach(() => { vi.clearAllMocks(); mock.loading.mockReturnValue(mock.close); });
  it('starts independent fetches together and waits for the manifest response', async () => {
    const manifest = deferred<{ compatible: boolean }>();
    const menu = [{ name: 'Authorized' }];
    mock.manifest.mockReturnValue(manifest.promise); mock.menus.mockResolvedValue(menu);
    const result = loadBackendMenus(); let completed = false;
    void result.then(() => { completed = true; });
    expect(mock.manifest).toHaveBeenCalledOnce(); expect(mock.menus).toHaveBeenCalledOnce();
    await Promise.resolve(); expect(completed).toBe(false); expect(mock.close).not.toHaveBeenCalled();
    manifest.resolve({ compatible: true });
    expect(await result).toBe(menu); expect(mock.close).toHaveBeenCalledOnce();
  });
  it('shows a warning but still loads menus when versions differ', async () => {
    mock.manifest.mockResolvedValue({ compatible: false }); mock.menus.mockResolvedValue([{ name: 'Wrong edition' }]);
    expect(await loadBackendMenus()).toEqual([{ name: 'Wrong edition' }]);
    expect(mock.warning).toHaveBeenCalledOnce(); expect(mock.close).toHaveBeenCalledOnce();
  });
  it('closes the loading indicator on request failure', async () => {
    mock.manifest.mockResolvedValue({ compatible: true }); mock.menus.mockRejectedValue(new Error('network failure'));
    await expect(loadBackendMenus()).rejects.toThrow('network failure');
    expect(mock.close).toHaveBeenCalledOnce();
  });
});

it('removes routes from the previous account before installing new menus', async () => {
  const router = { hasRoute: vi.fn().mockReturnValue(true), removeRoute: vi.fn() };
  vi.mocked(generateAccessible)
    .mockResolvedValueOnce({ accessibleMenus: [], accessibleRoutes: [{ name: 'OldMenu', path: '/old' }] } as never)
    .mockResolvedValueOnce({ accessibleMenus: [], accessibleRoutes: [] } as never);

  await generateAccess({ router } as never, []);
  await generateAccess({ router } as never, []);

  expect(router.removeRoute).toHaveBeenCalledWith('OldMenu');
});
