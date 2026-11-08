<script lang="ts" setup>
import type { UserCreatePayload, UserRecord, UserUpdatePayload } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';
import { Avatar, Button, message, Upload } from 'ant-design-vue';

import {
  createUserApi,
  getUserPostsApi,
  getUserRolesApi,
  updateUserApi,
  uploadUserAvatarApi,
  updateUserPostsApi,
  updateUserRolesApi,
} from '#/api';

import { useVbenForm } from '#/adapter/form';

import { useFormSchema } from '../data';
import { userPayloadForActor } from '../payload';

const emits = defineEmits<{ success: [] }>();

const userStore = useUserStore();
const ready = ref(false);
const avatarFile = ref<File>();
const avatarPreview = ref('');
let avatarObjectUrl: string | undefined;
function chooseAvatar(file: File) {
  if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)) {
    message.warning('请选择 JPG、PNG、GIF 或 WebP 图片');
    return Upload.LIST_IGNORE;
  }
  if (avatarObjectUrl) URL.revokeObjectURL(avatarObjectUrl);
  avatarFile.value = file;
  avatarObjectUrl = URL.createObjectURL(file);
  avatarPreview.value = avatarObjectUrl;
  return false;
}
let loadVersion = 0;
const userId = ref<string>();
const isPlatformActor = ref(false);
const targetTenantId = ref<string>();

const [Form, formApi] = useVbenForm({
  schema: [],
  showDefaultActions: false,
});

const [Drawer, drawerApi] = useVbenDrawer({
  async onConfirm() {
    if (!ready.value) return;
    const { valid } = await formApi.validate();
    if (!valid) return;

    const values = await formApi.getValues();
    delete values.id;
    const {
      password,
      post_ids: postIds = [],
      role_ids: roleIds = [],
      ...payload
    } = values;
    const userPayload = userPayloadForActor({
      ...(payload as UserCreatePayload),
      username: payload.username?.trim(),
      email: payload.email?.trim() || null,
      hire_date: payload.hire_date || null,
      mobile: payload.mobile?.trim() || null,
    }, isPlatformActor.value) as UserCreatePayload;

    if (!userId.value && !password) {
      return;
    }

    drawerApi.lock();
    try {
      if (userId.value) {
        delete userPayload.username;
        await updateUserApi(userId.value, {
          ...userPayload,
          ...(password ? { password } : {}),
        } as UserUpdatePayload, targetTenantId.value);
        await updateUserRolesApi(userId.value, { role_ids: roleIds }, targetTenantId.value);
        await updateUserPostsApi(userId.value, { post_ids: postIds }, targetTenantId.value);
      } else {
        const user = await createUserApi({
          ...userPayload,
          password,
        });
        userId.value = user.id;
        targetTenantId.value = user.tenant_id ?? undefined;
        if (roleIds.length > 0) {
          await updateUserRolesApi(user.id, { role_ids: roleIds });
        }
        if (postIds.length > 0) {
          await updateUserPostsApi(user.id, { post_ids: postIds });
        }
      }
      if (avatarFile.value && userId.value) {
        await uploadUserAvatarApi(userId.value, avatarFile.value, targetTenantId.value);
      }
      emits('success');
      drawerApi.close();
    } catch {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    const version = ++loadVersion;
    ready.value = false;
    if (avatarObjectUrl) URL.revokeObjectURL(avatarObjectUrl);
    avatarObjectUrl = undefined;
    avatarFile.value = undefined;
    avatarPreview.value = '';
    if (!isOpen) return;

    const data = drawerApi.getData<UserRecord>();
    formApi.resetForm();
    userId.value = data?.id;
    avatarPreview.value = data?.avatar_url || '';
    targetTenantId.value = data?.tenant_id ?? undefined;
    isPlatformActor.value = userStore.userInfo?.roles?.includes('super') === true;
    drawerApi.setState({ confirmLoading: true });
    formApi.setState({
      schema: useFormSchema(!!data?.id, isPlatformActor.value, targetTenantId.value),
    });
    if (data?.id) {
      // Show the existing row immediately; only relationship fields await requests.
      formApi.setValues({
        ...data,
        department_id: data.department_id || undefined,
        username: data.username || data.email || '',
        email: data.email || '',
        password: '',
      });
    }
    try {
      if (data?.id) {
        const [userRoles, userPosts] = await Promise.all([
          getUserRolesApi(data.id, targetTenantId.value),
          getUserPostsApi(data.id, targetTenantId.value),
        ]);
        if (version !== loadVersion) return;
        formApi.setValues({
          post_ids: userPosts.map((post) => post.id),
          role_ids: userRoles.map((role) => role.id),
        });
      }
      ready.value = true;
    } catch {
      // The request client reports the failure; keep saving disabled.
      return;
    } finally {
      if (version === loadVersion) drawerApi.setState({ confirmLoading: false });
    }
  },
});

const drawerTitle = computed(() =>
  userId.value ? '编辑用户' : '新增用户',
);
</script>

<template>
  <Drawer :title="drawerTitle">
    <div class="mb-4 flex items-center gap-3">
      <Avatar :src="avatarPreview || undefined" :size="72" shape="square">头像</Avatar>
      <Upload accept="image/jpeg,image/png,image/gif,image/webp" :show-upload-list="false" :before-upload="chooseAvatar" :disabled="!ready">
        <Button :disabled="!ready">选择员工照片</Button>
      </Upload>
    </div>
    <Form />
  </Drawer>
</template>
