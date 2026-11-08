import type { ListResult } from './esop';

import { requestClient } from '#/api/request';

export interface Channel { id: string; code: string; name: string; created_at: null | string }
export interface HardwareModel { id: string; channel_id: string; code: string; name: string; abi: string; created_at: null | string }
export interface OtaPackage {
  id: string;
  channel_id: string;
  hardware_model_id: string;
  version: string;
  version_code: number;
  package_name: string;
  file_id: string;
  file_name: string;
  release_notes: string;
  file_size: number;
  checksum_sha256: string;
  status: 'draft' | 'published' | 'superseded';
  created_at: string;
  published_at: null | string;
}

export function listChannels() { return requestClient.get<ListResult<Channel>>('/esop/channels'); }
export function saveChannel(data: Pick<Channel, 'code' | 'name'>, id?: string) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id ? requestClient.put<Channel>(`/esop/channels/${id}`, payload) : requestClient.post<Channel>('/esop/channels', payload);
}
export function listHardwareModels() { return requestClient.get<ListResult<HardwareModel>>('/esop/hardware-models'); }
export function saveHardwareModel(data: Omit<HardwareModel, 'created_at' | 'id'>, id?: string) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id ? requestClient.put<HardwareModel>(`/esop/hardware-models/${id}`, payload) : requestClient.post<HardwareModel>('/esop/hardware-models', payload);
}
export function uploadOtaFile(file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<{ id: string }>('/esop/ota/files/upload', data, { headers: { 'Content-Type': 'multipart/form-data' } });
}
export function listOtaPackages() { return requestClient.get<ListResult<OtaPackage>>('/esop/ota/packages'); }
export function createOtaPackage(data: Pick<OtaPackage, 'channel_id' | 'file_id' | 'hardware_model_id' | 'package_name' | 'release_notes' | 'version' | 'version_code'>) {
  return requestClient.post<OtaPackage>('/esop/ota/packages', data);
}
export function publishOtaPackage(id: string) { return requestClient.post<OtaPackage>(`/esop/ota/packages/${id}/publish`); }

export function downloadOtaPackage(id: string) {
  return requestClient.get<{ data: Blob; headers: Record<string, string> }>(`/esop/ota/packages/${id}/download`, { responseType: 'blob', responseReturn: 'raw' });
}
