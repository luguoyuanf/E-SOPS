import { describe, expect, it } from 'vitest';

import { tenantOwnershipLabel } from './tenant-ownership';

const tenants = [{ id: 'a', name: '工厂A', code: 'factory-a' }];
const labels = { platform: '平台全局', unknown: '归属未知' };

describe('tenant ownership labels', () => {
  it('resolves tenant names and codes from the row identity', () => {
    expect(tenantOwnershipLabel({ tenant_id: 'a' }, 'tenant', tenants, labels)).toBe('工厂A(factory-a)');
  });
  it('keeps the actual ID when a tenant is missing from the directory', () => {
    expect(tenantOwnershipLabel({ tenant_id: 'deleted' }, 'tenant', tenants, labels)).toBe('deleted');
  });
  it('never labels missing ownership as platform or the selected tenant', () => {
    expect(tenantOwnershipLabel({}, 'tenant', tenants, labels, 'a')).toBe('归属未知');
  });
  it('uses the authenticated tenant only for explicitly current-tenant queries', () => {
    expect(tenantOwnershipLabel({}, 'current', tenants, labels, 'a')).toBe('工厂A(factory-a)');
    expect(tenantOwnershipLabel({ tenant_id: 'other' }, 'current', tenants, labels, 'a')).toBe('other');
  });
  it('labels explicit global data and mixed global units', () => {
    expect(tenantOwnershipLabel({}, 'platform', tenants, labels)).toBe('平台全局');
    expect(tenantOwnershipLabel({ is_platform: true, tenant_id: 'a' }, 'current', tenants, labels)).toBe('平台全局');
  });
  it('uses the tenant list row itself rather than a selected tenant', () => {
    expect(tenantOwnershipLabel({ id: 'b', name: '工厂B', code: 'b' }, 'self', tenants, labels)).toBe('工厂B(b)');
  });
});
