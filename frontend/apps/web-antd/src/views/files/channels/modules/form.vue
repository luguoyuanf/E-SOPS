<script lang="ts" setup>
import type {
  FileStorageChannelCreatePayload,
  FileStorageChannelRecord,
  FileStorageChannelUpdatePayload,
} from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import {
  createFileStorageChannelApi,
  getFileStorageChannelApi,
  updateFileStorageChannelApi,
} from '#/api';

import { useFormSchema } from '../data';

const emits = defineEmits<{ success: [] }>();

const channelId = ref<string>();
let loadVersion = 0;

const [Form, formApi] = useVbenForm({
  schema: useFormSchema(),
  showDefaultActions: false,
});

const [Drawer, drawerApi] = useVbenDrawer({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) return;

    const values = await formApi.getValues();
    const payload = {
      access_key_id: values.access_key_id || undefined,
      addressing_style: values.addressing_style || 'auto',
      auto_create_bucket: values.auto_create_bucket ?? false,
      bucket: values.bucket || undefined,
      code: values.code?.trim() || undefined,
      endpoint_url: values.endpoint_url || undefined,
      is_active: values.is_active ?? true,
      is_default: values.is_default ?? false,
      name: values.name,
      object_prefix: values.object_prefix || undefined,
      provider: values.provider || 'local',
      region: values.region || undefined,
      remark: values.remark || undefined,
      secret_access_key:
        values.secret_access_key && values.secret_access_key !== '******'
          ? values.secret_access_key
          : undefined,
    };

    drawerApi.lock();
    try {
      if (channelId.value) {
        await updateFileStorageChannelApi(
          channelId.value,
          payload as FileStorageChannelUpdatePayload,
        );
      } else {
        await createFileStorageChannelApi(
          payload as FileStorageChannelCreatePayload,
        );
      }
      emits('success');
      drawerApi.close();
    } catch {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    const version = ++loadVersion;
    drawerApi.setState({ loading: false });
    formApi.resetForm();
    channelId.value = undefined;
    if (!isOpen) return;

    const data = drawerApi.getData<FileStorageChannelRecord>();
    channelId.value = data?.id;
    if (!data?.id) return;

    drawerApi.setState({ loading: true });
    try {
      const channel = await getFileStorageChannelApi(data.id);
      if (version === loadVersion) {
        formApi.setValues(channel);
      }
    } finally {
      if (version === loadVersion) {
        drawerApi.setState({ loading: false });
      }
    }
  },
});

const drawerTitle = computed(() =>
  channelId.value ? '编辑存储渠道' : '新增存储渠道',
);
</script>

<template>
  <Drawer :title="drawerTitle" class="w-[680px]">
    <Form />
  </Drawer>
</template>
