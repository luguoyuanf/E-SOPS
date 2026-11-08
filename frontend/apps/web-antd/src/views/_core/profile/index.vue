<script setup lang="ts">
import type { AuthApi } from '#/api';

import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Card, Tabs, message } from 'ant-design-vue';

import { getCurrentUserApi, getGoogleBindingApi } from '#/api';

import ProfileBase from './base-setting.vue';
import ProfileUser from './modules/profile-user.vue';
import ProfilePasswordSetting from './password-setting.vue';
import ProfileSecuritySetting from './security-setting.vue';

const activeName = ref('basic');
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const profile = ref<AuthApi.FastApiUser>();

async function loadProfile() {
  loading.value = true;
  try {
    profile.value = await getCurrentUserApi();
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const result = route.query.google_binding;
  if (result === 'success' || result === 'error') {
    activeName.value = 'security';
    if (result === 'success') {
      try {
        const binding = await getGoogleBindingApi();
        if (binding.eligible && binding.bound) message.success('Google 账号绑定成功');
        else message.error('未查到 Google 绑定记录，请重试');
      } catch {
        message.error('无法确认 Google 绑定状态，请在安全设置中重试');
      }
    } else message.error('Google 账号绑定失败，请检查账号是否已绑定其他企业');
    const query = { ...route.query };
    delete query.google_binding;
    void router.replace({ query });
  }
  void loadProfile();
});
</script>

<template>
  <Page auto-content-height>
    <div
      class="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(400px,2fr)_minmax(0,3fr)]"
    >
      <Card class="h-full" :loading="loading" title="个人中心">
        <ProfileUser :profile="profile" @success="loadProfile" />
      </Card>

      <Card class="min-w-0" :loading="loading">
        <Tabs v-model:active-key="activeName" class="-mt-4">
          <Tabs.TabPane key="basic" tab="基本设置">
            <ProfileBase :profile="profile" @success="loadProfile" />
          </Tabs.TabPane>
          <Tabs.TabPane key="password" tab="修改密码">
            <ProfilePasswordSetting />
          </Tabs.TabPane>
          <Tabs.TabPane key="security" force-render tab="安全设置">
            <ProfileSecuritySetting />
          </Tabs.TabPane>
        </Tabs>
      </Card>
    </div>
  </Page>
</template>
