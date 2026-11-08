import { describe, expect, it, vi } from 'vitest';
import { TerminalClient, TerminalError } from './client';
import { refreshTerminal } from './refresh';

describe('terminal connectivity and parallel reads', () => {
  it('does not load production data before employee login', async () => {
    const client = new TerminalClient('a');
    const request = vi.spyOn(client, 'request').mockResolvedValue({ tenantName: '租户' });
    const profile = vi.fn();
    await refreshTerminal(client, { profile, tasks: vi.fn(), orders: vi.fn(), failure: vi.fn() });
    expect(request).toHaveBeenCalledExactlyOnceWith('terminal/profile');
    expect(profile).toHaveBeenCalledOnce();
  });
  it('reports a business failure independently while heartbeat stays online', async () => {
    const client = new TerminalClient('a'); client.staff = { accessToken: 'staff' } as any;
    let online = false;
    const failure = vi.fn();
    const starts: string[] = [];
    vi.spyOn(client, 'request').mockImplementation(async (path) => {
      starts.push(path);
      await Promise.resolve();
      if (path === 'terminal/tasks') throw new TerminalError('任务读取失败', 503);
      return path === 'terminal/profile' ? { tenantName: '租户' } : [];
    });
    await refreshTerminal(client, { profile: () => { online = true; }, tasks: vi.fn(), orders: vi.fn(), failure });
    expect(starts).toEqual(['terminal/profile', 'terminal/tasks', 'terminal/orders']);
    expect(online).toBe(true);
    expect(failure).toHaveBeenCalledWith('tasks', expect.any(TerminalError));
  });
});
