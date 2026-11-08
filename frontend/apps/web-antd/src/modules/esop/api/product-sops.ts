import type { Operation } from './esop';

import { requestClient } from '#/api/request';

export type ProductSopStatus = 'approved' | 'pending' | 'rejected';
export interface ProductSopVersion {
  id: string;
  product_id: string;
  product_name: string;
  version: number;
  status: ProductSopStatus;
  operations: Operation[];
  base_version_id: null | string;
  created_by: null | string;
  submitted_at: string;
  reviewed_by: null | string;
  reviewer_name?: null | string;
  reviewed_at: null | string;
  review_note: null | string;
}
export type OperationState = 'approved' | 'draft' | 'pending' | 'pending_delete';
export interface ProductOperationState {
  operation: Operation;
  status: OperationState;
  has_approved_version: boolean;
  is_deleted: boolean;
}
export interface ProductSopSummary {
  product_id: string;
  status: 'approved' | 'draft' | 'pending';
  dirty: boolean;
  operation_count: number;
}
export const operationStateText: Record<OperationState, string> = {
  approved: '已生效', draft: '草稿', pending: '待审核', pending_delete: '待删除',
};
export interface ProductSopWorkspace {
  product_id: string;
  product_name: string;
  status: 'approved' | 'draft' | 'empty' | 'pending' | 'rejected';
  dirty: boolean;
  current_operations: Operation[];
  operation_states: ProductOperationState[];
  approved_version: null | ProductSopVersion;
  pending_version: null | ProductSopVersion;
}
export interface ProductSopDetail {
  version: ProductSopVersion;
  base_version: null | ProductSopVersion;
}

export const productSopStatusText: Record<ProductSopStatus | 'draft' | 'empty', string> = {
  approved: '已审核', draft: '草稿', empty: '未编制', pending: '待审核', rejected: '已驳回',
};

export function getProductSopWorkspace(productId: string) {
  return requestClient.get<ProductSopWorkspace>(`/esop/product-sops/${productId}/workspace`);
}
export function listProductSopVersions(productId: string) {
  return requestClient.get<{ items: ProductSopVersion[]; total: number }>(`/esop/product-sops/${productId}/versions`);
}
export function submitProductSop(productId: string) {
  return requestClient.post<ProductSopVersion>(`/esop/product-sops/${productId}/submit`);
}
export function discardProductSopDraft(productId: string) {
  return requestClient.post<ProductSopWorkspace>(`/esop/product-sops/${productId}/discard-draft`);
}
export function listProductSopReviews(status?: ProductSopStatus | 'reviewed', page = 1, pageSize = 20, keyword?: string, submittedFrom?: string, submittedTo?: string) {
  return requestClient.get<{ items: ProductSopVersion[]; total: number }>('/esop/product-sop-versions', { params: { status, page, page_size: pageSize, keyword, submitted_from: submittedFrom, submitted_to: submittedTo } });
}
export function getProductSopVersion(id: string) {
  return requestClient.get<ProductSopDetail>(`/esop/product-sop-versions/${id}`);
}
export function approveProductSop(id: string) {
  return requestClient.post<ProductSopVersion>(`/esop/product-sop-versions/${id}/approve`);
}
export function rejectProductSop(id: string, reason: string) {
  return requestClient.post<ProductSopVersion>(`/esop/product-sop-versions/${id}/reject`, { reason });
}
export function rollbackProductSop(id: string) {
  return requestClient.post<ProductSopWorkspace>(`/esop/product-sop-versions/${id}/rollback`);
}
export function getProductSopFile(productId: string, fileId: string, versionId?: string) {
  return requestClient.get<Blob>(`/esop/product-sops/${productId}/files/${fileId}/preview`, {
    params: { version_id: versionId }, responseType: 'blob',
  });
}

export function prepareProductSopMedia(productId: string) {
  return requestClient.post<ProductSopWorkspace>(`/esop/product-sops/${productId}/prepare-media`, undefined, { timeout: 300_000 });
}

export function getProductSopStatuses() {
  return requestClient.get<{ items: ProductSopSummary[]; total: number }>('/esop/product-sops/statuses');
}


export function getProductSopFileAccess(productId: string, fileId: string, versionId?: string) {
  return requestClient.get<{ url: string; expires_at: string }>(`/esop/product-sops/${productId}/files/${fileId}/access`, {
    params: { version_id: versionId },
  });
}
