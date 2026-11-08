import type { ListResult } from './esop';

import { requestClient } from '#/api/request';
import { exportTimezoneHeaders } from '#/utils/export-timezone';

export interface ChannelWorkspace { channel_id: string; channel_code: string; channel_name: string }
export interface ChannelCustomer { tenant_id: string; tenant_code: string; tenant_name: string; created_at: string }
export interface ChannelKey {
  id: string;
  batch_id: null | string;
  key: null | string;
  recoverable: boolean;
  tenant_id: null | string;
  hardware_model_id: null | string;
  created_at: string;
  used_at: null | string;
  used_terminal_id: null | string;
  status: 'activated' | 'assigned' | 'unassigned';
}
export interface ChannelBatch {
  batch_id: string;
  quantity: number;
  assigned_count: number;
  activated_count: number;
  created_at: string;
}
export interface BatchKey { id: string; key: string }
export interface KeyBatch { batch_id: string; keys: BatchKey[] }

export function getChannelWorkspace(quiet = false) { return requestClient.get<ChannelWorkspace>('/esop/channel-workspace/me', { skipErrorMessage: quiet }); }
export interface KeyQuery { batch_id?: string; created_from?: string; created_to?: string; page: number; page_size: number }
export interface KeyExport { batch_id?: string; key_ids?: string[] }
export function listChannelKeys(params: KeyQuery) { return requestClient.get<ListResult<ChannelKey>>('/esop/channel-workspace/keys', { params }); }
export function listChannelBatches() { return requestClient.get<ListResult<ChannelBatch>>('/esop/channel-workspace/keys/batches'); }
export function exportChannelKeys(data: KeyExport) { return requestClient.post<Blob>('/esop/channel-workspace/keys/export', data, { headers: exportTimezoneHeaders(), responseType: 'blob' }); }
export function listAdminChannelKeys(channelId: string, params: KeyQuery) { return requestClient.get<ListResult<ChannelKey>>(`/esop/channels/${channelId}/keys`, { params }); }
export function listAdminChannelBatches(channelId: string) { return requestClient.get<ListResult<ChannelBatch>>(`/esop/channels/${channelId}/keys/batches`); }
export function exportAdminChannelKeys(channelId: string, data: KeyExport) { return requestClient.post<Blob>(`/esop/channels/${channelId}/keys/export`, data, { headers: exportTimezoneHeaders(), responseType: 'blob' }); }
export function listChannelCustomers() { return requestClient.get<ListResult<ChannelCustomer>>('/esop/channel-workspace/customers'); }
export function createChannelCustomer(data: { code?: string; name: string }) {
  return requestClient.post<ChannelCustomer>('/esop/channel-workspace/customers', { ...data, code: data.code?.trim() || undefined });
}
export function assignChannelKeys(data: { key_ids: string[]; tenant_id: string }) {
  return requestClient.post<{ assigned_count: number }>('/esop/channel-workspace/keys/assign', data);
}
export function addChannelAdmin(channelId: string, userId: string) {
  return requestClient.post<{ channel_id: string; user_id: string }>(`/esop/channels/${channelId}/admins`, { user_id: userId });
}
export function issueChannelKeyBatch(channelId: string, quantity: number, hardwareModelId?: string) {
  return requestClient.post<KeyBatch>(`/esop/channels/${channelId}/keys/batches`, { quantity, hardware_model_id: hardwareModelId });
}
