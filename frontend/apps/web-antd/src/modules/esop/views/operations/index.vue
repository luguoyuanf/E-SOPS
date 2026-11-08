<script lang="ts" setup>
import { SelectableTable as Table } from '#/components/selectable-table';
import type { Operation, OperationAttachment, OperationMediaStatus, OperationProductTree } from '../../api/esop';
import type { ProductSopSummary, ProductSopWorkspace } from '../../api/product-sops';

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { IconifyIcon } from '@vben/icons';
import { Button, Checkbox, DatePicker, Drawer, Dropdown, Empty, Form, Input, Menu, message, Modal, Progress, Select, Spin, Tabs, Tag, Tree, TreeSelect } from 'ant-design-vue';

import { updateProductCategoryApi } from '#/modules/erp/api/erp';
import { createdRangeQuery } from '#/utils/created-range';

import { analyzeSopImport, deleteOperation, getEditorFileAccess, getOperationMediaStatus, getOperationProductTree, importProductSop, listOperations, moveOperation, retryOperationMedia, saveOperation, uploadOperationFile } from '../../api/esop';
import type { SopImportSheet } from '../../api/esop';
import { discardProductSopDraft, getProductSopStatuses, getProductSopWorkspace, operationStateText, prepareProductSopMedia, productSopStatusText, submitProductSop } from '../../api/product-sops';
import ProductSopHistory from '../../components/product-sop-history.vue';
import OperationAttachmentsPreview from '../../components/operation-attachments-preview.vue';
import ProductSopPreview from '../../components/product-sop-preview.vue';

const { hasAccessByCodes } = useAccess();
const operationActionCount = Number(hasAccessByCodes(['esop:operation:update']))
  + Number(hasAccessByCodes(['esop:operation:create']))
  + Number(hasAccessByCodes(['esop:operation:delete']));
const reordering = ref(false);
const deletingId = ref<string>();
const draggingId = ref('');
const dropId = ref('');
const dropAfter = ref(false);
const canReorder = computed(() => hasAccessByCodes(['esop:operation:update']) && !editingLocked.value && !loading.value && !reordering.value && !deletingId.value);

const workspace = ref<ProductSopWorkspace>();
const productStatuses = ref<Record<string, ProductSopSummary>>({});
const operationStates = computed(() => new Map(workspace.value?.operation_states.map((item) => [item.operation.id, item]) ?? []));
const deletedOperation = (row: Operation) => operationStates.value.get(row.id)?.is_deleted ?? false;
const workspaceLoading = ref(false);
const workspaceError = ref(false);
const submitting = ref(false);
const discarding = ref(false);
const preparingMedia = ref(false);
const historyOpen = ref(false);
const previewOpen = ref(false);
const attachmentsOpen = ref(false);
const editorPreviewOpen = ref(false);
const editorPreviewFile = ref('');
const editorPreviewTrigger = ref<HTMLElement>();
const editorPreviewOperation = ref<Operation>();
const editorPreviewId = ref<string>();
const conversionStates = ref<Record<string, OperationMediaStatus>>({});
const retryingFile = ref('');
let conversionTimer: ReturnType<typeof setInterval> | undefined;
let productMediaChecking = false;
const failedProductMedia = new Set<string>();
const needsConversion = (file: OperationAttachment) => ['word', 'excel', 'ppt', 'pdf', 'video'].includes(file.kind)
  && !file.display_pages?.length && !file.display_file_id;
async function refreshConversions() {
  if (!open.value) return;
  const session = editorSession;
  const candidates = form.attachments.filter((file) => needsConversion(file) && conversionStates.value[file.file_id]?.status !== 'failed');
  await Promise.all(candidates.map(async (file) => {
    try {
      const state = await getOperationMediaStatus(file.file_id, editingId.value);
      if (session !== editorSession || !open.value) return;
      conversionStates.value[file.file_id] = state;
      const current = form.attachments.find((item) => item.file_id === file.file_id);
      if (current && state.status === 'ready') {
        current.display_file_id = state.attachment.display_file_id;
        current.display_content_type = state.attachment.display_content_type;
        current.display_pages = state.attachment.display_pages;
      }
    } catch { /* Leave the pending state visible; the next poll can recover. */ }
  }));
}
async function refreshProductPreviews() {
  if (productMediaChecking || open.value || importOpen.value || workspaceLoading.value || !needsMedia.value) return;
  const productId = selectedProduct.value?.id;
  if (!productId || !workspace.value) return;
  const files = new Map<string, string>();
  for (const operation of workspace.value.current_operations) {
    for (const attachment of operation.attachments) {
      if (['word', 'excel', 'ppt', 'pdf'].includes(attachment.kind) && !attachment.display_pages?.length) {
        files.set(attachment.file_id, operation.id);
      }
    }
  }
  productMediaChecking = true;
  try {
    const states = await Promise.all([...files].map(async ([fileId, operationId]) => {
      try { return [fileId, await getOperationMediaStatus(fileId, operationId)] as const; }
      catch { return undefined; }
    }));
    if (selectedProduct.value?.id !== productId) return;
    if (states.some((item) => item?.[1].status === 'ready')) await refresh();
    for (const item of states) {
      if (item?.[1].status === 'failed' && !failedProductMedia.has(item[0])) {
        failedProductMedia.add(item[0]);
        message.error(item[1].error_message || '附件预览转换失败，请点击“生成预览”重试');
      }
    }
  } finally { productMediaChecking = false; }
}
async function retryConversion(fileId: string) {
  retryingFile.value = fileId;
  try {
    conversionStates.value[fileId] = await retryOperationMedia(fileId, editingId.value);
    message.success('已重新加入转换队列');
  } finally { retryingFile.value = ''; }
}
const renameOpen = ref(false);
const renameFileId = ref('');
const renameName = ref('');
let renameTrigger: HTMLElement | undefined;
const resolveEditorFile = (fileId: string) => getEditorFileAccess(fileId, editorPreviewId.value);
const attachmentsOperation = ref<Operation>();
const attachmentsVersionId = ref<string>();
const attachmentsProductId = ref('');
const attachmentsTrigger = ref<HTMLElement>();
const editingLocked = computed(() => workspaceLoading.value || workspaceError.value || workspace.value?.status === 'pending' || submitting.value || discarding.value || preparingMedia.value);
const canDiscardDraft = computed(() => workspace.value?.dirty && (workspace.value.approved_version || workspace.value.current_operations.length > 0));
const needsMedia = computed(() => workspace.value?.current_operations.some((operation) => operation.attachments.some((file) => ['word', 'excel', 'ppt', 'pdf'].includes(file.kind) && !file.display_pages?.length)) ?? false);
const previewOperations = computed(() => workspace.value?.pending_version?.operations ?? (workspace.value?.dirty ? workspace.value.current_operations : workspace.value?.approved_version?.operations) ?? workspace.value?.current_operations ?? []);
const previewVersionId = computed(() => workspace.value?.pending_version?.id ?? (workspace.value?.dirty ? undefined : workspace.value?.approved_version?.id));
const previewLabel = computed(() => workspace.value?.pending_version ? `待审核 V${workspace.value.pending_version.version}` : workspace.value?.dirty ? '草稿' : workspace.value?.approved_version ? `生效 V${workspace.value.approved_version.version}` : '未编制');

