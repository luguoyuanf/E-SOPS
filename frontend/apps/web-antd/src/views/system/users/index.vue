<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { DepartmentRecord, UserRecord } from '#/api';

import { computed, onMounted, ref } from 'vue';

import { Page, Tree, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { IconifyIcon, Plus } from '@vben/icons';

import { Alert, Button, Card, InputSearch, message } from 'ant-design-vue';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  deleteUserApi,
  downloadApi,
  listUserDepartmentOptionsApi,
  listUsersApi,
  resetUserMfaApi,
  updateUserApi,
  usersExportPath,
  usersImportTemplatePath,
} from '#/api';

import { $t } from '#/locales';
import { createdRangeQuery } from '#/utils/created-range';

import { buildDepartmentTree, confirmAction } from '../shared/utils';
import { useTenantReadScope } from '../shared/tenant-scope';
import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';
import Import from './modules/import.vue';

const allDepartments = ref<DepartmentRecord[]>([]);
const deptSearchValue = ref('');
const selectedDeptId = ref<string>('');

const deptTreeData = computed(() => {
  const keyword = deptSearchValue.value.trim().toLowerCase();
  const source = keyword
    ? allDepartments.value.filter((department) =>
        department.name.toLowerCase().includes(keyword),
      )
    : allDepartments.value;
  return buildDepartmentTree(source);
});

const tenantScope = useTenantReadScope();
const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [ImportModal, importModalApi] = useVbenModal({
  connectedComponent: Import,
  destroyOnClose: true,
});

async function onStatusChange(newStatus: boolean, row: UserRecord) {
  if (!(tenantScope.isRoot.value || tenantScope.canMutate(row))) { message.warning($t('system.tenantScope.switchFirst')); return false; }
  try {
    await confirmAction(
      $t('system.user.toggleStatusContent', [
        row.email,
        newStatus ? $t('common.enabled') : $t('common.disabled'),
      ]),
      $t('system.user.toggleStatusTitle'),
    );
    await updateUserApi(row.id, { is_active: newStatus }, row.tenant_id ?? undefined);
    return true;
  } catch {
    return false;
  }
}

function onActionClick({ code, row }: OnActionClickParams<UserRecord>) {
  if (!(tenantScope.isRoot.value || tenantScope.canMutate(row))) { message.warning($t('system.tenantScope.switchFirst')); return; }
  switch (code) {
    case 'delete': {
      void onDelete(row);
      break;
    }
    case 'edit': {
      formDrawerApi.setData(row).open();
      break;
    }
    case 'reset-mfa': {
      void onResetMfa(row);
      break;
    }
  }
}

async function onResetMfa(row: UserRecord) {
  try {
    await confirmAction(
      `确认重置用户 ${row.email} 的 MFA 吗？该用户的现有登录会话将失效。`,
      '重置 MFA',
    );
    await resetUserMfaApi(row.id, row.tenant_id ?? undefined);
    message.success('MFA 已重置');
    onRefresh();
  } catch {
    // 用户取消或接口失败时由全局错误处理接管
  }
}

