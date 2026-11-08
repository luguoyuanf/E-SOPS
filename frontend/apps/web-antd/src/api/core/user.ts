import type { UserInfo } from '@vben/types';

import { getCurrentUserApi } from './auth';

export const DEFAULT_AVATAR = '/images/avatar-v1.webp';

export function mapCurrentUserToUserInfo(
  user: Awaited<ReturnType<typeof getCurrentUserApi>>,
) {
  const role = user.is_superuser ? 'super' : 'user';

  return {
    avatar: user.avatar_url || DEFAULT_AVATAR,
    desc: user.is_superuser ? 'Super administrator' : 'User',
    homePath: '/dashboard',
    realName: user.full_name || user.username || user.email || user.id,
    roles: [role],
    token: '',
    tenantId: user.tenant_id,
    userId: user.id,
    username: user.username || user.email || user.id,
  } satisfies UserInfo & { tenantId?: string | null };
}

/**
 * 获取用户信息
 */
export async function getUserInfoApi() {
  return mapCurrentUserToUserInfo(await getCurrentUserApi());
}
