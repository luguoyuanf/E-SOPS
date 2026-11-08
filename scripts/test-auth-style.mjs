import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/apps/web-antd/package.json', import.meta.url));
const { parse, compileStyle } = require('vue/compiler-sfc');
const filename = new URL('../frontend/apps/web-antd/src/layouts/auth.vue', import.meta.url);
const { descriptor } = parse(readFileSync(filename, 'utf8'));
const style = descriptor.styles.find((item) => item.scoped);
assert.ok(style, 'Authentication styles must be scoped');
const result = compileStyle({ source: style.content, filename: filename.pathname, id: 'data-v-login-test', scoped: true });
assert.deepEqual(result.errors, []);
const darkSelectors = [...result.code.matchAll(/([^{}]+)\{/g)]
  .map((match) => match[1].trim()).filter((selector) => selector.includes('.dark'));
assert.ok(darkSelectors.length > 0);
for (const selector of darkSelectors) {
  assert.ok(selector.includes('.esops-') && selector.includes('[data-v-login-test]'),
    `Login styling must not override global theme containers: ${selector}`);
}
console.log('PASS: compiled authentication theme rules remain scoped to the login layout');
