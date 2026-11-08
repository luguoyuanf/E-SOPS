import { requestClient } from '#/api/request';
import { imageContentType, uploadImageDirect } from './direct-images';

export interface OperationAttachment {
  sheet_index?: null | number;
  display_file_id?: null | string;
  display_content_type?: null | string;
  display_pages?: string[];
  file_id: string;
  name: string;
  original_name?: null | string;
  kind: string;
  content_type: null | string;
  size: number;
}

export interface OperationProductTree {
  categories: { id: string; name: string; parent_id: null | string }[];
  products: (ProductOption & { category_id: null | string })[];
}

export interface Operation {
  created_at?: string;
  sort_order: number;
  id: string;
  code: string;
  name: string;
  product_id: null | string;
  description?: null | string;
  attachments: OperationAttachment[];
}

export interface ProcessRoute {
  id: string;
  code: string;
  name: string;
  operation_ids: string[];
}

export interface ProductOption {
  id: string;
  code: string;
  name: string;
}

export interface SopPage {
  file_id: string;
  sort: number;
  caption: null | string;
}

export type SopStatus = 'approved' | 'draft' | 'pending' | 'rejected';

export interface Sop {
  id: string;
  family_id: string;
  product_id: string;
  operation_id: string;
  title: string;
  version: number;
  status: SopStatus;
  pages: SopPage[];
  created_at: string;
  updated_at: string;
  reviewed_at: null | string;
}

export interface ListResult<T> {
  items: T[];
  total: number;
}

export function listOperations(params: { created_from?: string; created_to?: string; page?: number; page_size?: number; product_id?: string; unassigned?: boolean } = {}) {
  return requestClient.get<ListResult<Operation>>('/esop/operations', { params });
}

export function saveOperation(data: Pick<Operation, 'code' | 'name'> & Partial<Pick<Operation, 'product_id' | 'description' | 'attachments'>>, id?: string) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id
    ? requestClient.put<Operation>(`/esop/operations/${id}`, payload)
    : requestClient.post<Operation>('/esop/operations', payload);
}

export function listRoutes() {
  return requestClient.get<ListResult<ProcessRoute>>('/esop/routes');
}

export function saveRoute(
  data: Pick<ProcessRoute, 'code' | 'name' | 'operation_ids'>,
  id?: string,
) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id
    ? requestClient.put<ProcessRoute>(`/esop/routes/${id}`, payload)
    : requestClient.post<ProcessRoute>('/esop/routes', payload);
}

export function listProducts(keyword = '') {
  return requestClient.get<{ items: ProductOption[] }>('/esop/products', {
    params: { keyword },
  });
}

export function listSops(params: {
  latest_only?: boolean;
  operation_id?: string;
  page?: number;
  page_size?: number;
  product_id?: string;
  status?: SopStatus;
} = {}) {
  return requestClient.get<ListResult<Sop>>('/esop/sops', { params });
}

export function uploadSopFile(file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<{ id: string }>('/esop/sops/files/upload', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

export function getSop(id: string) {
  return requestClient.get<Sop>(`/esop/sops/${id}`);
}

export function getSopVersions(id: string) {
  return requestClient.get<ListResult<Sop>>(`/esop/sops/${id}/versions`);
}

export function createSop(data: {
  operation_id: string;
  pages: SopPage[];
  product_id: string;
  title: string;
}) {
  return requestClient.post<Sop>('/esop/sops', data);
}

export function updateSop(id: string, data: { pages: SopPage[]; title: string }) {
  return requestClient.put<Sop>(`/esop/sops/${id}`, data);
}

export function submitSop(id: string) {
  return requestClient.post<Sop>(`/esop/sops/${id}/submit`);
}

export function approveSop(id: string) {
  return requestClient.post<Sop>(`/esop/sops/${id}/approve`);
}

export function rejectSop(id: string, reason: string) {
  return requestClient.post<Sop>(`/esop/sops/${id}/reject`, { reason });
}

export function newSopVersion(id: string) {
  return requestClient.post<Sop>(`/esop/sops/${id}/new-version`);
}

export function rollbackSopVersion(id: string) {
  return requestClient.post<Sop>(`/esop/sops/${id}/rollback`);
}

export function getOperationProductTree() {
  return requestClient.get<OperationProductTree>('/esop/operations/product-tree');
}

export function uploadOperationFile(file: File, operationId?: string, onProgress?: (percent: number) => void, signal?: AbortSignal) {
  if (imageContentType(file.name)) return uploadImageDirect(file, operationId, onProgress, signal);
  const data = new FormData();
  data.append('file', file);
  const path = operationId ? `/esop/operations/${operationId}/files/upload` : '/esop/operations/files/upload';
  return requestClient.post<OperationAttachment>(path, data, {
    timeout: 300_000,
    signal,
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event) => {
      if (event.total) onProgress?.(Math.min(100, Math.round(event.loaded * 100 / event.total)));
    },
  });
}

export function moveOperation(id: string, targetId: string, position: 'after' | 'before') {
  return requestClient.post<Operation>(`/esop/operations/${id}/move`, { target_id: targetId, position });
}

export function deleteOperation(id: string) {
  return requestClient.delete<void>(`/esop/operations/${id}`);
}


export function getEditorFileAccess(fileId: string, operationId?: string) {
  const path = operationId ? `/esop/operations/${operationId}/files/${fileId}/access` : `/esop/operations/files/${fileId}/access`;
  return requestClient.get<{ url: string; expires_at: string }>(path);
}

export interface OperationMediaStatus {
  status: 'queued' | 'running' | 'ready' | 'failed';
  error_message: null | string;
  attachment: OperationAttachment;
}

export function getOperationMediaStatus(fileId: string, operationId?: string) {
  const path = operationId ? `/esop/operations/${operationId}/files/${fileId}` : `/esop/operations/files/${fileId}`;
  return requestClient.get<OperationMediaStatus>(`${path}/conversion`);
}

export function retryOperationMedia(fileId: string, operationId?: string) {
  const path = operationId ? `/esop/operations/${operationId}/files/${fileId}` : `/esop/operations/files/${fileId}`;
  return requestClient.post<OperationMediaStatus>(`${path}/conversion/retry`);
}

export interface SopImportSheet { index: number; name: string; selected: boolean }
export function analyzeSopImport(fileId: string) {
  return requestClient.get<{ sheets: SopImportSheet[] }>(`/esop/operations/files/${fileId}/sop-import`);
}
export function importProductSop(productId: string, body: { file_id: string; sheet_indexes: number[]; mode: 'append' | 'replace' }) {
  return requestClient.post<Operation[]>(`/esop/operations/products/${productId}/sop-import`, body);
}
