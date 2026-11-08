<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';
import { $t } from '@vben/locales';
import { LanguageToggle, ThemeToggle } from '@vben/layouts';
import esopsLogo from '#/assets/esops-logo.png';

const activeStep = ref(1);
const route = useRoute();
const activeSection = computed(() => route.hash.slice(1));
const steps = [1, 2, 3, 4];
</script>

<template>
  <div class="product-home">
    <header class="home-header">
      <RouterLink to="/" aria-label="ESOPS" class="brand"><img :src="esopsLogo" alt="ESOPS" /></RouterLink>
      <nav :aria-label="$t('authentication.home.home')">
        <RouterLink :to="{ hash: '#workflow' }" :class="{ active: activeSection === 'workflow' }" :aria-current="activeSection === 'workflow' ? 'location' : undefined">{{ $t('authentication.home.workflow') }}</RouterLink>
        <RouterLink :to="{ hash: '#capabilities' }" :class="{ active: activeSection === 'capabilities' }" :aria-current="activeSection === 'capabilities' ? 'location' : undefined">{{ $t('authentication.home.features') }}</RouterLink>
      </nav>
      <div class="header-actions"><LanguageToggle /><ThemeToggle /><RouterLink to="/auth/login" class="login-link">{{ $t('authentication.home.login') }} ↗</RouterLink></div>
    </header>
    <main>
      <section class="hero page-width">
        <div class="hero-copy">
          <p class="product-name">ESOPS · {{ $t('authentication.esops.product') }}</p>
          <h1>{{ $t('authentication.home.headline') }}</h1>
          <p class="hero-description">{{ $t('authentication.home.intro') }}</p>
          <div class="hero-actions"><RouterLink to="/auth/register" class="primary-link">{{ $t('authentication.home.register') }} <span aria-hidden="true">↗</span></RouterLink><a href="#workflow">{{ $t('authentication.home.explore') }} ↓</a></div>
        </div>
        <div class="workflow-preview" data-ui>
          <div class="preview-heading"><span>ESOPS</span><span>{{ $t('authentication.home.preview') }}</span></div>
          <div class="workflow-path" aria-hidden="true"><span v-for="step in steps" :key="step" :class="{ current: activeStep === step }">{{ $t(`authentication.home.step${step}`) }}</span></div>
          <div class="preview-document">
            <span class="document-label">{{ $t(`authentication.home.object${activeStep}`) }}</span>
            <h2>{{ $t(`authentication.home.step${activeStep}`) }}</h2>
            <p>{{ $t(`authentication.home.desc${activeStep}`) }}</p>
          </div>
          <div class="preview-tabs" :aria-label="$t('authentication.home.workflow')">
            <button v-for="step in steps" :key="step" type="button" :aria-pressed="activeStep === step" :class="{ selected: activeStep === step }" @click="activeStep = step">{{ $t(`authentication.home.step${step}`) }}</button>
          </div>
        </div>
      </section>
      <section id="workflow" class="workflow-section">
        <div class="page-width workflow-layout">
          <div><h2>{{ $t('authentication.home.flowTitle') }}</h2><p>{{ $t('authentication.home.flowIntro') }}</p></div>
          <div class="workflow-list">
            <button v-for="step in steps" :key="step" type="button" :aria-expanded="activeStep === step" @click="activeStep = step">
              <span class="step-heading">{{ $t(`authentication.home.step${step}`) }}<span aria-hidden="true">{{ activeStep === step ? '−' : '+' }}</span></span>
              <span v-if="activeStep === step" class="step-description">{{ $t(`authentication.home.desc${step}`) }}</span>
            </button>
          </div>
        </div>
      </section>
      <section id="capabilities" class="page-width capabilities">
        <h2>{{ $t('authentication.home.capTitle') }}</h2>
        <div v-for="item in [1, 2, 3]" :key="item" class="capability"><h3>{{ $t(`authentication.home.cap${item}`) }}</h3><p>{{ $t(`authentication.home.capDesc${item}`) }}</p></div>
      </section>
      <section class="cta-section"><div class="page-width cta-layout"><div><h2>{{ $t('authentication.home.ctaTitle') }}</h2><p>{{ $t('authentication.home.ctaDesc') }}</p><p class="sms-notice">{{ $t('authentication.home.smsNotice') }}</p></div><RouterLink class="primary-link" to="/auth/register">{{ $t('authentication.home.register') }} ↗</RouterLink></div></section>
    </main>
    <footer class="page-width home-footer"><span>© {{ new Date().getFullYear() }} ESOPS</span><span>{{ $t('authentication.home.footer') }}</span><nav :aria-label="$t('authentication.home.privacyLabel')" class="footer-legal"><a href="/privacy">{{ $t('authentication.home.privacyLabel') }}</a><a href="/terms">{{ $t('authentication.home.termsLabel') }}</a></nav><RouterLink to="/auth/login">{{ $t('authentication.home.login') }} ↗</RouterLink></footer>
  </div>
</template>