const catalog = ref<OperationProductTree>({ categories: [], products: [] });
const catalogLoading = ref(false);
const catalogError = ref(false);
const search = ref('');
const createdRange = ref<[string, string]>();
const selected = ref('');
const rows = ref<Operation[]>([]);
const loading = ref(false);
const saving = ref(false);
const activeUploads = ref(0);
const uploadStatus = ref('');
const uploadPercent = ref(0);
const open = ref(false);
const importOpen = ref(false);
const importing = ref(false);
const importUploading = ref(false);
const importProgress = ref(0);
const importFileId = ref('');
const importFileName = ref('');
const importSheets = ref<SopImportSheet[]>([]);
const importSelected = ref<number[]>([]);
const importMode = ref<'append' | 'replace'>('append');
const importProductId = ref('');
const importInput = ref<HTMLInputElement>();
let importAbort = new AbortController();
let importSession = 0;
function startSopImport(event: MouseEvent) {
  importSession++;
  returnFocus = event.currentTarget as HTMLElement;
  importAbort = new AbortController();
  importFileId.value = '';
  importFileName.value = '';
  importSheets.value = [];
  importSelected.value = [];
  importMode.value = 'append';
  importProgress.value = 0;
  importUploading.value = false;
  importProductId.value = selectedProduct.value?.id ?? '';
  importOpen.value = true;
}
function closeSopImport() {
  importSession++;
  importAbort.abort();
  importUploading.value = false;
  importOpen.value = false;
}
async function chooseSopWorkbook(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (file) await uploadSopWorkbook(file);
}
function chooseSopWorkbookFromDrop(event: DragEvent) {
  const file = event.dataTransfer?.files[0];
  if (file) void uploadSopWorkbook(file);
}
function toggleImportSheet(index: number) {
  importSelected.value = importSelected.value.includes(index)
    ? importSelected.value.filter((item) => item !== index)
    : [...importSelected.value, index];
}
async function uploadSopWorkbook(file: File) {
  if (importUploading.value) return;
  const session = ++importSession;
  if (!/\.(xls|xlsx)$/i.test(file.name)) { message.warning('请选择 Excel 文件'); return; }
  importFileId.value = '';
  importSheets.value = [];
  importSelected.value = [];
  importFileName.value = file.name;
  importProgress.value = 0;
  importUploading.value = true;
  importAbort = new AbortController();
  try {
    const stored = await uploadOperationFile(file, undefined, (percent) => { importProgress.value = percent; }, importAbort.signal);
    if (!importOpen.value || session !== importSession) return;
    const analysis = await analyzeSopImport(stored.file_id);
    if (!importOpen.value || session !== importSession) return;
    importFileId.value = stored.file_id;
    importSheets.value = analysis.sheets;
    importSelected.value = analysis.sheets.filter((sheet) => sheet.selected).map((sheet) => sheet.index);
  } catch { if (importOpen.value && session === importSession) message.error('上传或解析失败，请检查文件后重试'); }
  finally { if (session === importSession) importUploading.value = false; }
}
async function confirmSopImport() {
  if (!importProductId.value || !importFileId.value || !importSelected.value.length) return;
  importing.value = true;
  try {
    const created = await importProductSop(importProductId.value, {
      file_id: importFileId.value, sheet_indexes: importSelected.value, mode: importMode.value,
    });
    importOpen.value = false;
    page.value = 1;
    await refresh();
    void refreshProductPreviews();
    message.success(`已导入 ${created.length} 道工序为草稿，${needsMedia.value ? '预览正在后台生成' : '预览已生成'}`);
  } finally { importing.value = false; }
}
const categoryOpen = ref(false);
const categorySaving = ref(false);
const categoryDraftId = ref('');
const copyOpen = ref(false);
const copySaving = ref(false);
const copySource = ref<Operation>();
const copyCategoryId = ref('');
const copyProductId = ref('');
const formCategoryId = ref('');
const editingId = ref<string>();
const editingProductId = ref('');
const form = reactive({ code: '', name: '', description: '', product_id: '', attachments: [] as OperationAttachment[] });
const page = ref(1);
const total = ref(0);
const pageSize = 20;
const fileInput = ref<HTMLInputElement>();
const fileKind = ref('image');
let returnFocus: HTMLElement | undefined;
let editorSession = 0;
let uploadAbort = new AbortController();
let listRequest = 0;
const fileKinds = [
  { key: 'image', label: '图片', accept: '.png,.jpg,.jpeg,.webp,.gif' },
  { key: 'pdf', label: 'PDF', accept: '.pdf' },
  { key: 'word', label: 'Word', accept: '.doc,.docx' },
  { key: 'excel', label: 'Excel', accept: '.xls,.xlsx' },
  { key: 'ppt', label: 'PPT', accept: '.ppt,.pptx' },
  { key: 'video', label: '视频', accept: '.mp4,.webm,.mov' },
  { key: 'cad', label: 'CAD', accept: '.dxf' },
  { key: 'model3d', label: '3D 模型', accept: '.step,.stp,.stl,.obj,.glb,.gltf' },
  { key: 'model_resource', label: '模型资源', accept: '.bin,.mtl' },
];
const currentKind = computed(() => fileKinds.find((kind) => kind.key === fileKind.value)!);
const selectedProduct = computed(() => catalog.value.products.find((p) => `product:${p.id}` === selected.value));
const formProduct = computed(() => catalog.value.products.find((p) => p.id === form.product_id));
interface CategorySelectNode { key: string; value: string; title: string; selectable: boolean; children: CategorySelectNode[]; }
const categorySelectTree = computed(() => {
  const nodes = new Map(catalog.value.categories.map((c) => [c.id, {
    key: c.id, value: c.id, title: c.name, selectable: true, children: [] as CategorySelectNode[],
  }]));
  const roots: CategorySelectNode[] = [];
  for (const category of catalog.value.categories) {
    const node = nodes.get(category.id)!;
    const parent = category.parent_id ? nodes.get(category.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  for (const node of nodes.values()) node.selectable = node.children.length === 0;
  return roots;
});
const productOptions = computed(() => catalog.value.products.filter((p) => p.category_id === formCategoryId.value).map((p) => ({ label: `${p.name}（${p.code}）`, value: p.id })));
const copyProductOptions = computed(() => catalog.value.products.filter((p) => p.category_id === copyCategoryId.value && p.id !== copySource.value?.product_id).map((p) => ({ label: `${p.name}（${p.code}）`, value: p.id })));
const columns = [
  { title: '排序', key: 'sort', width: 70 },
  { title: '工序编码', dataIndex: 'code', key: 'code' },
  { title: '工序名称', dataIndex: 'name', key: 'name' },
  { title: '状态', key: 'state', width: 150 },
  { title: '附件', key: 'attachments' },
  { title: '操作', key: 'action', width: 120 },
];
interface TreeNode { key: string; title: string; status?: ProductSopSummary['status']; searchText?: string; children?: TreeNode[]; }
const treeData = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  const categories = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];
  for (const c of catalog.value.categories) categories.set(c.id, { key: `category:${c.id}`, title: c.name, children: [] });
  for (const c of catalog.value.categories) {
    const node = categories.get(c.id)!;
    const parent = c.parent_id ? categories.get(c.parent_id) : undefined;
    if (parent && parent !== node) parent.children!.push(node);
    else roots.push(node);
  }
  const uncategorized: TreeNode = { key: 'uncategorized', title: '未分类', children: [] };
  for (const p of catalog.value.products) {
    const node = { key: `product:${p.id}`, title: p.name, status: productStatuses.value[p.id]?.status, searchText: `${p.name} ${p.code}` };
    (categories.get(p.category_id ?? '') ?? uncategorized).children!.push(node);
  }
  if (uncategorized.children!.length) roots.push(uncategorized);
  function filter(nodes: TreeNode[], parentMatches = false): TreeNode[] {
    return nodes.flatMap((node) => {
      const matches = parentMatches || !keyword || (node.searchText ?? node.title).toLowerCase().includes(keyword);
      const children = node.children ? filter(node.children, matches) : undefined;
      return matches || children?.length ? [{ ...node, children }] : [];
    });
  }
  return [...filter(roots), { key: 'unassigned', title: '未关联产品的历史工序' }];
});

