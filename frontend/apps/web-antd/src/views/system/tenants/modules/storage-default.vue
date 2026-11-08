<script lang="ts" setup>
import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert, message } from 'ant-design-vue';

import { useVbenForm, z } from '#/adapter/form';
import { getStorageDefault, saveStorageDefault } from '#/api/core/tenant-storage';
import { $t } from '#/locales';

const loaded = ref(false);
const [Form, formApi] = useVbenForm({
  showDefaultActions: false,
  schema: [{
    component: 'InputNumber',
    componentProps: { min: 0, precision: 0, class: 'w-full' },
    fieldName: 'capacity_mib',
    label: $t('system.tenant.storageDefaultCapacity'),
    rules: z.number().int().min(0).max(8589934591),
  }],
});
const [Drawer, drawerApi] = useVbenDrawer({
  async onConfirm() {
    if (!loaded.value) return;
    const { valid } = await formApi.validate();
    if (!valid) return;
    drawerApi.lock();
    try {
      const values = await formApi.getValues();
      await saveStorageDefault({ capacity_mib: values.capacity_mib });
      message.success($t('system.common.success'));
      drawerApi.close();
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    loaded.value = false;
    formApi.resetForm();
    drawerApi.lock();
    try {
      formApi.setValues(await getStorageDefault());
      loaded.value = true;
    } finally {
      drawerApi.unlock();
    }
  },
});
</script>

<template>
  <Drawer :title="$t('system.tenant.storageDefault')" :confirm-disabled="!loaded" class="w-[min(520px,100vw)]">
    <Alert class="mb-5" type="info" show-icon :message="$t('system.tenant.storageDefaultHint')" />
    <Form />
  </Drawer>
</template>
