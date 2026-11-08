export interface TerminalProfile {
  tenantId: string; tenantName: string; tenantCode?: string; deviceName: string; serialNumber: string;
  deviceCode: string; lineName: string; siteName: string; siteId: string;
}
export interface TerminalAttachment {
  id: string; name: string; kind: string; mimeType: string; size: number;
  pages: { fileId: string; url: string }[];
}
export interface TerminalTask {
  id?: string; releaseId?: string; orderId?: string; orderCode?: string;
  productId: string; productCode: string; productName: string; productModel?: string;
  productCategoryName?: string; operationId: string; operationName: string;
  sopId: string; sopVersion: number; title: string; planQty?: number;
  attachments: TerminalAttachment[]; resources: TerminalAttachment[];
  pages: { fileId: string; url: string }[];
}
export interface Staff {
  accessToken: string; userId: string; username: string; name: string;
  post: string; phoneNumber: string; hiredate: string; avatar: string;
}
export interface OrderTask {
  id: string; orderCode: string; releaseId: string; sopId: string; operationName: string;
  productName: string; productModel: string; planQty: number;
  operationInputQty: number; operationGoodQty: number; operationDefectQty: number;
  completionRate: number; status: string;
}
export interface ProductionPlan {
  planId: string; planCode: string; releaseId: null | string;
  orderId: string; orderCode: string; productName: string; productModel: string;
  operationId: string; operationName: string; orderQty: number; dueDate: string;
  planQty: number; completedQty: number;
  status: string; groupName: string; canSwitch: boolean; isCurrent: boolean;
  startAt?: null | string; endAt?: null | string;
}
export interface SipPlan {
  releaseId: string; operationId: string; orderCode: string; planCode: string; productName: string;
  operationName: string; planQty: number; goodQty: number; badQty: number;
  reportedQty: number; inspectedQty: number; availableQty: number; status: string;
}
export interface Report {
  id: string; order_code: string; product_name: string; staff_name: string;
  input_qty: number; good_qty: number; defect_qty: number; revision: number;
  occurred_at: string; change_status?: string; change_kind?: string;
}
export interface Alarm {
  release_id?: null | string; plan_id?: null | string; plan_code?: null | string;
  order_id?: null | string; order_code?: null | string;
  id: string; type_name: string; reason: string; occurred_at: string; resolved_at: null | string;
}
export interface Broadcast {
  position: string; content: string; fontSize: number; backgroundColor: string; fontColor: string;
}
export interface Advertisement {
  id: string; title: string; layout: string; playback: string; intervalMinutes: number;
  startsAt: null | string; endsAt: null | string; dailyStart: null | string; dailyEnd: null | string;
  media: { kind: string; file_id?: string; content?: string; text?: string; duration_seconds?: number; url?: string }[];
}
export class TerminalError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function probeTerminalServer(): Promise<void> {
  let response: Response;
  try {
    response = await fetch('/api/v1/utils/health-check', {
      cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(8000),
    });
  } catch (cause) {
    throw new TerminalError(cause instanceof DOMException && cause.name === 'TimeoutError'
      ? '请求超时，请检查连接后重试' : '网络连接失败，请检查网络后重试', 0);
  }
  if (!response.ok) throw new TerminalError(`HTTP ${response.status}`, response.status);
  const body = await response.json().catch(() => null);
  if (body !== true && body?.data !== true) {
    throw new TerminalError('服务器接口响应异常', response.status);
  }
}
export class TerminalClient {
  token = '';
  staff: Staff | undefined;
  private urls = new Map<string, string>();
  constructor(public terminalId: string) {}
  async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.token) headers['X-Device-Token'] = this.token;
    if (this.staff) headers.Authorization = `Bearer ${this.staff.accessToken}`;
    let response: Response;
    try {
      response = await fetch(`/api/v1/esop/${path}`, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
        credentials: 'omit', signal: AbortSignal.timeout(method === 'GET' ? 8000 : 30_000), cache: 'no-store',
      });
    } catch (cause) {
      throw new TerminalError(cause instanceof DOMException && cause.name === 'TimeoutError' ? '请求超时，请检查连接后重试' : '网络连接失败，请检查网络后重试', 0);
    }
    const raw = await response.json().catch(() => ({}));
    if (!response.ok || (raw.code !== undefined && raw.code !== 0)) {
      const detail = raw.details?.detail ?? raw.detail ?? raw.message ?? raw.msg;
      throw new TerminalError(typeof detail === 'string' ? detail : '请求失败，请检查输入或重试', response.status);
    }
    return ('data' in raw ? raw.data : raw) as T;
  }
  async connect() {
    const identity = await this.request<{ deviceToken: string; profile?: TerminalProfile }>(`web-terminal/${this.terminalId}`);
    this.token = identity.deviceToken;
    return identity.profile ?? this.request<TerminalProfile>('terminal/profile');
  }
  async file(fileId: string): Promise<{ url: string; expires_at: string }> {
    if (!/^[\da-f-]{36}$/i.test(fileId)) throw new Error('无效附件编号');
    const known = this.urls.get(fileId);
    if (known) return { url: known, expires_at: '' };
    const path = `/api/v1/esop/terminal/files/${fileId}`;
    let response: Response;
    try {
      response = await fetch(path, { headers: { 'X-Device-Token': this.token }, credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(60_000) });
    } catch { throw new TerminalError('网络连接失败，请连接网络后重试', 0); }
    if (!response.ok) throw new TerminalError('附件已失效或无权查看', response.status);
    const url = URL.createObjectURL(await response.blob());
    this.urls.set(fileId, url);
    return { url, expires_at: '' };
  }
  releaseFiles() { for (const url of this.urls.values()) URL.revokeObjectURL(url); this.urls.clear(); }
  disconnect() { this.token = ''; this.staff = undefined; this.releaseFiles(); }
  async alarm(payload: { requestId: string; typeCode: string; reason: string }) {
    if (!this.staff) throw new Error('请先登录员工账号');
    // Resolve the current plan on the server; browser task data may be stale.
    return this.request<Alarm>('terminal/alarms', 'POST', {
      requestId: payload.requestId, typeCode: payload.typeCode, reason: payload.reason,
    });
  }
  async report(payload: Record<string, unknown>) {
    if (!this.staff) throw new Error('请先登录员工账号');
    await this.request('terminal/reports', 'POST', payload);
  }
  async productionPlans(page = 1, keyword = '', category: 'active' | 'completed' = 'active') {
    if (!this.staff) throw new Error('请先登录员工账号');
    return this.request<{ items: ProductionPlan[]; total: number }>(
      `terminal/production-plans?page=${page}&page_size=30&keyword=${encodeURIComponent(keyword)}&category=${category}`,
    );
  }
  async selectProductionPlan(releaseId: string) {
    if (!this.staff) throw new Error('请先登录员工账号');
    await this.request(`terminal/production-plans/${encodeURIComponent(releaseId)}/select`, 'POST');
  }
}
