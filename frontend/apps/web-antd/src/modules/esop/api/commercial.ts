import { requestClient } from '#/api/request';

export { getStorageUsage, grantStorage, listStorageGrants } from '#/api/core/tenant-storage';
export type { StorageGrant, StorageUsage } from '#/api/core/tenant-storage';

export type { PurchasePageContent, PurchasePrice } from './generated/types.gen';

export function getPurchaseContent() {
  return requestClient.get<import('./generated/types.gen').PurchasePageContent>('/esop/purchase-content');
}

export function savePurchaseContent(data: import('./generated/types.gen').PurchasePageContent) {
  return requestClient.put<import('./generated/types.gen').PurchasePageContent>('/esop/purchase-content', data);
}
