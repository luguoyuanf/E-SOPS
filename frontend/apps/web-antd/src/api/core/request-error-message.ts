const detailMessages: Record<string, string> = {
  'Email already exists': '该邮箱已注册，请直接登录或更换邮箱',
  'Tenant code already exists': '企业编码已存在，请更换后重试',
  'Mobile already exists': '该手机号已注册，请直接登录或更换手机号',
  'Customer is in use': '该客户已被使用，无法删除',
  'Product category is in use': '该产品分类下已有子分类或产品，无法删除',
  'Product is in use': '该产品已被业务单据使用，无法删除',
  'Product unit is in use': '该产品单位已被使用，无法删除',
  'Supplier is in use': '该供应商已被使用，无法删除',
  'Warehouse is in use': '该仓库已被使用，无法删除',
};

const codeMessages: Record<string, string> = {
  AUTH_RECOVERY_INVALID: '密码重置验证已失效，请重新验证邮箱',
  AUTH_PASSWORD_MISMATCH: '两次输入的密码不一致',
  AUTH_SLIDER_CAPTCHA_INVALID: '安全验证码无效或已过期，请重新验证',
  AUTH_EMAIL_UNAVAILABLE: '验证码邮件暂时无法发送，请稍后重试或联系管理员',
  AUTH_EMAIL_CODE_INVALID: '邮箱验证码错误或已过期，请重新获取',
  AUTH_EMAIL_CODE_REQUIRED: '请输入邮箱验证码',
  AUTH_EMAIL_RESEND_LIMITED: '验证码请求过于频繁，请稍后重试',
  AUTH_EMAIL_RATE_LIMITED: '邮件发送次数已达上限，请稍后重试',
  ERP_CATEGORY_CYCLE: '分类层级不能形成循环',
  ERP_DOCUMENT_STATE_CONFLICT: '当前单据状态不允许此操作',
  ERP_DOCUMENT_VERSION_CONFLICT: '单据已被更新，请刷新后重试',
  ERP_IDEMPOTENCY_CONFLICT: '操作正在处理或已提交，请勿重复提交',
  ERP_MASTER_DATA_INACTIVE: '所选基础资料已停用',
  ERP_MASTER_DATA_UNAVAILABLE: '所选基础资料不可用',
  ERP_RESOURCE_CODE_CONFLICT: '编码已存在，请更换后重试',
  ERP_RESOURCE_IN_USE: '该资料已被使用，无法删除',
  ERP_STOCK_INSUFFICIENT: '库存不足，无法完成操作',
  TENANT_FILE_QUOTA_EXCEEDED: '文件数量已达上限',
  TENANT_MEMBER_QUOTA_EXCEEDED: '成员数量已达上限',
  TENANT_STORAGE_QUOTA_EXCEEDED: '剩余存储空间不足，禁止上传，请联系购买存储扩容包',
};

const statusMessages: Record<number, string> = {
  400: '请求内容有误，请检查后重试',
  401: '登录状态已失效，请重新登录',
  403: '没有权限执行此操作',
  404: '数据不存在或已被删除',
  409: '数据存在冲突，请刷新后重试',
  413: '文件过大，请检查平台上传大小限制后重试',
  422: '输入内容有误，请检查后重试',
  429: '操作过于频繁，请稍后重试',
  500: '服务器内部错误，请稍后再试',
  502: '服务暂时不可用，请稍后再试',
  503: '服务暂时不可用，请稍后再试',
  504: '请求超时，请稍后重试',
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

export function requestErrorMessage(error: unknown, fallback: string): string {
  const source = asRecord(error);
  const response = asRecord(source.response);
  const body = asRecord(response.data);
  const payload = Object.keys(body).length ? body : source;
  const raw = [payload.error, payload.message, payload.detail, fallback].find(
    (value): value is string => typeof value === 'string' && !!value.trim(),
  );
  const code = typeof payload.code === 'string' ? payload.code : '';
  const status = typeof response.status === 'number' ? response.status : source.status;

  if (raw && detailMessages[raw]) return detailMessages[raw];
  if (raw && /[\u3400-\u9fff]/u.test(raw)) return raw;
  if (codeMessages[code]) return codeMessages[code];
  if (['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'].includes(code)
    || raw === 'Network Error' || raw === 'Failed to fetch') {
    return '网络连接失败，请检查网络后重试';
  }
  if (typeof status === 'number' && statusMessages[status]) return statusMessages[status];
  if (/[\u3400-\u9fff]/u.test(fallback)) return fallback;
  return '操作失败，请稍后再试';
}