async function loadCatalog() {
  catalogLoading.value = true;
  catalogError.value = false;
  try {
    const [tree, summaries] = await Promise.all([getOperationProductTree(), getProductSopStatuses()]);
    catalog.value = tree;
    productStatuses.value = Object.fromEntries(summaries.items.map((item) => [item.product_id, item]));
  }
  catch { catalogError.value = true; }
  finally { catalogLoading.value = false; }
}

async function refresh() {
  const request = ++listRequest;
  rows.value = [];
  total.value = 0;
  workspace.value = undefined;
  workspaceError.value = false;
  workspaceLoading.value = !!selectedProduct.value;
  if (!selectedProduct.value && selected.value !== 'unassigned') { loading.value = false; return; }
  loading.value = true;
  try {
    const productId = selectedProduct.value?.id;
    const [result, state] = await Promise.all([
      productId ? Promise.resolve({ items: [] as Operation[], total: 0 }) : listOperations({ page: page.value, page_size: pageSize, unassigned: true, ...createdRangeQuery(createdRange.value) }),
      productId ? getProductSopWorkspace(productId).catch(() => { if (request === listRequest) workspaceError.value = true; return undefined; }) : Promise.resolve(undefined),
    ]);
    if (request !== listRequest) return;
    workspace.value = state;
    const range = createdRangeQuery(createdRange.value);
    const allRows = state?.operation_states.map((item) => item.operation).filter((item) => {
      const time = new Date(item.created_at ?? '').getTime();
      return (!range.created_from || (Number.isFinite(time) && time >= new Date(range.created_from).getTime()))
        && (!range.created_to || time <= new Date(range.created_to).getTime());
    });
    rows.value = allRows ? allRows.slice((page.value - 1) * pageSize, page.value * pageSize) : result.items;
    total.value = allRows?.length ?? result.total;
    if (state?.status === 'empty') delete productStatuses.value[state.product_id];
    else if (state) productStatuses.value[state.product_id] = {
      product_id: state.product_id, status: state.pending_version ? 'pending' : state.dirty ? 'draft' : 'approved',
      dirty: state.dirty, operation_count: state.current_operations.length,
    };
  } catch { if (request === listRequest && selectedProduct.value) workspaceError.value = true; }
  finally { if (request === listRequest) { loading.value = false; workspaceLoading.value = false; } }
}

function selectNode(keys: (number | string)[]) {
  if (reordering.value || deletingId.value || preparingMedia.value || submitting.value || discarding.value) return;
  draggingId.value = '';
  dropId.value = '';
  selected.value = String(keys[0] ?? '');
  historyOpen.value = false;
  previewOpen.value = false;
  attachmentsOpen.value = false;
  page.value = 1;
  void refresh();
}

