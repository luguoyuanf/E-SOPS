import { createApp, defineComponent, h, nextTick, ref } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SelectableTable } from './selectable-table';

vi.mock('ant-design-vue', () => ({ DatePicker: { RangePicker: { render: () => h('input', { 'data-test': 'date-range' }) } }, Table: { render: () => null } }));

const apps: Array<ReturnType<typeof createApp>> = [];
afterEach(() => { apps.splice(0).forEach((app) => app.unmount()); });

describe('SelectableTable', () => {
  it('keeps a custom search beside the date filter', () => {
    const parent = defineComponent({
      setup: () => () => h(SelectableTable, { dateField: 'created_at' }, {
        toolbar: () => h('input', { 'data-test': 'name-search' }),
      }),
    });
    const element = document.createElement('div');
    const app = createApp(parent); apps.push(app); app.mount(element);
    const search = element.querySelector('[data-test="name-search"]');
    const date = element.querySelector('[data-test="date-range"]');
    expect(search?.parentElement).toBe(date?.parentElement);
    expect(search?.parentElement?.classList.contains('whitespace-nowrap')).toBe(true);
  });

  it('shows the controlled selection count after the parent changes it', async () => {
    const keys = ref<string[]>([]);
    const parent = defineComponent({
      setup: () => () => h(SelectableTable, { 'row-selection': { selectedRowKeys: keys.value, onChange: () => {} } }),
    });
    const element = document.createElement('div');
    const app = createApp(parent); apps.push(app); app.mount(element);
    expect(element.textContent).toContain('已选 0 项');
    keys.value = ['one', 'two'];
    await nextTick();
    expect(element.textContent).toContain('已选 2 项');
  });
});
