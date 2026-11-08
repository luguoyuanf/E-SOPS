import { beforeEach, describe, expect, it, vi } from 'vitest';

const { post, get } = vi.hoisted(() => ({post:vi.fn(),get:vi.fn()}));
vi.mock('#/api/request', () => ({baseRequestClient:{post},requestClient:{get}}));

import { loginApi } from './auth';
import { loginErrorMessageKey } from './login-error';
import { mapCurrentUserToUserInfo } from './user';
import { listUserDepartmentOptionsApi, listUserPostOptionsApi } from './users';

describe('password login HTTP contract', () => {
  beforeEach(()=>{ post.mockReset(); });
  it('reads the backend raw Token from the base Axios response', async()=>{
    post.mockResolvedValue({data:{access_token:'synthetic-test-token',token_type:'bearer',tenant_id:'test-tenant'}});
    const result=await loginApi({username:'test@example.com',password:'synthetic-password',tenant_code:'default',captcha_verification:'synthetic-verification'});
    expect(result).toEqual({accessToken:'synthetic-test-token'});
    expect(post.mock.calls[0]?.[0]).toBe('/login/access-token');
    const form=post.mock.calls[0]?.[1] as URLSearchParams;
    expect(form.get('tenant_code')).toBe('default');
    expect(form.get('captcha_verification')).toBe('synthetic-verification');
    expect(post.mock.calls[0]?.[2].headers['Content-Type']).toBe('application/x-www-form-urlencoded');
  });
  it('preserves the base-client unwrapped authentication error for inline display',async()=>{
    const failure={code:'AUTH_INVALID_CREDENTIALS',message:'Incorrect email or password'};
    post.mockRejectedValue(failure);
    const received = await loginApi({username:'test@example.com',password:'wrong'}).catch(error => error);
    expect(received).toEqual(failure);
    expect(loginErrorMessageKey(failure)).toBe('authentication.loginError.invalidCredentials');
  });
  it('explains when an account has no back-office menu access', () => {
    expect(loginErrorMessageKey({code: 'BACKOFFICE_MENU_REQUIRED'})).toBe('authentication.loginError.backofficeMenuRequired');
  });
  it('sends a username identifier without requiring an email address', async () => {
    post.mockResolvedValue({data:{access_token:'synthetic-test-token',token_type:'bearer'}});
    expect(await loginApi({username:'tangyun',password:'synthetic-password',tenant_code:'test'})).toEqual({accessToken:'synthetic-test-token'});
    expect((post.mock.calls[0]?.[1] as URLSearchParams).get('username')).toBe('tangyun');
  });

  it('displays the username and falls back to email for existing accounts', () => {
    type CurrentUser = Parameters<typeof mapCurrentUserToUserInfo>[0];
    const user = {id:'synthetic-id',email:'tangyun@test.example.com',is_superuser:false,is_active:true,full_name:null,username:'tangyun'} as CurrentUser;
    expect(mapCurrentUserToUserInfo(user).username).toBe('tangyun');
    expect(mapCurrentUserToUserInfo(user).realName).toBe('tangyun');
    const legacy = {...user,username:null} as CurrentUser;
    expect(mapCurrentUserToUserInfo(legacy).username).toBe('tangyun@test.example.com');
  });

});

describe('tenant-scoped user assignment option APIs', () => {
  beforeEach(() => { get.mockReset(); });
  it.each([
    ['/users/department-options', listUserDepartmentOptionsApi],
    ['/users/post-options', listUserPostOptionsApi],
  ] as const)('returns the raw option array from %s without management list calls', async (path, api) => {
    const options = [{id:'synthetic-option',name:'Current tenant option'}];
    get.mockResolvedValue(options);
    expect(await api()).toBe(options);
    expect(get).toHaveBeenCalledExactlyOnceWith(path);
  });
});
