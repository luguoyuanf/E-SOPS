<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type {
  DictionaryItemRecord,
  DictionaryTypeRecord,
} from '#/api';

import { computed, onMounted, ref, watch } from 'vue';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { IconifyIcon, Plus } from '@vben/icons';

import {
  Alert,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Empty,
  InputSearch,
  Menu,
  message,
  Spin,
  Select,
  Tag,
} from 'ant-design-vue';

import { useTenantVxeGrid as useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  deleteDictionaryItemApi,
  deleteDictionaryTypeApi,
  listDictionaryItemsApi,
  listDictionaryTypesApi,
  updateDictionaryItemApi,
} from '#/api';

import { buildKeyword, confirmAction } from '../shared/utils';
import { useTenantReadScope } from '../shared/tenant-scope';
import { $t } from '#/locales';
import { createdRangeQuery } from '#/utils/created-range';
import { useItemColumns, useItemGridFormSchema } from './data';
import ItemForm from './modules/item-form.vue';
import TypeForm from './modules/type-form.vue';

const tenantScope = useTenantReadScope();
const selectedTenantId = ref<string>();
const allTypes = ref<DictionaryTypeRecord[]>([]);
const typeSearchValue = ref('');
const typeCreatedRange = ref<[string, string]>();
const typeLoading = ref(false);
const selectedType = ref<DictionaryTypeRecord>();

const filteredTypes = computed(() => {
  const keyword = typeSearchValue.value.trim().toLowerCase();
  return allTypes.value.filter(
    (type) =>
      (!keyword || type.name.toLowerCase().includes(keyword) || type.code.toLowerCase().includes(keyword)) &&
      (!typeCreatedRange.value || (new Date(String(type.created_at ?? '')).getTime() >= new Date(typeCreatedRange.value[0]).getTime() && new Date(String(type.created_at ?? '')).getTime() <= new Date(typeCreatedRange.value[1]).getTime())),
  );
});

const itemTableTitle = computed(() => {
  if (!selectedType.value) {
    return '字典项';
  }
  return `字典项 · ${selectedType.value.name}`;
});

const [TypeFormDrawer, typeFormDrawerApi] = useVbenDrawer({
  connectedComponent: TypeForm,
  destroyOnClose: true,
});

const [ItemFormDrawer, itemFormDrawerApi] = useVbenDrawer({
  connectedComponent: ItemForm,
  destroyOnClose: true,
});

async function onItemStatusChange(
  newStatus: boolean,
  row: DictionaryItemRecord,
) {
  if (!tenantScope.canMutate(row)) { message.warning($t('system.tenantScope.switchFirst')); return false; }
  try {
    await confirmAction(
      `确认将字典项 ${row.label} 的状态切换为【${newStatus ? '启用' : '禁用'}】吗？`,
      '切换状态',
    );
    await updateDictionaryItemApi(row.id, { is_active: newStatus });
    return true;
  } catch {
    return false;
  }
}

function onItemActionClick({
  code,
  row,
}: OnActionClickParams<DictionaryItemRecord>) {
  if (!tenantScope.canMutate(row)) { message.warning($t('system.tenantScope.switchFirst')); return; }
  switch (code) {
    case 'delete': {
      void onDeleteItem(row);
      break;
    }
    case 'edit': {
      if (!selectedType.value) return;
      itemFormDrawerApi
        .setData({ record: row, typeId: selectedType.value.id })
        .open();
      break;
    }
  }
}

async function onDeleteType(row: DictionaryTypeRecord) {
  try {
    await confirmAction(`确认删除字典类型 ${row.name} 吗？`, '删除字典类型');
  } catch {
    return;
  }

  const hideLoading = message.loading({
    content: `正在删除 ${row.name}`,
    duration: 0,
    key: 'dict_type_delete',
  });
  try {
    await deleteDictionaryTypeApi(row.id);
    if (selectedType.value?.id === row.id) {
      selectedType.value = undefined;
    }
    message.success({
      content: `${row.name} 已删除`,
      key: 'dict_type_delete',
    });
    await loadTypes();
    itemGridApi.query();
  } catch {
    hideLoading();
  }
}

