import type {
  EsopStorageDefault,
  EsopStorageGrantCreate,
  EsopStorageGrantPublic,
  EsopStorageGrantsPublic,
  EsopStorageUsagePublic,
} from '#/api/generated';

import { requestClient } from '#/api/request';

export type StorageGrant = EsopStorageGrantPublic;
export type StorageUsage = EsopStorageUsagePublic;

export function listStorageGrants(tenantId: string) {
  return requestClient.get<EsopStorageGrantsPublic>('/esop/storage-grants', {
    params: { tenant_id: tenantId },
  });
}

export function getStorageUsage(tenantId: string) {
  return requestClient.get<StorageUsage>('/esop/storage-usage', {
    params: { tenant_id: tenantId },
  });
}

export function grantStorage(data: EsopStorageGrantCreate) {
  return requestClient.post<StorageGrant>('/esop/storage-grants', data);
}

export function getStorageDefault() {
  return requestClient.get<EsopStorageDefault>('/esop/storage-default');
}

export function saveStorageDefault(data: EsopStorageDefault) {
  return requestClient.put<EsopStorageDefault>('/esop/storage-default', data);
}
