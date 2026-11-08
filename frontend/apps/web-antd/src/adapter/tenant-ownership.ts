export type TenantOwnership = 'current' | 'platform' | 'self' | 'tenant';
export type TenantIdentity = { code?: string; id: string; name: string };

type OwnershipRow = {
  code?: string;
  id?: string;
  is_platform?: boolean;
  name?: string;
  tenant_id?: null | string;
  tenant_name?: null | string;
};

export function tenantOwnershipLabel(
  value: unknown,
  ownership: TenantOwnership,
  tenants: TenantIdentity[],
  labels: { platform: string; unknown: string },
  currentTenantId?: string,
): string {
  const row = value as OwnershipRow;
  if (ownership === 'platform' || row.is_platform === true) return labels.platform;
  const id = ownership === 'self' ? row.id : row.tenant_id || (ownership === 'current' ? currentTenantId : undefined);
  const tenant = tenants.find((item) => item.id === id);
  const name = ownership === 'self' ? row.name : row.tenant_name;
  const code = ownership === 'self' ? row.code : tenant?.code;
  const title = name || tenant?.name;
  return title ? (code ? `${title}(${code})` : title) : id || labels.unknown;
}
