import { fileURLToPath } from 'node:url';
import { defineConfig, mergeConfig } from 'vitest/config';
import rootConfig from '../../vitest.config';
export default mergeConfig(rootConfig, defineConfig({
  resolve: { alias: { '#': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { include: ['apps/web-antd/src/router/navigation-loading.test.ts', 'apps/web-antd/src/modules/manifest-compatibility.test.ts'] },
}));