function edit(row?: Operation, event?: Event) {
  if (editingLocked.value) { message.warning('当前产品待审核或状态尚未加载，暂不能修改工序'); return; }
  if (!row && !selectedProduct.value) return;
  returnFocus = (event?.currentTarget ?? document.activeElement) as HTMLElement;
  editorSession++;
  uploadAbort = new AbortController();
  editingId.value = row?.id;
  editingProductId.value = row?.product_id ?? '';
  form.code = row?.code ?? '';
  form.name = row?.name ?? '';
  form.description = row?.description ?? '';
  form.product_id = row ? (row.product_id ?? '') : selectedProduct.value!.id;
  formCategoryId.value = catalog.value.products.find((p) => p.id === form.product_id)?.category_id ?? '';
  form.attachments = row ? row.attachments.map((attachment) => ({ ...attachment })) : [];
  conversionStates.value = {};
  fileKind.value = 'image';
  open.value = true;
  void refreshConversions();
}

function close() { if (editorPreviewOpen.value || renameOpen.value) return; uploadAbort.abort(); editorSession++; open.value = false; }

function renameAttachment(attachment: OperationAttachment, event: Event) {
  renameTrigger = event.currentTarget as HTMLElement;
  renameFileId.value = attachment.file_id;
  renameName.value = attachment.name;
  renameOpen.value = true;
}

function confirmAttachmentName() {
  const attachment = form.attachments.find((item) => item.file_id === renameFileId.value);
  if (!attachment) return;
  const name = renameName.value.trim();
  const suffix = (value: string) => value.slice(value.lastIndexOf('.')).toLowerCase();
  if (!name || name.length > 255 || suffix(name) !== suffix(attachment.original_name || attachment.name)) {
    message.warning('请输入不超过 255 个字的文件名，并保留原文件扩展名');
    return;
  }
  attachment.name = name;
  renameOpen.value = false;
}

function afterOpenChange(visible: boolean) {
  if (!visible && !open.value) returnFocus?.focus();
}

function changeFormCategory() {
  if (formProduct.value?.category_id !== formCategoryId.value) form.product_id = '';
}

function editProductCategory(event: Event) {
  if (!selectedProduct.value) return;
  returnFocus = event.currentTarget as HTMLElement;
  categoryDraftId.value = selectedProduct.value.category_id ?? '';
  categoryOpen.value = true;
}

async function saveProductCategory() {
  if (!selectedProduct.value || !categoryDraftId.value || categorySaving.value) return;
  categorySaving.value = true;
  try {
    await updateProductCategoryApi(selectedProduct.value.id, categoryDraftId.value);
    categoryOpen.value = false;
    await loadCatalog();
    message.success('产品分类已更新');
  } finally { categorySaving.value = false; }
}

function openCopy(row: Operation, event: Event) {
  returnFocus = event.currentTarget as HTMLElement;
  copySource.value = row;
  copyCategoryId.value = '';
  copyProductId.value = '';
  copyOpen.value = true;
}

async function saveCopy() {
  if (!copySource.value || !copyProductId.value || copySaving.value) return;
  copySaving.value = true;
  try {
    await saveOperation({
      code: '', name: copySource.value.name, description: copySource.value.description,
      product_id: copyProductId.value, attachments: copySource.value.attachments,
    });
    copyOpen.value = false;
    selected.value = `product:${copyProductId.value}`;
    page.value = 1;
    await loadCatalog();
    await refresh();
    message.success('工序已复制为目标产品草稿，请提交审核');
  } finally { copySaving.value = false; }
}

async function addFiles(files: File[]) {
  const session = editorSession;
  const operationId = editingId.value;
  for (const file of files) {
    if (!open.value || session !== editorSession) return;
    const extension = `.${file.name.split('.').pop()?.toLowerCase()}`;
    if (!fileKinds.some((kind) => kind.accept.split(',').includes(extension))) {
      message.warning(`不支持的文件：${file.name}`);
      continue;
    }
    if (form.attachments.length >= 100) { message.warning('最多上传 100 个附件'); return; }
    activeUploads.value++;
    try {
      uploadPercent.value = 0;
      uploadStatus.value = `正在上传：${file.name}`;
      const stored = await uploadOperationFile(file, operationId, (percent) => {
        if (session !== editorSession) return;
        uploadPercent.value = percent;
        uploadStatus.value = percent < 100 ? `正在上传：${file.name}`
          : `上传完成，正在保存原文件：${file.name}`;
      }, uploadAbort.signal);
      if (session === editorSession && open.value) {
        form.attachments.push(stored);
        void refreshConversions();
      }
    } catch { /* Request client displays the upload error; keep the editor open for retry. */ }
    finally { activeUploads.value--; if (!activeUploads.value) uploadStatus.value = ''; }
  }
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  void addFiles(Array.from(input.files ?? []));
  input.value = '';
}

function paste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.items ?? [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile()).filter((item): item is File => item !== null);
  if (files.length) { event.preventDefault(); void addFiles(files); }
}

function previewAttachments(row: Operation, event: Event) {
  attachmentsTrigger.value = event.currentTarget as HTMLElement;
  if (!row.product_id || workspaceLoading.value || workspaceError.value) return;
  const deleted = deletedOperation(row);
  const versionId = deleted ? workspace.value?.approved_version?.id : previewVersionId.value;
  const snapshot = (deleted ? workspace.value?.approved_version?.operations : previewOperations.value)?.find((item) => item.id === row.id);
  if (versionId && !snapshot) { message.warning('该工序不属于当前版本，请刷新后重试'); return; }
  attachmentsOperation.value = snapshot ?? row;
  attachmentsVersionId.value = versionId;
  attachmentsProductId.value = row.product_id;
  attachmentsOpen.value = true;
}

function previewEditorAttachment(fileId: string, event: Event) {
  editorPreviewTrigger.value = event.currentTarget as HTMLElement;
  editorPreviewFile.value = fileId;
  editorPreviewId.value = editingId.value;
  editorPreviewOperation.value = {
    id: editingId.value ?? 'unsaved-operation', sort_order: 0,
    code: form.code, name: form.name || '未保存工序', product_id: form.product_id,
    description: form.description, attachments: [...form.attachments],
  };
  editorPreviewOpen.value = true;
}

