<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';

import { $t } from '@vben/locales';

import { useVbenModal } from '@vben-core/popup-ui';

interface Props {
  // 轮询时间，分钟
  checkUpdatesInterval?: number;
  // 检查更新的地址
  checkUpdateUrl?: string;
}

defineOptions({ name: 'CheckUpdates' });

const props = withDefaults(defineProps<Props>(), {
  checkUpdatesInterval: 1,
  checkUpdateUrl: import.meta.env.BASE_URL || '/',
});

const loadedReleaseId = document
  .querySelector<HTMLMetaElement>('meta[name="web-release-id"]')
  ?.content;
let isCheckingUpdates = false;
const currentVersionTag = ref('');
const lastVersionTag = ref(loadedReleaseId || '');
const timer = ref<ReturnType<typeof setInterval>>();

const [UpdateNoticeModal, modalApi] = useVbenModal({
  closable: false,
  closeOnClickModal: false,
  onConfirm() {
    lastVersionTag.value = currentVersionTag.value;
    window.location.reload();
    // handleSubmitLogout();
  },
});

async function getVersionTag() {
  try {
    if (import.meta.env.DEV && !loadedReleaseId) return null;
    if (loadedReleaseId) {
      const response = await fetch(
        `${import.meta.env.BASE_URL}index.html`,
        { cache: 'no-store' },
      );
      if (!response.ok) return null;
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      return html.querySelector<HTMLMetaElement>('meta[name="web-release-id"]')?.content || null;
    }
    const response = await fetch(props.checkUpdateUrl, {
      cache: 'no-store',
      method: 'HEAD',
      redirect: 'manual',
    });

    if (!response.ok) return null;
    return (
      response.headers.get('etag') || response.headers.get('last-modified')
    );
  } catch {
    console.error('Failed to fetch version tag');
    return null;
  }
}

async function checkForUpdates() {
  if (isCheckingUpdates) return;
  isCheckingUpdates = true;
  try {
    const versionTag = await getVersionTag();
    if (!versionTag) return;

    if (!lastVersionTag.value) {
      lastVersionTag.value = versionTag;
    } else if (lastVersionTag.value !== versionTag) {
      stop();
      handleNotice(versionTag);
    }
  } finally {
    isCheckingUpdates = false;
  }
}
function handleNotice(versionTag: string) {
  currentVersionTag.value = versionTag;
  modalApi.open();
}

function start() {
  if (props.checkUpdatesInterval <= 0 || timer.value || currentVersionTag.value) {
    return;
  }

  // 每 checkUpdatesInterval(默认值为1) 分钟检查一次
  timer.value = setInterval(
    checkForUpdates,
    props.checkUpdatesInterval * 60 * 1000,
  );
}

function handleVisibilitychange() {
  if (document.hidden) {
    stop();
  } else {
    checkForUpdates().finally(start);
  }
}

function stop() {
  clearInterval(timer.value);
  timer.value = undefined;
}

onMounted(() => {
  checkForUpdates();
  start();
  document.addEventListener('visibilitychange', handleVisibilitychange);
});

onUnmounted(() => {
  stop();
  document.removeEventListener('visibilitychange', handleVisibilitychange);
});
</script>
<template>
  <UpdateNoticeModal
    :cancel-text="$t('common.cancel')"
    :confirm-text="$t('common.refresh')"
    :fullscreen-button="false"
    :title="$t('ui.widgets.checkUpdatesTitle')"
    centered
    content-class="px-8 min-h-10"
    footer-class="border-none mb-3 mr-3"
    header-class="border-none"
  >
    {{ $t('ui.widgets.checkUpdatesDescription') }}
  </UpdateNoticeModal>
</template>
