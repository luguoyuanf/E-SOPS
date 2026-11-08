import { describe, expect, it } from 'vitest';
import { activationKeyColumns } from './activation-key-view';

describe('activation key columns by role', () => {
  it('preserves the complete platform view', () => {
    expect(activationKeyColumns(true, false).map(c => c.key)).toEqual([
      'key', 'tenant', 'channel', 'status', 'device_code', 'used_at', 'created_at', 'action',
    ]);
  });
  it('shows customer ownership and assignment for channels', () => {
    const keys = activationKeyColumns(false, true).map(c => c.key);
    expect(keys).toContain('tenant');
    expect(keys).toContain('action');
    expect(keys).not.toContain('channel');
  });
  it('hides tenant/channel ownership and operations from tenant accounts', () => {
    expect(activationKeyColumns(false, false).map(c => c.key)).toEqual([
      'key', 'status', 'device_code', 'used_at', 'created_at',
    ]);
  });
});
