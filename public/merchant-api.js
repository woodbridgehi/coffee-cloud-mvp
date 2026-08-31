/* ============================================================
   Coffee Cloud · B 端客户后台 · 真实 API 适配器
   - 基地址：同源 /api/v1/merchant；credentials: 'same-origin'。
   - 会话 Cookie 为服务端 HttpOnly，前端不可读；CSRF token 仅存
     本适配器内存变量，所有已登录写请求自动附 X-CSRF-Token。
   - 正常响应 {data, meta}；错误 {error:{code,message,fields,
     requestId}}。非 JSON（代理 HTML 错误页）转为通用错误，不注入 DOM。
   - 401 抛出后由应用层清理状态；本适配器不自动回退演示模式。
   ============================================================ */

import { inclusiveEndToExclusive } from './merchant-format.js';

export class MerchantError extends Error {
  constructor(status, code, message, options = {}) {
    super(message);
    this.name = 'MerchantError';
    this.status = status;
    this.code = code || `HTTP_${status}`;
    this.fields = options.fields || null;
    this.requestId = options.requestId || null;
    this.retryAfterMs = options.retryAfterMs || null;
    this.aborted = Boolean(options.aborted);
  }
}

function friendlyMessage(status, errBody) {
  const serverMessage = errBody && typeof errBody.message === 'string' && errBody.message.trim() ? errBody.message : '';
  if (serverMessage) return serverMessage;
  switch (status) {
    case 400: return '请求参数不正确';
    case 401: return '登录已过期或未登录，请重新登录';
    case 403: return '当前角色没有执行该操作的权限';
    case 404: return '资源不存在或没有访问权限';
    case 409: return '操作与当前状态冲突，请刷新后重试';
    case 422: return '提交内容未通过校验';
    case 429: return '请求过于频繁，请稍后再试';
    case 503: return '服务暂不可用或尚未配置';
    default: return `请求失败（HTTP ${status}）`;
  }
}

function parseRetryAfter(headerValue) {
  if (!headerValue) return null;
  const seconds = Number(headerValue);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const date = Date.parse(headerValue);
  if (Number.isFinite(date)) return Math.max(0, date - Date.now());
  return null;
}

