import type {
  DepartmentPublic,
  PostPublic,
  UserCreate,
  UserPublic,
  UsersPublic,
  UserUpdate,
} from '#/api/generated';

import { requestClient } from '#/api/request';

export type UserRecord = UserPublic;

export type UserListResult = UsersPublic;

export interface UserListParams {
  created_from?: string;
  created_to?: string;
  tenant_id?: string;
  department_id?: string;
  is_active?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export type UserCreatePayload = UserCreate;

export type UserUpdatePayload = UserUpdate;

export function listUsersApi(params: UserListParams) {
  return requestClient.get<UserListResult>('/users', { params });
}

export function listUserDepartmentOptionsApi(tenantId?: string) {
  return requestClient.get<DepartmentPublic[]>('/users/department-options', { params: { tenant_id: tenantId } });
}

export function listUserPostOptionsApi(tenantId?: string) {
  return requestClient.get<PostPublic[]>('/users/post-options', { params: { tenant_id: tenantId } });
}

export function createUserApi(data: UserCreatePayload) {
  return requestClient.post<UserRecord>('/users', data);
}

export function updateUserApi(userId: string, data: UserUpdatePayload, tenantId?: string) {
  return requestClient.request<UserRecord>(`/users/${userId}`, {
    data,
    method: 'PATCH',
    params: { tenant_id: tenantId },
  });
}

export function deleteUserApi(userId: string, tenantId?: string) {
  return requestClient.delete<void>(`/users/${userId}`, { params: { tenant_id: tenantId } });
}

export function resetUserMfaApi(userId: string, tenantId?: string) {
  return requestClient.post<{ message: string }>(`/users/${userId}/mfa/reset`, undefined, { params: { tenant_id: tenantId } });
}

export function importUsersApi(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return requestClient.post<{
    errors: Array<{ error: string; row: number }>;
    failed: number;
    success: number;
    total: number;
  }>('/users/import', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
}

export const usersExportPath = '/users/export';
export const usersImportTemplatePath = '/users/import-template';

export function uploadUserAvatarApi(userId: string, file: File, tenantId?: string) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<UserRecord>(`/users/${userId}/avatar`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params: { tenant_id: tenantId },
  });
}
