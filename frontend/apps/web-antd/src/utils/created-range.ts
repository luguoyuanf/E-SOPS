export function createdRangeQuery(value: unknown) {
  const range = Array.isArray(value) ? value : [];
  return {
    created_from: range[0] ? new Date(String(range[0])).toISOString() : undefined,
    created_to: range[1] ? new Date(String(range[1])).toISOString() : undefined,
  };
}

export const createdRangeField = {
  component: 'RangePicker' as const,
  componentProps: {
    allowClear: true,
    format: 'YYYY-MM-DD HH:mm:ss',
    showTime: true,
    valueFormat: 'YYYY-MM-DDTHH:mm:ss',
  },
  fieldName: 'created_range',
  label: '创建时间',
};
