<script lang="ts" setup>
import type { ChannelBatch, ChannelKey, KeyBatch } from '../../api/channel';
import type { Channel, HardwareModel, OtaPackage } from '../../api/ota';

import type { UserRecord } from '#/api/core/users';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { formatDateTime } from '@vben/utils';

import { SelectableTable } from '#/components/selectable-table';
import { Button, DatePicker, Drawer, Dropdown, Form, Input, InputNumber, Menu, message, Modal, Popconfirm, Select, Table, Tabs, Tag } from 'ant-design-vue';
import { createdRangeQuery } from '#/utils/created-range';

import { getCurrentUserApi } from '#/api/core/auth';

import { listUsersApi } from '#/api/core/users';

import { addChannelAdmin, exportAdminChannelKeys, issueChannelKeyBatch, listAdminChannelBatches, listAdminChannelKeys } from '../../api/channel';
import { createOtaPackage, downloadOtaPackage, listChannels, listHardwareModels, listOtaPackages, publishOtaPackage, saveChannel, saveHardwareModel, uploadOtaFile } from '../../api/ota';

const tab = ref('packages');
const { hasAccessByCodes } = useAccess();
const channelActionCount = Number(hasAccessByCodes(['esop:ota:manage']))
  + Number(hasAccessByCodes(['esop:channel:admin']))
  + 2 * Number(hasAccessByCodes(['esop:channel:issue']));