async function save() {
  if (editingLocked.value) { message.warning('当前产品待审核或状态尚未加载，暂不能保存修改'); return; }
  if (activeUploads.value || saving.value) return;
  if (!form.name.trim()) { message.warning('请填写工序名称'); return; }
  if (!form.product_id) { message.warning('请先选择产品'); return; }
  saving.value = true;
  const session = editorSession;
  try {
    const moved = !!editingId.value && form.product_id !== editingProductId.value;
    await saveOperation({ ...form, code: form.code.trim(), name: form.name.trim() }, editingId.value);
    if (session === editorSession) close();
    if (moved) selected.value = `product:${form.product_id}`;
    await loadCatalog();
    await refresh();
    message.success('工序已保存为草稿');
  } finally { saving.value = false; }
}

function startDrag(event: DragEvent, row: Operation) {
  if (!canReorder.value || deletedOperation(row)) { event.preventDefault(); return; }
  draggingId.value = row.id;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', row.id);
  }
}

function endDrag() { draggingId.value = ''; dropId.value = ''; }

async function move(id: string, targetId: string, position: 'after' | 'before') {
  if (id === targetId || !canReorder.value) return;
  reordering.value = true;
  endDrag();
  try {
    await moveOperation(id, targetId, position);
    await refresh();
    message.success('工序顺序已保存');
  } finally { reordering.value = false; }
}

function rowEvents(row: Operation) {
  return {
    class: row.id === dropId.value ? `operation-drop-target-${dropAfter.value ? 'after' : 'before'}` : '',
    onDragover: (event: DragEvent) => {
      if (deletedOperation(row) || !draggingId.value || !canReorder.value || draggingId.value === row.id) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
      dropAfter.value = event.clientY >= rect.top + rect.height / 2;
      dropId.value = row.id;
    },
    onDrop: (event: DragEvent) => {
      if (deletedOperation(row) || !draggingId.value || !canReorder.value) return;
      event.preventDefault();
      const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
      void move(draggingId.value, row.id, event.clientY < rect.top + rect.height / 2 ? 'before' : 'after');
    },
  };
}

function moveWithKeyboard(row: Operation, direction: -1 | 1) {
  const index = rows.value.findIndex((item) => item.id === row.id);
  const target = rows.value[index + direction];
  if (target && !deletedOperation(row) && !deletedOperation(target)) void move(row.id, target.id, direction < 0 ? 'before' : 'after');
}

function confirmDelete(row: Operation) {
  if (editingLocked.value) return;
  Modal.confirm({
    zIndex: 3000,
    title: '删除工序',
    content: `确认删除工序“${row.name}”？删除将保存为草稿变更；已生效内容需审核通过后移除。`,
    keyboard: true,
    okText: '删除', cancelText: '取消', okType: 'danger',
    async onOk() {
      deletingId.value = row.id;
      try {
        await deleteOperation(row.id);
        if (rows.value.length === 1 && page.value > 1) page.value--;
        await refresh();
        message.success('工序已删除');
      } finally { deletingId.value = undefined; }
    },
  });
}

async function prepareMedia() {
  if (!selectedProduct.value || editingLocked.value) return;
  preparingMedia.value = true;
  try {
    await prepareProductSopMedia(selectedProduct.value.id);
    await refresh();
    message.success('已加入后台转换队列，完成后会自动更新预览');
  } finally { preparingMedia.value = false; }
}

function submitForReview() {
  if (!selectedProduct.value || !workspace.value?.dirty || editingLocked.value) return;
  const product = selectedProduct.value;
  Modal.confirm({
    zIndex: 3000,
    title: `提交“${product.name}”审核`,
    content: `将冻结并提交当前产品的全部 ${workspace.value.current_operations.length} 道工序、顺序和附件，待审核期间不能修改。`,
    keyboard: true, okText: '提交审核', cancelText: '取消',
    async onOk() {
      submitting.value = true;
      try {
        await submitProductSop(product.id);
        await refresh();
        message.success('已提交审核，可在 SOP审核 页面查看');
      } finally { submitting.value = false; }
    },
  });
}

function confirmDiscardDraft() {
  if (!selectedProduct.value || !canDiscardDraft.value || editingLocked.value) return;
  const product = selectedProduct.value;
  Modal.confirm({
    zIndex: 3000,
    title: `取消“${product.name}”的草稿`,
    content: workspace.value?.approved_version
      ? `将撤销该产品所有未提交的工序、顺序和附件修改，恢复到生效 V${workspace.value.approved_version.version}。此操作不能撤销。`
      : '该产品尚无生效版本，将移除所有未提交的工序。此操作不能撤销。',
    keyboard: true, okText: '取消草稿', cancelText: '保留草稿', okType: 'danger',
    async onOk() {
      discarding.value = true;
      try {
        await discardProductSopDraft(product.id);
        page.value = 1;
        await refresh();
        message.success('草稿已取消');
      } finally { discarding.value = false; }
    },
  });
}

onMounted(() => {
  void loadCatalog();
  conversionTimer = setInterval(() => { void refreshConversions(); void refreshProductPreviews(); }, 3_000);
});
onBeforeUnmount(() => { if (conversionTimer) clearInterval(conversionTimer); });
</script>

