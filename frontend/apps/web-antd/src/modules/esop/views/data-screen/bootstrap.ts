import { createApp } from 'vue';
import DataScreen from './index.vue';
import './standalone.css';

export function bootstrap() {
  document.title = 'ESOPS 数据大屏';
  const referrer = document.createElement('meta');
  referrer.name = 'referrer';
  referrer.content = 'no-referrer';
  document.head.append(referrer);
  const key = new URLSearchParams(window.location.hash.slice(1)).get('key') ?? '';
  createApp(DataScreen, { accessKey: key }).mount('#app');
}
