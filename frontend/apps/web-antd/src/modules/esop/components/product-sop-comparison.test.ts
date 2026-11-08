import type { Operation } from '../api/esop';

import { describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import ProductSopComparison from './product-sop-comparison.vue';

vi.mock('ant-design-vue', () => {
  const component = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
  return { Button: component, Empty: component, Tag: component };
});

const operation = (id: string, name: string): Operation => ({
  id, product_id: 'product', code: id, name, sort_order: 0, attachments: [],
});

describe('SOP 审核差异展示', () => {
  it('只展示新增、删除、修改工序，不展示未变更工序', () => {
    const before = [operation('same', '未变更'), operation('deleted', '待删除'), operation('edited', '原名称')];
    const after = [before[0]!, operation('edited', '新名称'), operation('added', '新增')];
    const root = document.createElement('div');
    const app = createApp(ProductSopComparison, { before, after });
    app.mount(root);
    expect(root.textContent).toContain('本次变更 3 道工序');
    expect(root.textContent).not.toContain('未变更');
    expect(root.textContent).toContain('删除工序');
    expect(root.textContent).toContain('名称修改');
    expect(root.textContent).toContain('新增工序');
    app.unmount();
  });
});
