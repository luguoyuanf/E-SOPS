import { describe, expect, it, vi } from 'vitest';

import { createAlarmHistory } from './alarm-history';
import type { Alarm } from './client';

const alarm = (id: string) => ({ id, type_name: '生产问题', reason: '', occurred_at: '2026-10-31T00:00:00Z', resolved_at: null }) as Alarm;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('terminal alarm scroll history', () => {
  it('appends successive pages, deduplicates boundaries and stops at the end', async () => {
    const load = vi.fn().mockResolvedValueOnce({ items: [alarm('a'), alarm('b')], total: 3 })
      .mockResolvedValueOnce({ items: [alarm('b'), alarm('c')], total: 3 });
    const history = createAlarmHistory(load);
    await history.load(); await history.load(false); await history.load(false);
    expect(history.state.items.map((row) => row.id)).toEqual(['a', 'b', 'c']);
    expect(load.mock.calls).toEqual([[1], [2]]);
    expect(history.state.ended).toBe(true);
  });
  it('prevents duplicate loads while a page is pending', async () => {
    const pending = deferred<{ items: Alarm[]; total: number }>();
    const load = vi.fn().mockResolvedValueOnce({ items: [alarm('a')], total: 3 }).mockReturnValue(pending.promise);
    const history = createAlarmHistory(load); await history.load();
    const next = history.load(false); await history.load(false);
    expect(load).toHaveBeenCalledTimes(2);
    pending.resolve({ items: [alarm('b')], total: 3 }); await next;
    expect(history.state.items.map((row) => row.id)).toEqual(['a', 'b']);
  });
  it('filter resets supersede pending pages and restart with page one', async () => {
    const stale = deferred<{ items: Alarm[]; total: number }>();
    const load = vi.fn().mockResolvedValueOnce({ items: [alarm('old')], total: 4 })
      .mockReturnValueOnce(stale.promise).mockResolvedValueOnce({ items: [alarm('new-filter')], total: 1 });
    const history = createAlarmHistory(load); await history.load();
    const next = history.load(false); await history.load();
    stale.resolve({ items: [alarm('stale')], total: 4 }); await next;
    expect(history.state.items.map((row) => row.id)).toEqual(['new-filter']);
    expect(load.mock.calls).toEqual([[1], [2], [1]]);
    expect(history.state.loading).toBe(false);
  });
  it('retries a failed next page without advancing and treats an empty page as the end', async () => {
    const load = vi.fn().mockResolvedValueOnce({ items: [alarm('a')], total: 4 })
      .mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ items: [], total: 4 });
    const history = createAlarmHistory(load); await history.load();
    await expect(history.load(false)).rejects.toThrow('网络中断');
    expect(history.state.page).toBe(1); expect(history.state.error).toBe('网络中断');
    await history.load(false); await history.load(false);
    expect(load.mock.calls).toEqual([[1], [2], [2]]); expect(history.state.ended).toBe(true);
  });
  it('refresh replaces previous rows and logout clear invalidates pending user records', async () => {
    const pending = deferred<{ items: Alarm[]; total: number }>();
    const load = vi.fn().mockResolvedValueOnce({ items: [alarm('before')], total: 3 })
      .mockResolvedValueOnce({ items: [alarm('after')], total: 3 }).mockReturnValueOnce(pending.promise);
    const history = createAlarmHistory(load); await history.load(); await history.load();
    expect(history.state.items.map((row) => row.id)).toEqual(['after']);
    const next = history.load(false); history.clear();
    pending.resolve({ items: [alarm('previous-user')], total: 3 }); await next;
    expect(history.state.items).toEqual([]); expect(history.state.total).toBe(0);
  });
});
