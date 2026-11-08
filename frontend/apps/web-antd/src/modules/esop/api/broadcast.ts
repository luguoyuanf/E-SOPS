import type { ListResult } from './esop';

import { requestClient } from '#/api/request';

export type BroadcastPosition = 'bottom' | 'top';

export interface BroadcastInput {
  content: string;
  font_size: number;
  background_color: string;
  font_color: string;
  is_active: boolean;
}

export interface Broadcast extends BroadcastInput {
  id: string;
  position: BroadcastPosition;
  updated_at: string;
}

export function listBroadcasts() { return requestClient.get<ListResult<Broadcast>>('/esop/broadcasts'); }
export function saveBroadcast(position: BroadcastPosition, data: BroadcastInput) {
  return requestClient.put<Broadcast>(`/esop/broadcasts/${position}`, data);
}

export interface AdvertisementMedia {
  kind: 'image' | 'text' | 'video';
  file_id?: null | string;
  content: string;
  name: string;
  duration_seconds: number;
}
export interface AdvertisementInput {
  title: string;
  layout: 'bottom' | 'fullscreen' | 'left' | 'right' | 'top';
  playback: 'continuous' | 'interval';
  interval_minutes: number;
  starts_at: null | string;
  ends_at: null | string;
  daily_start: null | string;
  daily_end: null | string;
  media: AdvertisementMedia[];
  is_active: boolean;
}
export interface Advertisement extends AdvertisementInput {
  id: string;
  created_at: string;
  updated_at: string;
}
export type PublicationStatus = 'active' | 'ended' | 'paused' | 'scheduled';
export interface PublicationFilters {
  keyword: string;
  status?: PublicationStatus;
  created_range?: [string, string];
}
function publicationParams(filters: PublicationFilters, page: number, pageSize: number) {
  return { keyword: filters.keyword || undefined, status: filters.status, page, page_size: pageSize,
    created_from: filters.created_range?.[0] ? new Date(filters.created_range[0]).toISOString() : undefined,
    created_to: filters.created_range?.[1] ? new Date(filters.created_range[1]).toISOString() : undefined };
}
export function listAdvertisements(filters: PublicationFilters = { keyword: '' }, page = 1, pageSize = 20) {
  return requestClient.get<ListResult<Advertisement>>('/esop/advertisements', { params: publicationParams(filters, page, pageSize) });
}
export interface BroadcastRecord extends Broadcast { created_at: string; }
export function listBroadcastRecords(position: BroadcastPosition, filters: PublicationFilters, page = 1, pageSize = 20) {
  return requestClient.get<ListResult<BroadcastRecord>>(`/esop/broadcast-records/${position}`, { params: publicationParams(filters, page, pageSize) });
}
export function saveBroadcastRecord(position: BroadcastPosition, data: BroadcastInput, id?: string) {
  return id ? requestClient.put<BroadcastRecord>(`/esop/broadcast-records/${position}/${id}`, data)
    : requestClient.post<BroadcastRecord>(`/esop/broadcast-records/${position}`, data);
}
export function deleteBroadcastRecord(position: BroadcastPosition, id: string) {
  return requestClient.delete(`/esop/broadcast-records/${position}/${id}`);
}
export function saveAdvertisement(data: AdvertisementInput, id?: string) {
  return id ? requestClient.put<Advertisement>(`/esop/advertisements/${id}`, data)
    : requestClient.post<Advertisement>('/esop/advertisements', data);
}
export function deleteAdvertisement(id: string) { return requestClient.delete(`/esop/advertisements/${id}`); }
export function uploadAdvertisementFile(file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<{ id: string }>('/esop/advertisements/files/upload', data, {
    timeout: 300_000, headers: { 'Content-Type': 'multipart/form-data' },
  });
}

export function getAdvertisementFileAccess(fileId: string) {
  return requestClient.get<{ url: string; expires_at: string }>(`/esop/advertisements/files/${fileId}/access`);
}