async function onDeleteItem(row: DictionaryItemRecord) {
  const hideLoading = message.loading({
    content: `正在删除 ${row.label}`,
    duration: 0,
    key: 'dict_item_delete',
  });
  try {
    await deleteDictionaryItemApi(row.id);
    message.success({
      content: `${row.label} 已删除`,
      key: 'dict_item_delete',
    });
    onRefreshItems();
  } catch {
    hideLoading();
  }
}

const [ItemGrid, itemGridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useItemGridFormSchema(),
    submitOnChange: true,
  },
  gridOptions: {
    columns: useItemColumns(onItemActionClick, onItemStatusChange, tenantScope.canMutate),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          if (!selectedType.value) {
            return { items: [], total: 0 };
          }
          await tenantScope.ready;
          return await listDictionaryItemsApi({
            tenant_id: tenantScope.isRoot.value ? selectedType.value.tenant_id : undefined,
            keyword: buildKeyword(formValues.keyword) || undefined,
            ...createdRangeQuery(formValues.created_range),
            page: page.currentPage,
            page_size: page.pageSize,
            type_id: selectedType.value.id,
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
  } as VxeTableGridOptions<DictionaryItemRecord>,
});

watch(selectedType, () => {
  itemGridApi.query();
});

async function loadTypes() {
  typeLoading.value = true;
  try {
    await tenantScope.ready;
    const items: DictionaryTypeRecord[] = []; let page = 1;
    while (true) {
      const result = await listDictionaryTypesApi({page,page_size:500,tenant_id:tenantScope.isRoot.value?selectedTenantId.value:undefined});
      items.push(...result.items);
      if (!result.items.length || items.length >= result.total) break;
      page++;
    }
    allTypes.value = items;

    if (selectedType.value) {
      selectedType.value = items.find(
        (type) => type.id === selectedType.value?.id,
      );
    }
    if (!selectedType.value && items.length > 0) {
      selectedType.value = items[0];
    }
  } finally {
    typeLoading.value = false;
  }
}

function selectType(type: DictionaryTypeRecord) {
  selectedType.value = type;
}

function onTypeMenuClick(
  type: DictionaryTypeRecord,
  info: { key: number | string | symbol },
) {
  if (!tenantScope.canMutate(type)) { message.warning($t('system.tenantScope.switchFirst')); return; }
  switch (info.key) {
    case 'delete': {
      void onDeleteType(type);
      break;
    }
    case 'edit': {
      typeFormDrawerApi.setData(type).open();
      break;
    }
  }
}

function onRefreshTypes() {
  void loadTypes();
}

function onRefreshItems() {
  itemGridApi.query();
}

function onCreateType() {
  typeFormDrawerApi.setData(undefined).open();
}

function onCreateItem() {
  if (!selectedType.value) {
    message.warning('请先选择字典类型');
    return;
  }
  if (!tenantScope.canMutate(selectedType.value)) { message.warning($t('system.tenantScope.switchFirst')); return; }
  itemFormDrawerApi.setData({ typeId: selectedType.value.id }).open();
}

watch(selectedTenantId, () => { selectedType.value=undefined; void loadTypes(); });
onMounted(loadTypes);
</script>

