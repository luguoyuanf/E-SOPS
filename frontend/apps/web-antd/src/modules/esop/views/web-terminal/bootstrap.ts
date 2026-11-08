import { createApp } from 'vue';
import WebTerminal from './index.vue';
import './terminal-reset.css';

export function bootstrap() {
  document.title = 'ESOPS Web终端';
  createApp(WebTerminal).mount('#app');
}
