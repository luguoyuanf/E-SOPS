import { defineComponent, h, onUpdated, ref } from 'vue';

import { DatePicker, Table } from 'ant-design-vue';

const BaseSelectableTable = defineComponent({
  inheritAttrs: false,
  props: { dateField: String },
  setup(props, { attrs, slots }) {
    const selectedKeys = ref<Array<number | string>>([]);
    const dateRange = ref<[number, number]>();
    let previousSource = attrs.dataSource ?? attrs['data-source'];
    onUpdated(() => {
      const currentSource = attrs.dataSource ?? attrs['data-source'];
      if (currentSource !== previousSource) selectedKeys.value = [];
      previousSource = currentSource;
    });
    return () => {
      const rowSelection = attrs.rowSelection ?? attrs['row-selection'];
      const controlledKeys = (rowSelection as { selectedRowKeys?: Array<number | string> } | undefined)?.selectedRowKeys;
      const dataSource = attrs.dataSource ?? attrs['data-source'];
      const columns = (attrs.columns as Array<Record<string, unknown>> | undefined)?.map((column) =>
        column.key === 'action' || column.key === 'actions' || column.title === '操作'
          ? { ...column, fixed: 'right', width: column.width ?? 120 }
          : column,
      );
      const filteredRows = props.dateField && dateRange.value
        ? ((dataSource as Record<string, unknown>[]) ?? []).filter((row) => {
            const time = new Date(String(row[props.dateField!] ?? '')).getTime();
            return time >= dateRange.value![0] && time <= dateRange.value![1];
          })
        : dataSource;
      return h('div', [
        props.dateField && h('div', { class: 'mb-3 flex items-center gap-3 overflow-x-auto whitespace-nowrap' }, [
          slots.toolbar?.(),
          h('span', { class: 'text-sm' }, '创建时间'),
          h(DatePicker.RangePicker, {
            class: 'flex-none',
            allowClear: true,
            format: 'YYYY-MM-DD HH:mm:ss',
            showTime: true,
            onChange: (dates: any) => {
              dateRange.value = dates?.length === 2
                ? [dates[0].valueOf(), dates[1].valueOf()]
                : undefined;
              selectedKeys.value = [];
            },
          }),
        ]),
        h('div', { class: 'mb-2 text-sm text-muted-foreground' }, `已选 ${controlledKeys?.length ?? selectedKeys.value.length} 项`),
        h(Table, {
          ...attrs,
          columns,
          dataSource: filteredRows,
          rowSelection: rowSelection ?? {
            selectedRowKeys: selectedKeys.value,
            onChange: (keys: Array<number | string>) => { selectedKeys.value = keys; },
          },
        } as any, slots),
      ]);
    };
  },
});

export const SelectableTable = BaseSelectableTable as unknown as typeof Table & {
  new (): { $slots: { toolbar?: () => any } };
};
