import type { ListResult, OperationAttachment } from './esop';

import { requestClient } from '#/api/request';
import { exportTimezoneHeaders } from '#/utils/export-timezone';

export interface ReportSopPreview {
  product_id: string;
  operation_id: string;
  title: string;
  version: number;
  attachments: OperationAttachment[];
}
export function getReportSopPreview(reportId: string) {
  return requestClient.get<ReportSopPreview>(`/esop/reports/${reportId}/sop`);
}
export function getReportSopFileAccess(reportId: string, fileId: string) {
  return requestClient.get<{ url: string; expires_at: string }>(`/esop/reports/${reportId}/sop/files/${fileId}/access`);
}

export interface Terminal {
  created_at: string;
  id: string;
  device_code: string;
  serial_number: string;
  device_name: null | string;
  station_id: null | string;
  last_seen_at: null | string;
  last_ip: null | string;
  app_version: null | string;
  is_active: boolean;
  is_online: boolean;
}

export interface ActivationKey {
  id: string;
  tenant_id: null | string;
  key: null | string;
  device_code: null | string;
  used_terminal_id: null | string;
  channel_id: null | string;
  hardware_model_id: null | string;
  is_used: boolean;
  created_at: string;
  used_at: null | string;
}

export interface IssuedActivationKey extends Omit<ActivationKey, 'key'> {
  key: string;
}

export interface ProductionReport {
  revision: number;
  submitted_by?: null | string;
  terminal_id?: null | string;
  id: string;
  order_id: string;
  order_code: string;
  station_id: string;
  station_position: number;
  sop_id: string;
  sop_title: string;
  sop_version: number;
  staff_user_id: string;
  staff_name: string;
  input_qty: number;
  good_qty: number;
  defect_qty: number;
  occurred_at: string;
  created_at: string;
}

export interface OrderProgress {
  order_id: string;
  quantity: number;
  input_total: number;
  good_total: number;
  bad_total: number;
  completion_rate: number;
  operations: { operation_id: string; operation_name: string; completed_total: number; bad_total: number; completion_rate: number }[];
}

export interface Alarm {
  staff_name: null | string;
  terminal_name: null | string;
  station_name: null | string;
  resolved_at: null | string;
  resolved_by: null | string;
  id: string;
  terminal_id: string;
  station_id: string;
  level: string;
  reason: null | string;
  type_code: null | string;
  type_name: null | string;
  created_at: string;
}

export interface AlarmType {
  code: string;
  name: string;
  source: 'builtin' | 'platform' | 'tenant';
  enabled: boolean;
  sort: number;
  built_in: boolean;
  tenant_owned: boolean;
}

export interface AlarmTypeList {
  items: AlarmType[];
  can_manage_global: boolean;
}

export function listTerminals() {
  return requestClient.get<ListResult<Terminal>>('/esop/terminals');
}

export function bindTerminal(terminalId: string, stationId: null | string) {
  return requestClient.put<Terminal>(`/esop/terminals/${terminalId}/station`, {
    station_id: stationId,
  });
}

export function updateTerminalName(terminalId: string, deviceName: string) {
  return requestClient.put<Terminal>(`/esop/terminals/${terminalId}/name`, {
    device_name: deviceName,
  });
}

export interface ActivationFilters { is_used?: boolean; tenant_id?: string; channel_id?: string }
export function listActivationKeys(params: ActivationFilters = {}) {
  return requestClient.get<ListResult<ActivationKey>>('/esop/activation-keys', { params });
}
export function exportActivationKeys(params: ActivationFilters) {
  return requestClient.post<Blob>('/esop/activation-keys/export', {}, { headers: exportTimezoneHeaders(), params, responseType: 'blob' });
}
export function unbindActivationKey(id: string, reason: string) {
  return requestClient.post<ActivationKey>(`/esop/activation-keys/${id}/unbind`, { reason });
}

export function issueActivationKey(data: { tenant_id?: string; channel_id?: string; hardware_model_id?: string } = {}) {
  return requestClient.post<IssuedActivationKey>('/esop/activation-keys', data);
}

export function listReports(params: {
  end_at?: string;
  order_id?: string;
  line_id?: string;
  sop_id?: string;
  staff_user_id?: string;
  start_at?: string;
  station_id?: string;
} = {}) {
  return requestClient.get<ListResult<ProductionReport>>('/esop/reports', { params });
}

export function listOrderProgress() {
  return requestClient.get<{ items: OrderProgress[] }>('/esop/orders/progress');
}

