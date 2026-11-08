export function activationKeyColumns(isAdmin: boolean, isChannel: boolean) {
  return [
  { title: '激活密钥', dataIndex: 'key', key: 'key', width: 140 },
  ...(isAdmin || isChannel ? [{ title: '租户', key: 'tenant', width: 200 }] : []),
  ...(isAdmin ? [{ title: '渠道', key: 'channel', width: 150 }] : []),
  { title: '状态', key: 'status', width: 100 },
  { title: '设备编号', dataIndex: 'device_code', key: 'device_code', width: 180 },
  { title: '激活时间', dataIndex: 'used_at', key: 'used_at', width: 200 },
  { title: '生成时间', dataIndex: 'created_at', key: 'created_at', width: 200 },
  ...(isAdmin || isChannel ? [{ title: '操作', key: 'action', width: 110 }] : []),
  ];
}
