<script lang="ts" setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { $t } from '@vben/locales';
import esopsLogo from '#/assets/esops-logo.png';
import { buildManifest } from '#/modules/build-manifest';

import { AuthPageLayout, LanguageToggle, ThemeToggle } from '@vben/layouts';
import { preferences } from '@vben/preferences';

const route = useRoute();
const esopsLogin = computed(() => buildManifest.edition === 'esop' && ['/auth/login', '/auth/register', '/auth/forget-password', '/downloads'].includes(route.path));

const appName = computed(() => preferences.app.name);
const logo = computed(() => preferences.logo.source);
const logoDark = computed(() => preferences.logo.sourceDark);
</script>

<template>
  <div v-if="esopsLogin" class="esops-auth">
    <header class="esops-auth-header">
      <div class="esops-auth-brand">
        <a href="/" class="esops-logo"><img :src="esopsLogo" alt="ESOPS" /></a>
        <span class="esops-auth-product">{{ $t('authentication.esops.product') }}</span>
      </div>
      <div class="esops-auth-tools"><a href="/" class="esops-home-link">{{ $t('authentication.home.home') }}</a><LanguageToggle /><ThemeToggle /></div>
    </header>
    <main class="esops-auth-content">
      <section class="esops-auth-introduction">
        <p class="esops-auth-note">{{ $t('authentication.esops.note') }}</p>
        <div class="esops-auth-message">
          <span class="esops-logo esops-logo-large"><img :src="esopsLogo" alt="ESOPS" /></span>
          <h2>{{ $t('authentication.esops.headingOne') }}<br />{{ $t('authentication.esops.headingTwo') }}</h2>
          <p>{{ $t('authentication.esops.description') }}</p>
        </div>
        <p class="esops-auth-tagline">{{ $t('authentication.esops.tagline') }}</p>
      </section>
      <section class="esops-auth-form"><RouterView /></section>
    </main>
    <footer class="esops-auth-footer">Copyright © {{ new Date().getFullYear() }} ESOPS · <a href="mailto:support@esops.cc">support@esops.cc</a></footer>
  </div>
  <AuthPageLayout v-else
    :app-name="appName"
    :logo="logo"
    :logo-dark="logoDark"
    :page-description="`${appName} 项目管理系统`"
    page-title="欢迎使用"
  >
    <template #copyright>
      <div class="flex flex-col items-center gap-1">
        <span>Copyright © {{ new Date().getFullYear() }} {{ appName }}</span>
      </div>
    </template>
  </AuthPageLayout>
</template>

<style scoped>
.esops-auth {
  --primary: 160 84% 31%;
  --primary-foreground: 0 0% 100%;
  --ring: 160 84% 31%;
  --login-ink: #172230;
  --login-muted: #78827e;
  --login-panel: #fff;
  min-height: 100dvh;
  color: var(--login-ink);
  background: #f1f6f1;
}
.esops-auth-header { min-height: 88px; padding: 12px 3%; display: flex; align-items: center; justify-content: space-between; gap: 16px; background: var(--login-panel); }
.esops-auth-brand { display: flex; align-items: center; gap: 24px; min-width: 0; }
.esops-auth-product { font-size: 18px; font-weight: 600; }
.esops-home-link { color: var(--login-ink); font-size: 14px; white-space: nowrap; }
.esops-auth-tools { display: flex; align-items: center; gap: 16px; }
.esops-logo { display: inline-block; width: 190px; height: 54px; position: relative; overflow: hidden; flex-shrink: 0; }
.esops-logo img { width: 232px; max-width: none; position: absolute; top: -21px; left: -21px; }
.esops-auth-content { display: grid; grid-template-columns: minmax(0, 7fr) minmax(390px, 5fr); gap: 24px; width: min(1400px, 94%); margin: 36px auto 0; }
.esops-auth-introduction { padding: 40px; border-radius: 16px; background: linear-gradient(135deg, #f7f4ee, #ecfdf5, #f4f1eb); display: flex; flex-direction: column; justify-content: space-between; min-height: 640px; }
.esops-auth-note { font-size: 16px; color: var(--login-muted); }
.esops-auth-message { margin: 44px 0; }
.esops-logo-large { width: min(380px, 100%); height: 110px; }
.esops-logo-large img { width: 466px; top: -43px; left: -42px; }
.esops-auth-message h2 { margin: 40px 0 22px; font-size: clamp(28px, 3vw, 46px); font-weight: 700; line-height: 1.45; letter-spacing: -.8px; }
.esops-auth-message p { font-size: 18px; line-height: 1.8; color: var(--login-muted); max-width: 470px; }
.esops-auth-tagline { font-size: 16px; color: #047857; font-weight: 600; }
.esops-auth-form { border-radius: 16px; background: var(--login-panel); padding: 46px 40px 36px; display: flex; align-items: center; }
.esops-auth-footer { padding: 26px 20px; color: var(--login-muted); font-size: 12px; text-align: center; }
.dark .esops-auth { --login-ink: #e5eee8; --login-muted: #a6b3ab; --login-panel: #1e2924; background: #141d18; }
.dark .esops-auth-introduction { background: #25372d; }
.dark .esops-auth-tagline { color: #6ee7b7; }
.dark .esops-logo { background: #fff; border-radius: 8px; }
@media (min-width: 1600px) { .esops-auth-content { margin-top: 44px; } .esops-auth-form { padding: 52px; } }
@media (max-width: 999px) { .esops-auth-content { display: block; max-width: 560px; margin-top: 28px; } .esops-auth-introduction { display: none; } .esops-auth-form { padding: 36px; } }
@media (max-width: 600px) { .esops-auth-header { padding: 12px 18px; min-height: 76px; } .esops-auth-product { display: none; } .esops-logo { width: 154px; height: 44px; } .esops-logo img { width: 188px; left: -17px; top: -17px; } .esops-auth-tools { gap: 4px; } .esops-auth-form { padding: 30px 22px; } .esops-auth-content { width: calc(100% - 28px); margin-top: 20px; } }
</style>