async function onDelete(row: UserRecord) {
  const hideLoading = message.loading({
    content: $t('system.user.deleting', [row.email]),
    duration: 0,
    key: 'user_delete',
  });
  try {
    await deleteUserApi(row.id, row.tenant_id ?? undefined);
    message.success({
      content: $t('system.user.deleteSuccess'),
      key: 'user_delete',
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
    columns: [...(tenantScope.isRoot.value ? [{field:'tenant_id',title:$t('system.tenantScope.tenant'),minWidth:160,formatter:({row}: {row: unknown})=>tenantScope.tenantName(row)}] : []), ...(useColumns(onActionClick, onStatusChange, (row) => tenantScope.isRoot.value || tenantScope.canMutate(row), tenantScope.isRoot.value) ?? [])],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          await tenantScope.ready;
          const result = await listUsersApi({
            ...createdRangeQuery([formValues.startTime, formValues.endTime]),
            tenant_id: tenantScope.isRoot.value ? formValues.tenant_id : undefined,
            department_id: selectedDeptId.value || undefined,
            is_active:
              formValues.is_active === undefined || formValues.is_active === null
                ? undefined
                : formValues.is_active,
            keyword: formValues.keyword || undefined,
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
  } as VxeTableGridOptions<UserRecord>,
});

function onRefresh() {
  gridApi.query();
}

function onCreate() {
  formDrawerApi.setData(undefined).open();
}

async function exportUsers() {
  await downloadApi(usersExportPath, '用户列表.csv');
}

async function downloadTemplate() {
  await downloadApi(usersImportTemplatePath, '用户导入模板.csv');
}

function openImport() {
  importModalApi.open();
}

function selectDept(item?: { value: DepartmentRecord }) {
  selectedDeptId.value = item?.value.id ?? '';
  gridApi.query();
}

function getDeptNodeIcon(
  department: DepartmentRecord & { children?: DepartmentRecord[] },
) {
  return department.children?.length ? 'lucide:folder' : 'lucide:file';
}

async function loadDepartments() {
  allDepartments.value = await listUserDepartmentOptionsApi();
}

onMounted(() => { if (!tenantScope.isRoot.value) void loadDepartments(); });
</script>

<template>
  <Page auto-content-height>
    <Alert v-if="tenantScope.isRoot.value" class="mb-3" type="info" show-icon :message="$t('system.user.platformManagement')" />
    <FormDrawer @success="onRefresh" />
    <ImportModal @success="onRefresh" />
    <div class="flex size-full min-h-0">
      <Card
        v-if="!tenantScope.isRoot.value"
        :bordered="false"
        class="dept-tree-card flex h-full min-h-0 w-1/6 min-w-[220px] flex-col"
      >
        <InputSearch
          v-model:value="deptSearchValue"
          allow-clear
          class="mb-3 shrink-0"
          :placeholder="$t('system.user.placeholder')"
        />
        <div class="dept-tree-scroll min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          <div
            class="dept-tree-all mb-1 cursor-pointer py-1 text-sm"
            :class="{ 'dept-tree-all--active': !selectedDeptId }"
            @click="selectDept()"
          >
            {{ $t('system.dept.list') }}
          </div>
          <Tree
            v-model="selectedDeptId"
            class="dept-tree"
            :default-expanded-level="2"
            label-field="name"
            :show-icon="false"
            :transition="false"
            value-field="id"
            :tree-data="deptTreeData"
            @select="selectDept"
          >
            <template #node="{ value }">
              <span class="dept-tree-node">
                <IconifyIcon
                  class="dept-tree-node__icon"
                  :icon="getDeptNodeIcon(value)"
                />
                <span class="dept-tree-node__label">{{ value.name }}</span>
              </span>
            </template>
          </Tree>
        </div>
      </Card>

      <div class="min-w-0 flex-1" :class="tenantScope.isRoot.value ? '' : 'ml-4'">
        <Grid :table-title="$t('system.user.list')">
          <template #toolbar-tools>
            <Button v-access:code="'system:user:create'" type="primary" @click="onCreate">
              <Plus class="size-5" />
              {{ $t('system.user.createUser') }}
            </Button>
            <Button v-access:code="'system:user:list'" class="ml-2" @click="exportUsers">
              {{ $t('system.user.export') }}
            </Button>
            <Button
              v-access:code="'system:user:create'"
              class="ml-2"
              @click="downloadTemplate"
            >
              {{ $t('system.user.template') }}
            </Button>
            <Button v-access:code="'system:user:create'" class="ml-2" @click="openImport">
              {{ $t('system.user.import') }}
            </Button>
          </template>
        </Grid>
      </div>
    </div>
  </Page>
</template>

<style scoped>
.dept-tree-card :deep(.ant-card-body) {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  padding: 12px;
}

.dept-tree-all {
  color: hsl(var(--foreground) / 80%);
  line-height: 1.75;
}

.dept-tree-all--active {
  color: hsl(var(--foreground));
  text-decoration: underline;
  text-underline-offset: 2px;
}

.dept-tree :deep(.container) {
  font-weight: 400;
  border-radius: 0;
}

.dept-tree :deep(.tree-node) {
  margin: 0;
  padding: 4px 0;
  border-radius: 0;
  line-height: 1.75;
}

.dept-tree :deep(.tree-node[data-selected]) {
  background: transparent;
}

.dept-tree :deep(.tree-node[data-selected] .dept-tree-node__label) {
  color: hsl(var(--foreground));
  text-decoration: underline;
  text-underline-offset: 2px;
}

.dept-tree :deep(.tree-node:hover) {
  background: transparent;
}

.dept-tree :deep(.tree-node > svg:first-child) {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  margin-right: 2px;
  color: hsl(var(--foreground) / 65%);
  stroke-width: 2.5px;
}

.dept-tree-node {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
}

.dept-tree-node__icon {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: hsl(var(--foreground) / 70%);
}

.dept-tree-node__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: hsl(var(--foreground) / 85%);
}
</style>
