import type {
  LoginLogPublic,
  LoginLogsPublic,
  OperationLogPublic,
  OperationLogsPublic,
} from '#/api/generated';

import { requestClient } from '#/api/request';

export type LoginLogRecord = LoginLogPublic;
export type LoginLogListResult = LoginLogsPublic;

export type OperationLogRecord = OperationLogPublic;
export type OperationLogListResult = OperationLogsPublic;

export interface LoginLogListParams {
  created_from?: string;
  created_to?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
  status?: string;
}

export interface OperationLogListParams {
  created_from?: string;
  created_to?: string;
  keyword?: string;
  method?: string;
  page?: number;
  page_size?: number;
  status_code?: number;
}

export function listLoginLogsApi(params: LoginLogListParams = {}) {
  return requestClient.get<LoginLogListResult>('/logs/login', { params });
}

export function listOperationLogsApi(params: OperationLogListParams = {}) {
  return requestClient.get<OperationLogListResult>('/logs/operation', {
    params,
  });
}