<style scoped>
.product-home { --home-ground: #f1f6f1; --home-panel: #fff; --home-ink: #172b24; --home-muted: #52665a; --home-accent: #047857; min-height: 100dvh; color: var(--home-ink); background: var(--home-ground); font-size: 16px; line-height: 1.7; }
.page-width { width: min(1280px, 90%); margin-inline: auto; }
.home-header { position: sticky; top: 0; z-index: 30; display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 17px 5%; background: var(--home-panel); }
.brand { width: 172px; height: 50px; overflow: hidden; position: relative; flex-shrink: 0; }
.brand img { position: absolute; width: 214px; max-width: none; top: -20px; left: -20px; }
.home-header nav a { padding: 8px 12px; border-radius: 6px; }
.home-header nav a.active { color: var(--home-accent); background: var(--home-ground); font-weight: 600; }
#workflow, #capabilities { scroll-margin-top: 110px; }
.home-header nav, .header-actions { display: flex; align-items: center; gap: 28px; }
.header-actions { gap: 12px; }.login-link { margin-left: 12px; font-weight: 600; }
a { color: inherit; }
a, button { transition: color .15s, background-color .15s; }a:hover { color: var(--home-accent); }a:focus-visible, button:focus-visible { outline: 2px solid var(--home-accent); outline-offset: 5px; }
.hero { display: grid; grid-template-columns: 1fr 1fr; align-items: center; gap: 64px; padding-block: 96px 110px; }
.product-name { color: var(--home-accent); margin-bottom: 24px; font-weight: 600; }
h1 { font-size: clamp(36px, 3.5vw, 56px); font-weight: 650; line-height: 1.3; letter-spacing: -.035em; max-width: 620px; text-wrap: balance; }
.hero-description { margin-top: 28px; max-width: 470px; color: var(--home-muted); font-size: 18px; }.hero-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 28px; margin-top: 36px; }
.primary-link { display: inline-flex; align-items: center; justify-content: space-between; gap: 32px; padding: 13px 24px; background: var(--home-accent); color: #fff; border-radius: 6px; font-weight: 600; white-space: nowrap; }.primary-link:hover { background: #065f46; color: #fff; }
.workflow-preview { min-width: 0; background: var(--home-panel); border-radius: 16px; padding: 28px; }.preview-heading { display: flex; justify-content: space-between; gap: 16px; color: var(--home-muted); font-size: 14px; }.preview-heading > :first-child { font-weight: 750; font-size: 20px; color: var(--home-ink); }
.workflow-path { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-block: 24px; font-size: 12px; color: var(--home-muted); }.workflow-path span { flex: 1; padding-top: 12px; border-top: 3px solid #e2eae4; }.workflow-path .current { border-color: var(--home-accent); color: var(--home-accent); }
.preview-document { padding: 28px; min-height: 250px; border: 1px solid #e1e9e3; border-radius: 6px; }.document-label { font-size: 13px; color: var(--home-muted); }.preview-document h2 { font-size: 28px; margin-top: 18px; }.preview-document p { margin-top: 16px; color: var(--home-muted); }.preview-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 20px; }.preview-tabs button { flex: 1; padding: 10px 6px; border-radius: 4px; font-size: 13px; white-space: nowrap; }.preview-tabs .selected { background: var(--home-ground); color: var(--home-accent); font-weight: 600; }
h2 { font-size: clamp(26px, 2.4vw, 36px); font-weight: 600; line-height: 1.4; text-wrap: balance; }.workflow-section { padding-block: 90px; background: var(--home-panel); }.workflow-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 100px; }.workflow-layout > div > p { margin-top: 24px; color: var(--home-muted); }.workflow-list button { display: block; text-align: left; width: 100%; padding: 22px 0; }.workflow-list button:first-child { padding-top: 0; }.step-heading { display: flex; justify-content: space-between; font-size: 20px; font-weight: 600; gap: 24px; }.step-description { display: block; color: var(--home-muted); padding-top: 16px; }
.capabilities { padding-block: 100px; }.capabilities > h2 { margin-bottom: 48px; }.capability { display: grid; grid-template-columns: 1fr 1fr; gap: 100px; margin-top: 32px; }.capability h3 { font-size: 22px; font-weight: 600; }.capability p { color: var(--home-muted); }
.cta-section { background: #e2eee5; padding-block: 72px; }.cta-layout { display: flex; align-items: center; justify-content: space-between; gap: 48px; }.cta-layout p { margin-top: 18px; max-width: 680px; }.cta-layout .sms-notice { color: var(--home-muted); font-size: 14px; }.footer-legal { display: flex; gap: 24px; flex-wrap: wrap; }.home-footer { display: flex; justify-content: space-between; gap: 24px; padding-block: 28px; font-size: 13px; color: var(--home-muted); }
.dark .product-home { --home-ground: #141d18; --home-panel: #1e2924; --home-ink: #e5eee8; --home-muted: #afbeb4; --home-accent: #34d399; }.dark .primary-link { background: #047857; }.dark .cta-section { background: #25372d; }.dark .brand { background: white; border-radius: 6px; }.dark .workflow-list button, .dark .preview-document { border-color: #3b4d41; }
@media (max-width: 1000px) { .hero { gap: 32px; padding-block: 64px; }.workflow-layout, .capability { gap: 40px; }.home-header nav { display: none; }.workflow-preview { padding: 20px; }.preview-document { padding: 20px; }.workflow-path { display: none; }.preview-document { margin-top: 20px; } }
@media (max-width: 700px) { .hero, .workflow-layout, .capability { grid-template-columns: 1fr; gap: 32px; }.hero { padding-block: 48px 56px; }.hero-description { font-size: 16px; }h1 { font-size: 36px; }.home-header { gap: 12px; }.brand { width: 130px; height: 40px; }.brand img { width: 166px; left: -16px; top: -16px; }.header-actions { gap: 2px; }.login-link { font-size: 14px; margin-left: 4px; }.workflow-section, .capabilities { padding-block: 56px; }.capability { gap: 8px; }.capabilities > h2 { margin-bottom: 32px; }.cta-layout { flex-direction: column; align-items: flex-start; gap: 28px; }.cta-section { padding-block: 48px; }.home-footer { flex-wrap: wrap; gap: 12px 24px; }.home-footer > :nth-child(2) { width: 100%; order: 3; }.preview-document { min-height: 240px; }.hero-actions { gap: 20px; } }
</style>
