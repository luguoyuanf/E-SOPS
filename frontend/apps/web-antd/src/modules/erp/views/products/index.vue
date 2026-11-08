<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FormInstance } from 'ant-design-vue';
import type {
  ProductCategoryRecord,
  ProductRecord,
  ProductUnitRecord,
} from '#/modules/erp/api/erp';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { IconifyIcon, Plus } from '@vben/icons';
import { useAccess } from '@vben/access';
import { useMediaQuery } from '@vueuse/core';

import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Switch,
  Tag,
  Tree,
  TreeSelect,
} from 'ant-design-vue';

import { useTenantVxeGrid as useVbenVxeGrid, VbenTableAction } from '#/adapter/vxe-table';
import ExportCsvButton from '#/modules/erp/components/export-csv-button.vue';
import ErpRemoteSelect from '#/modules/erp/components/erp-remote-select.vue';
import { preloadErpSelectOptions } from '#/modules/erp/components/erp-select-options';
import { createdRangeField, createdRangeQuery } from '#/utils/created-range';
import {
  createMasterDataApi,
  createProductApi,
  deleteProductApi,
  listProductCategoriesApi,
  listProductsApi,
  listProductUnitsApi,
  updateProductApi,
} from '#/modules/erp/api/erp';
import { buildDepartmentTree, buildKeyword } from '#/views/system/shared/utils';

interface ProductFormValues {
  barcode?: string;
  category_id?: string;
  code: string;
  expiry_days: number;
  is_active: boolean;
  min_sale_price: number;
  model?: string;
  name: string;
  purchase_reference_price: number;
  remark?: string;
  sale_reference_price: number;
  specification?: string;
  unit_id?: string;
  weight: number;
}

const formRef = ref<FormInstance>();
const categoryFormRef = ref<FormInstance>();
const drawerOpen = ref(false);
const categoryModalOpen = ref(false);
const saving = ref(false);
const categorySaving = ref(false);
const editingId = ref<string>();
const exportQuery = ref<Record<string, string | undefined>>({});
const units = ref<ProductUnitRecord[]>([]);
const allCategories = ref<ProductCategoryRecord[]>([]);
const selectedCategoryId = ref('');
const categoryTreeLoading = ref(false);
const categoryTree = computed(() => buildDepartmentTree(allCategories.value));
const categoryTreeData = computed(() => {
  const convert = (nodes: typeof categoryTree.value): CategoryTreeNode[] =>
    nodes.map((category) => ({
      children: convert(category.children),
      key: category.id,
      title: category.name,
    }));
  return convert(categoryTree.value);
});
const categoryNames = computed(() => Object.fromEntries(allCategories.value.map((category) => [category.id, category.name])));
const isNarrowScreen = useMediaQuery('(max-width: 767px)');
const { hasAccessByCodes } = useAccess();
interface CategoryTreeNode {
  children: CategoryTreeNode[];
  key: string;
  title: string;
}
interface CategorySelectNode {
  children: CategorySelectNode[];
  disabled: boolean;
  key: string;
  selectable: boolean;
  title: string;
  value: string;
}
function toCategorySelectNodes(
  nodes: typeof categoryTree.value,
  leafOnly: boolean,
  ancestorActive = true,
): CategorySelectNode[] {
  return nodes.map((category) => {
    const active = ancestorActive && category.is_active;
    return {
      children: toCategorySelectNodes(category.children, leafOnly, active),
      disabled: !active,
      key: category.id,
      selectable: active && (!leafOnly || category.children.length === 0),
      title: category.is_active ? category.name : `${category.name}（已停用）`,
      value: category.id,
    };
  });
}
const categorySelectTree = computed(() => toCategorySelectNodes(categoryTree.value, true));
const categoryParentTree = computed(() => toCategorySelectNodes(categoryTree.value, false));
const categoryForm = reactive({ code: '', name: '', parent_id: undefined as string | undefined, sort: 0 });
const productForm = reactive<ProductFormValues>({
  barcode: undefined,
  category_id: undefined,
  code: '',
  expiry_days: 0,
  is_active: true,
  min_sale_price: 0,
  model: undefined,
  name: '',
  purchase_reference_price: 0,
  remark: undefined,
  sale_reference_price: 0,
  specification: undefined,
  unit_id: undefined,
  weight: 0,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [
      createdRangeField,
      {
        component: 'Input',
        componentProps: { placeholder: '请输入产品名称/编码/条码' },
        fieldName: 'keyword',
        label: '产品检索',
      },
    ],
    showCollapseButton: true,
  },
  gridOptions: {
    columns: [
      { field: 'code', minWidth: 150, title: '产品编码' },
      { field: 'name', minWidth: 220, showOverflow: true, title: '产品名称' },
      { field: 'model', minWidth: 160, showOverflow: true, title: '型号' },
      { field: 'barcode', minWidth: 160, title: '条码' },
      { field: 'specification', minWidth: 180, title: '规格' },
      { field: 'purchase_reference_price', title: '采购参考价', width: 120 },
      { field: 'sale_reference_price', title: '销售参考价', width: 120 },
      { field: 'category_id', minWidth: 180, slots: { default: 'category' }, title: '所属分类' },
      {
        field: 'is_active',
        slots: { default: 'status' },
        title: '状态',
        width: 96,
      },
      { field: 'updated_at', title: '最近更新', width: 180 },
      {
        align: 'center',
        field: 'operation',
        fixed: 'right',
        slots: { default: 'operation' },
        title: '操作',
        width: 180,
      },
    ],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, values) => {
          const keyword = buildKeyword(values.keyword);
          const createdRange = createdRangeQuery(values.created_range);
          exportQuery.value = {
            ...(keyword ? { keyword } : {}),
            ...(selectedCategoryId.value ? { category_id: selectedCategoryId.value } : {}),
            ...createdRange,
          };
          return await listProductsApi({
            ...createdRange,
            category_id: selectedCategoryId.value || undefined,
            keyword: keyword || undefined,
            page: page.currentPage,
            page_size: page.pageSize,
          });
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, refresh: true, search: true, zoom: true },
  } as VxeTableGridOptions<ProductRecord>,
}, 'current');

