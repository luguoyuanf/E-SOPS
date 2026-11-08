import type { ListResult } from './esop';

import { requestClient } from '#/api/request';
import { exportTimezoneHeaders } from '#/utils/export-timezone';

export interface Workshop {
  id: string;
  code: string;
  name: string;
  created_at: null | string;
}

export interface Station {
  id: string;
  row: number;
  column: number;
  position: number;
  name?: string;
  terminal_code: null | string;
  terminal_active?: boolean;
}

export interface ProductionLine {
  id: string;
  workshop_id: string;
  code: string;
  name: string;
  layout: 'double' | 'single';
  station_count: number;
  numbering_mode?: "odd_even" | "sequential";
  stations: Station[];
  created_at: null | string;
}

export interface ProductionOrder {
  id: string;
  code: string;
  product_id: string;
  quantity: number;
  due_date: string;
  created_at: string;
  is_published: boolean;
  product_sop_version_id: null | string;
  operation_ids: null | string[];
  production_status: 'completed' | 'in_progress' | 'unplanned' | 'waiting';
}

export interface PlanAssignment {
  operation_id: string;
  station_id: string;
  sop_id: string;
}

export interface ProductionPlan {
  created_at: string;
  input_total: number;
  good_total: number;
  bad_total: number;
  completion_rate: number;
  id: string;
  code: string;
  order_id: string;
  quantity: number;
  line_id: string;
  route_id: null | string;
  product_sop_version_id: null | string;
  product_sop_version: null | number;
  status: 'cancelled' | 'completed' | 'draft' | 'expired' | 'paused' | 'published';
  group_id: null | string;
  group_position: null | number;
  start_at: null | string;
  end_at: null | string;
  assignments: PlanAssignment[];
}

export interface ReleaseAssignment extends PlanAssignment {
  operation_name: string;
  station_position: number;
  sop_title: string;
  sop_version: number;
}

export interface ProductionRelease {
  product_sop_version_id: null | string;
  product_sop_version: null | number;
  id: string;
  plan_id: string;
  version: number;
  order_id: string;
  line_id: string;
  product_id: string;
  quantity: number;
  due_date: string;
  assignments: ReleaseAssignment[];
  published_at: string;
}

export interface PlanStationProgress {
  station_id: string;
  station_name: string;
  station_position: number;
  terminal_code: null | string;
  terminal_active: boolean;
  is_assigned: boolean;
  input_total: number;
  good_total: number;
  bad_total: number;
  last_report_at: null | string;
}

export interface PlanOperationProgress {
  operation_id: string;
  operation_name: string;
  is_assigned: boolean;
  input_total: number;
  good_total: number;
  bad_total: number;
  completed_total: number;
  remaining_qty: number;
  completion_rate: number;
  stations: PlanStationProgress[];
}

export interface PlanTaskDetail {
  plan: ProductionPlan;
  release: ProductionRelease;
  operations: PlanOperationProgress[];
}

export function listWorkshops() {
  return requestClient.get<ListResult<Workshop>>('/esop/workshops');
}

export function saveWorkshop(data: Pick<Workshop, 'code' | 'name'>, id?: string) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id
    ? requestClient.put<Workshop>(`/esop/workshops/${id}`, payload)
    : requestClient.post<Workshop>('/esop/workshops', payload);
}

export function listLines() {
  return requestClient.get<ListResult<ProductionLine>>('/esop/lines');
}

export function saveLine(
  data: Pick<ProductionLine, 'code' | 'layout' | 'name' | 'numbering_mode' | 'station_count' | 'workshop_id'> & { station_names?: Record<number, string> },
  id?: string,
) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id
    ? requestClient.put<ProductionLine>(`/esop/lines/${id}`, payload)
    : requestClient.post<ProductionLine>('/esop/lines', payload);
}

export interface OrderFilters {
  keyword?: string;
  product_id?: string;
  is_published?: boolean;
  created_at_from?: string;
  created_at_to?: string;
  due_date_from?: string;
  due_date_to?: string;
}

export function listOrders(params: OrderFilters & { page?: number; page_size?: number } = {}) {
  return requestClient.get<ListResult<ProductionOrder>>('/esop/orders', { params });
}

export function exportOrders(data: OrderFilters & { ids: string[] }) {
  return requestClient.post<Blob>('/esop/orders/export', data, { headers: exportTimezoneHeaders(), responseType: 'blob' });
}

export function saveOrder(
  data: Pick<ProductionOrder, 'code' | 'due_date' | 'product_id' | 'quantity' | 'product_sop_version_id' | 'operation_ids'>,
  id?: string,
) {
  const payload = { ...data, code: data.code.trim() || undefined };
  return id
    ? requestClient.put<ProductionOrder>(`/esop/orders/${id}`, payload)
    : requestClient.post<ProductionOrder>('/esop/orders', payload);
}

export function confirmOrderOperations(id: string, data: Pick<ProductionOrder, 'product_sop_version_id' | 'operation_ids'>) {
  return requestClient.post<ProductionOrder>(`/esop/orders/${id}/confirm-operations`, data);
}

export function getOrderOperations(id: string) {
  return requestClient.get<ApprovedProductOperations>(`/esop/orders/${id}/operations`);
}

export function listPlans(params?: { created_from?: string; created_to?: string; keyword?: string; page?: number; page_size?: number; status?: ProductionPlan['status'] }) {
  return requestClient.get<ListResult<ProductionPlan>>('/esop/plans', { params });
}

