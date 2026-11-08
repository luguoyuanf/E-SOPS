import type { MenuRecordRaw } from '@vben/types';

import { describe, expect, it } from 'vitest';

import { firstMenuPage } from '../first-menu-page';

const page = (path: string, extra: Partial<MenuRecordRaw> = {}): MenuRecordRaw => ({ name: path, path, ...extra });

describe('first menu page', () => {
  it('opens the first child in menu order', () => {
    expect(firstMenuPage([page('/root', { children: [page('/first'), page('/last')] })])).toBe('/first');
  });
  it('descends through third-level and deeper directories', () => {
    expect(firstMenuPage([page('/root', { children: [page('/group', { children: [page('/third')] })] })])).toBe('/third');
  });
  it('skips hidden, disabled and inaccessible branches', () => {
    expect(firstMenuPage([page('/hidden', { show: false }), page('/disabled', { disabled: true }), page('/group', { children: [page('/blocked', { disabled: true })] }), page('/allowed')])).toBe('/allowed');
  });
  it('does not navigate when no accessible page exists', () => {
    expect(firstMenuPage([page('/root', { children: [page('/disabled', { disabled: true })] })])).toBeUndefined();
    expect(firstMenuPage([])).toBeUndefined();
  });
  it('preserves a leaf path including external links', () => {
    expect(firstMenuPage([page('https://example.com')])).toBe('https://example.com');
  });
});
