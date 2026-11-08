<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { RoleRecord } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Alert, Button, message } from 'ant-design-vue';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteRoleApi, listRolesApi, updateRoleApi } from '#/api';
import { $t } from '#/locales';
import { createdRangeQuery } from '#/utils/created-range';

import { buildKeyword, confirmAction } from '../shared/utils';
import { useTenantReadScope } from '../shared/tenant-scope';
import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';
import Permission from './modules/permission.vue';

const tenantScope = useTenantReadScope();
const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [PermissionDrawer, permissionDrawerApi] = useVbenDrawer({
  connectedComponent: Permission,
  destroyOnClose: true,
});

async function onStatusChange(newStatus: boolean, row: RoleRecord) {
  if (!tenantScope.canMutate(row)) { message.warning($t('system.tenantScope.switchFirst')); return false; }
  try {
    await confirmAction(
      `确认将角色 ${row.name} 的状态切换为【${newStatus ? '启用' : '禁用'}】吗？`,
      '切换状态',
    );
    await updateRoleApi(row.id, { is_active: newStatus });
    return true;
  } catch {
    return false;
  }
}

function onActionClick({ code, row }: OnActionClickParams<RoleRecord>) {
  if (!tenantScope.canMutate(row)) { message.warning($t('system.tenantScope.switchFirst')); return; }
  switch (code) {
    case 'delete': {
      void onDelete(row);
      break;
    }
    case 'edit': {
      formDrawerApi.setData(row).open();
      break;
    }
    case 'permission': {
      permissionDrawerApi.setData(row).open();
      break;
    }
  }
}

async function onDelete(row: RoleRecord) {
  const hideLoading = message.loading({
    content: `正在删除 ${row.name}`,
    duration: 0,
    key: 'role_delete',
  });
  try {
    await deleteRoleApi(row.id);
    message.success({
      content: `${row.name} 已删除`,
      key: 'role_delete',
    });
    onRefresh();
  } catch {
    hideLoading();
  }
}

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    fieldMappingTime: [['createTime', ['startTime', 'endTime']]],
    schema: [...tenantScope.filterSchema(), ...useGridFormSchema()],
    submitOnChange: true,
  },
  gridOptions: {
    columns: [...(tenantScope.isRoot.value ? [{field:'tenant_id',title:$t('system.tenantScope.tenant'),minWidth:160,formatter:({row}: {row: unknown})=>tenantScope.tenantName(row)}] : []), ...(useColumns(onActionClick, onStatusChange, tenantScope.canMutate) ?? [])],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          await tenantScope.ready;
          const result = await listRolesApi({
            ...createdRangeQuery([formValues.startTime, formValues.endTime]),
            tenant_id: tenantScope.isRoot.value ? formValues.tenant_id : undefined,
            keyword: buildKeyword(
              formValues.name,
              formValues.code,
              formValues.description,
            ),
            page: page.currentPage,
            page_size: page.pageSize,
          });
          return {...result,items:result.items.map(row=>({...row,__scope_key:`${row.id}:${row.tenant_id}`}))};
        },
      },
    },
    rowConfig: {
      keyField: '__scope_key',
    },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: true,
      zoom: true,
    },
  } as VxeTableGridOptions<RoleRecord>,
});

function onRefresh() {
  gridApi.query();
}

function onCreate() {
  formDrawerApi.setData(undefined).open();
}
</script>

<template>
  <Page auto-content-height>
    <Alert v-if="tenantScope.isRoot.value" class="mb-3" type="info" show-icon :message="$t('system.tenantScope.readOnly')" />
    <FormDrawer @success="onRefresh" />
    <PermissionDrawer @success="onRefresh" />
    <Grid table-title="角色列表">
      <template #toolbar-tools>
        <Button
          v-access:code="'system:role:create'"
          type="primary"
          @click="onCreate"
        >
          <Plus class="size-5" />
          新增角色
        </Button>
      </template>
    </Grid>
  </Page>
</template>
