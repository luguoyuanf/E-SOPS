import { translate, translateCaptcha } from './translate';
import { createApp, h, nextTick, ref } from 'vue';

import Verification from '../../../packages/effects/common-ui/src/components/captcha/verification/index.vue';

export type VerificationHandle = Pick<InstanceType<typeof Verification>, 'onClose' | 'show'>;

export async function mountVerification(callbacks: {
  getCaptchaApi: (data: unknown) => Promise<unknown>;
  checkCaptchaApi: (data: unknown) => Promise<unknown>;
  onOnSuccess: (data: { captchaVerification: string }) => Promise<void>;
  onOnClose: () => void;
  onOnError: () => void;
}): Promise<VerificationHandle> {
  const verification = ref<InstanceType<typeof Verification>>();
  createApp({
    setup: () => () => h(Verification, {
      ...callbacks,
      ref: verification,
      brandLogo: '/logo.png',
      explain: translate('请按住滑块拖动'),
      mode: 'pop',
    }),
  }).mount('#verification');
  translateCaptcha(document.getElementById('verification')!);
  await nextTick();
  return verification.value!;
}