function formatUnit(unit: ProductUnitRecord) { return { disabled: !unit.is_active, label: `${unit.name} (${unit.code})`, value: unit.id }; }
async function loadUnits(keyword: string) {
  const items: ProductUnitRecord[] = [];
  let page = 1;
  while (true) {
    const result = await listProductUnitsApi({ keyword, page, page_size: 100 });
    items.push(...result.items);
    if (keyword || items.length >= result.total || result.items.length === 0) break;
    page += 1;
  }
  units.value = items;
  return units.value;
}
async function loadCategoryTree() {
  categoryTreeLoading.value = true;
  try {
    const items: ProductCategoryRecord[] = [];
    let page = 1;
    while (true) {
      const result = await listProductCategoriesApi({ page, page_size: 100 });
      items.push(...result.items);
      if (items.length >= result.total || result.items.length === 0) break;
      page += 1;
    }
    allCategories.value = items;
  } finally {
    categoryTreeLoading.value = false;
  }
}

function selectCategory(keys: (number | string)[] = []) {
  selectedCategoryId.value = String(keys[0] ?? '');
  gridApi.query();
}

function onCategoryRightClick(info: { event: MouseEvent; node: { key: number | string } }) {
  const category = allCategories.value.find((item) => item.id === String(info.node.key));
  if (category) onCategoryContextMenu(info.event, category);
}

function openCategoryCreate(parentId?: string) {
  if (!hasAccessByCodes(['erp:product-category:create'])) return;
  Object.assign(categoryForm, { code: '', name: '', parent_id: parentId, sort: 0 });
  categoryFormRef.value?.clearValidate();
  categoryModalOpen.value = true;
}

function onCategoryContextMenu(event: MouseEvent, category: ProductCategoryRecord) {
  if (!hasAccessByCodes(['erp:product-category:create'])) return;
  event.preventDefault();
  event.stopPropagation();
  if (!category.is_active) {
    message.warning('已停用分类不能作为上级分类');
    return;
  }
  openCategoryCreate(category.id);
}

