import { describe, expect, it, vi } from 'vitest';
import type { z } from '#/adapter/form';
type ZodTypeAny = z.ZodTypeAny;

vi.mock('#/adapter/form', async () => ({ z: (await import('@vben/common-ui')).z }));
vi.mock('#/locales', () => ({ $t: (key: string) => key }));
vi.mock('@vben/utils', () => ({ formatDateTime: vi.fn() }));
vi.mock('#/api', () => ({
  DEFAULT_TENANT_ID: 'default', getCurrentUserApi: vi.fn(),
  listDepartmentsApi: vi.fn(), listPostsApi: vi.fn(), listRolesApi: vi.fn(),
  listUserDepartmentOptionsApi: vi.fn(), listUserPostOptionsApi: vi.fn(),
  listSimpleTenantPlansApi: vi.fn(), listSimpleTenantTemplatesApi: vi.fn(),
}));

import { useColumns as userColumns, useFormSchema as userSchema } from './users/data';
import { useFormSchema as tenantSchema } from './tenants/data';
import { useFormSchema as postSchema } from './posts/data';
import { useFormSchema as roleSchema } from './roles/data';
import { useFormSchema as tenantPlanSchema } from './tenant-plans/data';
import { useFormSchema as tenantTemplateSchema } from './tenant-templates/data';
import { useTypeFormSchema as dictionarySchema } from './dictionaries/data';
import { userPayloadForActor } from './users/payload';
import { listUserDepartmentOptionsApi, listUserPostOptionsApi } from '#/api';

type Field = ReturnType<typeof tenantSchema>[number];
async function rule(field: Field, values: Record<string, unknown> = {}) {
  const dynamic = field.dependencies?.rules;
  return (dynamic ? await dynamic(values, {} as never, {} as never) : field.rules) as ZodTypeAny;
}
function field(schema: Field[], name: string) {
  const result = schema.find(item => item.fieldName === name);
  if (!result) throw new Error(`Missing ${name}`);
  return result;
}

