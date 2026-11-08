import { createApp, h } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({
  drawer: {} as any,
  data: {id: 'one', tenant_id: 'foreign-tenant', username: 'operator', full_name: 'Existing', email: null},
  form: {resetForm: vi.fn(), setState: vi.fn(), setValues: vi.fn(), validate: vi.fn(), getValues: vi.fn()},
  roles: vi.fn(), posts: vi.fn(), update: vi.fn(),
}));
vi.mock('@vben/common-ui', () => ({useVbenDrawer: (options: any) => {
  mock.drawer = options;
  return [() => null, {getData: () => mock.data, setState: vi.fn(), lock: vi.fn(), unlock: vi.fn(), close: vi.fn()}];
}}));
vi.mock('@vben/stores', () => ({useUserStore: () => ({userInfo: {roles: ['super']}})}));
vi.mock('#/adapter/form', () => ({useVbenForm: () => [() => null, mock.form]}));
vi.mock('./data', () => ({useFormSchema: vi.fn(() => [])}));
vi.mock('#/api', () => ({getUserRolesApi: mock.roles, getUserPostsApi: mock.posts,
  uploadUserAvatarApi: vi.fn(), updateUserApi: mock.update, createUserApi: vi.fn(), updateUserRolesApi: vi.fn(), updateUserPostsApi: vi.fn()}));
import Form from './modules/form.vue';

function deferred() {
  let resolve!: (value: any[]) => void;
  const promise = new Promise<any[]>(done => {resolve = done;});
  return {promise, resolve};
}

describe('user edit loading', () => {
  beforeEach(() => {vi.clearAllMocks();});
  it('fills existing fields before requests finish, blocks early save, and only fills relationships afterwards', async () => {
    const roles = deferred(); const posts = deferred();
    mock.roles.mockReturnValue(roles.promise); mock.posts.mockReturnValue(posts.promise);
    const app = createApp({render: () => h(Form)}); app.mount(document.createElement('div'));
    const pending = mock.drawer.onOpenChange(true);
    expect(mock.form.setValues).toHaveBeenCalledWith(expect.objectContaining({username: 'operator', full_name: 'Existing'}));
    expect(mock.roles).toHaveBeenCalledWith('one', 'foreign-tenant'); expect(mock.posts).toHaveBeenCalledWith('one', 'foreign-tenant');
    await mock.drawer.onConfirm(); expect(mock.form.validate).not.toHaveBeenCalled();
    roles.resolve([{id:'role'}]); posts.resolve([{id:'post'}]); await pending;
    expect(mock.form.setValues).toHaveBeenLastCalledWith({role_ids:['role'],post_ids:['post']});
    mock.form.validate.mockResolvedValue({valid: true});
    mock.form.getValues.mockResolvedValue({id: 'read-only-id', username: 'tampered', email: '', role_ids: ['role'], post_ids: ['post']});
    await mock.drawer.onConfirm();
    expect(mock.update).toHaveBeenCalledWith('one', expect.not.objectContaining({username: expect.anything()}), 'foreign-tenant');
    expect(mock.update.mock.calls[0]?.[1]).not.toHaveProperty('id');
    app.unmount();
  });
  it('shows the email login identifier for a legacy account without a username', async () => {
    const original = mock.data;
    mock.data = {id: 'legacy', username: '', full_name: 'Legacy', email: 'legacy@example.com'} as any;
    mock.roles.mockResolvedValue([]); mock.posts.mockResolvedValue([]);
    const app = createApp({render: () => h(Form)}); app.mount(document.createElement('div'));
    await mock.drawer.onOpenChange(true);
    expect(mock.form.setValues).toHaveBeenCalledWith(expect.objectContaining({username: 'legacy@example.com'}));
    app.unmount(); mock.data = original;
  });
  it('ignores responses arriving after the drawer was closed', async () => {
    const roles = deferred(); const posts = deferred();
    mock.roles.mockReturnValue(roles.promise); mock.posts.mockReturnValue(posts.promise);
    const app = createApp({render: () => h(Form)}); app.mount(document.createElement('div'));
    const pending = mock.drawer.onOpenChange(true); await mock.drawer.onOpenChange(false);
    const count = mock.form.setValues.mock.calls.length;
    roles.resolve([]); posts.resolve([]); await pending;
    expect(mock.form.setValues).toHaveBeenCalledTimes(count);
    app.unmount();
  });
});
