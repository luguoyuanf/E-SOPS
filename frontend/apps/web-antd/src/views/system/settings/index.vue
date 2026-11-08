<script lang="ts" setup>
import { createdRangeField, createdRangeQuery } from '#/utils/created-range';
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemSettingRecord } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';
import { Button } from 'ant-design-vue';
import { useRouter } from 'vue-router';

import { useTenantVxeGrid as useVbenVxeGrid } from '#/adapter/vxe-table';
import { listSettingsApi } from '#/api';

import { buildKeyword } from '../shared/utils';
import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

const router = useRouter();
const userStore = useUserStore();

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

function onActionClick({ code, row }: OnActionClickParams<SystemSettingRecord>) {
  if (code === 'edit') {
    formDrawerApi.setData(row).open();
  }
}

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [...useGridFormSchema(), createdRangeField],
    submitOnChange: true,
  },
  gridOptions: {
    columns: useColumns(onActionClick),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await listSettingsApi({
            ...createdRangeQuery(formValues.created_range),
            group: formValues.group || undefined,
            keyword: buildKeyword(formValues.keyword) || undefined,
            page: page.currentPage,
            page_size: page.pageSize,
          });
        },
      },
    },
    rowConfig: {
      keyField: 'id',
    },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: true,
      zoom: true,
    },
  } as VxeTableGridOptions<SystemSettingRecord>,
}, 'platform');

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="参数列表">
      <template #toolbar-tools>
        <Button v-if="userStore.userInfo?.roles?.includes('super')" type="primary" @click="router.push('/basic-settings/homepage')">官网首页内容</Button>
      </template>
    </Grid>
  </Page>
</template>