<template>
  <Page auto-content-height>
    <Alert v-if="tenantScope.isRoot.value" class="mb-3" type="info" show-icon :message="$t('system.tenantScope.readOnly')" />
    <Select v-if="tenantScope.isRoot.value" v-model:value="selectedTenantId" class="mb-3 w-64" allow-clear show-search option-filter-prop="label" :placeholder="$t('system.tenantScope.all')" :options="tenantScope.tenants.value.map(t=>({label:t.name,value:t.id}))" />
    <TypeFormDrawer @success="onRefreshTypes" />
    <ItemFormDrawer @success="onRefreshItems" />
    <div class="flex size-full">
      <Card class="flex w-1/6 min-w-[260px] flex-col">
        <div class="mb-3 flex items-center justify-between">
          <span class="font-medium">字典类型</span>
          <Button
            v-access:code="'system:dict:create'"
            size="small"
            type="primary"
            @click="onCreateType"
          >
            <Plus class="size-4" />
          </Button>
        </div>
        <InputSearch
          v-model:value="typeSearchValue"
          allow-clear
          class="mb-3"
          placeholder="搜索字典类型"
        />
        <div class="mb-3"><span class="text-sm">创建时间</span><DatePicker.RangePicker v-model:value="typeCreatedRange" class="w-full" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" /></div>
        <Spin :spinning="typeLoading">
          <div class="max-h-[calc(100vh-280px)] overflow-y-auto">
            <Empty
              v-if="!filteredTypes.length"
              :image="Empty.PRESENTED_IMAGE_SIMPLE"
              description="暂无字典类型"
            />
            <div
              v-for="type in filteredTypes"
              :key="type.id"
              class="group mb-1 flex items-center justify-between rounded-md px-2 py-2 text-sm transition-colors"
              :class="
                selectedType?.id === type.id
                  ? 'bg-accent'
                  : 'hover:bg-accent/50'
              "
            >
              <div
                class="min-w-0 flex-1 cursor-pointer"
                @click="selectType(type)"
              >
                <div class="flex items-center gap-2">
                  <span class="truncate font-medium">{{ type.name }}</span>
                  <Tag v-if="!type.is_active" color="default">禁用</Tag>
                </div>
                <div class="truncate text-xs text-muted-foreground">
                  {{ type.code }}<template v-if="tenantScope.isRoot.value"> · {{ tenantScope.tenantName(type) }}</template>
                </div>
              </div>
              <Dropdown placement="bottomRight" :trigger="['click']">
                <Button
                  v-access:code="['system:dict:update', 'system:dict:delete']"
                  :disabled="!tenantScope.canMutate(type)"
                  :title="!tenantScope.canMutate(type) ? $t('system.tenantScope.switchFirst') : undefined"
                  class="shrink-0"
                  :class="
                    selectedType?.id === type.id
                      ? 'opacity-100'
                      : 'opacity-0 group-hover:opacity-100'
                  "
                  size="small"
                  type="text"
                >
                  <IconifyIcon
                    class="size-4"
                    icon="lucide:ellipsis-vertical"
                  />
                </Button>
                <template #overlay>
                  <Menu @click="(info) => onTypeMenuClick(type, info)">
                    <Menu.Item v-access:code="'system:dict:update'" key="edit">
                      编辑
                    </Menu.Item>
                    <Menu.Item
                      v-access:code="'system:dict:delete'"
                      key="delete"
                      danger
                    >
                      删除
                    </Menu.Item>
                  </Menu>
                </template>
              </Dropdown>
            </div>
          </div>
        </Spin>
      </Card>

      <div class="ml-4 w-5/6 min-w-0">
        <ItemGrid :table-title="itemTableTitle">
          <template #toolbar-tools>
            <Button
              v-access:code="'system:dict:create'"
              :disabled="!selectedType || !tenantScope.canMutate(selectedType)"
              type="primary"
              @click="onCreateItem"
            >
              <Plus class="size-5" />
              新增字典项
            </Button>
          </template>
          <template #color="{ row }">
            <div v-if="row.color" class="flex items-center justify-center gap-2">
              <span
                class="inline-block size-4 shrink-0 rounded-full border"
                :style="{ backgroundColor: row.color }"
              />
              <span class="truncate">{{ row.color }}</span>
            </div>
            <span v-else class="text-muted-foreground">-</span>
          </template>
        </ItemGrid>
      </div>
    </div>
  </Page>
</template>
