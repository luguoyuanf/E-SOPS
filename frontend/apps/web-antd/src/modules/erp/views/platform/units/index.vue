<script setup lang="ts">
import type { FormInstance } from 'ant-design-vue';
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { PlatformProductUnitRecord, ProductUnitPayload } from '#/modules/erp/api/erp';

import { computed, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';
import { Alert, Button, Drawer, Form, Input, Switch, Tag, message } from 'ant-design-vue';

import { useTenantVxeGrid as useVbenVxeGrid, VbenTableAction } from '#/adapter/vxe-table';
import { $t } from '#/locales';
import {
  createPlatformProductUnitApi,
  listPlatformProductUnitsApi,
  updatePlatformProductUnitApi,
} from '#/modules/erp/api/erp';
import { buildKeyword } from '#/views/system/shared/utils';
import { createdRangeField, createdRangeQuery } from '#/utils/created-range';

const userStore = useUserStore();
const isPlatformAdmin = computed(() => userStore.userInfo?.roles?.includes('super') ?? false);
const drawerOpen = ref(false);
const saving = ref(false);
const editingId = ref<string>();
const formRef = ref<FormInstance>();
let drawerTrigger: HTMLElement | undefined;
const form = reactive<Omit<ProductUnitPayload, 'code' | 'symbol'> & { code: string; symbol: string }>({ code: '', name: '', symbol: '', is_active: true });
const drawerTitle = computed(() => $t(editingId.value ? 'erp.units.edit' : 'erp.units.create'));

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [createdRangeField, {
      component: 'Input',
      componentProps: { placeholder: $t('erp.units.searchPlaceholder') },
      fieldName: 'keyword',
      label: $t('erp.units.search'),
    }],
    showCollapseButton: true,
  },
  gridOptions: {
    columns: [
      { field: 'code', minWidth: 150, title: $t('erp.units.code') },
      { field: 'name', minWidth: 180, title: $t('erp.units.name') },
      { field: 'symbol', minWidth: 120, title: $t('erp.units.symbol') },
      { field: 'is_active', slots: { default: 'status' }, title: $t('erp.units.status'), width: 100 },
      { field: 'updated_at', title: $t('erp.units.updatedAt'), width: 180 },
      { field: 'operation', fixed: 'right', slots: { default: 'operation' }, title: $t('erp.units.operation'), width: 130 },
    ],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, values) => {
          if (!isPlatformAdmin.value) return { items: [], total: 0 };
          return listPlatformProductUnitsApi({
            ...createdRangeQuery(values.created_range),
            keyword: buildKeyword(values.keyword) || undefined,
            page: page.currentPage,
            page_size: page.pageSize,
          });
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, refresh: true, search: true, zoom: true },
  } as VxeTableGridOptions<PlatformProductUnitRecord>,
}, 'platform');

function openCreate() {
  if (!isPlatformAdmin.value) return;
  drawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
  editingId.value = undefined;
  Object.assign(form, { code: '', name: '', symbol: '', is_active: true });
  formRef.value?.clearValidate();
  drawerOpen.value = true;
}

function openEdit(row: PlatformProductUnitRecord) {
  if (!isPlatformAdmin.value) return;
  drawerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
  editingId.value = row.id;
  Object.assign(form, { code: row.code, name: row.name, symbol: row.symbol || '', is_active: row.is_active });
  formRef.value?.clearValidate();
  drawerOpen.value = true;
}

function afterDrawerOpenChange(open: boolean) {
  if (!open) drawerTrigger?.focus();
}

async function submit() {
  if (!isPlatformAdmin.value || saving.value) return;
  await formRef.value?.validate();
  saving.value = true;
  try {
    const payload = { ...form, code: form.code.trim() || undefined, symbol: form.symbol || null };
    if (editingId.value) {
      await updatePlatformProductUnitApi(editingId.value, payload);
    } else {
      await createPlatformProductUnitApi(payload);
    }
    drawerOpen.value = false;
    message.success($t('erp.units.saved'));
    await gridApi.query();
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Page auto-content-height>
    <Alert v-if="!isPlatformAdmin" :message="$t('erp.units.forbidden')" show-icon type="error" />
    <template v-else>
      <Alert class="mb-4" :message="$t('erp.units.description')" show-icon type="info" />
      <Grid :table-title="$t('erp.units.list')">
        <template #toolbar-tools>
          <Button v-access:code="'platform:erp-unit:create'" class="gap-1" type="primary" @click="openCreate">
            <Plus class="size-5" />
            {{ $t('erp.units.create') }}
          </Button>
        </template>
        <template #status="{ row }">
          <Tag :color="row.is_active ? 'success' : 'default'">
            {{ $t(row.is_active ? 'erp.units.active' : 'erp.units.inactive') }}
          </Tag>
        </template>
        <template #operation="{ row }">
          <VbenTableAction :actions="[{
            auth: ['platform:erp-unit:update'],
            icon: 'lucide:square-pen',
            onClick: openEdit.bind(null, row),
            text: $t('erp.units.edit'),
            variant: 'link',
          }]" />
        </template>
      </Grid>
      <Drawer
        v-model:open="drawerOpen"
        :title="drawerTitle"
        :keyboard="true"
        class="w-[min(620px,calc(100vw-24px))]"
        placement="right"
        @after-open-change="afterDrawerOpenChange"
      >
        <Form ref="formRef" :model="form" layout="vertical">
          <Form.Item :label="$t('erp.units.code')" name="code">
            <Input v-model:value="form.code" placeholder="留空自动生成" :maxlength="50" />
          </Form.Item>
          <Form.Item :label="$t('erp.units.name')" name="name" :rules="[{ required: true, whitespace: true, message: $t('erp.units.nameRequired') }]">
            <Input v-model:value="form.name" :maxlength="100" />
          </Form.Item>
          <Form.Item :label="$t('erp.units.symbol')" name="symbol">
            <Input v-model:value="form.symbol" :maxlength="20" />
          </Form.Item>
          <Form.Item :label="$t('erp.units.status')" name="is_active">
            <Switch v-model:checked="form.is_active" :checked-children="$t('erp.units.active')" :un-checked-children="$t('erp.units.inactive')" />
          </Form.Item>
        </Form>
        <template #footer>
          <div class="flex justify-end gap-2">
            <Button @click="drawerOpen = false">{{ $t('erp.units.cancel') }}</Button>
            <Button :loading="saving" type="primary" @click="submit">{{ $t('erp.units.save') }}</Button>
          </div>
        </template>
      </Drawer>
    </template>
  </Page>
</template>