const isAdmin = ref(false);
const downloading = ref<string>();
const channels = ref<Channel[]>([]);
const models = ref<HardwareModel[]>([]);
const packages = ref<OtaPackage[]>([]);
const loading = ref(false);
const saving = ref(false);
const channelOpen = ref(false);
const modelOpen = ref(false);
const packageOpen = ref(false);
const uploadButton = ref<{ $el: HTMLButtonElement }>();
const channelAdminOpen = ref(false);
const batchOpen = ref(false);
const issuedBatch = ref<KeyBatch>();
const inventoryOpen = ref(false);
const inventoryLoading = ref(false);
const inventoryBatches = ref<ChannelBatch[]>([]);
const inventoryKeys = ref<ChannelKey[]>([]);
const inventoryBatchId = ref<string>();
const inventoryCreatedRange = ref<[string, string]>();
const inventoryPage = ref(1);
const inventoryTotal = ref(0);
const inventorySelected = ref<string[]>([]);
const targetChannel = ref<Channel>();
const selectedUser = ref<string>();
const userOptions = ref<{ label: string; value: string }[]>([]);
const batchQuantity = ref(100);
const batchModelId = ref<string>();
const channelId = ref<string>();
const modelId = ref<string>();
const fileName = ref('');
const channelForm = reactive({ code: '', name: '' });
const modelForm = reactive({ channel_id: '', code: '', name: '', abi: '' });
const packageForm = reactive({ channel_id: '', hardware_model_id: '', version: '', version_code: 0, package_name: '', file_id: '', release_notes: '' });
const channelOptions = computed(() => channels.value.map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const modelOptions = computed(() => models.value.filter((item) => item.channel_id === packageForm.channel_id).map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const batchModelOptions = computed(() => models.value.filter((item) => item.channel_id === targetChannel.value?.id).map((item) => ({ label: `${item.name} (${item.code})`, value: item.id })));
const inventoryBatchOptions = computed(() => inventoryBatches.value.map((item) => ({ label: `${item.batch_id.slice(0, 8)} · ${item.quantity} 个`, value: item.batch_id })));
const channelNames = computed(() => new Map(channels.value.map((item) => [item.id, item.name])));
const modelNames = computed(() => new Map(models.value.map((item) => [item.id, item.name])));
const packageColumns = [
  { title: '渠道', key: 'channel', width: 140 }, { title: '硬件型号', key: 'model', width: 160 },
  { title: '原始文件名', key: 'file_name', width: 220 },
  { title: '版本', dataIndex: 'version', key: 'version', width: 130 },
  { title: '版本号', dataIndex: 'version_code', key: 'version_code', width: 90 },
  { title: 'ABI', key: 'abi', width: 130 },
  { title: '大小', key: 'size', width: 100 },
  { title: '状态', key: 'status', width: 110 }, { title: '安装与更新说明', dataIndex: 'release_notes', key: 'release_notes', width: 260 }, { title: 'SHA-256', key: 'checksum' },
  { title: '发布时间', dataIndex: 'published_at', key: 'published_at', width: 190 },
  { title: '操作', key: 'action', width: 160 },
];
const channelColumns = [
  { title: '编码', dataIndex: 'code', key: 'code' }, { title: '渠道名称', dataIndex: 'name', key: 'name' },
  { title: '操作', key: 'action', width: 120 },
];
const modelColumns = [
  { title: '渠道', key: 'channel' }, { title: '型号编码', dataIndex: 'code', key: 'code' },
  { title: '型号名称', dataIndex: 'name', key: 'name' }, { title: 'ABI', dataIndex: 'abi', key: 'abi' },
  { title: '操作', key: 'action', width: 100 },
];

async function refresh() {
  loading.value = true;
  try {
    isAdmin.value = (await getCurrentUserApi()).is_superuser === true;
    const [channelResult, modelResult, packageResult] = await Promise.all([listChannels(), listHardwareModels(), listOtaPackages()]);
    channels.value = channelResult.items;
    models.value = modelResult.items;
    packages.value = packageResult.items;
  } finally { loading.value = false; }
}

function editChannel(row?: Channel) {
  channelId.value = row?.id;
  channelForm.code = row?.code ?? '';
  channelForm.name = row?.name ?? '';
  channelOpen.value = true;
}

async function submitChannel() {
  if (!channelForm.name.trim()) return message.warning('请填写渠道名称');
  saving.value = true;
  try {
    await saveChannel({ code: channelForm.code.trim(), name: channelForm.name.trim() }, channelId.value);
    channelOpen.value = false;
    await refresh();
    message.success('渠道已保存');
  } finally { saving.value = false; }
}

function editModel(row?: HardwareModel) {
  modelId.value = row?.id;
  modelForm.channel_id = row?.channel_id ?? '';
  modelForm.code = row?.code ?? '';
  modelForm.name = row?.name ?? '';
  modelForm.abi = row?.abi ?? '';
  modelOpen.value = true;
}

async function submitModel() {
  if (!modelForm.channel_id || !modelForm.name.trim() || !modelForm.abi.trim()) return message.warning('请填写渠道、型号名称和 ABI');
  saving.value = true;
  try {
    await saveHardwareModel({ channel_id: modelForm.channel_id, code: modelForm.code.trim(), name: modelForm.name.trim(), abi: modelForm.abi.trim() }, modelId.value);
    modelOpen.value = false;
    await refresh();
    message.success('硬件型号已保存');
  } finally { saving.value = false; }
}

function newPackage() {
  Object.assign(packageForm, { channel_id: '', hardware_model_id: '', version: '', version_code: 0, package_name: '', file_id: '', release_notes: '' });
  fileName.value = '';
  packageOpen.value = true;
}

function afterPackageOpenChange(open: boolean) {
  if (!open) uploadButton.value?.$el.focus();
}

function selectPackageChannel() { packageForm.hardware_model_id = ''; }

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  input.value = '';
  if (!/\.(apk|exe|deb|appimage)$/i.test(file.name)) return message.warning('请选择 APK、EXE、DEB 或 AppImage 文件');
  saving.value = true;
  try {
    packageForm.file_id = (await uploadOtaFile(file)).id;
    fileName.value = file.name;
    message.success('安装包已上传');
  } finally { saving.value = false; }
}

async function submitPackage() {
  if (!packageForm.channel_id || !packageForm.hardware_model_id || !packageForm.version.trim() || !packageForm.file_id) return message.warning('请选择渠道、硬件型号、版本和安装包');
  if (!Number.isInteger(packageForm.version_code) || packageForm.version_code < 0) return message.warning('版本号须为非负整数');
  saving.value = true;
  try {
    await createOtaPackage({ ...packageForm, version: packageForm.version.trim(), package_name: packageForm.package_name.trim() });
    packageOpen.value = false;
    await refresh();
    message.success('安装包已保存为草稿');
  } finally { saving.value = false; }
}

async function download(row: OtaPackage) {
  downloading.value = row.id;
  try {
    const response = await downloadOtaPackage(row.id);
    const blob = response.data;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const filename = response.headers['content-disposition']?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    link.download = filename ? decodeURIComponent(filename) : `esop-${row.version}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } finally { downloading.value = undefined; }
}

async function publish(row: OtaPackage) {
  await publishOtaPackage(row.id);
  await refresh();
  message.success('已发布到该硬件型号');
}

async function openChannelAdmin(row: Channel) {
  targetChannel.value = row;
  selectedUser.value = undefined;
  const users = (await listUsersApi({ page: 1, page_size: 50 })).items as UserRecord[];
  userOptions.value = users.map((user) => ({ label: `${user.full_name || user.username} (${user.username})`, value: user.id }));
  channelAdminOpen.value = true;
}

async function saveChannelAdmin() {
  if (!targetChannel.value || !selectedUser.value) return message.warning('请选择用户');
  saving.value = true;
  try {
    await addChannelAdmin(targetChannel.value.id, selectedUser.value);
    channelAdminOpen.value = false;
    message.success('渠道管理员已关联');
  } finally { saving.value = false; }
}

function openBatch(row: Channel) {
  targetChannel.value = row;
  batchQuantity.value = 100;
  batchModelId.value = undefined;
  batchOpen.value = true;
}

async function issueBatch() {
  if (!targetChannel.value || !Number.isInteger(batchQuantity.value) || batchQuantity.value < 100 || batchQuantity.value > 1000) return message.warning('每批须发放 100–1000 个密钥');
  saving.value = true;
  try {
    issuedBatch.value = await issueChannelKeyBatch(targetChannel.value.id, batchQuantity.value, batchModelId.value);
    batchOpen.value = false;
    message.success('密钥已发放，可在渠道库存中随时查看和导出');
  } finally { saving.value = false; }
}

function downloadBatch() {
  if (!issuedBatch.value) return;
  const csv = `id,key\n${issuedBatch.value.keys.map((item) => `${item.id},${item.key}`).join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `渠道密钥-${issuedBatch.value.batch_id}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function closeIssuedBatch() { issuedBatch.value = undefined; }

async function loadInventory() {
  if (!targetChannel.value) return;
  inventoryLoading.value = true;
  try {
    const result = await listAdminChannelKeys(targetChannel.value.id, { batch_id: inventoryBatchId.value, page: inventoryPage.value, page_size: 20, ...createdRangeQuery(inventoryCreatedRange.value) });
    inventoryKeys.value = result.items;
    inventoryTotal.value = result.total;
  } finally { inventoryLoading.value = false; }
}

async function openInventory(row: Channel) {
  targetChannel.value = row;
  inventoryBatchId.value = undefined;
  inventoryPage.value = 1;
  inventorySelected.value = [];
  inventoryOpen.value = true;
  inventoryBatches.value = (await listAdminChannelBatches(row.id)).items;
  await loadInventory();
}

async function changeInventoryBatch() {
  inventoryPage.value = 1;
  inventorySelected.value = [];
  await loadInventory();
}

async function changeInventoryPage(pagination: { current?: number }) {
  inventoryPage.value = pagination.current || 1;
  inventorySelected.value = [];
  await loadInventory();
}

function toggleInventory(id: string, checked: boolean) {
  inventorySelected.value = checked ? [...inventorySelected.value, id] : inventorySelected.value.filter((item) => item !== id);
}

async function exportInventory(selection: 'batch' | 'selected') {
  if (!targetChannel.value) return;
  if (selection === 'batch' && !inventoryBatchId.value) return message.warning('请先选择批次');
  if (selection === 'selected' && inventorySelected.value.length === 0) return message.warning('请先勾选密钥');
  const blob = await exportAdminChannelKeys(targetChannel.value.id, selection === 'batch' ? { batch_id: inventoryBatchId.value } : { key_ids: inventorySelected.value });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `渠道密钥-${selection === 'batch' ? inventoryBatchId.value : '已选'}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

onMounted(() => void refresh());
</script>

<template>
  <Page title="渠道 OTA">
    <p class="mb-4 text-sm text-gray-500">下载适配本渠道硬件的终端安装包，用于设备重置后重新安装。请核对硬件型号和 ABI 后安装。</p>
    <Tabs v-model:active-key="tab">
      <Tabs.TabPane key="packages" tab="安装包">
        <div v-if="isAdmin" class="mb-4 flex justify-end"><Button v-access:code="'esop:ota:manage'" ref="uploadButton" type="primary" @click="newPackage">上传安装包</Button></div>
        <SelectableTable date-field="created_at" :columns="packageColumns" :data-source="packages" :loading="loading" :pagination="{ pageSize: 20 }" :scroll="{ x: 1200 }" row-key="id">
          <template #bodyCell="{ column, record }">
            <span v-if="column.key === 'channel'">{{ channelNames.get((record as OtaPackage).channel_id) }}</span>
            <span v-else-if="column.key === 'model'">{{ modelNames.get((record as OtaPackage).hardware_model_id) }}</span>
            <Button v-else-if="column.key === 'file_name'" :loading="downloading === (record as OtaPackage).id" type="link" class="!h-auto !whitespace-normal !p-0 !text-left" @click="download(record as OtaPackage)">{{ (record as OtaPackage).file_name || '文件已失效' }}</Button>
            <span v-else-if="column.key === 'abi'">{{ models.find((item) => item.id === (record as OtaPackage).hardware_model_id)?.abi }}</span>
            <span v-else-if="column.key === 'size'">{{ ((record as OtaPackage).file_size / 1024 / 1024).toFixed(1) }} MB</span>
            <Tag v-else-if="column.key === 'status'" :color="(record as OtaPackage).status === 'published' ? 'green' : undefined">{{ { draft: '草稿', published: '已发布', superseded: '已替代' }[(record as OtaPackage).status] }}</Tag>
            <span v-else-if="column.key === 'checksum'" class="font-mono text-xs" :title="(record as OtaPackage).checksum_sha256">{{ (record as OtaPackage).checksum_sha256.slice(0, 16) }}…</span>
            <span v-else-if="column.key === 'published_at'">{{ (record as OtaPackage).published_at ? formatDateTime((record as OtaPackage).published_at || undefined) : '—' }}</span>
            <template v-else-if="column.key === 'action'">
              <Button :loading="downloading === (record as OtaPackage).id" :disabled="!!downloading" type="link" @click="download(record as OtaPackage)">下载</Button>
              <Popconfirm v-if="isAdmin && (record as OtaPackage).status === 'draft'" :title="`发布后将替换 ${modelNames.get((record as OtaPackage).hardware_model_id)} 的当前安装包，确认发布？`" @confirm="publish(record as OtaPackage)">
                <Button v-access:code="'esop:ota:publish'" type="link">发布</Button>
              </Popconfirm>
            </template>
          </template>
        </SelectableTable>
      </Tabs.TabPane>
      <Tabs.TabPane v-if="isAdmin" key="models" tab="硬件型号">
        <div v-if="isAdmin" class="mb-4 flex justify-end"><Button v-access:code="'esop:ota:manage'" type="primary" @click="editModel()">新增型号</Button></div>
        <SelectableTable date-field="created_at" :columns="modelColumns" :data-source="models" :loading="loading" :pagination="false" row-key="id">
          <template #bodyCell="{ column, record }">
            <span v-if="column.key === 'channel'">{{ channelNames.get((record as HardwareModel).channel_id) }}</span>
            <Button v-else-if="column.key === 'action'" v-access:code="'esop:ota:manage'" type="link" @click="editModel(record as HardwareModel)">编辑</Button>
          </template>
        </SelectableTable>
      </Tabs.TabPane>
      <Tabs.TabPane v-if="isAdmin" key="channels" tab="渠道">
        <div v-if="isAdmin" class="mb-4 flex justify-end"><Button v-access:code="'esop:ota:manage'" type="primary" @click="editChannel()">新增渠道</Button></div>
        <SelectableTable date-field="created_at" :columns="channelColumns" :data-source="channels" :loading="loading" :pagination="false" row-key="id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'action'">
              <Dropdown v-if="channelActionCount >= 3" :trigger="['click']"><Button type="link">更多操作</Button><template #overlay><Menu>
                <Menu.Item v-access:code="'esop:ota:manage'" @click="editChannel(record as Channel)">编辑</Menu.Item>
                <Menu.Item v-access:code="'esop:channel:admin'" @click="openChannelAdmin(record as Channel)">关联管理员</Menu.Item>
                <Menu.Item v-access:code="'esop:channel:issue'" @click="openBatch(record as Channel)">批量发密钥</Menu.Item>
                <Menu.Item v-access:code="'esop:channel:issue'" @click="openInventory(record as Channel)">查看库存</Menu.Item>
              </Menu></template></Dropdown>
              <template v-else>
                <Button v-access:code="'esop:ota:manage'" type="link" @click="editChannel(record as Channel)">编辑</Button>
                <Button v-access:code="'esop:channel:admin'" type="link" @click="openChannelAdmin(record as Channel)">关联管理员</Button>
                <Button v-access:code="'esop:channel:issue'" type="link" @click="openBatch(record as Channel)">批量发密钥</Button>
                <Button v-access:code="'esop:channel:issue'" type="link" @click="openInventory(record as Channel)">查看库存</Button>
              </template>
            </template>
          </template>
        </SelectableTable>
      </Tabs.TabPane>
    </Tabs>

    <Drawer :open="channelOpen" :keyboard="true" title="渠道" width="min(480px, 100vw)" @close="channelOpen = false">
      <Form :model="channelForm" layout="vertical"><Form.Item label="编码"><Input v-model:value="channelForm.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item><Form.Item label="名称" required><Input v-model:value="channelForm.name" :maxlength="100" /></Form.Item></Form>
      <template #footer><Button class="mr-2" @click="channelOpen = false">取消</Button><Button :loading="saving" type="primary" @click="submitChannel">保存</Button></template>
    </Drawer>
    <Drawer :open="modelOpen" :keyboard="true" title="硬件型号" width="min(480px, 100vw)" @close="modelOpen = false">
      <Form :model="modelForm" layout="vertical">
        <Form.Item label="渠道" required><Select v-model:value="modelForm.channel_id" :options="channelOptions" placeholder="选择渠道" /></Form.Item>
        <Form.Item label="型号编码"><Input v-model:value="modelForm.code" placeholder="留空自动生成" :maxlength="50" /></Form.Item>
        <Form.Item label="型号名称" required><Input v-model:value="modelForm.name" :maxlength="100" /></Form.Item>
        <Form.Item label="ABI" required><Input v-model:value="modelForm.abi" :maxlength="30" placeholder="如 arm64-v8a" /></Form.Item>
      </Form>
      <template #footer><Button class="mr-2" @click="modelOpen = false">取消</Button><Button :loading="saving" type="primary" @click="submitModel">保存</Button></template>
    </Drawer>
    <Drawer :open="packageOpen" :keyboard="true" title="上传安装包" width="min(520px, 100vw)" @after-open-change="afterPackageOpenChange" @close="packageOpen = false">
      <Form :model="packageForm" layout="vertical">
        <Form.Item label="渠道" required><Select v-model:value="packageForm.channel_id" :options="channelOptions" placeholder="选择渠道" @change="selectPackageChannel" /></Form.Item>
        <Form.Item label="硬件型号" required><Select v-model:value="packageForm.hardware_model_id" :options="modelOptions" placeholder="选择硬件型号" /></Form.Item>
        <Form.Item label="版本名称" required><Input v-model:value="packageForm.version" :maxlength="80" placeholder="如 1.0.1" /></Form.Item>
        <Form.Item label="版本号"><InputNumber v-model:value="packageForm.version_code" :min="0" :precision="0" class="w-full" /></Form.Item>
        <Form.Item label="应用包名"><Input v-model:value="packageForm.package_name" :maxlength="200" placeholder="APK 可填写包名" /></Form.Item>
        <Form.Item label="安装与更新说明"><Input.TextArea v-model:value="packageForm.release_notes" :maxlength="4000" :rows="4" placeholder="填写适用硬件、安装步骤及本版本更新内容" /></Form.Item>
        <Form.Item label="APK / EXE / DEB / AppImage 文件" required><input accept=".apk,.exe,.deb,.AppImage" type="file" @change="selectFile" /><p v-if="fileName" class="mt-2 text-sm">已上传：{{ fileName }}</p></Form.Item>
      </Form>
      <template #footer><Button class="mr-2" @click="packageOpen = false">取消</Button><Button :disabled="!packageForm.file_id" :loading="saving" type="primary" @click="submitPackage">保存草稿</Button></template>
    </Drawer>
    <Modal :open="channelAdminOpen" :keyboard="true" :title="`关联 ${targetChannel?.name || ''} 管理员`" :confirm-loading="saving" ok-text="确认关联" @ok="saveChannelAdmin" @cancel="channelAdminOpen = false">
      <p class="mb-3">选择平台已有用户作为该渠道管理员。</p>
      <Select v-model:value="selectedUser" :options="userOptions" show-search option-filter-prop="label" class="w-full" placeholder="选择用户" />
    </Modal>
    <Modal :open="batchOpen" :keyboard="true" :title="`向 ${targetChannel?.name || ''} 发放密钥`" :confirm-loading="saving" ok-text="确认发放" @ok="issueBatch" @cancel="batchOpen = false">
      <p class="mb-3">每批 100–1000 个。发放后可在“查看库存”中再次查看和导出密钥。</p>
      <Select v-model:value="batchModelId" :options="batchModelOptions" allow-clear class="mb-3 w-full" placeholder="硬件型号（可选）" />
      <InputNumber v-model:value="batchQuantity" :min="100" :max="1000" :precision="0" class="w-full" />
    </Modal>
    <Modal :open="!!issuedBatch" :keyboard="true" title="渠道密钥已发放" :footer="null" width="min(640px, 100vw)" @cancel="closeIssuedBatch">
      <p class="mb-3">本批次 {{ issuedBatch?.keys.length }} 个密钥。可立即下载 CSV，之后也能在渠道库存中查看和导出。</p>
      <div class="mb-4 max-h-48 overflow-auto rounded bg-[var(--vben-bg-color)] p-3 font-mono text-sm">
        <div v-for="item in issuedBatch?.keys" :key="item.id">{{ item.key }}</div>
      </div>
      <div class="flex justify-end gap-2"><Button @click="downloadBatch">下载 CSV</Button><Button type="primary" @click="closeIssuedBatch">关闭</Button></div>
    </Modal>
    <Drawer :open="inventoryOpen" :keyboard="true" :title="`${targetChannel?.name || ''} · 密钥库存`" width="min(960px, 100vw)" @close="inventoryOpen = false">
      <div class="mb-4 flex flex-wrap gap-2">
        <Select v-model:value="inventoryBatchId" :options="inventoryBatchOptions" allow-clear class="min-w-56" placeholder="全部批次" @change="changeInventoryBatch" />
        <DatePicker.RangePicker v-model:value="inventoryCreatedRange" show-time value-format="YYYY-MM-DDTHH:mm:ss" format="YYYY-MM-DD HH:mm:ss" @change="changeInventoryBatch" />
        <Button :disabled="!inventoryBatchId" @click="exportInventory('batch')">导出当前批次</Button>
        <Button :disabled="!inventorySelected.length" @click="exportInventory('selected')">导出所选（{{ inventorySelected.length }}）</Button>
      </div>
      <Table :data-source="inventoryKeys" :loading="inventoryLoading" :pagination="{ current: inventoryPage, pageSize: 20, total: inventoryTotal, showSizeChanger: false }" row-key="id" @change="changeInventoryPage">
        <Table.Column key="select" title="选择" :width="60">
          <template #default="{ record }"><input type="checkbox" :checked="inventorySelected.includes((record as ChannelKey).id)" @change="toggleInventory((record as ChannelKey).id, ($event.target as HTMLInputElement).checked)" /></template>
        </Table.Column>
        <Table.Column key="key" title="密钥" :width="150"><template #default="{ record }"><code>{{ (record as ChannelKey).key || '不可回读' }}</code></template></Table.Column>
        <Table.Column key="batch" title="批次" :width="120"><template #default="{ record }"><span :title="(record as ChannelKey).batch_id || undefined">{{ (record as ChannelKey).batch_id?.slice(0, 8) || '旧密钥' }}</span></template></Table.Column>
        <Table.Column key="status" title="状态" :width="95"><template #default="{ record }"><Tag>{{ { unassigned: '可分配', assigned: '已分配', activated: '已激活' }[(record as ChannelKey).status] }}</Tag></template></Table.Column>
        <Table.Column data-index="tenant_id" title="客户租户" />
        <Table.Column data-index="used_at" title="激活时间" :width="185"><template #default="{ record }">{{ (record as ChannelKey).used_at ? formatDateTime((record as ChannelKey).used_at || undefined) : '—' }}</template></Table.Column>
      </Table>
      <template #footer><Button @click="inventoryOpen = false">关闭</Button></template>
    </Drawer>
  </Page>
</template>
