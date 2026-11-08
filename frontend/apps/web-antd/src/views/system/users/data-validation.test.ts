import { describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ locale: 'zh' }));
vi.mock('#/locales', () => ({
  $t: (key: string, args?: string[]) => {
    if (key === 'system.user.roles') return state.locale === 'zh' ? '角色' : 'Roles';
    if (key === 'ui.formRules.selectRequired') return state.locale === 'zh' ? `请选择${args?.[0]}` : `Please select ${args?.[0]}`;
    return key;
  },
}));

import { useFormSchema } from './data';

describe('new user role validation', () => {
  it.each([
    ['zh', '请选择角色'],
    ['en', 'Please select Roles'],
  ])('uses the selected language for missing roles (%s)', (locale, expected) => {
    state.locale = locale;
    const rules = useFormSchema().find((field) => field.fieldName === 'role_ids')!.rules as any;
    for (const value of [undefined, null, []]) {
      const result = rules.safeParse(value);
      expect(result.success).toBe(false);
      expect(result.error.issues[0].message).toBe(expected);
    }
    expect(rules.safeParse(['role-id']).success).toBe(true);
  });
});
