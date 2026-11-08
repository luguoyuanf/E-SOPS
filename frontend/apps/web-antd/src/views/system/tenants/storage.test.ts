import { createApp, defineComponent, h, nextTick } from 'vue';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  options: {} as any, model: {} as any,
  tenant: { id: 'tenant-a', name: 'Factory A' },
  usage: vi.fn(), history: vi.fn(), grant: vi.fn(), validate: vi.fn(),
  lock: vi.fn(), unlock: vi.fn(),
}));
vi.mock('@vben/common-ui', () => ({ useVbenDrawer: (options: any) => {
  mocks.options = options;
  return [defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }), {
    getData: () => mocks.tenant, lock: mocks.lock, unlock: mocks.unlock,
  }];
} }));
vi.mock('ant-design-vue', () => {
  const stub = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
  const form = defineComponent({
    props: ['model'], setup: (props, { expose, slots }) => {
      mocks.model = props.model;
      expose({ validate: mocks.validate, clearValidate: vi.fn() });
      return () => h('div', slots.default?.());
    },
  });
  return { Alert: stub, Button: stub, Descriptions: stub, DescriptionsItem: stub, Form: Object.assign(form, { Item: stub }), Input: stub, InputNumber: stub, Table: stub, Tag: stub, message: { success: vi.fn() } };
});
vi.mock('#/api/core/tenant-storage', () => ({ getStorageUsage: mocks.usage, listStorageGrants: mocks.history, grantStorage: mocks.grant }));
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
import Storage from './modules/storage.vue';

async function mount() {
  const app = createApp({ render: () => h(Storage) });
  app.mount(document.createElement('div'));
  await nextTick();
  await mocks.options.onOpenChange(true);
  await nextTick();
  return app;
}

describe('tenant storage drawer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.usage.mockResolvedValue({ used_bytes: 100, base_bytes: 1024, active_grant_bytes: 1024, limit_bytes: 2048 });
    mocks.history.mockResolvedValue({ items: [] });
    mocks.grant.mockResolvedValue({});
    mocks.validate.mockResolvedValue({});
  });
  it('loads the selected tenant and adds a one-year package in bytes', async () => {
    const app = await mount();
    expect(mocks.usage).toHaveBeenCalledWith('tenant-a');
    expect(mocks.history).toHaveBeenCalledWith('tenant-a');
    mocks.model.capacity_mb = 2048;
    mocks.model.starts_on = '2026-10-30';
    mocks.model.note = '  expansion  ';
    await mocks.options.onConfirm();
    const payload = mocks.grant.mock.calls[0]?.[0];
    expect(payload).toMatchObject({ tenant_id: 'tenant-a', capacity_bytes: 2147483648, note: 'expansion' });
    expect(new Date(payload.expires_at).getFullYear() - new Date(payload.starts_at).getFullYear()).toBe(1);
    expect(mocks.usage).toHaveBeenCalledTimes(2);
    expect(mocks.unlock).toHaveBeenCalledOnce();
    app.unmount();
  });
  it('does not grant capacity when validation fails', async () => {
    const app = await mount();
    mocks.validate.mockRejectedValue(new Error('required'));
    await mocks.options.onConfirm();
    expect(mocks.grant).not.toHaveBeenCalled();
    app.unmount();
  });
  it('does not grant if capacity cannot be loaded', async () => {
    mocks.usage.mockRejectedValue(new Error('unavailable'));
    const app = await mount();
    await mocks.options.onConfirm();
    expect(mocks.grant).not.toHaveBeenCalled();
    app.unmount();
  });
  it('prevents repeated confirmation while granting', async () => {
    const app = await mount();
    let done!: () => void;
    mocks.grant.mockImplementation(() => new Promise<void>((resolve) => { done = resolve; }));
    const first = mocks.options.onConfirm();
    await nextTick();
    await mocks.options.onConfirm();
    expect(mocks.grant).toHaveBeenCalledOnce();
    done();
    await first;
    app.unmount();
  });
});