export function getPlan(id: string) {
  return requestClient.get<ProductionPlan>(`/esop/plans/${id}`);
}

export function getPlanRelease(id: string) {
  return requestClient.get<ProductionRelease>(`/esop/plans/${id}/release`);
}

export function getPlanTask(id: string) {
  return requestClient.get<PlanTaskDetail>(`/esop/plans/${id}/task`);
}

export function removeUnboundPlanStation(id: string, stationId: string) {
  return requestClient.delete<PlanTaskDetail>(`/esop/plans/${id}/assignments/${stationId}`);
}

export function savePlan(
  data: Pick<ProductionPlan, 'assignments' | 'end_at' | 'line_id' | 'order_id' | 'product_sop_version_id' | 'quantity' | 'route_id' | 'start_at'> & { code?: string | null },
  id?: string,
) {
  return id
    ? requestClient.put<ProductionPlan>(`/esop/plans/${id}`, data)
    : requestClient.post<ProductionPlan>('/esop/plans', data);
}

export function publishPlan(id: string) {
  return requestClient.post<ProductionRelease>(`/esop/plans/${id}/publish`);
}

export function pausePlan(id: string) {
  return requestClient.post<ProductionPlan>(`/esop/plans/${id}/pause`);
}

export function resumePlan(id: string) {
  return requestClient.post<ProductionPlan>(`/esop/plans/${id}/resume`);
}

export function cancelPlan(id: string) {
  return requestClient.post<ProductionPlan>(`/esop/plans/${id}/cancel`);
}

export interface OrderAllocation {
  order_quantity: number;
  allocated_quantity: number;
  approved_supplement_quantity: number;
  remaining_quantity: number;
  operations: { operation_id: string; allocated_quantity: number; remaining_quantity: number; plan_codes: string[] }[];
}

export interface OrderSupplement {
  id: string;
  order_id: string;
  quantity: number;
  reason: string;
  status: 'approved' | 'pending' | 'rejected';
  requested_by: string;
  reviewed_by: null | string;
  review_note: null | string;
  created_at: string;
  reviewed_at: null | string;
}

export function getOrderAllocation(id: string) {
  return requestClient.get<OrderAllocation>(`/esop/orders/${id}/allocation`);
}

export function listOrderSupplements(orderId: string) {
  return requestClient.get<ListResult<OrderSupplement>>('/esop/order-supplements', { params: { order_id: orderId } });
}

export function requestOrderSupplement(data: Pick<OrderSupplement, 'order_id' | 'quantity' | 'reason'>) {
  return requestClient.post<OrderSupplement>('/esop/order-supplements', data);
}

export function reviewOrderSupplement(id: string, approve: boolean, note = '') {
  return requestClient.post<OrderSupplement>(`/esop/order-supplements/${id}/review`, { approve, note });
}

export interface PlanGroup {
  switch_mode: "together" | "independent";
  created_at: string;
  id: string;
  name: string;
  start_at: null | string;
  plan_ids: string[];
  is_paused: boolean;
}

export function listPlanGroups() {
  return requestClient.get<ListResult<PlanGroup>>('/esop/plan-groups');
}

export function savePlanGroup(data: Pick<PlanGroup, 'name' | 'plan_ids' | 'start_at' | 'switch_mode'>, id?: string) {
  return id
    ? requestClient.put<PlanGroup>(`/esop/plan-groups/${id}`, data)
    : requestClient.post<PlanGroup>('/esop/plan-groups', data);
}

export function deletePlanGroup(id: string) {
  return requestClient.delete(`/esop/plan-groups/${id}`);
}

export function resumePlanGroup(id: string) {
  return requestClient.post<PlanGroup>(`/esop/plan-groups/${id}/resume`);
}

export function pausePlanGroup(id: string) {
  return requestClient.post<PlanGroup>(`/esop/plan-groups/${id}/pause`);
}

export function startPlanGroupNow(id: string) {
  return requestClient.post<PlanGroup>(`/esop/plan-groups/${id}/start-now`);
}

export function listReleases() {
  return requestClient.get<ListResult<ProductionRelease>>('/esop/releases');
}


export interface ApprovedProductVersion {
  id: string;
  version: number;
  reviewed_at: null | string;
}

export interface ApprovedProductOperation {
  operation_id: string;
  code: string;
  name: string;
  sop_id: string;
  sop_title: string;
  sop_version: number;
}

export interface ApprovedProductOperations {
  product_id: string;
  product_sop_version_id: string;
  version: number;
  operations: ApprovedProductOperation[];
}

export function listApprovedProductVersions(productId: string) {
  return requestClient.get<ListResult<ApprovedProductVersion>>(`/esop/products/${productId}/approved-versions`);
}

export function getApprovedProductOperations(productId: string, versionId: string) {
  return requestClient.get<ApprovedProductOperations>(`/esop/products/${productId}/approved-operations`, {
    params: { version_id: versionId },
  });
}

export function deleteWorkshop(id: string) {
  return requestClient.delete(`/esop/workshops/${id}`);
}

export function deleteOrder(id: string) {
  return requestClient.delete(`/esop/orders/${id}`);
}

export function deleteLine(id: string) {
  return requestClient.delete(`/esop/lines/${id}`);
}
