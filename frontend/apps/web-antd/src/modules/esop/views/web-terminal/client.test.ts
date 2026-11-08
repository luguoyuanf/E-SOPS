import { afterEach, describe, expect, it, vi } from 'vitest';
import { TerminalClient, TerminalError } from './client';

describe('online-only web terminal', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('keeps employee authorization separate from the back office and binds the device header', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { ok: true }, code: 0 })));
    vi.stubGlobal('fetch', fetch);
    const client = new TerminalClient('terminal-a'); client.token = 'device-a';
    expect(await client.request('terminal/profile')).toEqual({ ok: true });
    const options = fetch.mock.calls[0]![1];
    expect(options.headers).toEqual({ 'Content-Type': 'application/json', 'X-Device-Token': 'device-a' });
    expect(options.credentials).toBe('omit');
    expect(options.cache).toBe('no-store');
  });
  it('uses the bundled profile without extra startup requests', async () => {
    const client = new TerminalClient('a');
    const request = vi.spyOn(client, 'request').mockResolvedValue({ deviceToken: 'device', profile: { tenantName: '租户', tenantCode: 'tenant-a' } });
    expect(await client.connect()).toEqual({ tenantName: '租户', tenantCode: 'tenant-a' });
    expect(request).toHaveBeenCalledExactlyOnceWith('web-terminal/a');
    expect(client.token).toBe('device');
  });
  it('clears device and employee credentials and attachment URLs when the device is revoked', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response(new Blob(['cached document'])));
    vi.stubGlobal('fetch', fetch);
    const createObjectURL = vi.fn().mockReturnValue('blob:old-device-document');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const client = new TerminalClient('a');
    client.token = 'old-device';
    client.staff = { accessToken: 'old-staff' } as any;
    const fileId = '11111111-1111-1111-1111-111111111111';
    await client.file(fileId);

    client.disconnect();

    expect(client.token).toBe('');
    expect(client.staff).toBeUndefined();
    expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:old-device-document');
    client.token = 'new-device';
    await client.file(fileId);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1]![1].headers).toEqual({ 'X-Device-Token': 'new-device' });
  });
  it('rejects offline reports without saving a queue or retrying in the background', async () => {
    const storage = { setItem: vi.fn() };
    vi.stubGlobal('localStorage', storage);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network offline')));
    const client = new TerminalClient('terminal-a');
    client.staff = { username: 'alice', accessToken: 'employee-token' } as any;
    await expect(client.report({ requestId: 'same-request', goodQty: 4 })).rejects.toBeInstanceOf(TerminalError);
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('rejects business failures and anonymous reporting', async () => {
    const client = new TerminalClient('terminal-a');
    await expect(client.report({ requestId: 'a' })).rejects.toThrow('请先登录');
    client.staff = { accessToken: 'staff' } as any;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '超出计划数量' }), { status: 409 })));
    await expect(client.report({ requestId: 'a' })).rejects.toThrow('超出计划数量');
  });
  it('submits alarms with staff/device identity and leaves plan association to the server', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'alarm-a', plan_id: 'plan-a', plan_code: 'PLAN-A', order_id: 'order-a', order_code: 'MO-A',
    })));
    vi.stubGlobal('fetch', fetch);
    const client = new TerminalClient('terminal-a');
    client.token = 'device-a';
    client.staff = { accessToken: 'staff-a' } as any;
    // Even an outdated caller's extra field cannot force an old release into the request.
    const alarm = await client.alarm({ requestId: 'alarm-request', typeCode: 'production', reason: '异常', releaseId: 'stale-release' } as any);
    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({ requestId: 'alarm-request', typeCode: 'production', reason: '异常' });
    expect(fetch.mock.calls[0]![1].headers).toMatchObject({ Authorization: 'Bearer staff-a', 'X-Device-Token': 'device-a' });
    expect(alarm.plan_code).toBe('PLAN-A');
    expect(alarm.order_code).toBe('MO-A');
  });
  it('supports alarms without a current plan and rejects anonymous alarms', async () => {
    const client = new TerminalClient('terminal-a');
    const payload = { requestId: 'standalone', typeCode: 'sop', reason: '' };
    await expect(client.alarm(payload)).rejects.toThrow('请先登录员工账号');
    client.staff = { accessToken: 'staff-a' } as any;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'standalone', release_id: null, plan_id: null, plan_code: null, order_id: null, order_code: null }))));
    const alarm = await client.alarm(payload);
    expect(alarm).toMatchObject({ release_id: null, plan_id: null, order_id: null });
  });

  it('requires employee identity and sends selected production plan to the station API', async () => {
    const client = new TerminalClient('terminal-a');
    client.token = 'device-a';
    await expect(client.productionPlans()).rejects.toThrow('请先登录员工账号');
    await expect(client.selectProductionPlan('release-a')).rejects.toThrow('请先登录员工账号');
    client.staff = { accessToken: 'staff-a' } as any;
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { items: [], total: 0 }, code: 0 })));
    vi.stubGlobal('fetch', fetch);
    await client.productionPlans(2, 'MO 001');
    await client.productionPlans(1, 'MO 001', 'completed');
    await client.selectProductionPlan('release-a');
    expect(fetch.mock.calls[0]![0]).toContain('terminal/production-plans?page=2&page_size=30&keyword=MO%20001&category=active');
    expect(fetch.mock.calls[1]![0]).toContain('terminal/production-plans?page=1&page_size=30&keyword=MO%20001&category=completed');
    expect(fetch.mock.calls[2]![0]).toContain('terminal/production-plans/release-a/select');
    expect(fetch.mock.calls[2]![1]).toMatchObject({ method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Device-Token': 'device-a', Authorization: 'Bearer staff-a' } });
  });

});