export function listAlarms() {
  return requestClient.get<ListResult<Alarm>>('/esop/alarms');
}
export function resolveAlarm(id: string) {
  return requestClient.post<Alarm>(`/esop/alarms/${id}/resolve`);
}

export function listAlarmTypes() {
  return requestClient.get<AlarmTypeList>('/esop/alarm-types');
}

export function createTenantAlarmType(name: string) {
  return requestClient.post<AlarmType>('/esop/alarm-types', { name });
}

export function renameTenantAlarmType(code: string, name: string) {
  return requestClient.request<AlarmType>(`/esop/alarm-types/${encodeURIComponent(code)}`, { data: { name }, method: 'PATCH' });
}

export function createPlatformAlarmType(name: string) {
  return requestClient.post<AlarmType>('/esop/platform/alarm-types', { name });
}

export function renamePlatformAlarmType(code: string, name: string) {
  return requestClient.request<AlarmType>(`/esop/platform/alarm-types/${encodeURIComponent(code)}`, { data: { name }, method: 'PATCH' });
}

export function saveAlarmTypePreferences(items: Pick<AlarmType, 'code' | 'enabled' | 'sort'>[]) {
  return requestClient.put<AlarmTypeList>('/esop/alarm-types/preferences', { items });
}


export interface ReportFilterOption { value: string; label: string }
export interface ReportFilterOptions {
  orders: ReportFilterOption[];
  lines: ReportFilterOption[];
  stations: (ReportFilterOption & { line_id: string })[];
  staff: ReportFilterOption[];
}
export function listReportFilterOptions() {
  return requestClient.get<ReportFilterOptions>('/esop/reports/filter-options');
}


export interface WebReportTask {
  release_id: string;
  order_code: string;
  plan_code: string;
  line_name: string;
  station_id: string;
  station_name: string;
  operation_id: string;
  operation_name: string;
  sop_id: string;
  sop_title: string;
  sop_version: number;
}
export interface WebReportOptions {
  can_select_staff: boolean;
  current_user_id: string;
  staff: ReportFilterOption[];
  tasks: WebReportTask[];
}
export interface WebReportInput {
  request_id: string;
  release_id: string;
  station_id: string;
  operation_id: string;
  sop_id: string;
  staff_user_id: string;
  input_qty: number;
  good_qty: number;
  defect_qty: number;
}
export function getWebReportOptions() {
  return requestClient.get<WebReportOptions>('/esop/reports/entry-options');
}
export function submitWebReport(data: WebReportInput) {
  return requestClient.post<ProductionReport>('/esop/reports', data);
}


export interface ReportCorrectionOptions { can_edit: boolean; staff: ReportFilterOption[] }
export interface ReportCorrectionInput {
  expected_revision: number;
  staff_user_id: string;
  input_qty: number;
  good_qty: number;
  defect_qty: number;
  reason: string;
}
export interface ReportSnapshot {
  is_deleted?: boolean;
  staff_user_id: string;
  staff_name: string;
  input_qty: number;
  good_qty: number;
  defect_qty: number;
}
export interface ReportRevision {
  id: string;
  report_id: string;
  revision: number;
  reason: string;
  changed_by: string;
  changed_by_name: string;
  changed_at: string;
  before: ReportSnapshot;
  after: ReportSnapshot;
}
export function getReportCorrectionOptions() {
  return requestClient.get<ReportCorrectionOptions>('/esop/reports/correction-options');
}
export function correctReport(id: string, data: ReportCorrectionInput) {
  return requestClient.request<ProductionReport>(`/esop/reports/${id}`, { method: 'PATCH', data });
}
export function listReportRevisions(id: string) {
  return requestClient.get<ListResult<ReportRevision>>(`/esop/reports/${id}/revisions`);
}


export interface ReportChange {
  kind: "edit" | "delete";
  id: string;
  report_id: string;
  order_code: string;
  sop_title: string;
  requested_by_name: string;
  requested_at: string;
  reason: string;
  status: string;
  before: Record<string, number | string>;
  after: Record<string, number | string>;
  reviewed_by_name: string | null;
  review_note: string | null;
}
export function listReportChanges(params: { status: string; page: number; page_size: number }) {
  return requestClient.get<ListResult<ReportChange>>('/esop/report-changes', { params });
}
export function reviewReportChange(id: string, data: { approve: boolean; note: string }) {
  return requestClient.post<ReportChange>(`/esop/report-changes/${id}/review`, data);
}

export function getWebTerminalAccess() {
  return requestClient.get<{ allowed: boolean }>('/esop/terminals/web-access');
}
export function openWebTerminal(id: string) {
  return requestClient.post<{ path: string }>(`/esop/terminals/${id}/open-web`);
}