async function submitCategory() {
  await categoryFormRef.value?.validate();
  categorySaving.value = true;
  try {
    await createMasterDataApi('category', {
      code: categoryForm.code.trim() || undefined,
      is_active: true,
      name: categoryForm.name.trim(),
      parent_id: categoryForm.parent_id || null,
      sort: categoryForm.sort,
    });
    categoryModalOpen.value = false;
    await loadCategoryTree();
    message.success('产品分类已添加');
  } finally {
    categorySaving.value = false;
  }
}

onMounted(() => { void Promise.all([loadCategoryTree(), preloadErpSelectOptions(loadUnits)]); });

function resetForm() {
  Object.assign(productForm, {
    barcode: undefined,
    category_id: undefined,
    code: '',
    expiry_days: 0,
    is_active: true,
    min_sale_price: 0,
    model: undefined,
    name: '',
    purchase_reference_price: 0,
    remark: undefined,
    sale_reference_price: 0,
    specification: undefined,
    unit_id: undefined,
    weight: 0,
  });
  formRef.value?.clearValidate();
}

async function openCreate() {
  editingId.value = undefined;
  resetForm();
  const selected = allCategories.value.find((category) => category.id === selectedCategoryId.value);
  if (selected?.is_active && !allCategories.value.some((category) => category.parent_id === selected.id)) {
    productForm.category_id = selected.id;
  }
  drawerOpen.value = true;
}

async function openEdit(row: ProductRecord) {
  await preloadErpSelectOptions(loadUnits);
  editingId.value = row.id;
  Object.assign(productForm, {
    barcode: row.barcode || undefined,
    category_id: row.category_id || undefined,
    code: row.code,
    expiry_days: row.expiry_days,
    is_active: row.is_active,
    min_sale_price: Number(row.min_sale_price),
    model: row.model || undefined,
    name: row.name,
    purchase_reference_price: Number(row.purchase_reference_price),
    remark: row.remark || undefined,
    sale_reference_price: Number(row.sale_reference_price),
    specification: row.specification || undefined,
    unit_id: row.unit_id,
    weight: Number(row.weight),
  });
  drawerOpen.value = true;
}

async function submit() {
  await formRef.value?.validate();
  if (!productForm.category_id || !productForm.unit_id) return;

  saving.value = true;
  try {
    const payload = {
      ...productForm,
      code: productForm.code.trim() || undefined,
      barcode: productForm.barcode || null,
      category_id: productForm.category_id,
      min_sale_price: String(productForm.min_sale_price),
      model: productForm.model?.trim() || null,
      purchase_reference_price: String(productForm.purchase_reference_price),
      remark: productForm.remark || null,
      sale_reference_price: String(productForm.sale_reference_price),
      specification: productForm.specification || null,
      unit_id: productForm.unit_id,
      weight: String(productForm.weight),
    };
    if (editingId.value) {
      await updateProductApi(editingId.value, payload);
    } else {
      await createProductApi(payload);
    }
    drawerOpen.value = false;
    gridApi.query();
  } finally {
    saving.value = false;
  }
}

async function removeProduct(row: ProductRecord) {
  await deleteProductApi(row.id);
  gridApi.query();
}

</script>

