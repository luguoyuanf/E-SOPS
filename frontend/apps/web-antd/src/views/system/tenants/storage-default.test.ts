import { createApp, h } from 'vue';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  options: {} as any,
  read: vi.fn(), save: vi.fn(),
  form: { resetForm: vi.fn(), setValues: vi.fn(), validate: vi.fn(), getValues: vi.fn() },
  close: vi.fn(), lock: vi.fn(), unlock: vi.fn(),
}));
vi.mock('@vben/common-ui', () => ({ useVbenDrawer: (options: any) => {
  mocks.options = options;
  return [() => null, { close: mocks.close, lock: mocks.lock, unlock: mocks.unlock }];
} }));
vi.mock('#/adapter/form', () => ({ useVbenForm: () => [() => null, mocks.form], z: {
  number: () => ({ int: () => ({ min: () => ({ max: () => ({}) }) }) }),
} }));
vi.mock('#/api/core/tenant-storage', () => ({ getStorageDefault: mocks.read, saveStorageDefault: mocks.save }));
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
vi.mock('ant-design-vue', () => ({ Alert: () => null, message: { success: vi.fn() } }));
import StorageDefault from './modules/storage-default.vue';

describe('platform default capacity', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ capacity_mib: 1024 });
    mocks.save.mockResolvedValue({ capacity_mib: 2048 });
    mocks.form.validate.mockResolvedValue({ valid: true });
    mocks.form.getValues.mockResolvedValue({ capacity_mib: 2048 });
  });
  it('loads the current default and saves the administrator value', async () => {
    const app = createApp({ render: () => h(StorageDefault) }); app.mount(document.createElement('div'));
    await mocks.options.onOpenChange(true);
    expect(mocks.form.setValues).toHaveBeenCalledWith({ capacity_mib: 1024 });
    await mocks.options.onConfirm();
    expect(mocks.save).toHaveBeenCalledWith({ capacity_mib: 2048 });
    expect(mocks.close).toHaveBeenCalledOnce();
    app.unmount();
  });
  it('does not save before loading or with invalid input', async () => {
    const app = createApp({ render: () => h(StorageDefault) }); app.mount(document.createElement('div'));
    await mocks.options.onConfirm(); expect(mocks.save).not.toHaveBeenCalled();
    await mocks.options.onOpenChange(true);
    mocks.form.validate.mockResolvedValue({ valid: false });
    await mocks.options.onConfirm(); expect(mocks.save).not.toHaveBeenCalled();
    app.unmount();
  });
});