<template>
  <Page title="SOP列表">
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside class="min-w-0 rounded-lg bg-background p-4" aria-label="产品分类和产品">
        <h2 class="mb-3 text-base font-medium">产品分类与产品</h2>
        <Input.Search v-model:value="search" allow-clear placeholder="搜索分类、产品名称或编码" class="mb-4" />
        <Spin :spinning="catalogLoading">
          <div v-if="catalogError"><p class="mb-2">产品目录加载失败</p><Button @click="loadCatalog">重试</Button></div>
          <Tree v-else-if="catalog.products.length || catalog.categories.length" :key="search" :tree-data="treeData" :selected-keys="selected ? [selected] : []" default-expand-all block-node @select="selectNode">
            <template #title="node">
              <span class="inline-flex items-center gap-2">
                <IconifyIcon v-if="node.key !== 'unassigned'" :icon="String(node.key).startsWith('product:') ? 'lucide:package' : 'lucide:folder'" class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span>{{ node.title }}</span>
                <Tag v-if="node.status && node.status !== 'approved'" :color="node.status === 'draft' ? 'orange' : 'blue'" class="!m-0">{{ node.status === 'draft' ? '草稿' : '待审核' }}</Tag>
              </span>
            </template>
          </Tree>
          <Empty v-else description="暂无产品，请先维护产品资料" />
          <Button v-if="!catalog.products.length && !catalogLoading" type="link" @click="selectNode(['unassigned'])">查看历史工序</Button>
        </Spin>
      </aside>
      <section class="min-w-0 rounded-lg bg-background p-4">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-medium">{{ selectedProduct?.name ?? (selected === 'unassigned' ? '未关联产品的历史工序' : '产品工序') }}</h2>
            <p v-if="selectedProduct" class="mt-1 text-sm text-muted-foreground">{{ selectedProduct.code }} · {{ workspace?.current_operations.length ?? total }} 道工序<span v-if="workspace?.operation_states.some((item) => item.is_deleted)"> · {{ workspace.operation_states.filter((item) => item.is_deleted).length }} 道待删除</span></p>
            <div v-if="workspace" class="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <Tag>{{ productSopStatusText[workspace.status] }}</Tag>
              <span v-if="workspace.approved_version" class="text-muted-foreground">生效 V{{ workspace.approved_version.version }}</span>
              <span v-if="workspace.pending_version" class="text-muted-foreground">待审核 V{{ workspace.pending_version.version }}</span>
              <span v-if="workspace.dirty && workspace.status !== 'pending'" class="text-muted-foreground">存在未提交的修改</span>
              <Button type="link" size="small" :disabled="loading || submitting" @click="refresh">刷新状态</Button>
              <Button v-access:code="'erp:product:update'" type="link" size="small" :disabled="catalogLoading || !catalog.categories.length" @click="editProductCategory">修改产品分类</Button>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button v-access:code="'esop:operation:create'" :disabled="!selectedProduct || editingLocked" type="primary" @click="edit(undefined, $event)">新建工序</Button>
            <Button v-access:code="'esop:operation:create'" :disabled="!selectedProduct || editingLocked" @click="startSopImport">导入SOP文件</Button>
            <Button v-access:code="'esop:sop:submit'" :disabled="!selectedProduct || !workspace?.dirty || needsMedia || editingLocked || loading || reordering" :loading="submitting" @click="submitForReview">提交审核</Button>
            <Button v-if="canDiscardDraft" v-access:code="'esop:operation:update'" :disabled="editingLocked || loading || reordering" :loading="discarding" danger @click="confirmDiscardDraft">取消草稿</Button>
            <Button v-if="needsMedia" v-access:code="'esop:operation:update'" :disabled="editingLocked" :loading="preparingMedia" @click="prepareMedia">生成预览</Button>
            <Button v-access:code="'esop:sop:list'" :disabled="!selectedProduct || workspaceLoading" @click="historyOpen = true">历史版本</Button>
            <Button :disabled="!selectedProduct || !previewOperations.length || workspaceLoading" @click="previewOpen = true">预览</Button>
          </div>
        </div>
        <div v-if="workspaceError" class="mb-4 flex flex-wrap items-center gap-2 text-sm"><span>工序或版本状态加载失败，已暂停编辑。</span><Button size="small" @click="refresh">重试</Button></div>
        <p v-if="needsMedia && workspace?.status !== 'pending'" class="mb-4 text-sm text-muted-foreground">部分 Office / PDF 附件正在后台生成预览，完成后会自动更新并可提交审核。</p>
        <p v-if="workspace?.status === 'pending'" class="mb-4 text-sm text-muted-foreground">当前提交已冻结，审核完成后可继续修改；现有生效版本仍可用于生产。</p>
        <div class="mb-3 flex items-center gap-2"><span>创建时间</span><DatePicker.RangePicker v-model:value="createdRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" @change="page = 1; refresh()" /></div>
        <Empty v-if="!selectedProduct && selected !== 'unassigned'" description="请在左侧选择具体产品，查看或创建工序" />
        <Table v-else :columns="columns" :data-source="rows" :loading="loading || reordering" :custom-row="rowEvents" :pagination="{ current: page, pageSize, total, showSizeChanger: false }" :scroll="{ x: 750 }" row-key="id" @change="(pagination) => { page = pagination.current ?? 1; refresh(); }">
          <template #bodyCell="{ column, record }">
            <span v-if="column.key === 'sort'" v-access:code="'esop:operation:update'" role="button" :tabindex="canReorder && !deletedOperation(record as Operation) ? 0 : -1" :draggable="canReorder && !deletedOperation(record as Operation)" :aria-disabled="!canReorder || deletedOperation(record as Operation)" :class="canReorder ? 'cursor-grab' : 'cursor-not-allowed'" class="inline-flex items-center p-1 text-muted-foreground" aria-label="拖拽排序，可按上下方向键调整" title="拖拽排序，也可按上/下方向键调整" @dragstart="startDrag($event, record as Operation)" @dragend="endDrag" @keydown.up.prevent="moveWithKeyboard(record as Operation, -1)" @keydown.down.prevent="moveWithKeyboard(record as Operation, 1)">
              <IconifyIcon icon="lucide:grip-vertical" class="pointer-events-none size-4" aria-hidden="true" />
            </span>
            <div v-if="column.key === 'state'">
              <Tag v-if="operationStates.get(record.id)" :color="operationStates.get(record.id)?.status === 'approved' ? 'green' : operationStates.get(record.id)?.status === 'pending' ? 'blue' : 'orange'">{{ operationStateText[operationStates.get(record.id)!.status] }}</Tag>
              <span v-else class="text-muted-foreground">历史工序</span>
              <p v-if="operationStates.get(record.id)?.has_approved_version && operationStates.get(record.id)?.status !== 'approved'" class="text-xs text-muted-foreground">已有生效版本{{ deletedOperation(record as Operation) && workspace?.pending_version ? ' · 待审核' : '' }}</p>
            </div>
            <Button v-if="column.key === 'attachments'" type="link" :disabled="!record.product_id || workspaceLoading || workspaceError" @click="previewAttachments(record as Operation, $event)">预览</Button>
            <div v-if="column.key === 'action'" class="flex items-center">
              <Dropdown v-if="operationActionCount >= 3" :trigger="['click']"><Button type="link">更多操作</Button><template #overlay><Menu>
                <Menu.Item :disabled="editingLocked || reordering || !!deletingId || deletedOperation(record as Operation)" @click="edit(record as Operation, $event)">编辑</Menu.Item>
                <Menu.Item :disabled="workspaceLoading || workspaceError || deletedOperation(record as Operation)" @click="openCopy(record as Operation, $event)">复制</Menu.Item>
                <Menu.Item danger :disabled="editingLocked || reordering || !!deletingId || deletedOperation(record as Operation)" @click="confirmDelete(record as Operation)">删除</Menu.Item>
              </Menu></template></Dropdown>
              <template v-else>
                <Button v-access:code="'esop:operation:update'" :disabled="editingLocked || reordering || !!deletingId || deletedOperation(record as Operation)" type="link" @click="edit(record as Operation, $event)">编辑</Button>
                <Button v-access:code="'esop:operation:create'" :disabled="workspaceLoading || workspaceError || deletedOperation(record as Operation)" type="link" @click="openCopy(record as Operation, $event)">复制</Button>
                <Button v-access:code="'esop:operation:delete'" :loading="deletingId === record.id" :disabled="editingLocked || reordering || !!deletingId || deletedOperation(record as Operation)" danger type="link" @click="confirmDelete(record as Operation)">删除</Button>
              </template>
            </div>
          </template>
        </Table>
      </section>
    </div>
    <Modal :open="importOpen" title="导入SOP文件" :keyboard="true" width="min(680px, 100vw)" :confirm-loading="importing" :ok-button-props="{ disabled: importUploading || !importFileId || !importSelected.length || editingLocked }" ok-text="生成工序草稿" cancel-text="取消" @cancel="closeSopImport" @ok="confirmSopImport" @after-close="returnFocus?.focus()">
      <p class="mb-4 text-sm text-muted-foreground">从 Excel 的工作表生成工序，工序名称使用 Sheet 名称。原文件保留，每道工序只预览对应工作表。</p>
      <div class="mb-4 rounded border border-dashed border-border p-5 text-center" @dragover.prevent @drop.prevent="chooseSopWorkbookFromDrop($event)">
        <Button :loading="importUploading" @click="importInput?.click()">选择 Excel 文件</Button>
        <input ref="importInput" type="file" accept=".xls,.xlsx" hidden @change="chooseSopWorkbook" />
        <p v-if="importFileName" class="mt-2 break-all text-sm">{{ importFileName }}</p>
        <Progress v-if="importUploading" :percent="importProgress" size="small" />
      </div>
      <template v-if="importSheets.length">
        <p class="mb-2 font-medium">选择要生成工序的 Sheet（{{ importSelected.length }}/{{ importSheets.length }}）</p>
        <div class="mb-4 max-h-56 overflow-y-auto rounded border border-border p-3">
          <div v-for="sheet in importSheets" :key="sheet.index" class="py-1"><Checkbox :checked="importSelected.includes(sheet.index)" @change="toggleImportSheet(sheet.index)">{{ sheet.name }}<span v-if="!sheet.selected" class="ml-2 text-xs text-muted-foreground">默认不选</span></Checkbox></div>
        </div>
        <Form layout="vertical"><Form.Item label="导入方式"><Select v-model:value="importMode" :options="[{ value: 'append', label: '追加到现有工序末尾' }, { value: 'replace', label: '替换当前草稿工序' }]" /></Form.Item></Form>
        <p class="text-sm text-muted-foreground">替换会将当前产品的工序改为待删除草稿；已生效版本仍保持不变。提交审核后才能生效。</p>
      </template>
    </Modal>
    <Drawer :open="open" :mask-style="{ zIndex: 0 }" :content-wrapper-style="{ zIndex: 1 }" :keyboard="!editorPreviewOpen && !renameOpen" :title="editingId ? '编辑工序' : '创建工序'" width="min(680px, 100vw)" @close="close" @after-open-change="afterOpenChange">
      <div @paste="paste">
        <Form :model="form" layout="vertical">
          <div class="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            <Form.Item label="产品分类" required><TreeSelect v-model:value="formCategoryId" :tree-data="categorySelectTree" show-search tree-default-expand-all tree-node-filter-prop="title" placeholder="选择末级分类" @change="changeFormCategory" /></Form.Item>
            <Form.Item label="关联产品" required><Select v-model:value="form.product_id" :options="productOptions" placeholder="选择产品" show-search option-filter-prop="label" /></Form.Item>
          </div>
          <p v-if="editingId && editingProductId && form.product_id && form.product_id !== editingProductId" class="mb-4 text-sm text-muted-foreground">改绑后，原产品工序进入待删除草稿，目标产品生成新工序草稿并使用新编码；两侧修改均需审核后生效。</p>
          <Form.Item label="工序编码"><Input v-model:value="form.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
          <Form.Item label="工序名称" required><Input v-model:value="form.name" :maxlength="100" /></Form.Item>
          <Form.Item label="工序说明"><Input.TextArea v-model:value="form.description" :maxlength="500" :rows="2" /></Form.Item>
        </Form>
        <h3 class="font-medium">工序附件</h3>
        <Tabs v-model:active-key="fileKind">
          <Tabs.TabPane v-for="kind in fileKinds" :key="kind.key" :tab="kind.label" />
        </Tabs>
        <div class="rounded border border-dashed border-border p-6 text-center focus-visible:outline focus-visible:outline-2" tabindex="0" aria-label="附件上传区域，支持拖拽文件和粘贴图片" @dragover.prevent @drop.prevent="addFiles(Array.from($event.dataTransfer?.files ?? []))">
          <p class="mb-3">拖拽文件到此处，或选择{{ currentKind.label }}文件</p>
          <Button :loading="activeUploads > 0" @click="fileInput?.click()">上传{{ currentKind.label }}</Button>
          <p v-if="['model3d', 'model_resource'].includes(fileKind)" class="mt-3 text-sm text-muted-foreground">GLTF / OBJ 使用外部资源时，请将同名配套 BIN、MTL 和纹理图片上传到同一工序；自包含 GLB 文件可直接查看。</p>
          <p class="mt-3 text-sm text-muted-foreground">支持 {{ currentKind.accept }}；支持复制图片后粘贴上传，文件大小遵循平台上传限制</p>
          <div v-if="activeUploads" role="status" class="mt-3">
            <Progress :percent="uploadPercent" :status="uploadPercent === 100 ? 'active' : 'normal'" />
            <p class="break-all text-sm">{{ uploadStatus }}</p>
            <p class="mt-1 text-sm text-muted-foreground">处理完成后可保存草稿；大文档转换需要一些时间。</p>
          </div>
          <input ref="fileInput" type="file" :accept="currentKind.accept" multiple hidden @change="chooseFiles" />
        </div>
        <ul v-if="form.attachments.length" class="mt-4 divide-y divide-border">
          <li v-for="(attachment, index) in form.attachments" :key="attachment.file_id" class="flex items-center justify-between gap-3 py-2">
            <span class="min-w-0 break-all"><Button type="link" class="!h-auto !whitespace-normal !p-0 !text-left" @click="previewEditorAttachment(attachment.file_id, $event)">{{ attachment.name }}</Button> <span class="text-sm text-muted-foreground">（{{ fileKinds.find((kind) => kind.key === attachment.kind)?.label }} · {{ Math.ceil(attachment.size / 1024) }} KB）</span><Tag v-if="needsConversion(attachment)" :color="conversionStates[attachment.file_id]?.status === 'failed' ? 'error' : 'processing'">{{ conversionStates[attachment.file_id]?.status === 'failed' ? '转换失败' : conversionStates[attachment.file_id]?.status === 'running' ? '转换中' : '排队中' }}</Tag><span v-if="conversionStates[attachment.file_id]?.status === 'failed'" class="text-sm text-red-600">{{ conversionStates[attachment.file_id]?.error_message }}</span></span>
            <div class="shrink-0"><Button v-if="conversionStates[attachment.file_id]?.status === 'failed'" type="link" :loading="retryingFile === attachment.file_id" @click="retryConversion(attachment.file_id)">重新转换</Button><Button type="link" :disabled="saving" @click="renameAttachment(attachment, $event)">重命名</Button><Button type="link" :disabled="saving" @click="form.attachments.splice(index, 1)">移除</Button></div>
          </li>
        </ul>
      </div>
      <template #footer>
        <Button class="mr-2" @click="close">取消</Button>
        <Button :loading="saving" :disabled="activeUploads > 0 || editingLocked" type="primary" @click="save">保存草稿</Button>
      </template>
    </Drawer>
    <Modal v-model:open="renameOpen" title="重命名附件" :keyboard="true" :z-index="3400" ok-text="确定" @ok="confirmAttachmentName" @after-close="renameTrigger?.focus()">
      <Input v-model:value="renameName" :maxlength="255" aria-label="附件名称" @press-enter="confirmAttachmentName" />
      <p class="mt-2 text-sm text-muted-foreground">仅修改显示名称，文件内容和扩展名保持不变。</p>
    </Modal>
    <Modal v-model:open="categoryOpen" title="修改产品所属分类" :keyboard="true" :confirm-loading="categorySaving" :ok-button-props="{ disabled: !categoryDraftId || categoryDraftId === selectedProduct?.category_id }" ok-text="保存" cancel-text="取消" @ok="saveProductCategory" @after-close="returnFocus?.focus()">
      <p class="mb-3">{{ selectedProduct?.name }}</p>
      <TreeSelect v-model:value="categoryDraftId" class="w-full" :tree-data="categorySelectTree" show-search tree-default-expand-all tree-node-filter-prop="title" placeholder="选择末级分类" />
      <p class="mt-2 text-sm text-muted-foreground">产品只能归入末级分类；含子分类的分类不能直接选择。</p>
    </Modal>
    <Modal v-model:open="copyOpen" title="复制工序到其他产品" :keyboard="true" :confirm-loading="copySaving" :ok-button-props="{ disabled: !copyProductId }" ok-text="复制" cancel-text="取消" @ok="saveCopy" @after-close="returnFocus?.focus()">
      <p class="mb-3">{{ copySource?.name }} · 附件一并复制，新工序自动生成编码。</p>
      <Form layout="vertical">
        <Form.Item label="目标产品分类" required><TreeSelect v-model:value="copyCategoryId" :tree-data="categorySelectTree" show-search tree-default-expand-all tree-node-filter-prop="title" placeholder="选择末级分类" @change="copyProductId = ''" /></Form.Item>
        <Form.Item label="目标产品" required><Select v-model:value="copyProductId" :options="copyProductOptions" show-search option-filter-prop="label" placeholder="选择其他产品" /></Form.Item>
      </Form>
      <p class="text-sm text-muted-foreground">原工序保持不变；复制后的工序需在目标产品提交审核。</p>
    </Modal>
    <OperationAttachmentsPreview v-if="editorPreviewOperation" v-model:open="editorPreviewOpen" :product-id="editorPreviewOperation.product_id ?? ''" :title="`${editorPreviewOperation.name} · 编辑附件预览`" :operations="[editorPreviewOperation]" :initial-file-id="editorPreviewFile" :resolve-file="resolveEditorFile" :trigger-element="editorPreviewTrigger" />
    <ProductSopHistory v-if="selectedProduct" v-model:open="historyOpen" :product-id="selectedProduct.id" :product-name="selectedProduct.name" :can-rollback="!editingLocked" @changed="refresh" />
    <OperationAttachmentsPreview v-if="attachmentsOperation" v-model:open="attachmentsOpen" :product-id="attachmentsProductId" :title="`${attachmentsOperation.name} · 附件预览`" :operations="[attachmentsOperation]" :version-id="attachmentsVersionId" :trigger-element="attachmentsTrigger" />
    <ProductSopPreview v-if="selectedProduct" v-model:open="previewOpen" :product-id="selectedProduct.id" :title="`${selectedProduct.name} · ${previewLabel} 终端预览`" :operations="previewOperations" :version-id="previewVersionId" />
  </Page>
</template>

<style scoped>
:deep(.ant-tree-node-content-wrapper) { min-width: 0; }
:deep(.ant-tree-title) { overflow-wrap: anywhere; }
:deep(.operation-drop-target-before > td) { box-shadow: inset 0 2px hsl(var(--primary)); }
:deep(.operation-drop-target-after > td) { box-shadow: inset 0 -2px hsl(var(--primary)); }
</style>
