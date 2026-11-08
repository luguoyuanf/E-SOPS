import type { VbenFormSchema } from '#/adapter/form';
import type { OnActionClickFn, VxeTableGridColumns } from '#/adapter/vxe-table';
import type { UserRecord } from '#/api';

import { z } from '#/adapter/form';
import { getCurrentUserApi, listUserDepartmentOptionsApi, listUserPostOptionsApi, listRolesApi } from '#/api';
import { $t } from '#/locales';

const PROTECTED_ADMIN_EMAIL = 'admin@example.com';

function isProtectedAdmin(row: UserRecord) {
  return row.email?.toLowerCase() === PROTECTED_ADMIN_EMAIL;
}

export function useFormSchema(isEdit = false, isPlatformActor = false, tenantId?: string): VbenFormSchema[] {
  const passwordRule = z.string()
    .min(8, $t('ui.formRules.minLength', [$t('system.user.password'), 8]))
    .max(128, $t('ui.formRules.maxLength', [$t('system.user.password'), 128]));
  return [
    ...(isEdit ? [{
      component: 'Input',
      componentProps: { readonly: true },
      fieldName: 'id',
      label: $t('system.user.id'),
    }] : []),
    {
      component: 'Input',
      componentProps: { maxlength: 64, autocomplete: 'off', disabled: isEdit },
      fieldName: 'username',
      label: $t('system.user.username'),
      rules: isEdit ? z.string().optional().or(z.literal('')) : z.string().trim().min(1).max(64)
        .regex(/^[A-Za-z0-9][A-Za-z0-9_.-]*$/),
    },
    {
      component: 'Input',
      fieldName: 'email',
      componentProps: { autocomplete: 'off' },
      label: $t('system.user.email'),
      rules: z.string().trim().email($t('system.user.emailInvalid')).optional().or(z.literal('')),
    },
    {
      component: 'Input',
      fieldName: 'full_name',
      label: $t('system.user.fullName'),
    },
    {
      component: 'Input',
      componentProps: {
        maxlength: 11,
        placeholder: '13800138000',
      },
      fieldName: 'mobile',
      label: $t('system.user.mobile'),
      rules: z
        .string()
        .regex(/^1[3-9]\d{9}$/, $t('system.user.mobileInvalid'))
        .optional()
        .or(z.literal('')),
    },
    {
      component: 'DatePicker',
      componentProps: { allowClear: true, valueFormat: 'YYYY-MM-DD', class: 'w-full' },
      fieldName: 'hire_date',
      label: $t('system.user.hireDate'),
    },
    {
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: () => listUserDepartmentOptionsApi(tenantId),
        class: 'w-full',
        labelField: 'name',
        valueField: 'id',
      },
      fieldName: 'department_id',
      label: $t('system.user.dept'),
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: async () => {
          const user = await getCurrentUserApi();
          const result = await listRolesApi({ page: 1, page_size: 200, tenant_id: tenantId || user.tenant_id || undefined });
          return result.items;
        },
        class: 'w-full',
        labelField: 'name',
        mode: 'multiple',
        valueField: 'id',
      },
      fieldName: 'role_ids',
      label: $t('system.user.roles'),
      rules: isEdit ? z.array(z.string()).optional() : z.preprocess(
        (value) => value == null ? [] : value,
        z.array(z.string()).min(
          1,
          $t('ui.formRules.selectRequired', [$t('system.user.roles')]),
        ),
      ),
    },
    {
      component: 'ApiSelect',
      componentProps: {
        api: () => listUserPostOptionsApi(tenantId),
        class: 'w-full',
        labelField: 'name',
        mode: 'multiple',
        valueField: 'id',
      },
      fieldName: 'post_ids',
      label: $t('system.user.posts'),
    },
    {
      component: 'InputPassword',
      componentProps: { autocomplete: 'new-password' },
      fieldName: 'password',
      label: isEdit
        ? $t('system.user.newPassword')
        : $t('system.user.password'),
      rules: isEdit ? passwordRule.optional().or(z.literal('')) : passwordRule,
    },
    {
      component: 'Switch',
      defaultValue: true,
      fieldName: 'is_active',
      label: $t('common.enabled'),
    },
    ...(isPlatformActor ? [{
      component: 'Switch',
      defaultValue: false,
      fieldName: 'is_superuser',
      label: $t('system.user.superuser'),
    }] : []),
  ];
}

export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      fieldName: 'keyword',
      label: $t('system.user.name'),
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: [
          { label: $t('common.enabled'), value: true },
          { label: $t('common.disabled'), value: false },
        ],
      },
      fieldName: 'is_active',
      label: $t('system.user.status'),
    },
    {
      component: 'RangePicker',
      fieldName: 'createTime',
      label: $t('system.user.createTime'),
    },
  ];
}

export function useColumns(
  onActionClick: OnActionClickFn<UserRecord>,
  onStatusChange?: (
    newStatus: boolean,
    row: UserRecord,
  ) => PromiseLike<boolean | undefined>,
  canMutate: (row: UserRecord) => boolean = () => true,
  isPlatformActor = false,
): VxeTableGridColumns<UserRecord> {
  return [
    {
      field: 'username',
      minWidth: 140,
      title: $t('system.user.username'),
    },
    {
      field: 'email',
      minWidth: 200,
      title: $t('system.user.email'),
    },
    {
      field: 'mobile',
      minWidth: 140,
      title: $t('system.user.mobile'),
    },
    {
      field: 'hire_date',
      minWidth: 130,
      title: $t('system.user.hireDate'),
    },
    {
      field: 'role_names',
      minWidth: 160,
      title: $t('system.user.roles'),
      formatter: ({ row }) => row.role_names?.join('、') || '—',
    },
    {
      field: 'post_names',
      minWidth: 140,
      title: $t('system.user.posts'),
      formatter: ({ row }) => row.post_names?.join('、') || '—',
    },
    {
      cellRender: {
        attrs: { auth: 'system:user:update', beforeChange: onStatusChange },
        name: onStatusChange ? 'CellSwitch' : 'CellTag',
        props: {
          disabled: (row: UserRecord) => (!isPlatformActor && isProtectedAdmin(row)) || !canMutate(row),
        },
      },
      field: 'is_active',
      title: $t('system.user.status'),
      width: 100,
    },
    {
      field: 'full_name',
      minWidth: 120,
      title: $t('system.user.remark'),
    },
    {
      field: 'created_at',
      title: $t('system.user.createTime'),
      width: 180,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'email',
          nameTitle: $t('system.user.name'),
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            auth: 'system:user:update',
            code: 'edit',
            disabled: (row: UserRecord) => (!isPlatformActor && isProtectedAdmin(row)) || !canMutate(row),
          },
          {
            auth: 'system:user:delete',
            code: 'delete',
            disabled: (row: UserRecord) => row.deletion_protected || row.is_superuser || !canMutate(row),
          },
          {
            auth: 'system:user:update',
            code: 'reset-mfa',
            disabled: (row: UserRecord) => (!isPlatformActor && isProtectedAdmin(row)) || !canMutate(row),
            text: '重置 MFA',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: $t('system.user.operation'),
      width: 112,
    },
  ];
}
