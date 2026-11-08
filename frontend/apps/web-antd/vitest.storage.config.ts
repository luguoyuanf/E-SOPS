import { fileURLToPath } from 'node:url';

import { defineConfig, mergeConfig } from 'vitest/config';

import rootConfig from '../../vitest.config';
export default mergeConfig(rootConfig, defineConfig({
  resolve: { alias: { '#': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { include: ['apps/web-antd/src/views/system/tenants/storage-default.test.ts', 'apps/web-antd/src/views/system/tenants/storage.test.ts', 'apps/web-antd/src/store/auth-storage.test.ts', 'apps/web-antd/src/api/core/request-error-message.test.ts'] },
}));