describe('required field contracts', () => {
  it.each([false, true])('validates provided user passwords at 8–128 characters (editing=%s)', async (editing) => {
    const password = await rule(field(userSchema(editing), 'password'));
    expect(password.safeParse('1234567').success).toBe(false);
    expect(password.safeParse('12345678').success).toBe(true);
    expect(password.safeParse('x'.repeat(128)).success).toBe(true);
    expect(password.safeParse('x'.repeat(129)).success).toBe(false);
    expect(password.safeParse('').success).toBe(editing);
    expect(password.safeParse(undefined).success).toBe(editing);
    expect(password.isOptional()).toBe(editing);
  });
  it('requires trial end only when lifecycle is trial', async () => {
    const trialEnd = field(tenantSchema(() => false), 'trial_ends_at');
    const required = await rule(trialEnd, {lifecycle_status:'trial'});
    expect(required.safeParse(undefined).success).toBe(false);
    expect(required.safeParse('').success).toBe(false);
    expect(required.safeParse('2026-11-01T00:00:00Z').success).toBe(true);
    expect(required.isOptional()).toBe(false);
    const optional = await rule(trialEnd, {lifecycle_status:'formal'});
    expect(optional.safeParse(undefined).success).toBe(true);
    expect(optional.isOptional()).toBe(true);
    expect(field(tenantSchema(() => false), 'effective_at').rules).toBeUndefined();
  });
  it('allows no initial administrator and makes only the provided credential counterpart required', async () => {
    const schema = tenantSchema(() => false);
    const email = field(schema, 'username');
    const password = field(schema, 'password');
    expect((await rule(email)).safeParse('').success).toBe(true);
    expect((await rule(password)).safeParse('').success).toBe(true);
    const requiredEmail = await rule(email, {password:'12345678'});
    expect(requiredEmail.isOptional()).toBe(false);
    expect(requiredEmail.safeParse('').success).toBe(false);
    expect(requiredEmail.safeParse('invalid').success).toBe(false);
    expect(requiredEmail.safeParse('admin@example.com').success).toBe(true);
    const requiredPassword = await rule(password, {username:'admin@example.com'});
    expect(requiredPassword.isOptional()).toBe(false);
    expect(requiredPassword.safeParse('').success).toBe(false);
    expect(requiredPassword.safeParse('short').success).toBe(false);
    expect(requiredPassword.safeParse('12345678').success).toBe(true);
    expect((await rule(password, {username:''})).isOptional()).toBe(true);
    expect((await rule(email, {password:''})).isOptional()).toBe(true);
  });
  it('allows optional usernames and enforces the backend identifier syntax', async () => {
    for (const entry of [field(tenantSchema(() => false), 'admin_username')]) {
      const username = await rule(entry);
      expect(username.isOptional()).toBe(true);
      for (const value of [undefined, '', '   ', 'tangyun', 'Tang_Yun.1', 'x'.repeat(64)]) {
        expect(username.safeParse(value).success).toBe(true);
      }
      for (const value of ['a@example.com', '_first', '中文', 'x'.repeat(65)]) {
        expect(username.safeParse(value).success).toBe(false);
      }
    }
  });
  it.each([false, true])('requires username and allows an empty email (editing=%s)', async (editing) => {
    const username = await rule(field(userSchema(editing), 'username'));
    const email = await rule(field(userSchema(editing), 'email'));
    for (const value of [undefined, '', '   ']) expect(username.safeParse(value).success).toBe(editing);
    expect(username.safeParse('operator.1').success).toBe(true);
    for (const value of [undefined, '', 'valid@example.com']) expect(email.safeParse(value).success).toBe(true);
    expect(email.safeParse('invalid').success).toBe(false);
  });
  it('locks existing usernames while allowing legacy users without a username to be edited', async () => {
    expect(field(userSchema(true), 'username').componentProps).toMatchObject({disabled: true});
    expect(field(userSchema(false), 'username').componentProps).toMatchObject({disabled: false});
    expect((await rule(field(userSchema(true), 'username'))).safeParse('').success).toBe(true);
  });
  it('requires email and password when a tenant initial administrator username is supplied', async () => {
    const schema = tenantSchema(() => false);
    for (const name of ['username', 'password']) {
      const required = await rule(field(schema, name), {admin_username:'tangyun'});
      expect(required.isOptional()).toBe(false);
      expect(required.safeParse('').success).toBe(false);
      const optional = await rule(field(schema, name), {admin_username:'   '});
      expect(optional.isOptional()).toBe(true);
    }
  });

  it('keeps account management fields separate from saved login credentials', () => {
    for (const schema of [userSchema(false), userSchema(true)]) {
      expect(field(schema, 'email').componentProps).toMatchObject({autocomplete:'off'});
      expect(field(schema, 'username').componentProps).toMatchObject({autocomplete:'off'});
      expect(field(schema, 'password').componentProps).toMatchObject({autocomplete:'new-password'});
    }
    const schema = tenantSchema(() => false);
    expect(field(schema, 'username').componentProps).toMatchObject({autocomplete:'off'});
    expect(field(schema, 'admin_username').componentProps).toMatchObject({autocomplete:'off'});
    expect(field(schema, 'password').componentProps).toMatchObject({autocomplete:'new-password'});
  });

  it('does not display or submit the platform privilege flag for tenant actors', () => {
    for (const editing of [false, true]) {
      expect(userSchema(editing, false).some(item => item.fieldName === 'is_superuser')).toBe(false);
      expect(userSchema(editing, true).some(item => item.fieldName === 'is_superuser')).toBe(true);
    }
    for (const flag of [false, true]) {
      const payload = {email:'test@example.com',full_name:'',is_superuser:flag,is_active:true};
      expect(userPayloadForActor(payload, false)).toEqual({email:'test@example.com',full_name:'',is_active:true});
      expect(userPayloadForActor(payload, true)).toEqual(payload);
      expect(payload).toHaveProperty('is_superuser', flag);
    }
  });

  it('binds user form choices directly to raw current-tenant option arrays', async () => {
    for (const [name, api] of [['department_id', listUserDepartmentOptionsApi], ['post_ids', listUserPostOptionsApi]] as const) {
      const options = [{id:'synthetic-option',name:'Current tenant option'}];
      vi.mocked(api).mockResolvedValue(options as never);
      const props = field(userSchema(true, true, 'target-tenant'), name).componentProps as {api: () => Promise<unknown>};
      expect(await props.api()).toBe(options);
      expect(api).toHaveBeenCalledWith('target-tenant');
    }
  });

  it('allows platform actors to edit and delete users across tenant rows', () => {
    const columns = userColumns(vi.fn(), undefined, () => true, true);
    const actions = (columns?.find(item => item.field === 'operation')?.cellRender as any).options;
    for (const action of actions.filter((item: any) => ['edit', 'delete'].includes(item.code))) {
      expect(action.disabled({email: 'admin@example.com', tenant_id: 'foreign'})).toBe(false);
    }
  });

});


describe('optional entity codes', () => {
  it.each([
    ['tenant', () => tenantSchema(() => false)],
    ['post', postSchema],
    ['role', roleSchema],
    ['tenant plan', tenantPlanSchema],
    ['tenant template', tenantTemplateSchema],
    ['dictionary', dictionarySchema],
  ])('allows blank codes for %s without weakening names', async (_name, schema) => {
    const fields = schema();
    const code = await rule(field(fields, 'code'));
    for (const value of [undefined, '', '   ', 'MANUAL-001']) {
      expect(code.safeParse(value).success).toBe(true);
    }
    expect(code.safeParse('x'.repeat(101)).success).toBe(false);
    expect((await rule(field(fields, 'name'))).safeParse('').success).toBe(false);
  });
});
