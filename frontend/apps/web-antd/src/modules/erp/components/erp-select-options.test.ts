import { describe, expect, it, vi } from 'vitest';

import { invalidateErpSelectOptions, preloadErpSelectOptions } from './erp-select-options';

describe('ERP page select options', () => {
  it('loads once per page and reference context, then reloads after invalidation', async () => {
    const load = vi.fn(async () => [{ id: '1' }]);

    await Promise.all([
      preloadErpSelectOptions(load, 'tenant-a'),
      preloadErpSelectOptions(load, 'tenant-a'),
    ]);
    expect(load).toHaveBeenCalledTimes(1);

    await preloadErpSelectOptions(load, 'tenant-b');
    expect(load).toHaveBeenCalledTimes(2);

    invalidateErpSelectOptions(load, 'tenant-a');
    await preloadErpSelectOptions(load, 'tenant-a');
    expect(load).toHaveBeenCalledTimes(3);
  });
});