function parseContentDisposition(headerValue) {
  if (!headerValue) return null;
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(headerValue);
  if (utf8Match) {
    try { return decodeURIComponent(utf8Match[1]); } catch (_) { /* fallthrough */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(headerValue);
  return plain ? plain[1] : null;
}

export function buildQuery(params) {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

/** 日期区间（含当日）转 API 参数：to 转为不含当日的右边界。 */
export function periodToApiParams(period) {
  if (!period || !period.from || !period.to) return {};
  return { from: period.from, to: inclusiveEndToExclusive(period.to) };
}

export function createRealAdapter() {
  const BASE = '/api/v1/merchant';
  let csrfToken = '';
  const controllers = new Set();

  function captureCsrf(body) {
    const candidate = body && body.data && body.data.csrfToken;
    if (typeof candidate === 'string' && candidate) csrfToken = candidate;
    return body;
  }

  async function perform(path, { method = 'GET', body, idempotencyKey, accept = 'application/json' } = {}) {
    const controller = new AbortController();
    controllers.add(controller);
    const headers = { Accept: accept };
    let payload;
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
    if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;

    let response;
    try {
      response = await fetch(`${BASE}${path}`, {
        method, headers, credentials: 'same-origin', cache: 'no-store', body: payload, signal: controller.signal,
      });
    } catch (err) {
      controllers.delete(controller);
      if (err && err.name === 'AbortError') {
        throw new MerchantError(0, 'ABORTED', '请求已取消', { aborted: true });
      }
      throw new MerchantError(0, 'NETWORK', '网络请求失败，请检查网络连接后重试');
    }

    try {
    // Successful downloads retain their body for the caller. Reading text here
    // consumes the stream and makes the subsequent blob() fail.
    if (response.ok && accept !== 'application/json') return { parsed: null, response };
    const text = await response.text();
    let parsed = null;
    if (text) {
      try { parsed = JSON.parse(text); } catch (_) { parsed = null; }
    }
    if (!response.ok) {
      const errBody = parsed && parsed.error ? parsed.error : null;
      throw new MerchantError(response.status, errBody ? errBody.code : '', friendlyMessage(response.status, errBody), {
        fields: errBody ? errBody.fields : null,
        requestId: errBody ? errBody.requestId : null,
        retryAfterMs: parseRetryAfter(response.headers.get('Retry-After')),
      });
    }
    if (!parsed || typeof parsed !== 'object' || !Object.hasOwn(parsed, 'data')) {
      throw new MerchantError(502, 'BAD_RESPONSE', '服务器响应格式不正确，请稍后重试');
    }
    return { parsed, response };
    } finally {
      controllers.delete(controller);
    }
  }

  async function json(path, opts = {}) {
    const { parsed } = await perform(path, opts);
    const body = parsed && typeof parsed === 'object' ? parsed : {};
    return captureCsrf(body);
  }

  function normalizeList(body) {
    const items = Array.isArray(body && body.data) ? body.data : [];
    const meta = (body && body.meta) || {};
    return { items, nextCursor: meta.nextCursor ?? null, total: meta.total };
  }

  /* ---------------- 适配器方法（与演示适配器同名同形） ---------------- */

  const adapter = {
    kind: 'real',

    abortAll() { for (const c of Array.from(controllers)) c.abort(); },
    clearSession() { csrfToken = ''; },

    /* ---- 认证与会话 ---- */
    /* 无需登录的非敏感配置：注册模式 / 密码长度 / 用户名规则 / 邮件能力。 */
    async authConfig() { return (await json('/auth/config')).data; },
    async register(body) { return (await json('/auth/register', { method: 'POST', body })).data; },
    async verifyEmail(body) { return (await json('/auth/verify-email', { method: 'POST', body })).data; },
    async login(body) { return (await json('/auth/login', { method: 'POST', body })).data; },
    async forgotPassword(body) { return (await json('/auth/forgot-password', { method: 'POST', body })).data; },
    async resetPassword(body) { return (await json('/auth/reset-password', { method: 'POST', body })).data; },
    async acceptInvitation(body) { return (await json('/auth/accept-invitation', { method: 'POST', body })).data; },
    async logout() { return (await json('/auth/logout', { method: 'POST', body: {} })).data; },
    async revokeOtherSessions() { return (await json('/auth/revoke-other-sessions', { method: 'POST', body: {} })).data; },
    async reauthenticate(body) { return (await json('/auth/reauthenticate', { method: 'POST', body })).data; },
    async getSession() { return (await json('/session')).data; },
    async switchTenant(membershipId) { return (await json('/session/tenant', { method: 'POST', body: { membershipId } })).data; },

    /* ---- 总览 ---- */
    async dashboard(params) { return (await json(`/dashboard${buildQuery(params)}`)).data; },

    /* ---- 设备 ---- */
    async listDevices(params) { return normalizeList(await json(`/devices${buildQuery(params)}`)); },
    async getDevice(id) { return (await json(`/devices/${encodeURIComponent(id)}`)).data; },
    async claimDevice(body, idempotencyKey) { return (await json('/devices/claim', { method: 'POST', body, idempotencyKey })).data; },
    async updateDevice(id, body) { return (await json(`/devices/${encodeURIComponent(id)}`, { method: 'PATCH', body })).data; },
    async deviceLifecycle(id, body) { return (await json(`/devices/${encodeURIComponent(id)}/lifecycle`, { method: 'POST', body })).data; },
    async sendDeviceCommand(id, body, idempotencyKey) {
      return (await json(`/devices/${encodeURIComponent(id)}/commands`, { method: 'POST', body, idempotencyKey })).data;
    },
    async getDeviceCommand(id, commandId) { return (await json(`/devices/${encodeURIComponent(id)}/commands/${encodeURIComponent(commandId)}`)).data; },
    async createUnbindRequest(id, body) { return (await json(`/devices/${encodeURIComponent(id)}/unbind-requests`, { method: 'POST', body })).data; },
    async createTransferRequest(id, body, idempotencyKey) {
      return (await json(`/devices/${encodeURIComponent(id)}/transfer-requests`, { method: 'POST', body, idempotencyKey })).data;
    },
    async listTransfers(params) { return normalizeList(await json(`/transfers${buildQuery(params)}`)); },
    async acceptTransfer(id, body) { return (await json(`/transfers/${encodeURIComponent(id)}/accept`, { method: 'POST', body })).data; },
    async cancelTransfer(id, body) { return (await json(`/transfers/${encodeURIComponent(id)}/cancel`, { method: 'POST', body })).data; },

    /* ---- 门店与价格 ---- */
    async listStores(params) { return normalizeList(await json(`/stores${buildQuery(params)}`)); },
    async createStore(body) { return (await json('/stores', { method: 'POST', body })).data; },
    async updateStore(id, body) { return (await json(`/stores/${encodeURIComponent(id)}`, { method: 'PATCH', body })).data; },
    async listPrices(params) { return normalizeList(await json(`/prices${buildQuery(params)}`)); },
    async createPrice(body) { return (await json('/prices', { method: 'POST', body })).data; },

    /* ---- 订单与退款 ---- */
    async listOrders(params = {}) {
      // The original UI/demo labels differ from persisted order states.
      const status = ({ DELIVERED: 'READY', PENDING: 'AWAITING_PAYMENT' })[params.status] || params.status;
      return normalizeList(await json(`/orders${buildQuery({ ...params, status })}`));
    },
    async getOrder(id) { return (await json(`/orders/${encodeURIComponent(id)}`)).data; },
    async createRefund(id, body, idempotencyKey) {
      return (await json(`/orders/${encodeURIComponent(id)}/refunds`, { method: 'POST', body, idempotencyKey })).data;
    },

    /* ---- 物料 / 采购 / 库存 ---- */
    async listMaterials(params) { return normalizeList(await json(`/materials${buildQuery(params)}`)); },
    async createMaterial(body) { return (await json('/materials', { method: 'POST', body })).data; },
    async listPurchases(params) { return normalizeList(await json(`/purchases${buildQuery(params)}`)); },
    async createPurchase(body, idempotencyKey) { return (await json('/purchases', { method: 'POST', body, idempotencyKey })).data; },
    async updatePurchase(id, body) { return (await json(`/purchases/${encodeURIComponent(id)}`, { method: 'PATCH', body })).data; },
    async postPurchase(id, body) { return (await json(`/purchases/${encodeURIComponent(id)}/post`, { method: 'POST', body })).data; },
    async getInventory(params) { return normalizeList(await json(`/inventory${buildQuery(params)}`)); },
    async listMovements(params) { return normalizeList(await json(`/inventory/movements${buildQuery(params)}`)); },
    async createMovement(body, idempotencyKey) { return (await json('/inventory/movements', { method: 'POST', body, idempotencyKey })).data; },

    /* ---- 运营费用 ---- */
    async listExpenses(params) { return normalizeList(await json(`/expenses${buildQuery(params)}`)); },
    async createExpense(body, idempotencyKey) { return (await json('/expenses', { method: 'POST', body, idempotencyKey })).data; },
    async postExpense(id, body) { return (await json(`/expenses/${encodeURIComponent(id)}/post`, { method: 'POST', body })).data; },
    async reverseExpense(id, body) { return (await json(`/expenses/${encodeURIComponent(id)}/reversals`, { method: 'POST', body })).data; },

    /* ---- 报表 ---- */
    async operatingReport(params) { return (await json(`/reports/operating${buildQuery(params)}`)).data; },
    async operatingCsv(params) {
      const { response } = await perform(`/reports/operating.csv${buildQuery(params)}`, { accept: 'text/csv' });
      const type = response.headers.get('Content-Type') || '';
      if (!/csv|octet-stream|text\/plain/i.test(type)) {
        throw new MerchantError(502, 'BAD_CONTENT_TYPE', '导出响应不是 CSV 文件，已取消下载');
      }
      const blob = await response.blob();
      const filename = parseContentDisposition(response.headers.get('Content-Disposition'))
        || `operating-${params.grain || 'DAY'}-${params.from || 'x'}_${params.to || 'x'}.csv`;
      return { blob, filename };
    },

    /* ---- 成员与邀请 ---- */
    async listMembers(params) { return normalizeList(await json(`/members${buildQuery(params)}`)); },
    async updateMember(id, body) { return (await json(`/members/${encodeURIComponent(id)}`, { method: 'PATCH', body })).data; },
    async listInvitations(params) { return normalizeList(await json(`/invitations${buildQuery(params)}`)); },
    async createInvitation(body, idempotencyKey) { return (await json('/invitations', { method: 'POST', body, idempotencyKey })).data; },
    async revokeInvitation(id) { return (await json(`/invitations/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: {} })).data; },

    /* ---- 收款账户 ---- */
    async listPaymentAccounts(params) { return normalizeList(await json(`/payment-accounts${buildQuery(params)}`)); },
    async createPaymentAccount(body, idempotencyKey) { return (await json('/payment-accounts', { method: 'POST', body, idempotencyKey })).data; },
    async validatePaymentAccount(id, body) { return (await json(`/payment-accounts/${encodeURIComponent(id)}/validate`, { method: 'POST', body })).data; },
    async setDefaultPaymentAccount(id, body) { return (await json(`/payment-accounts/${encodeURIComponent(id)}/set-default`, { method: 'POST', body })).data; },
    async disablePaymentAccount(id, body) { return (await json(`/payment-accounts/${encodeURIComponent(id)}/disable`, { method: 'POST', body })).data; },

    /* ---- 组织与审计 ---- */
    async getTenant() { return (await json('/tenant')).data; },
    async updateTenant(body) { return (await json('/tenant', { method: 'PATCH', body })).data; },
    async listAudit(params) { return normalizeList(await json(`/audit${buildQuery(params)}`)); },
  };

  return adapter;
}
