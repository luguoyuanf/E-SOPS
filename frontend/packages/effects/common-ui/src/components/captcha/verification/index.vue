<script setup lang="ts">
import type { VerificationProps } from './typing';

import { nextTick, ref } from 'vue';

import VerifySlide from './verify-slide.vue';

import './verify.css';

defineOptions({ name: 'Verification' });

const props = withDefaults(defineProps<VerificationProps>(), {
  barSize: () => ({ height: '42px', width: '400px' }),
  captchaType: 'blockPuzzle',
  explain: '',
  imgSize: () => ({ height: '200px', width: '400px' }),
  mode: 'fixed',
});

const emit = defineEmits<{
  onClose: [];
  onError: [unknown];
  onReady: [unknown];
  onSuccess: [data: { captchaVerification: string }];
}>();

const showBox = ref(false);
const maskRef = ref<HTMLDialogElement>();
const slideRef = ref<InstanceType<typeof VerifySlide>>();

function show() {
  showBox.value = true;
  void nextTick(() => maskRef.value?.showModal());
  slideRef.value?.refresh();
}

function onClose() {
  maskRef.value?.close();
  showBox.value = false;
  emit('onClose');
}

function onSuccess(data: { captchaVerification: string }) {
  emit('onSuccess', data);
}

defineExpose({ onClose, show, refresh: () => slideRef.value?.refresh() });
</script>

<template>
  <dialog v-if="showBox" ref="maskRef" class="verify-mask" :class="{ 'verify-esops': props.brandLogo }" aria-label="安全验证" @cancel.prevent="onClose" @click.self="onClose">
    <div class="verifybox">
      <div class="verifybox-top">
        <img v-if="props.brandLogo" class="verify-brand-logo" :src="props.brandLogo" alt="ESOPS" />
        <span>{{ props.brandLogo ? '安全验证' : '滑动验证' }}</span>
        <button type="button" class="verifybox-close" aria-label="关闭" @click="onClose">×</button>
      </div>
      <div class="verifybox-bottom">
        <p v-if="props.brandLogo" class="verify-brand-hint">拖动滑块，将拼图移至缺口处</p>
        <VerifySlide
          ref="slideRef"
          :bar-size="props.barSize"
          :captcha-type="props.captchaType"
          :check-captcha-api="props.checkCaptchaApi"
          :explain="props.explain"
          :get-captcha-api="props.getCaptchaApi"
          :img-size="props.imgSize"
          @on-error="(error) => emit('onError', error)"
          @on-ready="(ready) => emit('onReady', ready)"
          @on-success="onSuccess"
        />
      </div>
    </div>
  </dialog>
</template>
