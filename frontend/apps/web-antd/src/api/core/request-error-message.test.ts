import { describe, expect, it } from 'vitest';

import { requestErrorMessage } from './request-error-message';

describe('request error messages shown to users', () => {
  it('explains registration conflicts using the server detail', () => {
    expect(requestErrorMessage({ response: { status: 409, data: { detail: 'Email already exists' } } }, 'Request failed'))
      .toBe('该邮箱已注册，请直接登录或更换邮箱');
    expect(requestErrorMessage({ response: { status: 409, data: { detail: 'Tenant code already exists' } } }, 'Request failed'))
      .toBe('企业编码已存在，请更换后重试');
  });
  it('explains an upload rejected by a proxy size limit', () => {
    expect(requestErrorMessage({ response: { status: 413, data: '<html>413 Request Entity Too Large</html>' } }, 'Request failed'))
      .toBe('文件过大，请检查平台上传大小限制后重试');
  });
  it('explains why a referenced product category cannot be deleted', () => {
    expect(requestErrorMessage({
      response: {
        data: { code: 'ERP_RESOURCE_IN_USE', message: 'Product category is in use' },
        status: 409,
      },
    }, 'Request failed')).toBe('该产品分类下已有子分类或产品，无法删除');
  });

  it('uses a specific Chinese message for other known business conflicts', () => {
    expect(requestErrorMessage({ code: 'ERP_RESOURCE_IN_USE', message: 'Product unit is in use' }, 'Request failed'))
      .toBe('该产品单位已被使用，无法删除');
  });

  it('preserves an already localized message', () => {
    expect(requestErrorMessage({
      response: { data: { code: 'CONFLICT', message: '当前分类不能删除' }, status: 409 },
    }, 'Request failed')).toBe('当前分类不能删除');
  });

  it('never exposes an unknown English server detail', () => {
    expect(requestErrorMessage({
      response: { data: { code: 'CONFLICT', message: 'SQL constraint failed' }, status: 409 },
    }, 'Request failed')).toBe('数据存在冲突，请刷新后重试');
    expect(requestErrorMessage({
      response: { data: { message: 'Internal server error' }, status: 500 },
    }, 'Request failed')).toBe('服务器内部错误，请稍后再试');
    expect(requestErrorMessage(new Error('Network Error'), 'Network Error'))
      .toBe('网络连接失败，请检查网络后重试');
  });
});