<template>
  <Page auto-content-height>
    <Modal
      v-model:open="categoryModalOpen"
      :confirm-loading="categorySaving"
      cancel-text="取消"
      destroy-on-close
      ok-text="保存分类"
      title="新增产品分类"
      width="min(520px, calc(100vw - 32px))"
      @ok="submitCategory"
    >
      <Form ref="categoryFormRef" :model="categoryForm" layout="vertical">
        <Form.Item label="分类名称" name="name" :rules="[{ required: true, whitespace: true, message: '请输入分类名称' }]">
          <Input v-model:value="categoryForm.name" :maxlength="100" placeholder="请输入分类名称" />
        </Form.Item>
        <Form.Item label="分类编码" name="code">
          <Input v-model:value="categoryForm.code" :maxlength="50" placeholder="留空自动生成" />
        </Form.Item>
        <Form.Item label="上级分类" name="parent_id">
          <TreeSelect
            v-model:value="categoryForm.parent_id"
            allow-clear
            class="w-full"
            :tree-data="categoryParentTree"
            show-search
            tree-default-expand-all
            tree-node-filter-prop="title"
            placeholder="不选则为一级分类"
          />
        </Form.Item>
        <Form.Item label="排序" name="sort">
          <InputNumber v-model:value="categoryForm.sort" :min="0" :precision="0" class="w-full" />
        </Form.Item>
      </Form>
    </Modal>
    <Drawer
      v-model:open="drawerOpen"
      :confirm-loading="saving"
      :title="editingId ? '编辑产品' : '新增产品'"
      :width="isNarrowScreen ? '100vw' : '50vw'"
      placement="right"
      @close="resetForm"
    >
      <Form ref="formRef" class="mx-3" :model="productForm" layout="vertical">
        <div class="grid grid-cols-1 gap-x-4 md:grid-cols-2">
          <Form.Item
            label="产品编码"
            name="code"
          >
            <Input v-model:value="productForm.code" placeholder="留空自动生成" :maxlength="100" />
          </Form.Item>
          <Form.Item
            label="产品名称"
            name="name"
            :rules="[{ required: true, message: '请输入产品名称' }]"
          >
            <Input v-model:value="productForm.name" :maxlength="200" />
          </Form.Item>
          <Form.Item label="型号" name="model">
            <Input v-model:value="productForm.model" :maxlength="100" />
          </Form.Item>
          <Form.Item
            label="产品单位"
            name="unit_id"
            :rules="[{ required: true, message: '请选择产品单位' }]"
          >
            <ErpRemoteSelect
              v-model:value="productForm.unit_id"
              :format-option="formatUnit"
              :load="loadUnits"
              placeholder="选择已启用单位"
            />
          </Form.Item>
          <Form.Item
            label="产品分类"
            name="category_id"
            :rules="[{ required: true, message: '请选择产品分类' }]"
          >
            <TreeSelect
              v-model:value="productForm.category_id"
              class="w-full"
              :loading="categoryTreeLoading"
              :tree-data="categorySelectTree"
              show-search
              tree-default-expand-all
              tree-node-filter-prop="title"
              placeholder="选择启用的末级产品分类"
            />
          </Form.Item>
          <Form.Item label="条码" name="barcode">
            <Input v-model:value="productForm.barcode" :maxlength="100" />
          </Form.Item>
          <Form.Item label="重量" name="weight">
            <InputNumber v-model:value="productForm.weight" :min="0" :precision="6" class="w-full" />
          </Form.Item>
          <Form.Item label="保质天数" name="expiry_days">
            <InputNumber v-model:value="productForm.expiry_days" :min="0" :precision="0" class="w-full" />
          </Form.Item>
          <Form.Item label="采购参考价" name="purchase_reference_price">
            <InputNumber
              v-model:value="productForm.purchase_reference_price"
              :min="0"
              :precision="4"
              class="w-full"
            />
          </Form.Item>
          <Form.Item label="销售参考价" name="sale_reference_price">
            <InputNumber
              v-model:value="productForm.sale_reference_price"
              :min="0"
              :precision="4"
              class="w-full"
            />
          </Form.Item>
          <Form.Item label="最低销售价" name="min_sale_price">
            <InputNumber
              v-model:value="productForm.min_sale_price"
              :min="0"
              :precision="4"
              class="w-full"
            />
          </Form.Item>
          <Form.Item label="状态" name="is_active">
            <Switch
              v-model:checked="productForm.is_active"
              checked-children="启用"
              un-checked-children="停用"
            />
          </Form.Item>
        </div>
        <Form.Item label="规格" name="specification">
          <Input v-model:value="productForm.specification" :maxlength="500" />
        </Form.Item>
        <Form.Item label="备注" name="remark">
          <Input.TextArea v-model:value="productForm.remark" :maxlength="500" :rows="3" show-count />
        </Form.Item>
      </Form>
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button @click="drawerOpen = false">取消</Button>
          <Button :loading="saving" type="primary" @click="submit">保存产品</Button>
        </div>
      </template>
    </Drawer>

    <div class="flex size-full min-h-0 flex-col gap-4 lg:flex-row">
      <aside class="flex min-h-0 w-full shrink-0 flex-col rounded-lg bg-background p-4 lg:h-full lg:w-[280px]" aria-label="产品分类">
        <div class="mb-3 flex items-center justify-between gap-2">
          <h2 class="text-base font-medium">产品分类</h2>
          <Button v-access:code="'erp:product-category:create'" size="small" type="link" @click="openCategoryCreate()">
            <Plus class="size-4" />新增分类
          </Button>
        </div>
        <div class="category-tree-scroll min-h-0 flex-1 overflow-y-auto">
          <button
            class="category-tree-all mb-1 inline-flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm"
            :class="{ 'category-tree-all--active': !selectedCategoryId }"
            type="button"
            @click="selectCategory([])"
          >
            <IconifyIcon icon="lucide:folder" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            全部产品
          </button>
          <div v-if="categoryTreeLoading" class="px-2 py-2 text-sm text-muted-foreground">分类加载中…</div>
          <Tree
            v-if="categoryTreeData.length"
            :key="allCategories.length"
            :tree-data="categoryTreeData"
            :selected-keys="selectedCategoryId ? [selectedCategoryId] : []"
            block-node
            default-expand-all
            @select="selectCategory"
            @right-click="onCategoryRightClick"
          >
            <template #title="node">
              <span class="inline-flex items-center gap-2">
                <IconifyIcon icon="lucide:folder" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span>{{ node.title }}</span>
              </span>
            </template>
          </Tree>
          <Empty v-else-if="!categoryTreeLoading" description="暂无产品分类" />
        </div>
        <div class="mt-2 text-xs text-muted-foreground">右键分类可新增子分类</div>
      </aside>
      <div class="min-h-0 min-w-0 flex-1">
    <Grid table-title="产品列表">
      <template #toolbar-tools>
        <div class="flex items-center gap-1">
          <Button
            v-access:code="'erp:product:create'"
            class="gap-1"
            type="primary"
            @click="openCreate"
          >
            <Plus class="size-5" />
            <span>新增产品</span>
          </Button>
          <ExportCsvButton
            file-name="产品列表.csv"
            permission="erp:product:export"
            :query="exportQuery"
            resource="product"
          />
        </div>
      </template>
      <template #status="{ row }">
        <Tag :color="row.is_active ? 'success' : 'default'">
          {{ row.is_active ? '启用' : '停用' }}
        </Tag>
      </template>
      <template #category="{ row }">
        {{ row.category_id ? categoryNames[row.category_id] || '' : '' }}
      </template>
      <template #operation="{ row }">
        <VbenTableAction
          :actions="[
            {
              auth: ['erp:product:update'],
              icon: 'lucide:square-pen',
              onClick: openEdit.bind(null, row),
              text: '编辑',
              variant: 'link',
            },
            {
              auth: ['erp:product:delete'],
              danger: true,
              icon: 'lucide:trash-2',
              popConfirm: {
                cancelText: '取消',
                confirm: removeProduct.bind(null, row),
                okText: '确认',
                title: `确认删除产品 ${row.name} 吗？`,
              },
              text: '删除',
              variant: 'link',
            },
          ]"
        />
      </template>
    </Grid>
      </div>
    </div>
  </Page>
</template>

<style scoped>
.category-tree-scroll {
  max-height: 240px;
}

@media (min-width: 1024px) {
  .category-tree-scroll {
    max-height: none;
  }
}

:deep(.ant-tree-node-content-wrapper) { min-width: 0; }
:deep(.ant-tree-title) { overflow-wrap: anywhere; }

.category-tree-all--active {
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
  font-weight: 600;
}
</style>
