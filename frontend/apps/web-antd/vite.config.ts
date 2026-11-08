import { randomUUID } from 'node:crypto';

import { defineConfig } from '@vben/vite-config';

export default defineConfig(async ({ command }) => {
  const releaseId = randomUUID();
  return {
    application: {},
    vite: {
      build: {
        // Keep hashed assets usable by tabs opened before a local rebuild.
        emptyOutDir: false,
      },
      plugins:
        command === 'build'
          ? [
              {
                name: 'esop:web-release',
                generateBundle() {
                  this.emitFile({
                    fileName: 'web-release.json',
                    source: JSON.stringify({ id: releaseId }),
                    type: 'asset',
                  });
                },
                transformIndexHtml() {
                  return [
                    {
                      attrs: { content: releaseId, name: 'web-release-id' },
                      injectTo: 'head',
                      tag: 'meta',
                    },
                  ];
                },
              },
            ]
          : [],
      server: {
        proxy: {
          '/api': {
            changeOrigin: true,
            target: 'http://localhost:8000',
            ws: true,
          },
        },
      },
    },
  };
});
