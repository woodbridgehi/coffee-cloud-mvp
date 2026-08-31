/* ============================================================
   Coffee Cloud · B 端客户运营后台（原生实现，无框架）
   - 默认使用真实 /api/v1/merchant 适配器；仅当 URL 显式含
     ?demo=1 时启用内存演示适配器，失败绝不自动回退演示。
   - 会话 Cookie 由服务端管理；CSRF token 只存内存。密码与
     链接 token 不写入任何浏览器存储、不输出 console。
   - API 字符串一律通过 textContent / DOM 节点插入；innerHTML
     仅用于不含任何 API 数据的静态 SVG 图标。
   ============================================================ */
import { MerchantError, createRealAdapter, periodToApiParams } from './merchant-api.js';
import { createDemoAdapter, DEMO_ROLES } from './merchant-demo.js';
import {
  fmtMoney, fmtMoneyCompact, fmtQty, parseYuanToMinor, parseQuantity, isBlank,
  fmtDateTime, fmtDate, todayInTz, addDays, rangeShortcut, isValidRange,
  inclusiveEndToExclusive, exclusiveEndToInclusive, looksLikeEmail, niceTicks, sumMinor, percent,
  normalizeUsername, validateUsername, validateNewPassword, DEFAULT_USERNAME_PATTERN,
} from './merchant-format.js';

const DEMO = new URLSearchParams(location.search).get('demo') === '1';
const adapter = DEMO ? createDemoAdapter() : createRealAdapter();

const PERM = {
  dashboard: 'dashboard.read', devicesRead: 'devices.read', devicesManage: 'devices.manage',
  devicesClaim: 'devices.claim', devicesTransfer: 'devices.transfer', commands: 'commands.execute',
  storesRead: 'stores.read', storesManage: 'stores.manage', ordersRead: 'orders.read',
  refundsManage: 'refunds.manage', pricesRead: 'prices.read', pricesManage: 'prices.manage',
  inventoryRead: 'inventory.read', inventoryManage: 'inventory.manage', costsRead: 'costs.read',
  costsManage: 'costs.manage', reportsRead: 'reports.read', reportsExport: 'reports.export',
  membersRead: 'members.read', membersManage: 'members.manage', paymentsRead: 'payments.read',
  paymentsManage: 'payments.manage', tenantManage: 'tenant.manage', auditRead: 'audit.read',
};

const ROLE_LABEL = { OWNER: '所有者 OWNER', OPERATOR: '运维员 OPERATOR', FINANCE: '财务 FINANCE' };

const LIFECYCLE = {
  ACTIVE: { label: '运行中', kind: 'green' },
  SUSPENDED: { label: '已停用', kind: 'red' },
  PENDING_ACTIVATION: { label: '待激活', kind: 'gray' },
  ARCHIVED: { label: '已归档', kind: 'gray' },
};
const PAY_STATUS = {
  PENDING: { label: '待支付', kind: 'amber' }, PAID: { label: '已支付', kind: 'green' },
  REFUNDING: { label: '退款申请中', kind: 'amber' }, REFUNDED: { label: '已退款', kind: 'gray' },
  PARTIALLY_REFUNDED: { label: '部分退款', kind: 'amber' }, FAILED: { label: '支付失败', kind: 'red' },
};
const PROD_STATUS = {
  QUEUED: { label: '排队中', kind: 'blue' }, MAKING: { label: '制作中', kind: 'blue' },
  HOLD: { label: '待人工确认', kind: 'amber' }, DELIVERED: { label: '已交付', kind: 'green' },
  FAILED: { label: '制作失败', kind: 'red' }, CANCELLED: { label: '已取消', kind: 'gray' },
};
const TRANSFER_STATUS = {
  PENDING_RECIPIENT: { label: '等待接收方确认', kind: 'amber' },
  PENDING_PLATFORM: { label: '等待平台审核', kind: 'blue' },
  COMPLETED: { label: '已完成', kind: 'green' },
  BLOCKED: { label: '已阻断', kind: 'red' },
  CANCELLED: { label: '已取消', kind: 'gray' },
  REJECTED: { label: '已拒绝', kind: 'red' },
};
const EXPENSE_CATEGORY = {
  RENT: '租金', LABOR: '人工', UTILITIES: '水电', MAINTENANCE: '维护', OTHER: '其他',
};
const MOVEMENT_TYPE = {
  RESTOCK: { label: '补货入库', kind: 'green' }, WASTE: { label: '损耗报损', kind: 'red' },
  ADJUSTMENT: { label: '盘点差额', kind: 'amber' }, TRANSFER: { label: '转移调拨', kind: 'blue' },
};
const COMMAND_LABEL = {
  RELOAD_CONFIG: '重载配置', SYNC_CONFIG: '同步配置', CLEAN: '清洗管路', RESTART_APP: '重启应用',
};
const COMPLETENESS = {
  COMPLETE: { label: '成本数据完整', kind: 'green' },
  ESTIMATED: { label: '部分成本为估算', kind: 'amber' },
  INCOMPLETE: { label: '成本未完整录入', kind: 'amber' },
};

/* ---------------- 静态图标（innerHTML 仅用于此处，无 API 数据） ---------------- */

const icon = {
  dashboard: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><rect x="3.5" y="3.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/></svg>',
  orders: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M6 3h12v18l-3-1.8L12 21l-3-1.8L6 21V3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9.5 8h5M9.5 12h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  report: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 20V4M4 20h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M8 16v-5M12.5 16V7M17 16v-3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  device: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><rect x="4" y="3.5" width="16" height="17" rx="2.4" stroke="currentColor" stroke-width="1.8"/><path d="M9 7.5h6M9 11h6M9 14.5h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="15.4" cy="17.6" r="1.2" fill="currentColor"/></svg>',
  swap: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M7 4v13m0 0-3-3m3 3 3-3M17 20V7m0 0-3 3m3-3 3 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  store: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M4 9.5 5.5 4h13L20 9.5M4 9.5v10h16v-10M4 9.5h16" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M9.5 19.5v-6h5v6" stroke="currentColor" stroke-width="1.7"/></svg>',
  price: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 3v18M8.5 6.5h5.8a2.7 2.7 0 0 1 0 5.4H9a2.7 2.7 0 0 0 0 5.4h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  material: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M5 7.5 12 4l7 3.5v9L12 20l-7-3.5v-9Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M5 7.5 12 11l7-3.5M12 11v9" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
  expense: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5v9M9.5 14.8c.5.9 1.4 1.4 2.5 1.4 1.5 0 2.6-.8 2.6-2s-1-1.7-2.6-2.1c-1.5-.4-2.4-1-2.4-2s1-1.9 2.4-1.9c1 0 1.9.5 2.4 1.3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  members: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><circle cx="9" cy="8.5" r="3.2" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="16.8" cy="9.5" r="2.5" stroke="currentColor" stroke-width="1.7"/><path d="M15.8 14.6c2.3.1 4.1 1.5 4.7 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  wallet: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><rect x="3.5" y="6" width="17" height="13" rx="2.4" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 10h17" stroke="currentColor" stroke-width="1.8"/><circle cx="16.5" cy="14.5" r="1.3" fill="currentColor"/></svg>',
  settings: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/><path d="M12 3.5v2.4M12 18.1v2.4M4.6 7.8l2 1.2M17.4 15l2 1.2M4.6 16.2l2-1.2M17.4 9l2-1.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  audit: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M8 5.5h12M8 12h12M8 18.5h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="4.3" cy="5.5" r="1.3" fill="currentColor"/><circle cx="4.3" cy="12" r="1.3" fill="currentColor"/><circle cx="4.3" cy="18.5" r="1.3" fill="currentColor"/></svg>',
  plus: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 1 1-2.4-5.7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20 3.5V7h-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 19.5h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  alert: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M12 3 2.5 20h19L12 3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 9.5v4.5M12 17.4v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  info: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 11v5.5M12 7.6v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M4.5 12.5 10 18 19.5 6.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  empty: '<svg width="42" height="42" viewBox="0 0 24 24" fill="none"><path d="M4 9h12v6.5a4.5 4.5 0 0 1-4.5 4.5h-3A4.5 4.5 0 0 1 4 15.5V9Z" stroke="currentColor" stroke-width="1.6"/><path d="M16 10.5h1.8a2.7 2.7 0 0 1 0 5.4H16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  shield: '<svg width="42" height="42" viewBox="0 0 24 24" fill="none"><path d="M12 3 5 5.8v5.4c0 4.4 3 7.9 7 9.8 4-1.9 7-5.4 7-9.8V5.8L12 3Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  menu: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  coffee: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none"><path d="M4 9h12v6.5a4.5 4.5 0 0 1-4.5 4.5h-3A4.5 4.5 0 0 1 4 15.5V9Z" fill="currentColor" opacity=".92"/><path d="M16 10.5h1.8a2.7 2.7 0 0 1 0 5.4H16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M7.5 6c0-1.2 1-1.6 1-2.8M11 6c0-1.2 1-1.6 1-2.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity=".7"/></svg>',
};

/* ---------------- DOM 辅助 ---------------- */

const $ = id => document.getElementById(id);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value; // 仅静态 SVG 图标
    else if (key === 'value') node.value = value;
    else if (key === 'disabled') node.disabled = true;
    else if (key === 'checked') node.checked = true;
    else if (key === 'selected') node.selected = true;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clearNode(node) { node.replaceChildren(); }

function badge(kind, label) { return el('span', { class: `badge ${kind}` }, label); }

function statusBadge(map, key) {
  const meta = map[key] || { label: key || '—', kind: 'gray' };
  return badge(meta.kind, meta.label);
}

function kv(label, value, { mono = false, wide = false } = {}) {
  return el('div', { class: `kv${wide ? ' kv-wide' : ''}` },
    el('label', null, label),
    el('strong', mono ? { class: 'mono' } : null, isBlank(value) ? '—' : String(value)));
}

/* 单元格：直接子内容为 .num（金额 / 数量 / 版本）时自动标记为数值列，
   配合 CSS 右对齐；makeTable 会同步标记对应表头。 */
function tdl(content, label) {
  const numeric = Boolean(content && content.nodeType === 1 && content.classList && content.classList.contains('num'));
  return el('td', { 'data-label': label, class: numeric ? 'num' : null }, content);
}

function busy(btn, text) {
  btn.disabled = true;
  btn.replaceChildren(el('span', { class: 'spin', 'aria-hidden': 'true' }), document.createTextNode(text || '处理中…'));
}
function unbusy(btn, text) {
  btn.disabled = false;
  btn.replaceChildren(document.createTextNode(text));
}

function newIdemScope() {
  let key = null;
  const make = () => (window.crypto && crypto.randomUUID
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  return { current: () => key || (key = make()), reset: () => { key = null; } };
}

function describeMerchantError(error) {
  if (!(error instanceof MerchantError)) return '请求失败，请稍后重试';
  const parts = [error.message];
  if (error.requestId) parts.push(`（requestId: ${error.requestId}）`);
  return parts.join(' ');
}

/* ---------------- 全局状态 ---------------- */

const state = {
  demo: DEMO,
  session: null,
  permissions: new Set(),
  epoch: 0,
  stores: [],
  storeId: '',
  period: null,        // {from, to} 界面含当日
  environment: 'LIVE',
  view: '',
  authToken: null,     // 邮箱链接 token，仅内存
  blobUrls: [],
  ordersFocusId: null,
  demoEmailUnavailable: false,
  authConfig: null,      // 非敏感认证配置（注册模式/密码长度/邮件能力），刷新与失效会话均保留
  authConfigError: null, // 配置获取失败时的错误对象（诚实展示，不臆测模式）
};

function can(perm) { return state.permissions.has(perm); }
function tz() { return state.session && state.session.tenant ? (state.session.tenant.timezone || 'Asia/Shanghai') : 'Asia/Shanghai'; }
function stale(epoch) { return epoch !== state.epoch; }
function roleNow() {
  const current = state.session && state.session.memberships
    ? state.session.memberships.find(m => m.id === state.session.membershipId || m.tenantId === (state.session.tenant && state.session.tenant.id))
    : null;
  return current ? current.role : '';
}

function trackBlob(url) { state.blobUrls.push(url); return url; }
function revokeBlobs() {
  for (const url of state.blobUrls) { try { URL.revokeObjectURL(url); } catch (_) { /* noop */ } }
  state.blobUrls = [];
}

/* ---------------- 认证配置（/auth/config，非敏感） ---------------- */

/** 归一化认证配置；未加载时返回 loaded:false，调用方必须诚实处理。 */
function authPolicy() {
  const cfg = state.authConfig && typeof state.authConfig === 'object' ? state.authConfig : {};
  const min = Number.isFinite(Number(cfg.passwordMinLength)) && Number(cfg.passwordMinLength) > 0
    ? Math.floor(Number(cfg.passwordMinLength)) : 15;
  const max = Number.isFinite(Number(cfg.passwordMaxLength)) && Number(cfg.passwordMaxLength) >= min
    ? Math.floor(Number(cfg.passwordMaxLength)) : 128;
  return {
    loaded: Boolean(state.authConfig),
    mode: cfg.registrationMode === 'USERNAME' ? 'USERNAME' : 'EMAIL',
    usernameMode: cfg.registrationMode === 'USERNAME',
    passwordMinLength: min,
    passwordMaxLength: max,
    usernamePattern: typeof cfg.usernamePattern === 'string' && cfg.usernamePattern ? cfg.usernamePattern : DEFAULT_USERNAME_PATTERN,
    mailEnabled: cfg.mailEnabled !== false, /* 仅明确的 false 才视为禁用 */
    limitedRelease: cfg.limitedRelease === true,
  };
}

function passwordLengthLabel() {
  const p = authPolicy();
  return `${p.passwordMinLength}–${p.passwordMaxLength}`;
}

/** 账号展示：优先 username 再 email，最后回退 displayName，绝不展示 null。 */
function accountLabel(user) {
  if (!user) return '—';
  const username = typeof user.username === 'string' && user.username.trim() ? user.username.trim() : '';
  const email = typeof user.email === 'string' && user.email.trim() ? user.email.trim() : '';
  const displayName = typeof user.displayName === 'string' && user.displayName.trim() ? user.displayName.trim() : '';
  return username || email || displayName || '—';
}

/* ---------------- Toast ---------------- */

function toast(message, kind = 'info') {
  const root = $('toast-root');
  if (!root) return;
  const node = el('div', { class: `toast ${kind}`, onclick: () => node.remove() },
    el('span', { class: 't-icon', html: kind === 'success' ? icon.check : kind === 'error' ? icon.alert : icon.info, 'aria-hidden': 'true' }),
    el('span', null, message));
  root.append(node);
  setTimeout(() => { node.classList.add('leaving'); setTimeout(() => node.remove(), 320); }, 5000);
}

/* ---------------- 弹窗 / 抽屉（焦点圈定 + Escape） ---------------- */

let activeModal = null;
let activeDrawer = null;

function focusTrap(container) {
  const handler = event => {
    if (event.key !== 'Tab') return;
    const focusables = Array.from(container.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'))
      .filter(node => node.offsetParent !== null || node === document.activeElement);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  container.addEventListener('keydown', handler);
  return () => container.removeEventListener('keydown', handler);
}

function openModal({ title, body, footer, wide, dismissible = true, onClose }) {
  closeModal();
  const root = $('modal-root');
  const previous = document.activeElement;
  const close = () => {
    if (!activeModal || activeModal.root !== root) return;
    activeModal.release();
    activeModal = null;
    root.classList.add('hidden');
    root.setAttribute('aria-hidden', 'true');
    clearNode(root);
    if (onClose) onClose();
    if (previous && previous.focus) previous.focus();
  };
  const card = el('div', { class: `modal${wide ? ' wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
  card.append(
    el('div', { class: 'modal-head' },
      el('h3', null, title),
      dismissible ? el('button', { class: 'modal-close', type: 'button', 'aria-label': '关闭', onclick: close, html: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5.5 5.5 18.5 18.5M18.5 5.5 5.5 18.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' }) : null),
    el('div', { class: 'modal-body' }, body),
    footer ? el('div', { class: 'modal-foot' }, footer) : null,
  );
  card.addEventListener('click', event => event.stopPropagation());
  root.classList.remove('hidden');
  root.setAttribute('aria-hidden', 'false');
  root.replaceChildren(card);
  root.onclick = dismissible ? close : () => { };
  activeModal = { root, release: focusTrap(card), close, card };
  const focusable = card.querySelector('input, select, textarea, button:not(.modal-close)');
  if (focusable) focusable.focus();
  return activeModal;
}

function closeModal() {
  if (!activeModal) return;
  activeModal.close();
}

function openDrawer({ title, sub, content, footer, onClose }) {
  closeDrawer();
  const root = $('drawer-root');
  const previous = document.activeElement;
  let releaseTrap = null;
  const close = () => {
    if (!activeDrawer || activeDrawer.root !== root) return;
    if (releaseTrap) releaseTrap();
    activeDrawer = null;
    root.classList.add('hidden');
    root.setAttribute('aria-hidden', 'true');
    clearNode(root);
    if (onClose) onClose();
    if (previous && previous.focus) previous.focus();
  };
  const panel = el('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
  const body = el('div', { class: 'drawer-body' }, content);
  panel.append(
    el('div', { class: 'drawer-head' },
      el('div', null,
        el('h3', null, title),
        sub ? el('p', { class: 'muted drawer-sub' }, sub) : null),
      el('button', { class: 'modal-close', type: 'button', 'aria-label': '关闭', onclick: close, html: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5.5 5.5 18.5 18.5M18.5 5.5 5.5 18.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' })),
    body,
    footer ? el('div', { class: 'drawer-foot' }, footer) : null,
  );
  const veil = el('div', { class: 'drawer-veil', onclick: close });
  root.classList.remove('hidden');
  root.setAttribute('aria-hidden', 'false');
  root.replaceChildren(veil, panel);
  releaseTrap = focusTrap(panel);
  activeDrawer = { root, close, body, panel };
  const focusable = panel.querySelector('button');
  if (focusable) focusable.focus();
  return activeDrawer;
}

function closeDrawer() {
  if (!activeDrawer) return;
  activeDrawer.close();
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (activeDrawer) { activeDrawer.close(); return; }
  if (activeModal && activeModal.root.onclick) activeModal.root.onclick();
});

function confirmModal({ title, message, confirmText = '确认', cancelText = '取消', danger = false, requireText = '' }) {
  return new Promise(resolve => {
    let input = null;
    let confirmBtn = null;
    const body = [typeof message === 'string' ? el('p', { style: 'margin:0' }, message) : message];
    if (requireText) {
      input = el('input', { class: 'input', placeholder: `输入“${requireText}”以确认`, autocomplete: 'off' });
      input.addEventListener('input', () => { confirmBtn.disabled = input.value.trim() !== requireText; });
      body.push(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '请输入确认文字'), input));
    }
    const done = result => { modal.close(); resolve(result); };
    confirmBtn = el('button', { class: `btn ${danger ? 'danger' : 'primary'}`, type: 'button', disabled: Boolean(requireText), onclick: () => done(true) }, confirmText);
    const modal = openModal({
      title, body,
      footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => done(false) }, cancelText), confirmBtn],
    });
  });
}

/* ---------------- 表单字段错误（422 fields → 行内提示） ---------------- */

function clearFieldErrors(scope) {
  for (const node of scope.querySelectorAll('.field-error-inline')) node.remove();
}

function showFieldErrors(scope, fields, fallbackNode, fallbackMessage) {
  clearFieldErrors(scope);
  let shown = 0;
  for (const [field, message] of Object.entries(fields || {})) {
    const wrap = scope.querySelector(`[data-field="${field}"]`);
    if (wrap) {
      wrap.append(el('p', { class: 'form-error field-error-inline', role: 'alert' }, message));
      shown += 1;
    }
  }
  if (!shown && fallbackNode) fallbackNode.textContent = fallbackMessage;
}

/* 版本冲突（409）：提示 + 主动重新读取入口，绝不静默覆盖 */
function isVersionConflict(error) {
  return error instanceof MerchantError && error.status === 409
    && (error.code === 'VERSION_CONFLICT' || error.code === 'CONFLICT' || error.code === 'STALE_VERSION');
}

function showConflictRetry(node, error, closeAndReload) {
  clearNode(node);
  node.append(
    document.createTextNode(`${describeMerchantError(error)} 请重新读取最新数据后再提交。`),
    el('button', {
      class: 'btn secondary small', type: 'button', style: 'margin-left:8px',
      onclick: closeAndReload,
    }, '重新读取'));
}

/* ---------------- 高风险操作：重新验证 ---------------- */

async function withReauth(run) {
  try {
    return await run();
  } catch (error) {
    if (error instanceof MerchantError && error.code === 'REAUTH_REQUIRED') {
      const ok = await reauthModal();
      if (!ok) throw error;
      return await run();
    }
    throw error;
  }
}

function reauthModal() {
  return new Promise(resolve => {
    const password = el('input', { class: 'input', type: 'password', autocomplete: 'current-password', placeholder: '输入当前账号密码' });
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '验证身份');
    const modal = openModal({
      title: '重新验证身份',
      body: [
        el('p', { class: 'field-hint' }, '该操作较为敏感，需要重新验证密码后继续。密码只用于本次验证，不会被记录。'),
        el('div', { class: 'field', 'data-field': 'password' }, el('span', { class: 'field-label' }, '当前密码'), password),
        errorNode,
      ],
      footer: [
        el('button', { class: 'btn secondary', type: 'button', onclick: () => { modal.close(); resolve(false); } }, '取消'),
        submit,
      ],
    });
    submit.addEventListener('click', async () => {
      busy(submit, '验证中…');
      try {
        const result = await adapter.reauthenticate({ password: password.value });
        modal.close();
        toast(`身份验证通过，有效期至 ${fmtDateTime(result.validUntil, tz())}`, 'success');
        password.value = '';
        resolve(true);
      } catch (error) {
        unbusy(submit, '验证身份');
        errorNode.textContent = describeMerchantError(error);
      }
    });
  });
}

/* ---------------- 区域状态：loading / empty / error / denied ---------------- */

function skeletonRows(rows = 4) {
  const items = [];
  for (let i = 0; i < rows; i += 1) items.push(el('div', { class: `skel-row ${i % 3 === 0 ? 'w60' : i % 3 === 1 ? 'w80' : 'w40'}` }));
  return el('div', { class: 'skeleton', 'aria-hidden': 'true', role: 'status' }, el('span', { class: 'visually-hidden' }, '加载中'), items);
}

function skeletonCards(count = 4) {
  const cards = [];
  for (let i = 0; i < count; i += 1) cards.push(el('div', { class: 'stat' }, skeletonRows(2)));
  return cards;
}

function emptyState(title, hint) {
  return el('div', { class: 'empty' },
    el('span', { html: icon.empty, 'aria-hidden': 'true' }),
    el('div', { class: 'e-title' }, title),
    hint ? el('div', { class: 'muted' }, hint) : null);
}

function deniedState(perm, hint) {
  return el('div', { class: 'empty denied' },
    el('span', { html: icon.shield, 'aria-hidden': 'true' }),
    el('div', { class: 'e-title' }, `当前角色缺少 ${perm} 权限`),
    el('div', { class: 'muted' }, hint || '权限由组织 OWNER 在「成员权限」中分配；角色名仅用于展示，实际以服务器返回的权限为准。'));
}

function errorState(error, retry) {
  const isDenied = error instanceof MerchantError && error.status === 403;
  if (isDenied) return deniedState('相应权限');
  const box = el('div', { class: 'empty error-box' },
    el('span', { html: icon.alert, 'aria-hidden': 'true' }),
    el('div', { class: 'e-title' }, '加载失败'),
    el('div', { class: 'muted', style: 'overflow-wrap:anywhere' }, describeMerchantError(error)),
    error instanceof MerchantError && error.status === 429 && error.retryAfterMs
      ? el('div', { class: 'muted' }, `请约 ${Math.ceil(error.retryAfterMs / 1000)} 秒后重试（服务器 Retry-After）`) : null,
    retry ? el('button', { class: 'btn secondary small', type: 'button', onclick: retry }, '重试') : null);
  return box;
}

function handleErrorGlobal(error) {
  if (error instanceof MerchantError && error.status === 401) {
    forceLogout(error.message || '登录已过期，请重新登录');
    return true;
  }
  return false;
}

async function loadRegion(container, loader) {
  const epoch = state.epoch;
  try {
    await loader(container);
  } catch (error) {
    if (error && error.aborted) return;
    if (stale(epoch)) return;
    if (handleErrorGlobal(error)) return;
    clearNode(container);
    container.append(errorState(error, () => loadRegion(container, loader)));
  }
}

/* ---------------- 简单表格 ---------------- */

function makeTable({ headers, rows, responsive = true, minTable = 760 }) {
  /* 数值列判定：该列所有数据单元格均带 num 类时，表头同步右对齐 */
  const numericColumns = headers.map((_, index) => {
    if (!rows.length) return false;
    return rows.every(row => {
      const cell = row.children && row.children[index];
      return Boolean(cell && cell.nodeType === 1 && cell.classList.contains('num'));
    });
  });
  const thead = el('thead', null, el('tr', null, headers.map((h, i) => el('th', { class: numericColumns[i] ? 'num' : null }, h))));
  const tbody = el('tbody', null, rows);
  return el('div', { class: 'table-scroll' },
    el('table', { class: `grid${responsive ? ' responsive' : ''}`, style: minTable ? `min-width:${minTable}px` : '' }, thead, tbody));
}

/* ---------------- SVG 图表（附文字摘要与数据表） ---------------- */

function svgEl(tag, attrs, ...children) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  for (const child of children) node.append(child);
  return node;
}

function chartNode({ labels, series, kind = 'line', yFmt = fmtMoneyCompact, height = 240 }) {
  const width = 860;
  const padLeft = 64; const padRight = 16; const padTop = 18; const padBottom = 30;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const values = series.flatMap(s => s.values.filter(v => v !== null && v !== undefined));
  const max = values.length ? Math.max(...values) : 0;
  const ticks = niceTicks(max || 1, 4);
  const yMax = ticks[ticks.length - 1] || 1;
  const n = labels.length;
  const xAt = i => (n <= 1 ? padLeft + plotW / 2 : padLeft + (plotW * i) / (n - 1));
  const yAt = v => padTop + plotH - (plotH * v) / yMax;

  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart-svg', role: 'img' });
  for (const t of ticks) {
    const y = yAt(t);
    svg.append(svgEl('line', { x1: padLeft, x2: width - padRight, y1: y, y2: y, class: 'chart-grid' }));
    const label = svgEl('text', { x: padLeft - 8, y: y + 4, class: 'chart-ylabel', 'text-anchor': 'end' });
    label.textContent = yFmt(t);
    svg.append(label);
  }
  const labelEvery = Math.max(1, Math.ceil(n / 10));
  labels.forEach((label, i) => {
    if (i % labelEvery !== 0 && i !== n - 1) return;
    const text = svgEl('text', { x: xAt(i), y: height - 8, class: 'chart-xlabel', 'text-anchor': 'middle' });
    text.textContent = label;
    svg.append(text);
  });

  if (kind === 'bar' && series.length === 1) {
    const s = series[0];
    const slot = n ? plotW / n : plotW;
    const barW = Math.max(3, Math.min(38, slot * 0.55));
    s.values.forEach((v, i) => {
      const x = padLeft + (plotW * i) / Math.max(1, n) + (slot - barW) / 2;
      if (v === null || v === undefined) {
        svg.append(svgEl('rect', { x, y: yAt(yMax * 0.04), width: barW, height: plotH * 0.04, class: 'chart-gap' }));
        const t = svgEl('title'); t.textContent = `${labels[i]}：数据缺失（待补全）`;
        svg.lastChild.append(t);
      } else {
        const rect = svgEl('rect', { x, y: yAt(v), width: barW, height: Math.max(1, padTop + plotH - yAt(v)), class: `chart-bar${s.className ? ' ' + s.className : ''}` });
        const title = svgEl('title'); title.textContent = `${labels[i]}：${fmtMoney(v)}`;
        rect.append(title);
        svg.append(rect);
      }
    });
  } else {
    for (const s of series) {
      let segment = [];
      const flush = () => {
        if (segment.length > 1) {
          svg.append(svgEl('polyline', {
            points: segment.map(p => `${p.x},${p.y}`).join(' '),
            class: `chart-line${s.className ? ' ' + s.className : ''}`, fill: 'none',
          }));
        }
        for (const p of segment) {
          const dot = svgEl('circle', { cx: p.x, cy: p.y, r: 3, class: `chart-dot${s.className ? ' ' + s.className : ''}` });
          const title = svgEl('title'); title.textContent = `${p.label}：${fmtMoney(p.value)}`;
          dot.append(title);
          svg.append(dot);
        }
        segment = [];
      };
      s.values.forEach((v, i) => {
        if (v === null || v === undefined) { flush(); return; }
        segment.push({ x: xAt(i), y: yAt(v), label: labels[i], value: v });
      });
      flush();
    }
  }
  return svg;
}

function chartCard({ title, hint, labels, series, kind, summaryText }) {
  const legend = el('div', { class: 'chart-legend' },
    series.map(s => el('span', { class: 'chart-legend-item' },
      el('i', { class: `chart-swatch${s.className ? ' ' + s.className : ''}` }), s.name)));
  const dataRows = labels.map((label, i) => el('tr', null,
    el('td', { 'data-label': '区间' }, label),
    ...series.map(s => el('td', { 'data-label': s.name, class: 'num' }, fmtMoney(s.values[i])))));
  const details = el('details', { class: 'chart-data' },
    el('summary', null, '查看图表数据表'),
    makeTable({ headers: ['区间', ...series.map(s => s.name)], rows: dataRows, minTable: 0 }));
  return el('section', { class: 'card' },
    el('div', { class: 'card-head' }, el('h3', null, title), hint ? el('span', { class: 'muted' }, hint) : null),
    el('div', { class: 'card-body chart-body' },
      legend,
      chartNode({ labels, series, kind }),
      summaryText ? el('p', { class: 'field-hint chart-summary' }, summaryText) : null,
      details));
}

/* ============================================================
   认证界面
   ============================================================ */

function hashRoute() {
  const raw = (location.hash || '').replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?');
  return { path: path || '', params: new URLSearchParams(query) };
}

function readFragmentToken() {
  const { path, params } = hashRoute();
  if (['verify', 'reset', 'invite'].includes(path) && params.get('token')) {
    state.authToken = params.get('token'); // 仅存内存
    history.replaceState(null, '', `${location.pathname}${location.search}#/${path}`);
  }
}

function authShell(card) {
  const wrap = $('auth-view');
  clearNode(wrap);
  wrap.append(el('div', { class: 'auth-card' },
    el('div', { class: 'auth-brand' },
      el('span', { class: 'auth-mark', html: icon.coffee, 'aria-hidden': 'true' }),
      el('div', null,
        el('div', { class: 'auth-eyebrow' }, 'Coffee Cloud'),
        el('h1', null, '客户运营后台'))),
    card));
  wrap.classList.remove('hidden');
  $('shell').classList.add('hidden');
}

function authLinkRow(links) {
  return el('div', { class: 'auth-links' }, links);
}

function mailDisabledNotice(title) {
  authShell(el('div', { class: 'auth-result' },
    el('span', { class: 'result-icon', html: icon.info, 'aria-hidden': 'true' }),
    el('h2', null, title),
    el('p', { class: 'muted' }, '邮件服务未配置，此功能暂未开放；忘记密码请联系平台管理员。'),
    el('div', { class: 'auth-links' }, el('a', { class: 'btn secondary', href: '#/login' }, '返回登录'))));
}

function renderAuth() {
  const policy = authPolicy();
  if (!policy.loaded) {
    renderAuthConfigError(state.authConfigError || new MerchantError(0, 'CONFIG_MISSING', '登录配置尚未加载'));
    return;
  }
  const mode = state.session ? '' : (hashRoute().path || 'login');
  const authModes = ['login', 'register', 'forgot', 'reset', 'verify', 'invite'];
  const m = authModes.includes(mode) ? mode : 'login';
  /* 依赖邮件链接的入口：邮件服务未配置时统一说明，不展示可提交的表单 */
  if (!policy.mailEnabled && ['forgot', 'reset', 'verify', 'invite'].includes(m)) {
    mailDisabledNotice({
      forgot: '找回密码暂未开放', reset: '重置密码暂未开放',
      verify: '验证邮箱暂未开放', invite: '接受邀请暂未开放',
    }[m]);
    return;
  }
  document.title = 'Coffee Cloud · 客户运营后台';
  const demoHints = state.demo ? adapter.demoHints() : null;
  const hintBox = demoHints ? el('div', { class: 'callout demo-callout' },
    el('strong', null, '演示模式提示'),
    el('div', { class: 'muted' }, `${demoHints.loginHint}；验证邮箱 token：${demoHints.verifyToken}；重置 token：${demoHints.resetToken}；邀请 token：${demoHints.inviteToken}`)) : null;

  if (m === 'login') {
    const usernameMode = policy.usernameMode;
    const ident = usernameMode
      ? el('input', { class: 'input', type: 'text', autocomplete: 'username', placeholder: '用户名，或已注册邮箱', required: true })
      : el('input', { class: 'input', type: 'email', autocomplete: 'username', placeholder: 'name@company.com', required: true });
    const password = el('input', { class: 'input', type: 'password', autocomplete: 'current-password', placeholder: '账号密码', required: true });
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, '登录');
    const form = el('form', {
      class: 'auth-form', autocomplete: 'off',
      onsubmit: async event => {
        event.preventDefault();
        errorNode.textContent = '';
        busy(submit, '登录中…');
        try {
          const session = usernameMode
            ? await adapter.login({ username: normalizeUsername(ident.value), password: password.value })
            : await adapter.login({ email: ident.value.trim(), password: password.value });
          password.value = '';
          enterShell(session);
        } catch (error) {
          unbusy(submit, '登录');
          errorNode.textContent = describeMerchantError(error);
        }
      },
    },
      el('div', { class: 'field', 'data-field': usernameMode ? 'username' : 'email' },
        el('span', { class: 'field-label' }, usernameMode ? '用户名' : '邮箱'), ident,
        usernameMode ? el('span', { class: 'field-hint' }, '已注册邮箱账号仍可用邮箱登录。') : null),
      el('div', { class: 'field', 'data-field': 'password' }, el('span', { class: 'field-label' }, '密码'), password),
      submit, errorNode);
    const links = [el('a', { href: '#/register' }, '创建组织账号')];
    if (policy.mailEnabled) {
      links.push(el('a', { href: '#/forgot' }, '忘记密码'));
      links.push(el('a', { href: '#/invite' }, '使用邀请链接'));
      links.push(el('a', { href: '#/verify' }, '验证邮箱'));
    }
    authShell(el('div', null,
      el('p', { class: 'auth-note' }, '会话由服务端 HttpOnly Cookie 管理；本页面不保存任何密码或令牌。'),
      hintBox, form,
      authLinkRow(links)));
    return;
  }

  if (m === 'register') {
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, '创建账号');
    let form;
    if (policy.usernameMode) {
      /* USERNAME 模式：用户名 + 姓名 + 组织 + 密码；成功即 REGISTERED，可直接登录 */
      const username = el('input', { class: 'input mono', type: 'text', autocomplete: 'username', maxlength: '32', required: true });
      const password = el('input', {
        class: 'input', type: 'password', autocomplete: 'new-password',
        minlength: String(policy.passwordMinLength), maxlength: String(policy.passwordMaxLength), required: true,
      });
      const displayName = el('input', { class: 'input', autocomplete: 'name', required: true });
      const tenantName = el('input', { class: 'input', required: true });
      form = el('form', {
        class: 'auth-form', autocomplete: 'off',
        onsubmit: async event => {
          event.preventDefault();
          clearFieldErrors(form);
          errorNode.textContent = '';
          const checkUsername = validateUsername(username.value, policy.usernamePattern);
          if (!checkUsername.ok) { showFieldErrors(form, { username: checkUsername.reason }); return; }
          const checkPassword = validateNewPassword(password.value, policy);
          if (!checkPassword.ok) { showFieldErrors(form, { password: checkPassword.reason }); return; }
          if (!displayName.value.trim()) { showFieldErrors(form, { displayName: '请填写你的姓名' }); return; }
          if (!tenantName.value.trim()) { showFieldErrors(form, { tenantName: '请填写组织名称' }); return; }
          busy(submit, '提交中…');
          try {
            const result = await adapter.register({
              username: checkUsername.value, password: password.value,
              displayName: displayName.value.trim(), tenantName: tenantName.value.trim(),
            });
            password.value = '';
            if (result && result.status && result.status !== 'REGISTERED') {
              authResultPage('注册请求已提交', [
                `服务器返回状态：${result.status}，未确认注册完成。请稍后在登录页尝试，或联系平台管理员。`,
              ], [{ label: '去登录', href: '#/login' }]);
            } else {
              authResultPage('注册成功，可直接登录', [
                '账号已创建，使用刚设置的用户名和密码即可登录。',
                '无需验证邮箱；忘记密码时请联系平台管理员重置。',
              ], [{ label: '去登录', href: '#/login' }]);
            }
          } catch (error) {
            unbusy(submit, '创建账号');
            showFieldErrors(form, error.fields, errorNode, describeMerchantError(error));
          }
        },
      },
        el('div', { class: 'field', 'data-field': 'username' },
          el('span', { class: 'field-label' }, '用户名 *'), username,
          el('span', { class: 'field-hint' }, '3–32 位：字母开头，后续可用小写字母、数字、点、下划线或连字符；不区分大小写，提交前自动转小写。')),
        el('div', { class: 'field', 'data-field': 'displayName' }, el('span', { class: 'field-label' }, '你的姓名 *'), displayName),
        el('div', { class: 'field', 'data-field': 'tenantName' }, el('span', { class: 'field-label' }, '组织名称 *'), tenantName),
        el('div', { class: 'field', 'data-field': 'password' },
          el('span', { class: 'field-label' }, `设置密码（${passwordLengthLabel()} 个字符）*`), password),
        submit, errorNode);
    } else {
      /* EMAIL 模式：维持旧流程（验证邮件 + VERIFICATION_PENDING） */
      const email = el('input', { class: 'input', type: 'email', autocomplete: 'username', required: true });
      const password = el('input', {
        class: 'input', type: 'password', autocomplete: 'new-password',
        minlength: String(policy.passwordMinLength), maxlength: String(policy.passwordMaxLength), required: true,
      });
      const displayName = el('input', { class: 'input', autocomplete: 'name', required: true });
      const tenantName = el('input', { class: 'input', required: true });
      form = el('form', {
        class: 'auth-form', autocomplete: 'off',
        onsubmit: async event => {
          event.preventDefault();
          clearFieldErrors(form);
          errorNode.textContent = '';
          if (!looksLikeEmail(email.value)) { showFieldErrors(form, { email: '请输入正确的邮箱地址' }); return; }
          const checkPassword = validateNewPassword(password.value, policy);
          if (!checkPassword.ok) { showFieldErrors(form, { password: checkPassword.reason }); return; }
          busy(submit, '提交中…');
          try {
            await adapter.register({ email: email.value.trim(), password: password.value, displayName: displayName.value.trim(), tenantName: tenantName.value.trim() });
            password.value = '';
            authResultPage('注册成功，等待邮箱验证', [
              '验证邮件已发送（若邮件服务可用）。请到邮箱中点击验证链接完成验证；链接需要你在验证页面主动点击确认。',
              '如果长时间未收到邮件，请检查垃圾箱或联系平台管理员。邮件服务未配置时，服务器会明确提示不可用。',
            ]);
          } catch (error) {
            unbusy(submit, '创建账号');
            showFieldErrors(form, error.fields, errorNode, describeMerchantError(error));
          }
        },
      },
        el('div', { class: 'field', 'data-field': 'email' }, el('span', { class: 'field-label' }, '工作邮箱 *'), email),
        el('div', { class: 'field', 'data-field': 'password' },
          el('span', { class: 'field-label' }, `设置密码（${passwordLengthLabel()} 个字符）*`), password),
        el('div', { class: 'field', 'data-field': 'displayName' }, el('span', { class: 'field-label' }, '你的姓名 *'), displayName),
        el('div', { class: 'field', 'data-field': 'tenantName' }, el('span', { class: 'field-label' }, '组织名称 *'), tenantName),
        submit, errorNode);
    }
    authShell(el('div', null, el('p', { class: 'auth-note' }, '创建组织账号后，你将成为该组织的 OWNER。'), hintBox, form,
      authLinkRow([el('a', { href: '#/login' }, '返回登录')])));
    return;
  }

  if (m === 'forgot') {
    const email = el('input', { class: 'input', type: 'email', required: true });
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, '发送找回链接');
    const form = el('form', {
      class: 'auth-form', onsubmit: async event => {
        event.preventDefault();
        errorNode.textContent = '';
        busy(submit, '发送中…');
        try {
          await adapter.forgotPassword({ email: email.value.trim() });
          email.value = '';
          authResultPage('请求已受理', [
            '如果该邮箱注册过账号，重置链接将发送到该邮箱。',
            '出于防枚举考虑，无论账号是否存在都返回相同结果。',
          ]);
        } catch (error) {
          unbusy(submit, '发送找回链接');
          errorNode.textContent = describeMerchantError(error);
        }
      },
    },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '注册邮箱 *'), email),
      submit, errorNode);
    authShell(el('div', null, el('p', { class: 'auth-note' }, '通过邮箱链接重置密码。'), form,
      authLinkRow([el('a', { href: '#/login' }, '返回登录')])));
    return;
  }

  if (m === 'reset') {
    const tokenInput = el('input', { class: 'input mono', value: state.authToken || '', placeholder: '粘贴重置 token', autocomplete: 'off' });
    const password = el('input', {
      class: 'input', type: 'password', autocomplete: 'new-password',
      minlength: String(policy.passwordMinLength), maxlength: String(policy.passwordMaxLength), required: true,
    });
    const confirm = el('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true });
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary block', type: 'submit' }, '设置新密码');
    const form = el('form', {
      class: 'auth-form', onsubmit: async event => {
        event.preventDefault();
        errorNode.textContent = '';
        const checkPassword = validateNewPassword(password.value, policy);
        if (!checkPassword.ok) { errorNode.textContent = checkPassword.reason; return; }
        if (password.value !== confirm.value) { errorNode.textContent = '两次输入的密码不一致'; return; }
        busy(submit, '提交中…');
        try {
          await adapter.resetPassword({ token: tokenInput.value.trim(), password: password.value });
          password.value = ''; confirm.value = '';
          authResultPage('密码已更新', ['请使用新密码登录。'], [{ label: '去登录', href: '#/login' }]);
        } catch (error) {
          unbusy(submit, '设置新密码');
          errorNode.textContent = describeMerchantError(error);
        }
      },
    },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '重置 token *'), tokenInput),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, `新密码（${passwordLengthLabel()} 个字符）*`), password),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '确认新密码 *'), confirm),
      submit, errorNode);
    authShell(el('div', null, el('p', { class: 'auth-note' }, 'token 来自邮件链接的地址栏片段，仅保留在当前页面内存中。'), form,
      authLinkRow([el('a', { href: '#/login' }, '返回登录')])));
    return;
  }

  if (m === 'verify') {
    const tokenInput = el('input', { class: 'input mono', value: state.authToken || '', placeholder: '粘贴验证 token', autocomplete: 'off' });
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary block', type: 'button' }, '确认验证邮箱');
    submit.addEventListener('click', async () => {
      errorNode.textContent = '';
      busy(submit, '验证中…');
      try {
        await adapter.verifyEmail({ token: tokenInput.value.trim() });
        authResultPage('邮箱验证成功', ['现在可以使用该邮箱登录。'], [{ label: '去登录', href: '#/login' }]);
      } catch (error) {
        unbusy(submit, '确认验证邮箱');
        errorNode.textContent = describeMerchantError(error);
      }
    });
    authShell(el('div', null,
      el('p', { class: 'auth-note' }, '验证不会自动执行：请核对 token 后点击按钮确认，验证链接只能使用一次。'),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '验证 token *'), tokenInput),
      submit, errorNode,
      authLinkRow([el('a', { href: '#/login' }, '返回登录')])));
    return;
  }

  /* invite */
  const tokenInput = el('input', { class: 'input mono', value: state.authToken || '', placeholder: '粘贴邀请 token', autocomplete: 'off' });
  const displayName = el('input', { class: 'input', required: true });
  const password = el('input', {
    class: 'input', type: 'password', autocomplete: 'new-password',
    minlength: String(policy.passwordMinLength), maxlength: String(policy.passwordMaxLength), required: true,
  });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary block', type: 'submit' }, '接受邀请');
  const form = el('form', {
    class: 'auth-form', onsubmit: async event => {
      event.preventDefault();
      errorNode.textContent = '';
      const checkPassword = validateNewPassword(password.value, policy);
      if (!checkPassword.ok) { errorNode.textContent = checkPassword.reason; return; }
      busy(submit, '提交中…');
      try {
        await adapter.acceptInvitation({ token: tokenInput.value.trim(), displayName: displayName.value.trim(), password: password.value });
        password.value = '';
        authResultPage('已接受邀请', ['你已加入组织，请使用邮箱登录。'], [{ label: '去登录', href: '#/login' }]);
      } catch (error) {
        unbusy(submit, '接受邀请');
        errorNode.textContent = describeMerchantError(error);
      }
    },
  },
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, '邀请 token *'), tokenInput),
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, '你的姓名 *'), displayName),
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, `设置密码（${passwordLengthLabel()} 个字符）*`), password),
    submit, errorNode);
  authShell(el('div', null,
    el('p', { class: 'auth-note' }, '已有账号的成员请先登录，再通过组织内的邀请确认入口接受，无需在此修改密码。'),
    form, authLinkRow([el('a', { href: '#/login' }, '返回登录')])));
}

function authResultPage(title, lines, links = []) {
  authShell(el('div', { class: 'auth-result' },
    el('span', { class: 'result-icon', html: icon.check, 'aria-hidden': 'true' }),
    el('h2', null, title),
    ...lines.map(line => el('p', { class: 'muted' }, line)),
    links.length ? el('div', { class: 'auth-links' }, links.map(l => el('a', { class: 'btn secondary', href: l.href }, l.label))) : null));
}

/** 配置获取失败：诚实展示错误与重试，不回退演示、不假定任何登录方式可用。 */
function renderAuthConfigError(error) {
  const wrap = $('auth-view');
  if (!wrap) return;
  clearNode(wrap);
  wrap.append(el('div', { class: 'auth-card' },
    el('div', { class: 'auth-brand' },
      el('span', { class: 'auth-mark', html: icon.coffee, 'aria-hidden': 'true' }),
      el('div', null,
        el('div', { class: 'auth-eyebrow' }, 'Coffee Cloud'),
        el('h1', null, '客户运营后台'))),
    el('div', { class: 'auth-result' },
      el('span', { class: 'result-icon error', html: icon.alert, 'aria-hidden': 'true' }),
      el('h2', null, '无法加载登录配置'),
      el('p', { class: 'muted' }, '页面需要先获取注册与登录方式配置，才能展示正确的表单。当前配置获取失败，不会假定认证可用。'),
      el('p', { class: 'muted', style: 'overflow-wrap:anywhere' }, describeMerchantError(error)),
      el('div', { class: 'auth-links' },
        el('button', { class: 'btn secondary', type: 'button', onclick: () => startWithAuthConfig() }, '重试')),
      el('p', { class: 'field-hint' }, '可稍后重试，或刷新页面重新加载；不会回退到演示模式，也不会在未取得配置前展示登录表单。'))));
  wrap.classList.remove('hidden');
  $('shell')?.classList.add('hidden');
}

/* ============================================================
   会话 / 外壳
   ============================================================ */

function applySession(session) {
  state.session = session;
  state.permissions = new Set(session.permissions || []);
  if (!state.period) state.period = rangeShortcut('last7', todayInTz(tz()));
}

async function enterShell(session) {
  applySession(session);
  $('auth-view').classList.add('hidden');
  $('shell').classList.remove('hidden');
  state.storeId = '';
  state.environment = 'LIVE';
  updateEnvBanner();
  buildShell();
  await refreshStores();
  buildShellControls();
  if (!location.hash || !findViewDef(location.hash.replace(/^#\//, '').split('?')[0])) {
    const fallback = VIEW_DEFS.find(def => can(def.perm));
    location.hash = fallback ? `#/${fallback.id}` : '#/dashboard';
  }
  route();
  if (state.demo) syncDemoTools();
}

function forceLogout(message) {
  state.epoch += 1;
  adapter.abortAll();
  adapter.clearSession();
  state.session = null;
  state.permissions = new Set();
  state.period = null;
  state.stores = [];
  state.storeId = '';
  state.environment = 'LIVE';
  state.authToken = null;
  revokeBlobs();
  closeDrawer();
  if (activeModal) closeModal();
  $('shell').classList.add('hidden');
  updateEnvBanner();
  renderAuth();
  if (message) toast(message, 'error');
}

async function doLogout() {
  try { await adapter.logout(); } catch (_) { /* 会话可能已失效 */ }
  forceLogout('已退出登录');
}

async function switchOrg(membershipId) {
  if (!state.session) return;
  state.epoch += 1;
  adapter.abortAll();
  closeDrawer();
  revokeBlobs();
  try {
    const session = await adapter.switchTenant(membershipId);
    if (!session) throw new MerchantError(0, 'EMPTY', '切换组织响应为空');
    applySession(session);
    state.storeId = '';
    state.environment = 'LIVE';
    state.period = rangeShortcut('last7', todayInTz(tz()));
    updateEnvBanner();
    buildShell();
    await refreshStores();
    buildShellControls();
    route();
    if (state.demo) syncDemoTools();
    toast(`已切换到「${session.tenant.name}」，页面数据已按新组织重新加载`, 'info');
  } catch (error) {
    if (error && error.aborted) return;
    toast(`切换组织失败：${describeMerchantError(error)}`, 'error');
    buildShellControls();
  }
}

async function refreshStores() {
  if (!can(PERM.storesRead)) { state.stores = []; return; }
  try {
    const { items } = await adapter.listStores();
    const scope = state.session.storeScope;
    state.stores = scope && scope.mode === 'SELECTED' && scope.storeIds.length
      ? items.filter(s => scope.storeIds.includes(s.id))
      : items;
  } catch (_) {
    state.stores = [];
  }
}

function storeOptions(selectedId, { allLabel = '全部门店' } = {}) {
  const options = [el('option', { value: '', selected: selectedId === '' || selectedId == null }, allLabel)];
  for (const store of state.stores) {
    options.push(el('option', { value: store.id, selected: store.id === selectedId }, store.name));
  }
  return options;
}

/* ---------------- 侧栏与顶栏 ---------------- */

function buildShell() {
  const nav = $('side-nav');
  clearNode(nav);
  let lastGroup = '';
  for (const def of VIEW_DEFS) {
    if (!can(def.perm)) continue;
    if (def.group !== lastGroup) {
      lastGroup = def.group;
      nav.append(el('div', { class: 'side-group' }, def.group));
    }
    nav.append(el('button', {
      class: `nav-item${state.view === def.id ? ' active' : ''}`,
      type: 'button',
      onclick: () => { location.hash = `#/${def.id}`; closeMobileNav(); },
    },
      el('span', { class: 'n-icon', html: def.icon, 'aria-hidden': 'true' }),
      el('span', null, def.label)));
  }
  const who = $('who');
  clearNode(who);
  if (state.session) {
    who.append(
      el('strong', null, state.session.user.displayName || accountLabel(state.session.user)),
      el('span', { class: 'muted' }, `${ROLE_LABEL[roleNow()] || roleNow() || ''} · ${state.session.tenant.name}`));
  }
}

function closeMobileNav() {
  document.body.classList.remove('nav-open');
  $('nav-veil')?.classList.add('hidden');
}

function buildShellControls() {
  const holder = $('top-controls');
  clearNode(holder);

  /* 组织切换 */
  const orgSelect = el('select', { class: 'input m-select', 'aria-label': '当前组织' },
    state.session.memberships.map(m => el('option', {
      value: m.id,
      selected: m.tenantId === state.session.tenant.id,
    }, `${m.tenantName}（${ROLE_LABEL[m.role] || m.role}）`)));
  orgSelect.addEventListener('change', () => switchOrg(orgSelect.value));

  /* 门店筛选 */
  const storeSelect = el('select', { class: 'input m-select', 'aria-label': '门店筛选' },
    storeOptions(state.storeId, { allLabel: '全部门店' }));
  storeSelect.addEventListener('change', () => { state.storeId = storeSelect.value; reloadView(); });

  /* 日期区间（含当日的界面区间） */
  const rangeBtnLabel = () => `${state.period.from} ~ ${state.period.to}`;
  const rangeBtn = el('button', { class: 'btn secondary small m-range-btn', type: 'button', 'aria-expanded': 'false' }, rangeBtnLabel());
  const fromInput = el('input', { class: 'input', type: 'date', value: state.period.from, 'aria-label': '开始日期（含当日）' });
  const toInput = el('input', { class: 'input', type: 'date', value: state.period.to, 'aria-label': '结束日期（含当日）' });
  const rangeError = el('p', { class: 'form-error', role: 'alert' });
  const applyRange = () => {
    if (!isValidRange(fromInput.value, toInput.value)) { rangeError.textContent = '开始日期不能晚于结束日期'; return; }
    rangeError.textContent = '';
    state.period = { from: fromInput.value, to: toInput.value };
    rangeBtn.replaceChildren(document.createTextNode(rangeBtnLabel()));
    closePopover(pop);
    reloadView();
  };
  const quickRow = el('div', { class: 'pop-quick' },
    [['today', '今天'], ['last7', '近 7 天'], ['thisMonth', '本月'], ['thisYear', '本年']].map(([kind, label]) =>
      el('button', {
        class: 'btn ghost small', type: 'button', onclick: () => {
          state.period = rangeShortcut(kind, todayInTz(tz()));
          fromInput.value = state.period.from;
          toInput.value = state.period.to;
          rangeBtn.replaceChildren(document.createTextNode(rangeBtnLabel()));
          closePopover(pop);
          reloadView();
        },
      }, label)));
  const pop = openPopoverAttach(rangeBtn, el('div', { class: 'pop-panel-body' },
    quickRow,
    el('div', { class: 'pop-fields' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '开始（含当日）'), fromInput),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '结束（含当日）'), toInput)),
    rangeError,
    el('div', { class: 'pop-actions' },
      el('span', { class: 'muted' }, `时区 ${tz()} · 结束日含当日`),
      el('button', { class: 'btn primary small', type: 'button', onclick: applyRange }, '应用'))));

  /* 数据环境 */
  const envSeg = el('div', { class: 'm-seg', role: 'group', 'aria-label': '数据环境' },
    el('button', { class: state.environment === 'LIVE' ? 'active' : '', type: 'button', onclick: () => setEnvironment('LIVE') }, '正式'),
    el('button', { class: state.environment === 'TEST' ? 'active' : '', type: 'button', onclick: () => setEnvironment('TEST') }, '测试'));
  const envWrap = can(PERM.ordersRead) || can(PERM.reportsRead) ? envSeg : el('span', { class: 'muted small-text' }, '环境 LIVE');

  holder.append(
    el('label', { class: 'm-ctl' }, el('span', { class: 'm-ctl-label' }, '组织'), orgSelect),
    el('label', { class: 'm-ctl' }, el('span', { class: 'm-ctl-label' }, '门店'), storeSelect),
    el('div', { class: 'm-ctl' }, el('span', { class: 'm-ctl-label' }, '日期区间'), rangeBtn),
    el('div', { class: 'm-ctl' }, el('span', { class: 'm-ctl-label' }, '数据环境'), envWrap),
    buildUserMenu());
}

function setEnvironment(environment) {
  state.environment = environment;
  updateEnvBanner();
  buildShellControls();
  reloadView();
}

function updateEnvBanner() {
  const banner = $('env-banner');
  if (state.environment === 'TEST' && state.session) {
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}

function buildUserMenu() {
  const role = roleNow();
  const btn = el('button', { class: 'btn secondary small user-btn', type: 'button', 'aria-expanded': 'false' },
    el('span', null, state.session.user.displayName || accountLabel(state.session.user)));
  const panel = el('div', { class: 'pop-panel user-panel' },
    el('div', { class: 'user-panel-head' },
      el('strong', null, state.session.user.displayName || '—'),
      typeof state.session.user.username === 'string' && state.session.user.username
        ? el('span', { class: 'muted mono' }, `用户名 ${state.session.user.username}`) : null,
      typeof state.session.user.email === 'string' && state.session.user.email
        ? el('span', { class: 'muted' }, state.session.user.email) : null,
      el('span', { class: 'muted' }, `${ROLE_LABEL[role] || role || ''}`)),
    el('div', { class: 'user-panel-actions' },
      el('button', {
        class: 'btn secondary small block', type: 'button',
        onclick: async () => { closePopover(pop); await reauthModal(); },
      }, '重新验证身份'),
      el('button', {
        class: 'btn secondary small block', type: 'button',
        onclick: async () => {
          closePopover(pop);
          const ok = await confirmModal({
            title: '撤销其他会话',
            message: '撤销除当前浏览器以外的所有登录会话？其他设备将需要重新登录。',
            confirmText: '撤销', danger: true,
          });
          if (!ok) return;
          try {
            const result = await adapter.revokeOtherSessions();
            toast(`已撤销 ${result.revokedCount} 个其他会话`, 'success');
          } catch (error) { toast(describeMerchantError(error), 'error'); }
        },
      }, '撤销其他会话'),
      el('button', { class: 'btn ghost small block', type: 'button', onclick: () => { closePopover(pop); doLogout(); } }, '退出登录')));
  const pop = attachPopover(btn, panel);
  return el('div', { class: 'm-ctl' }, el('span', { class: 'm-ctl-label' }, '账号'), btn);
}

/* ---------------- Popover ---------------- */

const popovers = [];

function closePopover(handle) {
  if (!handle) return;
  handle.panel.classList.add('hidden');
  handle.anchor.setAttribute('aria-expanded', 'false');
  if (handle.outside) handle.outside.remove();
  handle.outside = null;
  const index = popovers.indexOf(handle);
  if (index >= 0) popovers.splice(index, 1);
}

function attachPopover(anchor, panel) {
  const wrap = el('div', { class: 'm-pop' }, anchor, panel);
  panel.classList.add('hidden');
  const handle = { anchor, panel, wrap, outside: null };
  anchor.addEventListener('click', event => {
    event.stopPropagation();
    const isOpen = !panel.classList.contains('hidden');
    for (const other of [...popovers]) closePopover(other);
    if (!isOpen) {
      panel.classList.remove('hidden');
      anchor.setAttribute('aria-expanded', 'true');
      handle.outside = el('div', { class: 'pop-outside', onclick: () => closePopover(handle) });
      wrap.append(handle.outside);
      popovers.push(handle);
      const focusable = panel.querySelector('select, input, button');
      if (focusable) focusable.focus();
    } else {
      closePopover(handle);
    }
  });
  return handle;
}

function openPopoverAttach(anchor, body) {
  const panel = el('div', { class: 'pop-panel' }, body);
  return attachPopover(anchor, panel);
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') for (const handle of [...popovers]) closePopover(handle);
});

/* ---------------- 路由 ---------------- */

const VIEW_DEFS = [
  { id: 'dashboard', group: '经营', label: '总览', title: '经营总览', sub: '设备、收入、成本与告警快照', perm: PERM.dashboard, icon: icon.dashboard, render: renderDashboardView },
  { id: 'orders', group: '经营', label: '订单', title: '订单', sub: '支付、制作进度与退款', perm: PERM.ordersRead, icon: icon.orders, render: renderOrdersView },
  { id: 'reports', group: '经营', label: '经营报表', title: '经营报表', sub: '日 / 月 / 年口径与导出', perm: PERM.reportsRead, icon: icon.report, render: renderReportsView },
  { id: 'devices', group: '设备', label: '我的设备', title: '我的设备', sub: '资产、运维与远程命令', perm: PERM.devicesRead, icon: icon.device, render: renderDevicesView },
  { id: 'transfers', group: '设备', label: '设备转让', title: '设备转让', sub: '转让申请、阻断与确认', perm: PERM.devicesTransfer, icon: icon.swap, render: renderTransfersView },
  { id: 'stores', group: '设备', label: '门店', title: '门店', sub: '经营场所与归档', perm: PERM.storesRead, icon: icon.store, render: renderStoresView },
  { id: 'prices', group: '设备', label: '商品价格', title: '商品价格', sub: '当前价与计划生效价', perm: PERM.pricesRead, icon: icon.price, render: renderPricesView },
  { id: 'materials', group: '成本', label: '物料·采购·库存', title: '物料、采购与库存', sub: '物料档案、采购入账、库存与出入库', perm: PERM.inventoryRead, icon: icon.material, render: renderMaterialsView },
  { id: 'expenses', group: '成本', label: '运营费用', title: '运营费用', sub: '租金、人工、水电与维护', perm: PERM.costsRead, icon: icon.expense, render: renderExpensesView },
  { id: 'members', group: '组织', label: '成员权限', title: '成员权限', sub: '角色、门店范围与邀请', perm: PERM.membersRead, icon: icon.members, render: renderMembersView },
  { id: 'accounts', group: '组织', label: '收款账户', title: '收款账户', sub: '商户账户、校验与默认', perm: PERM.paymentsRead, icon: icon.wallet, render: renderAccountsView },
  { id: 'settings', group: '组织', label: '组织设置', title: '组织设置', sub: '名称与时区', perm: PERM.tenantManage, icon: icon.settings, render: renderSettingsView },
  { id: 'audit', group: '组织', label: '审计', title: '审计日志', sub: '操作者、动作与结果', perm: PERM.auditRead, icon: icon.audit, render: renderAuditView },
];

function findViewDef(id) {
  return VIEW_DEFS.find(def => def.id === id && can(def.perm));
}

function route() {
  if (!state.session) { renderAuth(); return; }
  closeDrawer();
  for (const handle of [...popovers]) closePopover(handle);
  const target = hashRoute().path;
  let def = findViewDef(target);
  if (!def) {
    def = VIEW_DEFS.find(item => can(item.perm));
    if (!def) { renderNoAccess(); return; }
    if (def.id !== target) { location.hash = `#/${def.id}`; return; }
  }
  state.view = def.id;
  document.title = `Coffee Cloud · ${def.title}`;
  $('view-title').textContent = def.title;
  $('view-sub').textContent = def.sub;
  buildShell();
  dashboardMemo = { key: '', promise: null }; /* 新视图 / 新筛选不再复用旧总览快照 */
  const workspace = $('workspace');
  clearNode(workspace);
  def.render(workspace);
  $('workspace').focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

function renderNoAccess() {
  const workspace = $('workspace');
  clearNode(workspace);
  workspace.append(el('section', { class: 'card' }, deniedState('任何视图权限', '当前账号没有可用的后台视图。请联系组织 OWNER 分配角色。')));
}

function reloadView() {
  if (!state.session) return;
  route();
}

window.addEventListener('hashchange', () => {
  if (state.session) route();
  else renderAuth();
});

/* ============================================================
   视图一：经营总览
   ============================================================ */

function dashboardParams() {
  return {
    ...periodToApiParams(state.period),
    storeId: state.storeId || undefined,
    environment: state.environment,
  };
}

/* 总览一次渲染会请求 4 个区域（卡片 / 趋势 / 告警 / 最近订单）：
   合并为同一快照请求，保证四块数据一致，也避免 4 次重复往返。
   route() 时失效；组织切换 / 重载会走 route，不会拿到旧组织数据。 */
let dashboardMemo = { key: '', promise: null };

function fetchDashboardSnapshot() {
  const key = JSON.stringify(dashboardParams());
  if (dashboardMemo.key !== key || !dashboardMemo.promise) {
    const promise = adapter.dashboard(dashboardParams());
    /* 失败（含网络中断 / 中止）后清空缓存：重试按钮必须发起新请求，
       而不是回放同一个被拒绝的 Promise。 */
    promise.catch(() => { if (dashboardMemo.promise === promise) dashboardMemo = { key: '', promise: null }; });
    dashboardMemo = { key, promise };
  }
  return dashboardMemo.promise;
}

function statCard(label, value, { sub, kind, num = true } = {}) {
  return el('div', { class: 'stat' },
    el('div', { class: 'stat-label' }, label),
    el('div', { class: `stat-value${kind ? ' ' + kind : ''}${num ? ' num' : ''}` }, value),
    sub ? el('div', { class: 'stat-sub' }, sub) : null);
}

/** 有限发布说明：仅在总览顶部出现一次，不逐页重复。 */
function releaseNoteNode() {
  if (!state.session || !authPolicy().limitedRelease) return null;
  return el('div', { class: 'callout release-note', role: 'note', 'aria-label': '上线说明' },
    el('strong', null, '上线说明（首批开放）'),
    el('span', null, '当前已开放账号、组织、门店与基础运营管理；设备转让、商户收款配置暂未开放；设备消耗自动计成本尚未接入，报表缺项会显示“待补全”；库存为账面库存，不代表设备实时可用量。'));
}

function renderDashboardView(root) {
  const cards = el('div', { class: 'm-cards', id: 'dash-cards' }, skeletonCards(4));
  const trend = el('div', { id: 'dash-trend' }, skeletonRows(5));
  const alerts = el('section', { class: 'card', id: 'dash-alerts' },
    el('div', { class: 'card-head' }, el('h3', null, '待处理告警'), el('span', { class: 'muted' }, '设备与库存')),
    el('div', { class: 'card-body' }, skeletonRows(3)));
  const recent = el('section', { class: 'card', id: 'dash-recent' },
    el('div', { class: 'card-head' }, el('h3', null, '最近订单'),
      el('button', { class: 'btn ghost small', type: 'button', onclick: () => { location.hash = '#/orders'; } }, '全部订单 →')),
    el('div', { class: 'card-body' }, skeletonRows(4)));
  root.append(releaseNoteNode(), cards, trend, el('div', { class: 'split-2' }, alerts, recent));
  loadRegion(cards, loadDashboardCards);
  loadRegion(trend, loadDashboardTrend);
  loadRegion(alerts, loadDashboardAlerts);
  loadRegion(recent, loadDashboardRecent);
}

function completenessNote(completeness) {
  if (!completeness || completeness.status === 'COMPLETE') return null;
  const meta = COMPLETENESS[completeness.status] || COMPLETENESS.INCOMPLETE;
  const missing = (completeness.missing || []).join('、');
  return el('div', { class: `callout ${completeness.status === 'INCOMPLETE' ? 'callout-amber' : 'callout-amber'}` },
    el('span', null, statusBadge(COMPLETENESS, completeness.status)),
    el('span', null, missing ? `缺失项：${missing}。对应金额显示“待补全”，不会按 0 计算。` : '部分成本为估算值，利润仅供参考。'));
}

async function loadDashboardCards(container) {
  const data = await fetchDashboardSnapshot();
  clearNode(container);
  if (!data || !data.metrics) {
    container.append(el('section', { class: 'card' }, emptyState('暂无总览数据', '当前筛选条件下没有数据。')));
    return;
  }
  const m = data.metrics;
  const operatorView = !can(PERM.costsRead) && !can(PERM.reportsRead);
  const onlineRate = percent(m.onlineCount, m.deviceCount);
  if (operatorView) {
    container.append(
      statCard('设备总数', String(m.deviceCount ?? '—'), { sub: `在线 ${m.onlineCount ?? '—'}`, num: false }),
      statCard('在线率', onlineRate ?? '—', { kind: 'green' }),
      statCard('完成杯数', String(m.deliveredCupCount ?? '—')),
      statCard('待处理告警', String((data.alerts || []).length), { kind: (data.alerts || []).length ? 'red' : 'green' }));
    container.append(el('p', { class: 'field-hint' }, '当前角色为运维视角：设备与订单运维数据可见，经营收入与利润不展示。'));
  } else {
    container.append(
      statCard('设备 / 在线', `${m.deviceCount ?? '—'} / ${m.onlineCount ?? '—'}`, { sub: '资产与实时在线', num: false }),
      statCard('营业净收入', fmtMoney(m.recognizedRevenueMinor), { sub: '制作交付确认的收入口径', kind: 'green' }),
      statCard('净收款', fmtMoney(m.netCashMinor), { sub: `实收 ${fmtMoney(m.receivedMinor)} − 退款 ${fmtMoney(m.refundedMinor)}（资金流）` }),
      statCard('经营利润（估算）', fmtMoney(m.estimatedProfitMinor), { sub: '毛利 − 损耗 − 手续费 − 分摊费用', kind: m.estimatedProfitMinor === null ? 'amber' : 'green' }));
    const chips = [
      ['支付订单数', String(m.paidOrderCount ?? '—')], ['完成杯数', String(m.deliveredCupCount ?? '—')],
      ['材料成本', fmtMoney(m.materialCostMinor)], ['损耗', fmtMoney(m.wasteCostMinor)],
      ['支付手续费', fmtMoney(m.paymentFeeMinor)], ['运营费用（分摊）', fmtMoney(m.operatingExpenseMinor)],
    ];
    container.append(el('div', { class: 'chip-row', style: 'grid-column:1/-1' },
      chips.map(([label, value]) => el('div', { class: 'chip' }, el('span', { class: 'chip-label' }, label), el('span', { class: 'chip-value num' }, value))),
      el('div', { style: 'display:contents' }, completenessNote(data.completeness))));
  }
}

async function loadDashboardTrend(container) {
  if (!can(PERM.costsRead) && !can(PERM.reportsRead)) {
    clearNode(container);
    return;
  }
  const data = await fetchDashboardSnapshot();
  clearNode(container);
  if (!data || !data.trend || !data.trend.length) {
    container.append(el('section', { class: 'card' }, emptyState('区间内没有趋势数据', '调整日期区间或门店筛选后重试。')));
    return;
  }
  const labels = data.trend.map(p => p.date.slice(5));
  const receivedSum = sumMinor(data.trend, 'receivedMinor');
  const profitSum = sumMinor(data.trend, 'estimatedProfitMinor');
  container.append(chartCard({
    title: '收款与估算利润趋势',
    hint: `${exclusiveEndToInclusive(data.period.to)} 前（含） · ${data.period.timezone}`,
    labels,
    series: [
      { name: '实收', values: data.trend.map(p => p.receivedMinor), className: 'c-main' },
      { name: '经营利润（估算）', values: data.trend.map(p => p.estimatedProfitMinor), className: 'c-green' },
    ],
    summaryText: `区间实收合计 ${fmtMoney(receivedSum.sum)}${receivedSum.hasUnknown ? '（部分未知按缺口处理）' : ''}；估算利润合计 ${fmtMoney(profitSum.sum)}${profitSum.hasUnknown ? '（成本缺失日期不绘制，不按 0 计算）' : ''}。`,
  }));
}

const SEVERITY = { ERROR: { label: '严重', kind: 'red' }, WARNING: { label: '警告', kind: 'amber' }, INFO: { label: '提示', kind: 'blue' } };

async function loadDashboardAlerts(container) {
  const data = await fetchDashboardSnapshot();
  const body = container.querySelector('.card-body');
  if (!body) return;
  clearNode(body);
  const alerts = (data && data.alerts) || [];
  if (!alerts.length) {
    body.append(emptyState('没有待处理告警', '设备与库存状态正常'));
    return;
  }
  body.append(el('div', { class: 'alert-list' }, alerts.map(alert => el('div', { class: 'alert-item' },
    statusBadge(SEVERITY, alert.severity),
    el('div', null,
      el('div', { class: 'cell-strong' }, alert.title),
      el('div', { class: 'cell-sub' }, alert.description || ''))))));
}

async function loadDashboardRecent(container) {
  const data = await fetchDashboardSnapshot();
  const body = container.querySelector('.card-body');
  if (!body) return;
  clearNode(body);
  const orders = (data && data.recentOrders) || [];
  if (!orders.length) { body.append(emptyState('最近没有订单', '设备产生订单后显示在这里')); return; }
  const rows = orders.map(order => el('tr', {
    class: 'clickable',
    onclick: () => { state.ordersFocusId = order.id; location.hash = '#/orders'; },
  },
    tdl(el('span', { class: 'mono cell-strong' }, order.orderNo), '订单'),
    tdl(fmtDateTime(order.createdAt, tz()), '时间'),
    tdl(`${order.storeNameSnapshot || '—'} · ${order.deviceNameSnapshot || ''}`, '门店 / 设备'),
    tdl(el('span', { class: 'num' }, fmtMoney(order.totalMinor)), '金额'),
    tdl(statusBadge(PAY_STATUS, order.paymentStatus), '支付'),
    tdl(statusBadge(PROD_STATUS, order.productionStatus), '制作'),
    tdl(order.environment === 'TEST' ? badge('amber', '测试') : badge('outline', '正式'), '环境')));
  body.append(makeTable({ headers: ['订单', '时间', '门店 / 设备', '金额', '支付', '制作', '环境'], rows, minTable: 720 }));
}

/* ============================================================
   视图二：我的设备
   ============================================================ */

function renderDevicesView(root) {
  const search = el('input', { class: 'input', type: 'search', placeholder: '搜索名称 / 设备号 / 序列号' });
  const statusSel = el('select', { class: 'input' },
    [el('option', { value: '' }, '全部状态'),
      ...Object.entries(LIFECYCLE).map(([value, meta]) => el('option', { value }, meta.label))]);
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  const listRegion = el('section', { class: 'card', id: 'device-list' });
  const refresh = () => {
    state.deviceFilters = { q: search.value.trim(), status: statusSel.value, storeId: storeSel.value };
    loadRegion(listRegion, loadDeviceList);
  };
  search.addEventListener('input', refresh);
  statusSel.addEventListener('change', refresh);
  storeSel.addEventListener('change', refresh);
  state.deviceFilters = { q: '', status: '', storeId: state.storeId };
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '搜索'), search),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '生命周期'), statusSel),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'toolbar-actions' },
        can(PERM.devicesClaim)
          ? el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>认领设备</span>', onclick: openClaimModal })
          : null)),
    listRegion);
  listRegion.append(skeletonRows(5));
  loadRegion(listRegion, loadDeviceList);
}

async function loadDeviceList(container) {
  const filters = state.deviceFilters || {};
  const { items } = await adapter.listDevices({
    storeId: filters.storeId || undefined, status: filters.status || undefined,
  });
  let filtered = items;
  if (filters.q) {
    const q = filters.q.toLowerCase();
    filtered = filtered.filter(d => [d.name, d.deviceId, d.serialNumber, d.storeName].join(' ').toLowerCase().includes(q));
  }
  clearNode(container);
  if (!filtered.length) {
    container.append(emptyState(items.length ? '没有符合筛选条件的设备' : '还没有设备',
      items.length ? '调整筛选条件后重试' : (can(PERM.devicesClaim) ? '使用「认领设备」录入出厂资产认领码接入设备' : '需要 devices.claim 权限认领设备')));
    return;
  }
  const rows = filtered.map(device => el('tr', {
    class: 'clickable',
    onclick: () => openDeviceDrawer(device.id),
  },
    tdl(el('div', null,
      el('div', { class: 'cell-strong' }, device.name || '未命名'),
      el('div', { class: 'cell-sub mono' }, `${device.deviceId} · ${device.serialNumber || '—'}`)), '设备'),
    tdl(device.storeName || '—', '门店'),
    tdl(statusBadge(LIFECYCLE, device.lifecycle), '生命周期'),
    tdl(device.online ? badge('green', '在线') : badge(device.lastSeenAt ? 'red' : 'gray', device.lastSeenAt ? '离线' : '未上线'), '连接'),
    tdl(fmtDateTime(device.lastSeenAt, tz()), '最近心跳'),
    tdl(el('span', { class: 'muted num' }, `v${device.version} / ov${device.ownershipVersion}`), '版本')));
  container.append(makeTable({ headers: ['设备', '门店', '生命周期', '连接', '最近心跳', '版本'], rows, minTable: 780 }));
}

function openClaimModal() {
  const claimCode = el('input', { class: 'input mono', placeholder: '出厂资产认领码', autocomplete: 'off', required: true });
  const storeSel = el('select', { class: 'input' }, storeOptions('', { allLabel: '请选择门店' }));
  const name = el('input', { class: 'input', placeholder: '例如：大堂 1 号机', maxlength: '60' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '认领');
  submit.addEventListener('click', () => form.requestSubmit());
  const idem = newIdemScope();
  const form = el('form', {
    onsubmit: async event => {
      event.preventDefault();
      clearFieldErrors(form);
      errorNode.textContent = '';
      if (!claimCode.value.trim()) { showFieldErrors(form, { claimCode: '请填写认领码' }); return; }
      busy(submit, '认领中…');
      try {
        const device = await adapter.claimDevice({
          claimCode: claimCode.value.trim(), storeId: storeSel.value || undefined, name: name.value.trim() || undefined,
        }, idem.current());
        modal.close();
        toast(`设备 ${device.deviceId} 已认领到「${device.storeName || '门店'}」`, 'success');
        reloadView();
      } catch (error) {
        unbusy(submit, '认领');
        showFieldErrors(form, error.fields, errorNode, describeMerchantError(error));
        idem.reset();
      }
    },
  },
    el('p', { class: 'field-hint' }, '认领码是出厂资产的归属凭据，不是设备 HTTP / MQTT 激活凭据；每个认领码只能使用一次。'),
    el('div', { class: 'field', 'data-field': 'claimCode' }, el('span', { class: 'field-label' }, '资产认领码 *'), claimCode),
    el('div', { class: 'field', 'data-field': 'storeId' }, el('span', { class: 'field-label' }, '归属门店 *'), storeSel),
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, '设备名称'), name),
    errorNode);
  const modal = openModal({
    title: '认领出厂设备',
    body: [form],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
}

let devicePollTimer = null;

async function openDeviceDrawer(deviceId) {
  if (devicePollTimer) { clearInterval(devicePollTimer); devicePollTimer = null; }
  const content = el('div', null, skeletonRows(6));
  const drawer = openDrawer({ title: '设备详情', sub: '', content, onClose: () => { if (devicePollTimer) clearInterval(devicePollTimer); } });
  const epoch = state.epoch;
  try {
    const device = await adapter.getDevice(deviceId);
    if (stale(epoch) || !activeDrawer || activeDrawer !== drawer) return;
    paintDeviceDrawer(drawer, device);
  } catch (error) {
    if (error && error.aborted) return;
    if (stale(epoch)) return;
    if (handleErrorGlobal(error)) return;
    clearNode(drawer.body);
    drawer.body.append(errorState(error, () => openDeviceDrawer(deviceId)));
  }
}

function paintDeviceDrawer(drawer, device) {
  const store = device.storeName || '—';
  drawer.panel.setAttribute('aria-label', `设备详情 ${device.name || device.deviceId}`);
  clearNode(drawer.body);
  drawer.body.append(
    el('div', { class: 'drawer-title-row' },
      el('div', null,
        el('h4', null, device.name || '未命名设备'),
        el('p', { class: 'muted mono' }, `${device.deviceId} · SN ${device.serialNumber || '—'}`)),
      el('div', { class: 'badge-col' },
        statusBadge(LIFECYCLE, device.lifecycle),
        device.online ? badge('green', '在线') : badge(device.lastSeenAt ? 'red' : 'gray', device.lastSeenAt ? '离线' : '未上线'))),
    el('div', { class: 'detail-sec' },
      el('h4', null, '基本信息'),
      el('div', { class: 'kv-grid' },
        kv('门店', store),
        kv('最近心跳', fmtDateTime(device.lastSeenAt, tz())),
        kv('归属版本', `v${device.ownershipVersion}`),
        kv('数据版本', `v${device.version}`),
        kv('当前任务', device.currentJob ? `${device.currentJob.status}${device.currentJob.productName ? ' · ' + device.currentJob.productName : ''}` : '无'),
        kv('告警数', String((device.alerts || []).length)))),
    el('div', { class: 'detail-sec' },
      el('h4', null, '能力清单（设备上报）'),
      (device.capabilities || []).length
        ? el('div', { class: 'plain-list' }, device.capabilities.map(cap => el('div', { class: 'plain-item' },
            el('span', null, cap.name || cap.id),
            el('span', { class: 'muted' }, cap.estimatedSeconds ? `约 ${Math.ceil(cap.estimatedSeconds / 60)} 分钟` : ''))))
        : emptyState('尚未上报能力', '')),
    el('div', { class: 'detail-sec' },
      el('h4', null, '物料余量'),
      (device.inventory || []).length
        ? el('div', { class: 'material-list' }, device.inventory.map(mat => {
            const onHand = Number(mat.onHandQuantity || 0);
            /* 契约未含容量字段：条宽按状态分级展示，不臆造容量百分比 */
            const level = mat.status === 'CRITICAL' ? 'crit' : mat.status === 'LOW' ? 'low' : 'ok';
            const ratio = level === 'crit' ? 0.12 : level === 'low' ? 0.35 : 1;
            void onHand;
            return el('div', { class: 'material-item' },
              el('div', { class: 'm-row' },
                el('strong', null, mat.name),
                badge(level === 'crit' ? 'red' : level === 'low' ? 'amber' : 'green',
                  mat.status === 'CRITICAL' ? '危急' : mat.status === 'LOW' ? '偏低' : '正常')),
              el('div', { class: 'material-bar' }, el('i', { class: level, style: `width:${Math.round(ratio * 100)}%` })),
              el('div', { class: 'm-row' },
                el('span', { class: 'muted' }, `可用 ${mat.availableQuantity ?? '—'} / 在存 ${mat.onHandQuantity ?? '—'} ${mat.unit || ''}`),
                el('span', { class: 'muted' }, `占用 ${mat.reservedQuantity ?? '—'}`)));
          }))
        : emptyState('尚未上报物料', '')),
    (device.alerts || []).length ? el('div', { class: 'detail-sec' },
      el('h4', null, '告警'),
      el('div', { class: 'alert-list' }, device.alerts.map(a => el('div', { class: 'alert-item' },
        statusBadge(SEVERITY, a.severity),
        el('div', null, el('div', { class: 'cell-strong' }, a.title), el('div', { class: 'cell-sub' }, a.description || '')))))) : null,
    el('div', { class: 'detail-sec', id: 'device-actions-sec' },
      el('h4', null, '操作'),
      deviceActionsRow(device),
      el('div', { id: 'command-status-slot' })),
  );
}

function deviceActionsRow(device) {
  const allowed = new Set(device.allowedActions || []);
  const buttons = [];
  if ((allowed.has('RENAME') || allowed.has('REASSIGN')) && can(PERM.devicesManage)) {
    buttons.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => openDeviceEditModal(device) }, '编辑资料'));
  }
  const lifecycleActions = ['SUSPEND', 'RESUME', 'ARCHIVE'].filter(a => allowed.has(a));
  if (lifecycleActions.length && can(PERM.devicesManage)) {
    buttons.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => openLifecycleModal(device, lifecycleActions) }, '生命周期变更'));
  }
  if (allowed.has('REQUEST_UNBIND') && can(PERM.devicesManage)) {
    buttons.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => openUnbindModal(device) }, '申请解绑'));
  }
  if (allowed.has('REQUEST_TRANSFER') && can(PERM.devicesTransfer)) {
    buttons.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => openTransferRequestModal(device) }, '发起转让'));
  }
  for (const command of ['RELOAD_CONFIG', 'SYNC_CONFIG', 'CLEAN', 'RESTART_APP']) {
    if (!allowed.has(`COMMAND_${command}`)) continue;
    if (!can(PERM.commands)) continue;
    buttons.push(el('button', {
      class: `btn small ${command === 'RESTART_APP' ? 'danger' : 'secondary'}`, type: 'button',
      onclick: () => sendDeviceCommandFlow(device, command),
    }, COMMAND_LABEL[command] || command));
  }
  if (!buttons.length) return el('p', { class: 'muted' }, '当前状态或角色没有可用操作。');
  return el('div', { class: 'action-row' }, buttons,
    el('p', { class: 'field-hint', style: 'flex-basis:100%' }, '操作项由服务器 allowedActions 决定；远程命令经确认后下发，成功仅代表已受理。'));
}

function openDeviceEditModal(device) {
  const name = el('input', { class: 'input', value: device.name || '', maxlength: '60' });
  const storeSel = el('select', { class: 'input' }, storeOptions(device.storeId, { allLabel: '未分配门店' }));
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '保存');
  const modal = openModal({
    title: `编辑设备 · ${device.deviceId}`,
    body: [
      el('div', { class: 'field', 'data-field': 'name' }, el('span', { class: 'field-label' }, '设备名称'), name),
      el('div', { class: 'field', 'data-field': 'storeId' }, el('span', { class: 'field-label' }, '归属门店'), storeSel),
      el('p', { class: 'field-hint' }, `携带版本 v${device.version} 提交；若其他成员已修改将返回 409，需要重新读取。`),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    busy(submit, '保存中…');
    try {
      await adapter.updateDevice(device.id, { name: name.value.trim(), storeId: storeSel.value || undefined, version: device.version });
      modal.close();
      toast('设备资料已更新', 'success');
      openDeviceDrawer(device.id);
      reloadDeviceListOnly();
    } catch (error) {
      unbusy(submit, '保存');
      if (isVersionConflict(error)) { showConflictRetry(errorNode, error, () => { modal.close(); openDeviceDrawer(device.id); reloadDeviceListOnly(); }); return; }
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

function openLifecycleModal(device, actions) {
  const actionSel = el('select', { class: 'input' },
    actions.map(a => el('option', { value: a }, {
      SUSPEND: 'SUSPEND · 停用（停止派单与售卖）',
      RESUME: 'RESUME · 恢复运行',
      ARCHIVE: 'ARCHIVE · 归档（退役，不可恢复运行）',
    }[a] || a)));
  const reason = el('textarea', { class: 'input', placeholder: '填写原因（写入审计日志）', maxlength: '500' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn danger', type: 'button' }, '提交变更');
  const modal = openModal({
    title: `生命周期变更 · ${device.name || device.deviceId}`,
    body: [
      el('p', { class: 'field-hint' }, `门店「${device.storeName || '—'}」· 归属版本 v${device.ownershipVersion}。ARCHIVE 为退役操作，请谨慎确认。`),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '目标状态 *'), actionSel),
      el('div', { class: 'field', 'data-field': 'reason' }, el('span', { class: 'field-label' }, '原因（必填）'), reason),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (reason.value.trim().length < 3) { showFieldErrors(modal.card, { reason: '原因至少 3 个字符' }); return; }
    const action = actionSel.value;
    if (action === 'ARCHIVE') {
      const ok = await confirmModal({ title: '二次确认', message: `确认归档设备「${device.name || device.deviceId}」？归档后设备退役，历史订单保留。`, confirmText: '确认归档', danger: true, requireText: '归档' });
      if (!ok) return;
    }
    busy(submit, '提交中…');
    try {
      await withReauth(() => adapter.deviceLifecycle(device.id, { action, reason: reason.value.trim(), version: device.version }));
      modal.close();
      toast(`生命周期已变更为 ${action}`, 'success');
      openDeviceDrawer(device.id);
      reloadDeviceListOnly();
    } catch (error) {
      unbusy(submit, '提交变更');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

function openUnbindModal(device) {
  const reason = el('textarea', { class: 'input', placeholder: '申请解绑原因（平台将审核）', maxlength: '500' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '提交申请');
  const modal = openModal({
    title: `申请解绑 · ${device.name || device.deviceId}`,
    body: [
      el('p', { class: 'field-hint' }, '解绑申请需平台审核；审核通过前设备的归属、订单与历史保持不变。'),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '原因（必填）'), reason),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    errorNode.textContent = '';
    if (reason.value.trim().length < 3) { errorNode.textContent = '原因至少 3 个字符'; return; }
    busy(submit, '提交中…');
    try {
      const result = await adapter.createUnbindRequest(device.id, { reason: reason.value.trim(), ownershipVersion: device.ownershipVersion });
      modal.close();
      toast(`解绑申请已提交（${result.status === 'PENDING_APPROVAL' ? '等待平台审核' : result.status}）`, 'success');
    } catch (error) {
      unbusy(submit, '提交申请');
      errorNode.textContent = describeMerchantError(error);
    }
  });
}

function openTransferRequestModal(device) {
  const target = el('input', { class: 'input', placeholder: '目标组织标识（由对方提供）', autocomplete: 'off' });
  const reason = el('textarea', { class: 'input', placeholder: '转让原因', maxlength: '500' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '提交转让申请');
  const idem = newIdemScope();
  const modal = openModal({
    title: `发起转让 · ${device.name || device.deviceId}`,
    body: [
      el('p', { class: 'field-hint' }, '转让流程：接收方确认 → 平台审核 → 完成。存在在途生产、退款或人工 HOLD 时会被阻断；历史订单仍归属本组织。'),
      el('div', { class: 'field', 'data-field': 'targetTenantReference' }, el('span', { class: 'field-label' }, '目标组织 *'), target),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '原因'), reason),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!target.value.trim()) { showFieldErrors(modal.card, { targetTenantReference: '请填写目标组织' }); return; }
    busy(submit, '提交中…');
    try {
      const result = await adapter.createTransferRequest(device.id, {
        targetTenantReference: target.value.trim(), reason: reason.value.trim(), ownershipVersion: device.ownershipVersion,
      }, idem.current());
      modal.close();
      if (result.status === 'BLOCKED') {
        toast('转让申请被阻断，请在「设备转让」查看阻断原因', 'error');
      } else {
        toast(`转让申请已提交（${TRANSFER_STATUS[result.status] ? TRANSFER_STATUS[result.status].label : result.status}）`, 'success');
      }
    } catch (error) {
      unbusy(submit, '提交转让申请');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

async function sendDeviceCommandFlow(device, command) {
  const confirmed = await confirmModal({
    title: `下发命令 · ${COMMAND_LABEL[command] || command}`,
    message: el('div', null,
      el('p', { style: 'margin:0 0 6px' }, `即将向设备「${device.name || device.deviceId}」（门店：${device.storeName || '—'}）下发 ${COMMAND_LABEL[command] || command}。`),
      el('p', { class: 'muted', style: 'margin:0' }, command === 'RESTART_APP' ? '重启会中断进行中的制作，进行中订单可能进入待人工确认状态。' : '命令经设备命令通道下发，受理后异步执行。')),
    confirmText: '确认下发',
    danger: command === 'RESTART_APP',
  });
  if (!confirmed) return;
  const slot = $('command-status-slot');
  if (!slot) return;
  clearNode(slot);
  const statusLine = el('div', { class: 'command-status' }, badge('blue', '已受理 PENDING'), el('span', { class: 'muted' }, '命令已提交，等待设备执行…'));
  slot.append(statusLine);
  let commandId = null;
  try {
    const result = await adapter.sendDeviceCommand(device.id, { command, parameters: {}, ownershipVersion: device.ownershipVersion }, newIdemScope().current());
    commandId = result.id;
  } catch (error) {
    clearNode(slot);
    slot.append(el('div', { class: 'command-status' }, badge('red', '下发失败'), el('span', { class: 'muted' }, describeMerchantError(error))));
    return;
  }
  let polls = 0;
  const poll = async () => {
    polls += 1;
    try {
      const status = await adapter.getDeviceCommand(device.id, commandId);
      clearNode(slot);
      const kind = status.status === 'SUCCEEDED' ? 'green' : status.status === 'FAILED' ? 'red' : 'blue';
      const label = { PENDING: '已受理 PENDING', EXECUTING: '执行中 EXECUTING', SUCCEEDED: '完成 SUCCEEDED', FAILED: '失败 FAILED', TIMEOUT: '超时 TIMEOUT' }[status.status] || status.status;
      slot.append(el('div', { class: 'command-status' }, badge(kind, label),
        el('span', { class: 'muted' }, status.resultMessage || `命令 ${command} · ${commandId}`)));
      if (status.status === 'PENDING' || status.status === 'EXECUTING') {
        if (polls >= 8) {
          slot.append(el('div', { class: 'command-status' }, badge('amber', '查询超时'), el('span', { class: 'muted' }, '设备长时间未回报，请稍后手动刷新或联系运维。')));
          return;
        }
        devicePollTimer = setTimeout(poll, 2500);
      }
    } catch (error) {
      clearNode(slot);
      slot.append(el('div', { class: 'command-status' }, badge('red', '状态查询失败'), el('span', { class: 'muted' }, describeMerchantError(error))));
    }
  };
  devicePollTimer = setTimeout(poll, 1800);
}

function reloadDeviceListOnly() {
  const container = $('device-list');
  if (container) loadRegion(container, loadDeviceList);
}

/* ============================================================
   视图三：设备转让
   ============================================================ */

function renderTransfersView(root) {
  const region = el('section', { class: 'card' });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '转让记录'),
        el('span', { class: 'field-hint' }, '状态流：等待接收方确认 → 等待平台审核 → 完成；也可被阻断、取消或拒绝。')),
      el('div', { class: 'toolbar-actions' },
        el('button', { class: 'btn secondary small', type: 'button', html: icon.refresh + '<span>刷新</span>', onclick: () => loadRegion(region, loadTransfers) }))),
    region);
  region.append(skeletonRows(4));
  loadRegion(region, loadTransfers);
}

async function loadTransfers(container) {
  const { items } = await adapter.listTransfers();
  clearNode(container);
  if (!items.length) {
    container.append(emptyState('没有转让记录', '在「我的设备」详情中发起转让申请'));
    return;
  }
  const rows = items.map(transfer => {
    const actions = [];
    if (transfer.status === 'PENDING_RECIPIENT' && transfer.direction === 'IN' && can(PERM.devicesTransfer)) {
      actions.push(el('button', {
        class: 'btn primary small', type: 'button',
        onclick: () => transferAction(transfer, 'accept'),
      }, '确认接收'));
    }
    if (['PENDING_RECIPIENT', 'PENDING_PLATFORM', 'BLOCKED'].includes(transfer.status) && can(PERM.devicesTransfer)) {
      actions.push(el('button', {
        class: 'btn secondary small', type: 'button',
        onclick: () => transferAction(transfer, 'cancel'),
      }, '取消'));
    }
    return el('tr', null,
      tdl(el('div', null,
        el('div', { class: 'cell-strong' }, transfer.deviceName || transfer.deviceId || '—'),
        el('div', { class: 'cell-sub' }, `发起于 ${fmtDateTime(transfer.createdAt, tz())}${transfer.reason ? ' · ' + transfer.reason : ''}`)), '设备'),
      tdl(transfer.direction === 'IN' ? badge('blue', '转入') : badge('outline', '转出'), '方向'),
      tdl(transfer.counterpartName || '—', '对方组织'),
      tdl(el('div', null,
        statusBadge(TRANSFER_STATUS, transfer.status),
        (transfer.blockingReasons || []).length ? el('div', { class: 'cell-sub' }, `阻断：${transfer.blockingReasons.join('、')}`) : null), '状态'),
      tdl(el('span', { class: 'muted num' }, `v${transfer.version}`), '版本'),
      tdl(actions.length ? el('div', { class: 'action-row' }, actions) : el('span', { class: 'muted' }, '—'), '操作'));
  });
  container.append(makeTable({ headers: ['设备', '方向', '对方组织', '状态', '版本', '操作'], rows, minTable: 760 }));
}

async function transferAction(transfer, action) {
  const isAccept = action === 'accept';
  const confirmed = await confirmModal({
    title: isAccept ? `确认接收 · ${transfer.deviceName || ''}` : `取消转让 · ${transfer.deviceName || ''}`,
    message: isAccept
      ? `确认接收来自「${transfer.counterpartName || '—'}」的设备「${transfer.deviceName || ''}」？确认后进入平台审核。`
      : `取消该转让申请？取消后如需转让需重新发起。`,
    confirmText: isAccept ? '确认接收' : '取消转让',
    danger: !isAccept,
  });
  if (!confirmed) return;
  try {
    const updated = isAccept
      ? await adapter.acceptTransfer(transfer.id, { version: transfer.version })
      : await adapter.cancelTransfer(transfer.id, { version: transfer.version });
    toast(`转让状态已更新：${TRANSFER_STATUS[updated.status] ? TRANSFER_STATUS[updated.status].label : updated.status}`, 'success');
    reloadView();
  } catch (error) {
    if (error.status === 409) {
      toast(`${describeMerchantError(error)} 请刷新列表获取最新版本。`, 'error');
    } else {
      toast(describeMerchantError(error), 'error');
    }
  }
}

/* ============================================================
   视图四：门店
   ============================================================ */

function renderStoresView(root) {
  const region = el('section', { class: 'card' });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '门店'),
        el('span', { class: 'field-hint' }, '删除采用归档；有设备的门店归档会返回 409 并给出指引。')),
      can(PERM.storesManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增门店</span>', onclick: () => openStoreModal(null) }))
        : null),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, loadStores);
}

async function loadStores(container) {
  const { items } = await adapter.listStores();
  clearNode(container);
  if (!items.length) { container.append(emptyState('还没有门店', can(PERM.storesManage) ? '使用「新增门店」创建第一个经营场所' : '需要 stores.manage 权限')); return; }
  const rows = items.map(store => el('tr', null,
    tdl(el('div', null, el('div', { class: 'cell-strong' }, store.name), el('div', { class: 'cell-sub' }, store.address || '未填写地址')), '门店'),
    tdl(store.status === 'ACTIVE' ? badge('green', '营业中') : badge('gray', '已归档'), '状态'),
    tdl(el('span', { class: 'num' }, String(store.deviceCount ?? 0)), '设备数'),
    tdl(el('span', { class: 'muted num' }, `v${store.version}`), '版本'),
    tdl(can(PERM.storesManage)
      ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => openStoreModal(store) }, '编辑')
      : el('span', { class: 'muted' }, '只读'), '操作')));
  container.append(makeTable({ headers: ['门店', '状态', '设备数', '版本', '操作'], rows, minTable: 640 }));
}

function openStoreModal(store) {
  const isNew = !store;
  const name = el('input', { class: 'input', value: store ? store.name : '', maxlength: '80', required: true });
  const address = el('input', { class: 'input', value: store ? store.address || '' : '', maxlength: '160' });
  const statusSel = el('select', { class: 'input' },
    el('option', { value: 'ACTIVE', selected: !store || store.status === 'ACTIVE' }, 'ACTIVE · 营业中'),
    el('option', { value: 'ARCHIVED', selected: store && store.status === 'ARCHIVED' }, 'ARCHIVED · 归档'));
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, isNew ? '创建' : '保存');
  const modal = openModal({
    title: isNew ? '新增门店' : `编辑门店 · ${store.name}`,
    body: [
      el('div', { class: 'field', 'data-field': 'name' }, el('span', { class: 'field-label' }, '门店名称 *'), name),
      el('div', { class: 'field', 'data-field': 'address' }, el('span', { class: 'field-label' }, '地址'), address),
      isNew ? null : el('div', { class: 'field' }, el('span', { class: 'field-label' }, '状态'), statusSel),
      isNew ? null : el('p', { class: 'field-hint' }, `归档门店前需先处理其下 ${store.deviceCount ?? 0} 台设备（转移或归档），否则服务器返回 409。历史订单与数据不会丢失。`),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!name.value.trim()) { showFieldErrors(modal.card, { name: '请填写门店名称' }); return; }
    busy(submit, '提交中…');
    try {
      if (isNew) {
        await adapter.createStore({ name: name.value.trim(), address: address.value.trim() });
      } else {
        const body = { name: name.value.trim(), address: address.value.trim(), status: statusSel.value, version: store.version };
        if (statusSel.value === 'ARCHIVED') {
          const ok = await confirmModal({ title: '归档门店', message: `确认归档「${store.name}」？归档不可直接恢复。`, confirmText: '归档', danger: true });
          if (!ok) { unbusy(submit, '保存'); return; }
        }
        await adapter.updateStore(store.id, body);
      }
      modal.close();
      toast(isNew ? '门店已创建' : '门店已更新', 'success');
      await refreshStores();
      buildShellControls();
      reloadView();
    } catch (error) {
      unbusy(submit, isNew ? '创建' : '保存');
      if (isVersionConflict(error)) { showConflictRetry(errorNode, error, () => { modal.close(); reloadView(); }); return; }
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

/* ============================================================
   视图五：商品价格
   ============================================================ */

function renderPricesView(root) {
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  const deviceInput = el('input', { class: 'input mono', placeholder: '按设备 ID 过滤（可选）' });
  const region = el('section', { class: 'card' });
  const refresh = () => {
    state.priceFilters = { storeId: storeSel.value, deviceId: deviceInput.value.trim() };
    loadRegion(region, loadPrices);
  };
  storeSel.addEventListener('change', refresh);
  deviceInput.addEventListener('change', refresh);
  state.priceFilters = { storeId: state.storeId, deviceId: '' };
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '设备'), deviceInput),
      can(PERM.pricesManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增价格</span>', onclick: () => openPriceModal() }))
        : null),
    el('p', { class: 'field-hint' }, '当前价立即生效；计划价在生效时间后自动适用。新价格只影响之后创建的订单，历史订单价格不变。'),
    region);
  region.append(skeletonRows(4));
  loadRegion(region, loadPrices);
}

async function loadPrices(container) {
  const filters = state.priceFilters || {};
  const { items } = await adapter.listPrices({ storeId: filters.storeId || undefined, deviceId: filters.deviceId || undefined });
  clearNode(container);
  if (!items.length) { container.append(emptyState('没有价格记录', can(PERM.pricesManage) ? '使用「新增价格」配置菜单售价' : '需要 prices.manage 权限')); return; }
  const now = new Date().toISOString();
  const rows = items.map(price => {
    const isPlanned = price.effectiveAt && price.effectiveAt > now;
    const scope = price.deviceId ? `设备 ${price.deviceId}` : price.storeId ? (state.stores.find(s => s.id === price.storeId) || {}).name || price.storeId : '全组织';
    return el('tr', null,
      tdl(el('div', null, el('div', { class: 'cell-strong' }, price.name || price.sku), el('div', { class: 'cell-sub mono' }, price.sku)), '商品'),
      tdl(scope, '适用范围'),
      tdl(isPlanned ? badge('blue', '计划生效') : badge('green', '当前价'), '状态'),
      tdl(el('span', { class: 'num' }, fmtMoney(price.priceMinor)), '售价'),
      tdl(fmtDateTime(price.effectiveAt, tz()), '生效时间'),
      tdl(el('span', { class: 'muted num' }, `v${price.version ?? '—'}`), '版本'));
  });
  container.append(makeTable({ headers: ['商品', '适用范围', '状态', '售价', '生效时间', '版本'], rows, minTable: 720 }));
}

function openPriceModal() {
  const sku = el('input', { class: 'input mono', placeholder: '例如 LATTE-M', required: true });
  const name = el('input', { class: 'input', placeholder: '例如 拿铁（中杯）' });
  const storeSel = el('select', { class: 'input' }, storeOptions('', { allLabel: '全组织（默认）' }));
  const deviceInput = el('input', { class: 'input mono', placeholder: '设备 ID（可选，优先于门店）' });
  const price = el('input', { class: 'input', inputmode: 'decimal', placeholder: '例如 15.00（元）', required: true });
  const effectiveAt = el('input', { class: 'input', type: 'datetime-local' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '保存价格');
  const modal = openModal({
    title: '新增价格',
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field', 'data-field': 'sku' }, el('span', { class: 'field-label' }, 'SKU *'), sku),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '显示名称'), name),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店范围'), storeSel),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '设备范围'), deviceInput),
        el('div', { class: 'field', 'data-field': 'priceMinor' }, el('span', { class: 'field-label' }, '售价（元，最多两位小数）*'), price),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '生效时间（留空立即生效）'), effectiveAt)),
      el('p', { class: 'field-hint' }, '服务端决定最终售价；客户端不提交可信结算金额。历史订单价格不随新价变动。'),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    const parsed = parseYuanToMinor(price.value);
    if (!sku.value.trim()) { showFieldErrors(modal.card, { sku: '请填写 SKU' }); return; }
    if (!parsed.ok) { showFieldErrors(modal.card, { priceMinor: parsed.reason }); return; }
    busy(submit, '保存中…');
    try {
      await adapter.createPrice({
        sku: sku.value.trim(), name: name.value.trim() || sku.value.trim(),
        storeId: storeSel.value || undefined, deviceId: deviceInput.value.trim() || undefined,
        priceMinor: parsed.minor, effectiveAt: effectiveAt.value ? new Date(effectiveAt.value).toISOString() : undefined,
      });
      modal.close();
      toast('价格已保存', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '保存价格');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

/* ============================================================
   视图六：订单
   ============================================================ */

const ORDER_STATUS_OPTIONS = ['', 'PAID', 'PENDING', 'REFUNDING', 'REFUNDED', 'PARTIALLY_REFUNDED', 'QUEUED', 'MAKING', 'HOLD', 'DELIVERED', 'FAILED', 'CANCELLED'];

function renderOrdersView(root) {
  const statusSel = el('select', { class: 'input' },
    ORDER_STATUS_OPTIONS.map(value => el('option', { value, selected: value === '' }, value ? `${PAY_STATUS[value] ? PAY_STATUS[value].label : PROD_STATUS[value] ? PROD_STATUS[value].label : value}（${value}）` : '全部状态')));
  const deviceInput = el('input', { class: 'input mono', placeholder: '设备 ID（可选）' });
  const region = el('section', { class: 'card' });
  const moreBar = el('div', { class: 'load-more hidden', id: 'orders-more' });
  state.ordersFilters = { status: '', deviceId: '', cursor: null, items: [], region };
  const refresh = reset => {
    state.ordersFilters.status = statusSel.value;
    state.ordersFilters.deviceId = deviceInput.value.trim();
    if (reset) state.ordersFilters.cursor = null;
    loadRegion(region, loadOrdersPage);
  };
  statusSel.addEventListener('change', () => refresh(true));
  deviceInput.addEventListener('change', () => refresh(true));
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '状态'), statusSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '设备'), deviceInput),
      el('div', { class: 'toolbar-actions' },
        el('button', { class: 'btn secondary small', type: 'button', html: icon.refresh + '<span>查询</span>', onclick: () => refresh(true) }))),
    el('p', { class: 'field-hint' }, `日期、门店与数据环境使用顶栏全局筛选（当前 ${state.period.from} ~ ${state.period.to}，${state.environment === 'TEST' ? '测试' : '正式'}环境）。`),
    region, moreBar);
  region.append(skeletonRows(5));
  refresh(true);
}

async function loadOrdersPage(container) {
  const filters = state.ordersFilters;
  const params = {
    ...periodToApiParams(state.period),
    storeId: state.storeId || undefined,
    deviceId: filters.deviceId || undefined,
    status: filters.status || undefined,
    environment: state.environment,
    cursor: filters.cursor || undefined,
  };
  const { items, nextCursor } = await adapter.listOrders(params);
  filters.items = filters.cursor ? filters.items.concat(items) : items;
  filters.cursor = nextCursor;
  clearNode(container);
  if (!filters.items.length) {
    container.append(emptyState('没有符合条件的订单', '调整状态、设备或顶栏日期 / 门店 / 环境筛选后重试'));
    $('orders-more')?.classList.add('hidden');
    return;
  }
  const rows = filters.items.map(order => el('tr', {
    class: 'clickable',
    onclick: () => openOrderDrawer(order.id),
  },
    tdl(el('div', null, el('div', { class: 'mono cell-strong' }, order.orderNo), el('div', { class: 'cell-sub' }, fmtDateTime(order.createdAt, tz()))), '订单'),
    tdl(el('div', null, el('div', null, order.storeNameSnapshot || '—'), el('div', { class: 'cell-sub' }, order.deviceNameSnapshot || order.deviceId || '')), '门店 / 设备'),
    tdl((order.items || []).map(item => `${item.name}×${item.quantity}`).join('、') || '—', '商品'),
    tdl(el('span', { class: 'num' }, fmtMoney(order.totalMinor)), '金额'),
    tdl(statusBadge(PAY_STATUS, order.paymentStatus), '支付'),
    tdl(statusBadge(PROD_STATUS, order.productionStatus), '制作'),
    tdl(order.environment === 'TEST' ? badge('amber', '测试') : badge('outline', '正式'), '环境')));
  container.append(makeTable({ headers: ['订单', '门店 / 设备', '商品', '金额', '支付', '制作', '环境'], rows, minTable: 860 }));
  const more = $('orders-more');
  if (nextCursor && more) {
    more.classList.remove('hidden');
    clearNode(more);
    const btn = el('button', { class: 'btn secondary block', type: 'button' }, '加载更多');
    btn.addEventListener('click', () => loadRegion(state.ordersFilters.region, loadOrdersPage));
    more.append(btn);
  } else if (more) {
    more.classList.add('hidden');
  }
  if (state.ordersFocusId) {
    const focusId = state.ordersFocusId;
    state.ordersFocusId = null;
    openOrderDrawer(focusId);
  }
}

async function openOrderDrawer(orderId) {
  const content = el('div', null, skeletonRows(6));
  const drawer = openDrawer({ title: '订单详情', sub: '', content });
  const epoch = state.epoch;
  try {
    const order = await adapter.getOrder(orderId);
    if (stale(epoch) || !activeDrawer || activeDrawer !== drawer) return;
    paintOrderDrawer(drawer, order);
  } catch (error) {
    if (error && error.aborted) return;
    if (stale(epoch)) return;
    if (handleErrorGlobal(error)) return;
    clearNode(drawer.body);
    drawer.body.append(errorState(error, () => openOrderDrawer(orderId)));
  }
}

function paintOrderDrawer(drawer, order) {
  clearNode(drawer.body);
  const canRefund = can(PERM.refundsManage) && (order.allowedActions || []).includes('REFUND');
  drawer.body.append(
    el('div', { class: 'drawer-title-row' },
      el('div', null,
        el('h4', { class: 'mono' }, order.orderNo || order.id),
        el('p', { class: 'muted' }, `${order.storeNameSnapshot || '—'} · ${order.deviceNameSnapshot || order.deviceId || '—'}`)),
      el('div', { class: 'badge-col' },
        statusBadge(PAY_STATUS, order.paymentStatus),
        statusBadge(PROD_STATUS, order.productionStatus),
        order.environment === 'TEST' ? badge('amber', '测试数据') : null)),
    el('div', { class: 'detail-sec' },
      el('h4', null, '基本信息'),
      el('div', { class: 'kv-grid' },
        kv('创建时间', fmtDateTime(order.createdAt, tz())),
        kv('支付时间', fmtDateTime(order.paidAt, tz())),
        kv('交付时间', fmtDateTime(order.deliveredAt, tz())),
        kv('订单金额', fmtMoney(order.totalMinor)),
        kv('实收金额', fmtMoney(order.receivedMinor)),
        kv('已退金额', fmtMoney(order.refundedMinor)))),
    el('div', { class: 'detail-sec' },
      el('h4', null, '商品明细'),
      el('div', { class: 'plain-list' }, (order.items || []).map(item => el('div', { class: 'plain-item' },
        el('span', null, `${item.name} × ${item.quantity}`),
        el('span', { class: 'num' }, fmtMoney(item.unitPriceMinor)))))),
    el('div', { class: 'detail-sec' },
      el('h4', null, '支付与退款'),
      el('div', { class: 'plain-list' }, (order.payments || []).map(payment => el('div', { class: 'plain-item' },
        el('span', null, `${payment.provider}${payment.accountLabel ? ' · ' + payment.accountLabel : ''}${payment.environment && payment.environment !== 'LIVE' ? '（' + payment.environment + '）' : ''}`),
        el('span', null, `${payment.status === 'SUCCESS' ? badge('green', '成功') : statusBadge(PAY_STATUS, payment.status)} ${fmtMoney(payment.amountMinor)}`)))),
      (order.refunds || []).length ? el('div', { class: 'plain-list', style: 'margin-top:8px' }, order.refunds.map(refund => el('div', { class: 'plain-item' },
        el('span', null, `${refund.status === 'PENDING' ? badge('amber', '退款申请中') : refund.status === 'SUCCESS' ? badge('green', '退款成功') : badge('red', '退款失败')} ${refund.reason || ''}`),
        el('span', { class: 'num' }, fmtMoney(refund.amountMinor))))) : el('p', { class: 'muted' }, '无退款记录'),
      order.costSummary ? el('p', { class: 'field-hint' }, `材料成本：${order.costSummary.materialCostMinor === null || order.costSummary.materialCostMinor === undefined ? '待补全' : fmtMoney(order.costSummary.materialCostMinor)}（${order.costSummary.status === 'MISSING' ? '成本缺失' : order.costSummary.status === 'ESTIMATED' ? '标准配方估算' : '已确认'}）`) : null),
    el('div', { class: 'detail-sec' },
      el('h4', null, '时间线'),
      el('div', { class: 'timeline' }, (order.timeline || []).map(entry => el('div', { class: 'timeline-item' },
        el('span', { class: 'muted' }, fmtDateTime(entry.at, tz())),
        el('span', null, entry.label))))),
    canRefund ? el('div', { class: 'detail-sec' },
      el('h4', null, '操作'),
      el('div', { class: 'action-row' },
        el('button', { class: 'btn danger small', type: 'button', onclick: () => openRefundModal(order, drawer) }, '发起退款'),
        el('span', { class: 'field-hint', style: 'align-self:center' }, '可退上限以服务端校验为准；提交后状态为“退款申请中”，成功以退款记录为准。'))) : null,
  );
}

function openRefundModal(order, drawer) {
  /* 可退上限依赖实收 / 已退金额：任一缺失（null）时按未知处理，
     绝不 coercion 成 0；提交入口同步禁用。 */
  const received = order.receivedMinor;
  const refunded = order.refundedMinor;
  const unknownLimit = received === null || received === undefined || refunded === null || refunded === undefined;
  const max = unknownLimit ? null : Math.max(0, received - refunded);
  const amount = el('input', {
    class: 'input', inputmode: 'decimal',
    value: unknownLimit ? '' : (max / 100).toFixed(2),
    disabled: unknownLimit || null,
    'aria-label': '退款金额（元）',
  });
  const reason = el('textarea', { class: 'input', placeholder: '退款原因（写入审计）', maxlength: '300' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn danger', type: 'button', disabled: unknownLimit || null }, '确认退款');
  const idem = newIdemScope();
  const modal = openModal({
    title: `发起退款 · ${order.orderNo || order.id}`,
    body: [
      unknownLimit
        ? el('p', { class: 'field-hint' }, '实收或已退金额待补全，无法计算可退上限；请稍后重开此弹窗重试，或联系平台核实。')
        : el('p', { class: 'field-hint' }, `订单金额 ${fmtMoney(order.totalMinor)} · 实收 ${fmtMoney(order.receivedMinor)} · 已退 ${fmtMoney(order.refundedMinor)}。可退上限 ${fmtMoney(max)}；允许部分退款，最终以服务端限制为准。`),
      el('div', { class: 'field', 'data-field': 'amountMinor' }, el('span', { class: 'field-label' }, '退款金额（元）*'), amount),
      el('div', { class: 'field', 'data-field': 'reason' }, el('span', { class: 'field-label' }, '原因'), reason),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    if (unknownLimit) return;
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    const parsed = parseYuanToMinor(amount.value);
    if (!parsed.ok) { showFieldErrors(modal.card, { amountMinor: parsed.reason }); return; }
    if (parsed.minor <= 0) { showFieldErrors(modal.card, { amountMinor: '退款金额必须大于 0' }); return; }
    if (parsed.minor > max) { showFieldErrors(modal.card, { amountMinor: `超过可退上限 ${fmtMoney(max)}` }); return; }
    busy(submit, '提交中…');
    try {
      const refund = await withReauth(() => adapter.createRefund(order.id, { amountMinor: parsed.minor, reason: reason.value.trim() }, idem.current()));
      modal.close();
      toast(`退款已提交，状态：${refund.status === 'PENDING' ? '申请中（未成功，不代表已退款）' : refund.status}`, refund.status === 'PENDING' ? 'info' : 'success');
      openOrderDrawer(order.id);
      reloadOrderListOnly();
    } catch (error) {
      unbusy(submit, '确认退款');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
  void drawer;
}

function reloadOrderListOnly() {
  const cards = $('workspace').querySelectorAll('.card');
  for (const card of cards) {
    if (card.querySelector('.table-scroll')) {
      state.ordersFilters.cursor = null;
      loadRegion(card, loadOrdersPage);
      return;
    }
  }
}

/* ============================================================
   视图七：物料 / 采购 / 库存
   ============================================================ */

function renderMaterialsView(root) {
  const tabs = [['materials', '物料'], ['purchases', '采购'], ['inventory', '库存'], ['movements', '出入库']];
  state.materialsTab = state.materialsTab || 'materials';
  const tabBar = el('div', { class: 'tabs', role: 'tablist' }, tabs.map(([id, label]) => el('button', {
    class: `tab${state.materialsTab === id ? ' active' : ''}`,
    type: 'button', role: 'tab', 'aria-selected': state.materialsTab === id ? 'true' : 'false',
    onclick: () => { state.materialsTab = id; renderMaterialsView(root); },
  }, label)));
  clearNode(root);
  const body = el('div', null);
  root.append(tabBar, body);
  ({
    materials: renderMaterialsTab,
    purchases: renderPurchasesTab,
    inventory: renderInventoryTab,
    movements: renderMovementsTab,
  })[state.materialsTab](body);
}

async function loadMaterialsData() {
  const { items } = await adapter.listMaterials();
  return items;
}

function renderMaterialsTab(root) {
  const region = el('section', { class: 'card' });
  const showCost = can(PERM.costsRead);
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '物料档案'),
        el('span', { class: 'field-hint' }, '单位与精度由服务端统一定义；平均成本来自移动加权平均。')),
      can(PERM.costsManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增物料</span>', onclick: openMaterialModal }))
        : null),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, async container => {
    const items = await loadMaterialsData();
    clearNode(container);
    if (!items.length) { container.append(emptyState('还没有物料', can(PERM.costsManage) ? '先创建物料档案再录入采购' : '需要 costs.manage 权限')); return; }
    const rows = items.map(material => el('tr', null,
      tdl(el('div', { class: 'cell-strong' }, material.name), '物料'),
      tdl(material.unit || '—', '单位'),
      tdl(el('span', { class: 'num' }, String(material.unitPrecision ?? 0)), '小数位'),
      showCost ? tdl(material.averageUnitCostMinor === null || material.averageUnitCostMinor === undefined
        ? el('span', { class: 'muted' }, '待补全')
        : el('span', { class: 'num' }, fmtMoney(material.averageUnitCostMinor)), '平均单位成本') : null,
      tdl(material.status === 'ACTIVE' ? badge('green', '启用') : badge('gray', '停用'), '状态')));
    container.append(makeTable({
      headers: showCost ? ['物料', '单位', '小数位', '平均单位成本', '状态'] : ['物料', '单位', '小数位', '状态'],
      rows, minTable: 560,
    }));
  });
}

function openMaterialModal() {
  const name = el('input', { class: 'input', required: true, maxlength: '80' });
  const unit = el('input', { class: 'input', required: true, placeholder: '例如 g / ml / 个', maxlength: '12' });
  const precision = el('input', { class: 'input', type: 'number', min: '0', max: '6', value: '0' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '创建');
  const modal = openModal({
    title: '新增物料',
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field', 'data-field': 'name' }, el('span', { class: 'field-label' }, '名称 *'), name),
        el('div', { class: 'field', 'data-field': 'unit' }, el('span', { class: 'field-label' }, '单位 *'), unit),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '数量小数位'), precision)),
      el('p', { class: 'field-hint' }, '新物料尚无采购记录时平均成本为空（待补全），不按 0 计算。'),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!name.value.trim() || !unit.value.trim()) { showFieldErrors(modal.card, { name: '请填写名称与单位' }); return; }
    busy(submit, '创建中…');
    try {
      await adapter.createMaterial({ name: name.value.trim(), unit: unit.value.trim(), unitPrecision: Number(precision.value) || 0 });
      modal.close();
      toast('物料已创建', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '创建');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

function renderPurchasesTab(root) {
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  const region = el('section', { class: 'card' });
  state.purchaseFilters = { storeId: state.storeId };
  storeSel.addEventListener('change', () => { state.purchaseFilters.storeId = storeSel.value; loadRegion(region, loadPurchases); });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '日期'),
        el('span', { class: 'field-hint' }, `使用顶栏区间 ${state.period.from} ~ ${state.period.to}`)),
      can(PERM.costsManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新建采购</span>', onclick: () => openPurchaseModal(null) }))
        : null),
    el('p', { class: 'field-hint' }, '采购先存为草稿，确认后入账；已入账单据不可直接修改，更正走后续调整。合计中的「＊」表示部分明细金额待补全，不计入合计。'),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, loadPurchases);
}

async function loadPurchases(container) {
  const params = { ...periodToApiParams(state.period), storeId: state.purchaseFilters.storeId || undefined };
  const { items } = await adapter.listPurchases(params);
  clearNode(container);
  if (!items.length) { container.append(emptyState('区间内没有采购单', can(PERM.costsManage) ? '使用「新建采购」录入采购草稿' : '需要 costs.manage 权限')); return; }
  const rows = items.map(purchase => {
    /* 合计仅累加已知金额；缺失明细标记待补全，不按 0 混入展示 */
    const total = sumMinor(purchase.lines || [], 'totalCostMinor');
    const actions = [];
    if (can(PERM.costsManage)) {
      if (purchase.status === 'DRAFT') {
        actions.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => openPurchaseModal(purchase) }, '编辑'));
        actions.push(el('button', { class: 'btn primary small', type: 'button', onclick: () => postPurchaseFlow(purchase) }, '入账'));
      }
    }
    return el('tr', null,
      tdl(el('div', null, el('div', { class: 'cell-strong' }, purchase.supplier || '未填供应商'), el('div', { class: 'cell-sub' }, purchase.purchasedOn)), '采购'),
      tdl((state.stores.find(s => s.id === purchase.storeId) || {}).name || purchase.storeId || '—', '门店'),
      tdl(el('div', { class: 'cell-sub' }, (purchase.lines || []).map(l => `${l.materialName || l.materialId} × ${l.quantity}${l.unit || ''}`).join('；') || '—'), '明细'),
      tdl((purchase.lines || []).length
        ? el('span', {
            class: 'num',
            title: total.hasUnknown ? '部分明细金额待补全，合计仅包含已知金额' : null,
          }, fmtMoney(total.sum) + (total.hasUnknown ? ' ＊' : ''))
        : el('span', { class: 'num' }, '—'), '合计'),
      tdl(purchase.status === 'DRAFT' ? badge('amber', '草稿') : badge('green', '已入账'), '状态'),
      tdl(el('span', { class: 'muted num' }, `v${purchase.version}`), '版本'),
      tdl(actions.length ? el('div', { class: 'action-row' }, actions) : el('span', { class: 'muted' }, '只读'), '操作'));
  });
  container.append(makeTable({ headers: ['采购', '门店', '明细', '合计', '状态', '版本', '操作'], rows, minTable: 820 }));
}

function openPurchaseModal(purchase) {
  const isEdit = Boolean(purchase);
  const storeSel = el('select', { class: 'input' }, storeOptions(purchase ? purchase.storeId : '', { allLabel: '请选择门店' }));
  const purchasedOn = el('input', { class: 'input', type: 'date', value: purchase ? purchase.purchasedOn : todayInTz(tz()) });
  const supplier = el('input', { class: 'input', value: purchase ? purchase.supplier || '' : '', maxlength: '80' });
  const note = el('input', { class: 'input', value: purchase ? purchase.note || '' : '', maxlength: '160' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const linesBox = el('div', { class: 'lines-box' });
  const lineRows = [];
  const materialsCache = [];
  const addLine = (line = {}) => {
    const materialSel = el('select', { class: 'input' },
      materialsCache.map(material => el('option', { value: material.id }, `${material.name}（${material.unit}）`)));
    const quantityInput = el('input', { class: 'input', inputmode: 'decimal', placeholder: '数量', value: line.quantity || '' });
    const costInput = el('input', { class: 'input', inputmode: 'decimal', placeholder: '金额（元）', value: line.totalCostMinor != null ? (line.totalCostMinor / 100).toFixed(2) : '' });
    const removeBtn = el('button', { class: 'btn ghost small', type: 'button', 'aria-label': '删除该行', html: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' });
    const node = el('div', { class: 'line-row' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '物料'), materialSel),
      el('div', { class: 'field', style: 'max-width:130px' }, el('span', { class: 'field-label' }, '数量'), quantityInput),
      el('div', { class: 'field', style: 'max-width:150px' }, el('span', { class: 'field-label' }, '金额（元）'), costInput),
      el('div', { style: 'align-self:end' }, removeBtn));
    if (line.materialId) materialSel.value = line.materialId;
    else if (materialsCache.length) materialSel.selectedIndex = 0;
    const row = {
      collect: () => {
        const cost = parseYuanToMinor(costInput.value);
        return { materialId: materialSel.value, quantity: quantityInput.value.trim(), totalCostMinor: cost.ok ? cost.minor : null, costParse: cost };
      },
      node,
    };
    removeBtn.addEventListener('click', () => {
      const index = lineRows.indexOf(row);
      if (index >= 0) lineRows.splice(index, 1);
      node.remove();
    });
    lineRows.push(row);
    linesBox.append(node);
    return row;
  };
  const submit = el('button', { class: 'btn primary', type: 'button' }, isEdit ? '保存草稿' : '创建草稿');
  const idem = newIdemScope();
  const modal = openModal({
    title: isEdit ? `编辑采购草稿 · ${purchase.id}` : '新建采购',
    wide: true,
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field', 'data-field': 'storeId' }, el('span', { class: 'field-label' }, '门店 *'), storeSel),
        el('div', { class: 'field', 'data-field': 'purchasedOn' }, el('span', { class: 'field-label' }, '采购日期 *'), purchasedOn),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '供应商'), supplier),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '备注'), note)),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '明细 *'), linesBox,
        el('button', { class: 'btn secondary small', type: 'button', onclick: () => addLine() }, '+ 添加一行')),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  loadMaterialsData().then(materials => {
    materialsCache.push(...materials);
    const starter = isEdit && purchase.lines && purchase.lines.length ? purchase.lines : [{}];
    for (const line of starter) addLine(line);
  }).catch(() => addLine());
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!storeSel.value) { showFieldErrors(modal.card, { storeId: '请选择门店' }); return; }
    if (!lineRows.length) { errorNode.textContent = '请至少添加一行明细'; return; }
    const lines = [];
    for (const row of lineRows) {
      const collected = row.collect();
      if (!collected.materialId) { errorNode.textContent = '明细中存在未选择物料的行'; return; }
      const qty = parseQuantity(collected.quantity);
      if (!qty.ok) { errorNode.textContent = qty.reason; return; }
      if (!collected.costParse.ok) { errorNode.textContent = collected.costParse.reason; return; }
      lines.push({ materialId: collected.materialId, quantity: qty.value, totalCostMinor: collected.totalCostMinor });
    }
    busy(submit, '提交中…');
    try {
      const body = { storeId: storeSel.value, purchasedOn: purchasedOn.value, supplier: supplier.value.trim(), note: note.value.trim(), lines };
      if (isEdit) await adapter.updatePurchase(purchase.id, { ...body, version: purchase.version });
      else await adapter.createPurchase(body, idem.current());
      modal.close();
      toast(isEdit ? '草稿已保存' : '采购草稿已创建', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, isEdit ? '保存草稿' : '创建草稿');
      if (isVersionConflict(error)) { showConflictRetry(errorNode, error, () => { modal.close(); reloadView(); }); return; }
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

async function postPurchaseFlow(purchase) {
  const confirmed = await confirmModal({
    title: `采购入账 · ${purchase.supplier || purchase.id}`,
    message: '入账后采购将进入成本账（移动加权平均），不可直接修改；如需更正请使用后续调整。',
    confirmText: '确认入账',
  });
  if (!confirmed) return;
  try {
    await adapter.postPurchase(purchase.id, { version: purchase.version });
    toast('采购已入账', 'success');
    reloadView();
  } catch (error) {
    toast(describeMerchantError(error), 'error');
  }
}

function renderInventoryTab(root) {
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  const region = el('section', { class: 'card' });
  state.inventoryFilters = { storeId: state.storeId, deviceId: '' };
  storeSel.addEventListener('change', () => { state.inventoryFilters.storeId = storeSel.value; loadRegion(region, loadInventory); });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '说明'),
        el('span', { class: 'field-hint' }, '可用 = 在存 − 占用；成本状态为“成本缺失”时相关金额显示待补全。'))),
    region);
  region.append(skeletonRows(4));
  loadRegion(region, loadInventory);
}

async function loadInventory(container) {
  const { items } = await adapter.getInventory({ storeId: state.inventoryFilters.storeId || undefined });
  clearNode(container);
  if (!items.length) { container.append(emptyState('没有库存记录', '认领设备并补货后显示')); return; }
  const rows = items.map(row => el('tr', null,
    tdl(el('div', { class: 'cell-strong' }, row.name), '物料'),
    tdl(`${row.deviceName || row.deviceId || '—'}`, '设备'),
    tdl(el('span', { class: 'num' }, `${fmtQty(row.onHandQuantity, 3)} ${row.unit || ''}`), '在存'),
    tdl(el('span', { class: 'num' }, fmtQty(row.reservedQuantity, 3)), '占用'),
    tdl(el('span', { class: 'num' }, `${fmtQty(row.availableQuantity, 3)} ${row.unit || ''}`), '可用'),
    tdl(row.costStatus === 'MISSING_COST' ? badge('amber', '成本缺失') : badge('green', '正常'), '成本状态')));
  container.append(makeTable({ headers: ['物料', '设备', '在存', '占用', '可用', '成本状态'], rows, minTable: 720 }));
}

function renderMovementsTab(root) {
  const typeSel = el('select', { class: 'input' },
    [el('option', { value: '' }, '全部类型'), ...Object.entries(MOVEMENT_TYPE).map(([value, meta]) => el('option', { value }, meta.label))]);
  const region = el('section', { class: 'card' });
  state.movementFilters = { type: '' };
  typeSel.addEventListener('change', () => { state.movementFilters.type = typeSel.value; loadRegion(region, loadMovements); });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '类型'), typeSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '事件流水'),
        el('span', { class: 'field-hint' }, '每条流水有稳定事件 ID，可关联设备与原始事件。')),
      can(PERM.inventoryManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增出入库</span>', onclick: openMovementModal }))
        : null),
    region);
  region.append(skeletonRows(4));
  loadRegion(region, loadMovements);
}

async function loadMovements(container) {
  const { items } = await adapter.listMovements({ type: state.movementFilters.type || undefined });
  clearNode(container);
  if (!items.length) { container.append(emptyState('没有出入库流水', can(PERM.inventoryManage) ? '使用「新增出入库」记录补货 / 报损 / 盘点 / 调拨' : '需要 inventory.manage 权限')); return; }
  const rows = items.map(movement => {
    const from = movement.sourceStoreId ? `${(state.stores.find(s => s.id === movement.sourceStoreId) || {}).name || movement.sourceStoreId}${movement.sourceDeviceId ? ' · ' + movement.sourceDeviceId : ''}` : '';
    const to = movement.targetStoreId ? `${(state.stores.find(s => s.id === movement.targetStoreId) || {}).name || movement.targetStoreId}${movement.targetDeviceId ? ' · ' + movement.targetDeviceId : ''}` : '';
    return el('tr', null,
      tdl(fmtDateTime(movement.createdAt, tz()), '时间'),
      tdl(statusBadge(MOVEMENT_TYPE, movement.type), '类型'),
      tdl(el('div', null, el('div', { class: 'cell-strong' }, movement.materialName || movement.materialId), el('div', { class: 'cell-sub mono' }, movement.eventId || '')), '物料'),
      tdl(el('span', { class: 'num' }, `${movement.quantity.startsWith('-') ? '' : '+'}${movement.quantity} ${movement.unit || ''}`), '数量'),
      tdl(from || to ? `${from || '—'} → ${to || '—'}` : '—', '流向'),
      tdl(movement.reason || '—', '原因'));
  });
  container.append(makeTable({ headers: ['时间', '类型', '物料', '数量', '流向', '原因'], rows, minTable: 780 }));
}

function openMovementModal() {
  const typeSel = el('select', { class: 'input' },
    Object.entries(MOVEMENT_TYPE).map(([value, meta]) => el('option', { value }, meta.label)));
  const quantityLabel = el('span', { class: 'field-label' }, '数量（正数）');
  const quantity = el('input', { class: 'input', inputmode: 'decimal', placeholder: '例如 12.5' });
  const reason = el('input', { class: 'input', maxlength: '160', placeholder: '原因 / 备注' });
  const sourceStore = el('select', { class: 'input' }, storeOptions('', { allLabel: '选择来源门店' }));
  const targetStore = el('select', { class: 'input' }, storeOptions('', { allLabel: '选择目标门店' }));
  const sourceDeviceWrap = el('div');
  const targetDeviceWrap = el('div');
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '提交');
  const idem = newIdemScope();
  const syncFields = () => {
    const type = typeSel.value;
    quantityLabel.textContent = type === 'ADJUSTMENT' ? '差额（盘点结果 − 账面，可为负）' : '数量（必须为正数）';
    quantity.placeholder = type === 'ADJUSTMENT' ? '例如 -3 或 5' : '例如 12.5';
    clearNode(sourceDeviceWrap); clearNode(targetDeviceWrap);
    const deviceInput = () => el('input', { class: 'input mono', placeholder: '设备 ID（可选）' });
    let sd = null; let td = null;
    if (type === 'RESTOCK') {
      sourceStore.parentElement.classList.add('hidden');
      targetStore.parentElement.classList.remove('hidden');
      td = deviceInput(); targetDeviceWrap.append(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '目标设备'), td));
    } else if (type === 'WASTE' || type === 'ADJUSTMENT') {
      sourceStore.parentElement.classList.remove('hidden');
      targetStore.parentElement.classList.add('hidden');
      sd = deviceInput(); sourceDeviceWrap.append(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '设备'), sd));
    } else {
      sourceStore.parentElement.classList.remove('hidden');
      targetStore.parentElement.classList.remove('hidden');
      sd = deviceInput(); td = deviceInput();
      sourceDeviceWrap.append(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '来源设备'), sd));
      targetDeviceWrap.append(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '目标设备'), td));
    }
    currentDevices = { sd, td };
  };
  let currentDevices = { sd: null, td: null };
  typeSel.addEventListener('change', syncFields);
  const materialsCache = [];
  const materialSel = el('select', { class: 'input' });
  const modal = openModal({
    title: '新增出入库',
    wide: true,
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '类型 *'), typeSel),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '物料 *'), materialSel),
        el('div', { class: 'field', 'data-field': 'quantity' }, quantityLabel, quantity),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '原因'), reason),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '来源门店'), sourceStore, sourceDeviceWrap),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '目标门店'), targetStore, targetDeviceWrap)),
      el('p', { class: 'field-hint' }, '盘点差额为带正负号的调整值；补货 / 报损 / 调拨数量必须为正。服务端校验实际库存与并发版本。'),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  loadMaterialsData().then(materials => {
    materialsCache.push(...materials);
    for (const material of materials) materialSel.append(el('option', { value: material.id }, `${material.name}（${material.unit}）`));
  }).catch(() => { errorNode.textContent = '物料列表加载失败，无法提交'; });
  syncFields();
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    const parsed = parseQuantity(quantity.value, { allowNegative: typeSel.value === 'ADJUSTMENT' });
    if (!parsed.ok) { showFieldErrors(modal.card, { quantity: parsed.reason }); return; }
    const type = typeSel.value;
    const body = {
      type, materialId: materialSel.value, quantity: parsed.value, reason: reason.value.trim(),
      sourceStoreId: type === 'RESTOCK' ? undefined : sourceStore.value || undefined,
      sourceDeviceId: currentDevices.sd && currentDevices.sd.value.trim() ? currentDevices.sd.value.trim() : undefined,
      targetStoreId: type === 'WASTE' || type === 'ADJUSTMENT' ? undefined : targetStore.value || undefined,
      targetDeviceId: currentDevices.td && currentDevices.td.value.trim() ? currentDevices.td.value.trim() : undefined,
    };
    if (!body.materialId) { errorNode.textContent = '请选择物料'; return; }
    const needSource = type !== 'RESTOCK';
    const needTarget = type === 'RESTOCK' || type === 'TRANSFER';
    if (needSource && !body.sourceStoreId) { errorNode.textContent = '请选择来源门店'; return; }
    if (needTarget && !body.targetStoreId) { errorNode.textContent = '请选择目标门店'; return; }
    const semantic = {
      RESTOCK: `向目标入库 +${parsed.value}`,
      WASTE: `从来源扣减 −${parsed.value}`,
      ADJUSTMENT: `按差额 ${parsed.value} 调整账面`,
      TRANSFER: `从来源调出 −${parsed.value}，目标调入 +${parsed.value}`,
    }[type];
    const confirmed = await confirmModal({ title: '确认提交', message: `即将记录：${semantic}。提交后立即生效并写入事件流水。`, confirmText: '确认提交' });
    if (!confirmed) return;
    busy(submit, '提交中…');
    try {
      await adapter.createMovement(body, idem.current());
      modal.close();
      toast('出入库已记录', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '提交');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

/* ============================================================
   视图八：运营费用
   ============================================================ */

function renderExpensesView(root) {
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  const region = el('section', { class: 'card' });
  state.expenseFilters = { storeId: state.storeId };
  storeSel.addEventListener('change', () => { state.expenseFilters.storeId = storeSel.value; loadRegion(region, loadExpenses); });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '日期'),
        el('span', { class: 'field-hint' }, `使用顶栏区间 ${state.period.from} ~ ${state.period.to}`)),
      can(PERM.costsManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增费用</span>', onclick: openExpenseModal }))
        : null),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, loadExpenses);
}

async function loadExpenses(container) {
  const { items } = await adapter.listExpenses({ ...periodToApiParams(state.period), storeId: state.expenseFilters.storeId || undefined });
  clearNode(container);
  if (!items.length) { container.append(emptyState('区间内没有费用', can(PERM.costsManage) ? '使用「新增费用」录入租金、人工等运营费用' : '需要 costs.manage 权限')); return; }
  const rows = items.map(expense => {
    const scope = expense.deviceId ? `设备 ${expense.deviceId}` : (state.stores.find(s => s.id === expense.storeId) || {}).name || expense.storeId || '全组织';
    const allocation = expense.allocationMethod === 'DAILY_EQUAL'
      ? `按日均摊 ${expense.allocationStart} ~ ${expense.allocationEnd}`
      : '一次性计入';
    const statusBadgeNode = expense.status === 'DRAFT' ? badge('amber', '草稿') : expense.status === 'POSTED' ? badge('green', '已入账') : badge('gray', '已冲正');
    const actions = [];
    if (can(PERM.costsManage)) {
      if (expense.status === 'DRAFT') actions.push(el('button', { class: 'btn primary small', type: 'button', onclick: () => postExpenseFlow(expense) }, '入账'));
      if (expense.status === 'POSTED') actions.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => reverseExpenseFlow(expense) }, '冲正'));
    }
    return el('tr', null,
      tdl(el('div', { class: 'cell-strong' }, EXPENSE_CATEGORY[expense.category] || expense.category), '类别'),
      tdl(el('span', { class: 'num' }, fmtMoney(expense.amountMinor)), '金额'),
      tdl(scope, '归属'),
      tdl(expense.occurredOn || '—', '发生日'),
      tdl(allocation, '分摊'),
      tdl(statusBadgeNode, '状态'),
      tdl(actions.length ? el('div', { class: 'action-row' }, actions) : el('span', { class: 'muted' }, '只读'), '操作'));
  });
  container.append(makeTable({ headers: ['类别', '金额', '归属', '发生日', '分摊', '状态', '操作'], rows, minTable: 820 }));
}

function openExpenseModal() {
  const category = el('select', { class: 'input' }, Object.entries(EXPENSE_CATEGORY).map(([value, label]) => el('option', { value }, label)));
  const amount = el('input', { class: 'input', inputmode: 'decimal', placeholder: '例如 4500.00（元）', required: true });
  const storeSel = el('select', { class: 'input' }, storeOptions('', { allLabel: '全组织' }));
  const deviceInput = el('input', { class: 'input mono', placeholder: '设备 ID（可选）' });
  const occurredOn = el('input', { class: 'input', type: 'date', value: todayInTz(tz()) });
  const method = el('select', { class: 'input' },
    el('option', { value: 'ONCE' }, 'ONCE · 一次性计入'),
    el('option', { value: 'DAILY_EQUAL' }, 'DAILY_EQUAL · 按日均摊'));
  const allocationStart = el('input', { class: 'input', type: 'date' });
  const allocationEnd = el('input', { class: 'input', type: 'date' });
  const allocationWrap = el('div', { class: 'kv-grid hidden' },
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, '分摊开始'), allocationStart),
    el('div', { class: 'field' }, el('span', { class: 'field-label' }, '分摊结束'), allocationEnd));
  const note = el('input', { class: 'input', maxlength: '160', placeholder: '备注' });
  const preview = el('p', { class: 'field-hint' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '创建草稿');
  const idem = newIdemScope();
  const syncPreview = () => {
    if (method.value !== 'DAILY_EQUAL') { allocationWrap.classList.add('hidden'); preview.textContent = ''; return; }
    allocationWrap.classList.remove('hidden');
    const parsed = parseYuanToMinor(amount.value);
    if (isValidRange(allocationStart.value, allocationEnd.value) && parsed.ok) {
      const days = Math.round((Date.parse(allocationEnd.value) - Date.parse(allocationStart.value)) / 86400000) + 1;
      preview.textContent = `区间共 ${days} 天，估算日均约 ${(parsed.minor / 100 / days).toFixed(2)} 元/天（仅预览，实际分摊以服务器入账为准）。`;
    } else {
      preview.textContent = '填写完整区间后显示估算预览（仅供参考）。';
    }
  };
  method.addEventListener('change', syncPreview);
  [amount, allocationStart, allocationEnd].forEach(input => input.addEventListener('input', syncPreview));
  const modal = openModal({
    title: '新增运营费用',
    wide: true,
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '类别 *'), category),
        el('div', { class: 'field', 'data-field': 'amountMinor' }, el('span', { class: 'field-label' }, '金额（元）*'), amount),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店归属'), storeSel),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '设备归属'), deviceInput),
        el('div', { class: 'field', 'data-field': 'occurredOn' }, el('span', { class: 'field-label' }, '发生日 *'), occurredOn),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '分摊方式'), method)),
      allocationWrap,
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '备注'), note),
      preview, errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    const parsed = parseYuanToMinor(amount.value);
    if (!parsed.ok) { showFieldErrors(modal.card, { amountMinor: parsed.reason }); return; }
    if (!occurredOn.value) { showFieldErrors(modal.card, { occurredOn: '请选择发生日' }); return; }
    if (method.value === 'DAILY_EQUAL' && !isValidRange(allocationStart.value, allocationEnd.value)) {
      errorNode.textContent = '按日均摊需要完整的分摊区间（开始 ≤ 结束）';
      return;
    }
    busy(submit, '提交中…');
    try {
      await adapter.createExpense({
        category: category.value, amountMinor: parsed.minor,
        storeId: storeSel.value || undefined, deviceId: deviceInput.value.trim() || undefined,
        occurredOn: occurredOn.value,
        allocationMethod: method.value,
        allocationStart: method.value === 'DAILY_EQUAL' ? allocationStart.value : undefined,
        allocationEnd: method.value === 'DAILY_EQUAL' ? allocationEnd.value : undefined,
        note: note.value.trim(),
      }, idem.current());
      modal.close();
      toast('费用草稿已创建', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '创建草稿');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

async function postExpenseFlow(expense) {
  const confirmed = await confirmModal({
    title: '费用入账',
    message: '入账后费用进入经营账（按分摊规则计提），不可直接删除；如需更正使用冲正。',
    confirmText: '确认入账',
  });
  if (!confirmed) return;
  try {
    await adapter.postExpense(expense.id, { version: expense.version });
    toast('费用已入账', 'success');
    reloadView();
  } catch (error) { toast(describeMerchantError(error), 'error'); }
}

async function reverseExpenseFlow(expense) {
  const reason = el('input', { class: 'input', maxlength: '160', placeholder: '冲正原因（必填）' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn danger', type: 'button' }, '确认冲正');
  const modal = openModal({
    title: `冲正费用 · ${EXPENSE_CATEGORY[expense.category] || expense.category}`,
    body: [
      el('p', { class: 'field-hint' }, `金额 ${fmtMoney(expense.amountMinor)}。冲正会生成反向事实，原费用记录保留，不直接删除历史。`),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '原因 *'), reason),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    if (reason.value.trim().length < 3) { errorNode.textContent = '原因至少 3 个字符'; return; }
    busy(submit, '冲正中…');
    try {
      await adapter.reverseExpense(expense.id, { reason: reason.value.trim() });
      modal.close();
      toast('费用已冲正', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '确认冲正');
      errorNode.textContent = describeMerchantError(error);
    }
  });
}

/* ============================================================
   视图九：经营报表
   ============================================================ */

const REPORT_METRICS = [
  { key: 'netCashMinor', label: '净收款', className: 'c-main' },
  { key: 'recognizedRevenueMinor', label: '营业净收入', className: 'c-blue' },
  { key: 'materialCostMinor', label: '材料成本', className: 'c-red' },
  { key: 'estimatedProfitMinor', label: '经营利润（估算）', className: 'c-green' },
];

function renderReportsView(root) {
  state.reportGrain = state.reportGrain || 'DAY';
  state.reportMetric = state.reportMetric || 'netCashMinor';
  const grainSeg = el('div', { class: 'm-seg', role: 'group', 'aria-label': '统计粒度' },
    [['DAY', '日'], ['MONTH', '月'], ['YEAR', '年']].map(([value, label]) => el('button', {
      class: state.reportGrain === value ? 'active' : '', type: 'button',
      onclick: () => { state.reportGrain = value; renderReportsView(root); },
    }, label)));
  const metricSel = el('select', { class: 'input' },
    REPORT_METRICS.map(metric => el('option', { value: metric.key, selected: state.reportMetric === metric.key }, metric.label)));
  metricSel.addEventListener('change', () => { state.reportMetric = metricSel.value; renderReportsView(root); });
  const storeSel = el('select', { class: 'input' }, storeOptions(state.storeId));
  storeSel.addEventListener('change', () => { state.storeId = storeSel.value; renderReportsView(root); });
  const exportBtn = can(PERM.reportsExport)
    ? el('button', { class: 'btn secondary small', type: 'button', html: icon.download + '<span>导出 CSV</span>', onclick: exportReportCsv })
    : null;
  const totals = el('div', { class: 'm-cards' }, skeletonCards(4));
  const chart = el('div', null, skeletonRows(5));
  const table = el('section', { class: 'card' }, skeletonRows(6));
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '粒度'), grainSeg),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '图表指标'), metricSel),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店'), storeSel),
      el('div', { class: 'toolbar-actions' }, exportBtn)),
    el('p', { class: 'field-hint' }, `区间 ${state.period.from} ~ ${state.period.to}（含当日） · 时区 ${tz()} · ${state.environment === 'TEST' ? '测试数据，不计入正式经营' : '正式数据'}`),
    totals, chart, table,
    el('details', { class: 'card metric-defs' },
      el('summary', null, '口径说明'),
      el('div', { class: 'card-body' },
        el('ul', { class: 'defs-list' },
          el('li', null, '实收 = 支付成功金额；退款 = 退款成功金额（申请中不计入）。'),
          el('li', null, '净收款 = 本期实收 − 本期退款，是资金流口径，不等于利润。'),
          el('li', null, '营业净收入 = 制作交付确认的收入 − 对应收入冲回；已收款未交付单独体现。'),
          el('li', null, '毛利 = 营业净收入 − 直接材料成本；损耗与支付手续费单列。'),
          el('li', null, '经营利润（估算）= 毛利 − 损耗 − 支付手续费 − 分摊运营费用；缺项显示“待补全”，不按 0 计算。')))));
  loadRegion(totals, async container => {
    const data = await fetchReport();
    clearNode(container);
    const chips = [
      ['实收', data.totals.receivedMinor], ['退款', data.totals.refundedMinor], ['净收款', data.totals.netCashMinor],
      ['营业净收入', data.totals.recognizedRevenueMinor], ['材料成本', data.totals.materialCostMinor],
      ['损耗', data.totals.wasteCostMinor], ['支付手续费', data.totals.paymentFeeMinor],
      ['运营费用', data.totals.operatingExpenseMinor], ['经营利润（估算）', data.totals.estimatedProfitMinor],
      ['完成杯数', data.totals.deliveredCupCount],
    ];
    container.append(...chips.slice(0, 4).map(([label, value]) => statCard(label, typeof value === 'number' ? String(value) : fmtMoney(value), { num: false })));
    container.append(el('div', { class: 'chip-row', style: 'grid-column:1/-1' },
      chips.slice(4).map(([label, value]) => el('div', { class: 'chip' },
        el('span', { class: 'chip-label' }, label),
        el('span', { class: 'chip-value num' }, typeof value === 'number' ? String(value) : fmtMoney(value)))),
      el('div', { style: 'display:contents' }, completenessNote(data.completeness))));
  });
  loadRegion(chart, async container => {
    const data = await fetchReport();
    clearNode(container);
    if (!data.rows.length) { container.append(el('section', { class: 'card' }, emptyState('区间内没有报表数据', '调整区间、门店或数据环境后重试'))); return; }
    const metric = REPORT_METRICS.find(m => m.key === state.reportMetric) || REPORT_METRICS[0];
    const summary = data.rows.filter(r => r[metric.key] === null || r[metric.key] === undefined).length;
    container.append(chartCard({
      title: `${metric.label} · 按${{ DAY: '日', MONTH: '月', YEAR: '年' }[data.grain]}分布`,
      hint: `共 ${data.rows.length} 个区间`,
      labels: data.rows.map(r => r.period),
      series: [{ name: metric.label, values: data.rows.map(r => r[metric.key]), className: metric.className }],
      kind: 'bar',
      summaryText: summary ? `${summary} 个区间因成本缺失无${metric.label}数据，图中以缺口标记，不按 0 绘制。` : `全部区间数据完整。`,
    }));
  });
  loadRegion(table, async container => {
    const data = await fetchReport();
    clearNode(container);
    if (!data.rows.length) {
      container.classList.add('hidden');
      return;
    }
    container.classList.remove('hidden');
    const headerRow = ['区间', '实收', '退款', '净收款', '营业净收入', '材料成本', '损耗', '手续费', '运营费用', '利润（估算）', '杯数', '完整性'];
    const money = v => el('span', { class: 'num' }, fmtMoney(v));
    const rows = data.rows.map(r => el('tr', null,
      tdl(r.period, '区间'),
      tdl(money(r.receivedMinor), '实收'),
      tdl(money(r.refundedMinor), '退款'),
      tdl(money(r.netCashMinor), '净收款'),
      tdl(money(r.recognizedRevenueMinor), '营业净收入'),
      tdl(money(r.materialCostMinor), '材料成本'),
      tdl(money(r.wasteCostMinor), '损耗'),
      tdl(money(r.paymentFeeMinor), '手续费'),
      tdl(money(r.operatingExpenseMinor), '运营费用'),
      tdl(money(r.estimatedProfitMinor), '利润（估算）'),
      tdl(el('span', { class: 'num' }, String(r.deliveredCupCount ?? '—')), '杯数'),
      tdl(statusBadge(COMPLETENESS, r.completeness && r.completeness.status), '完整性')));
    const t = data.totals;
    rows.push(el('tr', { class: 'totals-row' },
      tdl(el('strong', null, '合计'), '区间'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.receivedMinor)), '实收'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.refundedMinor)), '退款'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.netCashMinor)), '净收款'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.recognizedRevenueMinor)), '营业净收入'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.materialCostMinor)), '材料成本'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.wasteCostMinor)), '损耗'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.paymentFeeMinor)), '手续费'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.operatingExpenseMinor)), '运营费用'),
      tdl(el('strong', { class: 'num' }, fmtMoney(t.estimatedProfitMinor)), '利润（估算）'),
      tdl(el('strong', { class: 'num' }, String(t.deliveredCupCount ?? '—')), '杯数'),
      tdl(statusBadge(COMPLETENESS, data.completeness && data.completeness.status), '完整性')));
    container.append(
      el('div', { class: 'card-head' }, el('h3', null, '明细数据'), el('span', { class: 'muted' }, '金额为人民币分换算展示；未知为待补全')),
      makeTable({ headers: headerRow, rows, minTable: 1080 }));
  });
}

async function fetchReport() {
  const params = {
    grain: state.reportGrain,
    ...periodToApiParams(state.period),
    storeId: state.storeId || undefined,
    environment: state.environment,
  };
  return adapter.operatingReport(params);
}

async function exportReportCsv() {
  const params = {
    grain: state.reportGrain,
    ...periodToApiParams(state.period),
    storeId: state.storeId || undefined,
    environment: state.environment,
  };
  try {
    const { blob, filename } = await adapter.operatingCsv(params);
    const url = trackBlob(URL.createObjectURL(blob));
    const anchor = el('a', { href: url, download: filename });
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => { try { URL.revokeObjectURL(url); } catch (_) { /* noop */ } const index = state.blobUrls.indexOf(url); if (index >= 0) state.blobUrls.splice(index, 1); }, 4000);
    toast(`已导出 ${filename}`, 'success');
  } catch (error) {
    toast(`导出失败：${describeMerchantError(error)}`, 'error');
  }
}

/* ============================================================
   视图十：成员权限
   ============================================================ */

function renderMembersView(root) {
  const membersRegion = el('section', { class: 'card' });
  const inviteRegion = el('section', { class: 'card' });
  const mailOk = authPolicy().mailEnabled;
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '成员与邀请'),
        el('span', { class: 'field-hint' }, 'OWNER 全部运营能力；OPERATOR 限授权门店设备运维与库存；FINANCE 订单成本报表只读。')),
      can(PERM.membersManage)
        ? el('div', { class: 'toolbar-actions' },
            mailOk
              ? el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>邀请新成员</span>', onclick: openInviteModal })
              : el('span', { class: 'invite-disabled-note' },
                  el('button', { class: 'btn primary small', type: 'button', disabled: true, html: icon.plus + '<span>邀请新成员</span>' }),
                  el('span', { class: 'field-hint' }, '邮件服务未配置，此功能暂未开放')))
        : null),
    el('div', { class: 'split-2' }, membersRegion, inviteRegion));
  membersRegion.append(skeletonRows(4));
  inviteRegion.append(skeletonRows(2));
  loadRegion(membersRegion, loadMembers);
  loadRegion(inviteRegion, loadInvitations);
}

async function loadMembers(container) {
  const { items } = await adapter.listMembers();
  clearNode(container);
  container.append(el('div', { class: 'card-head' }, el('h3', null, '成员'), el('span', { class: 'muted' }, `${items.length} 位`)));
  if (!items.length) { container.append(emptyState('还没有成员', '')); return; }
  const rows = items.map(member => el('tr', null,
    tdl(el('div', null, el('div', { class: 'cell-strong' }, member.displayName), el('div', { class: 'cell-sub' }, accountLabel(member))), '成员'),
    tdl(member.role === 'OWNER' ? badge('blue', ROLE_LABEL[member.role]) : member.role === 'FINANCE' ? badge('green', ROLE_LABEL[member.role]) : badge('outline', ROLE_LABEL[member.role] || member.role), '角色'),
    tdl(member.storeScope && member.storeScope.mode === 'SELECTED'
      ? `指定门店（${(member.storeScope.storeIds || []).length} 家）`
      : '全部门店', '门店范围'),
    tdl(member.status === 'ACTIVE' ? badge('green', '启用') : badge('gray', '停用'), '状态'),
    tdl(can(PERM.membersManage) ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => openMemberModal(member) }, '编辑') : el('span', { class: 'muted' }, '只读'), '操作')));
  container.append(makeTable({ headers: ['成员', '角色', '门店范围', '状态', '操作'], rows, minTable: 720 }));
}

async function loadInvitations(container) {
  const { items } = await adapter.listInvitations();
  clearNode(container);
  container.append(el('div', { class: 'card-head' }, el('h3', null, '邀请'), el('span', { class: 'muted' }, '邀请成功不代表邮件已送达')));
  if (!items.length) { container.append(emptyState('没有邀请记录', !authPolicy().mailEnabled ? '邮件服务未配置，暂无法发送新邀请' : (can(PERM.membersManage) ? '使用「邀请新成员」发送邀请' : ''))); return; }
  const rows = items.map(invitation => el('tr', null,
    tdl(el('span', { class: 'mono' }, invitation.email), '邮箱'),
    tdl(badge('outline', ROLE_LABEL[invitation.role] || invitation.role), '角色'),
    tdl(invitation.status === 'PENDING' ? badge('amber', '待接受') : invitation.status === 'REVOKED' ? badge('gray', '已撤销') : badge('green', '已接受'), '状态'),
    tdl(invitation.deliveryStatus === 'QUEUED' ? badge('green', '已进入发送队列') : invitation.deliveryStatus === 'UNAVAILABLE' ? badge('red', '邮件服务不可用') : badge('gray', invitation.deliveryStatus || '—'), '邮件'),
    tdl(fmtDateTime(invitation.expiresAt, tz()), '过期时间'),
    tdl(can(PERM.membersManage) && invitation.status === 'PENDING'
      ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => revokeInvitationFlow(invitation) }, '撤销')
      : el('span', { class: 'muted' }, '—'), '操作')));
  container.append(makeTable({ headers: ['邮箱', '角色', '状态', '邮件', '过期时间', '操作'], rows, minTable: 720 }));
}

function storeScopeEditor(scope) {
  const modeSel = el('select', { class: 'input' },
    el('option', { value: 'ALL', selected: !scope || scope.mode === 'ALL' }, 'ALL · 全部门店'),
    el('option', { value: 'SELECTED', selected: scope && scope.mode === 'SELECTED' }, 'SELECTED · 指定门店'));
  const checks = el('div', { class: 'store-checks' },
    state.stores.map(store => el('label', { class: 'check-row' },
      el('input', { type: 'checkbox', value: store.id, checked: Boolean(scope && scope.storeIds && scope.storeIds.includes(store.id)) }),
      el('span', null, store.name))));
  const wrap = el('div', null, modeSel, checks);
  const sync = () => { checks.classList.toggle('hidden', modeSel.value !== 'SELECTED'); };
  modeSel.addEventListener('change', sync);
  sync();
  return { node: wrap, collect: () => ({ mode: modeSel.value, storeIds: modeSel.value === 'SELECTED' ? Array.from(wrap.querySelectorAll('input[type=checkbox]:checked')).map(cb => cb.value) : [] }) };
}

function openInviteModal() {
  if (!authPolicy().mailEnabled) {
    toast('邮件服务未配置，此功能暂未开放；新增成员请联系平台管理员', 'error');
    return;
  }
  const email = el('input', { class: 'input', type: 'email', required: true, placeholder: 'name@company.com' });
  const roleSel = el('select', { class: 'input' },
    ['OWNER', 'OPERATOR', 'FINANCE'].map(role => el('option', { value: role }, ROLE_LABEL[role])));
  const scope = storeScopeEditor({ mode: 'ALL', storeIds: [] });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '发送邀请');
  const idem = newIdemScope();
  const modal = openModal({
    title: '邀请新成员',
    body: [
      el('div', { class: 'field', 'data-field': 'email' }, el('span', { class: 'field-label' }, '邮箱 *'), email),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '角色'), roleSel),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店范围'), scope.node,
        el('span', { class: 'field-hint' }, 'OPERATOR 不选择任何门店时不应默认全部门店；请明确勾选授权门店。')),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!looksLikeEmail(email.value)) { showFieldErrors(modal.card, { email: '请输入正确的邮箱地址' }); return; }
    const scopeValue = scope.collect();
    if (roleSel.value === 'OPERATOR' && scopeValue.mode === 'SELECTED' && !scopeValue.storeIds.length) {
      errorNode.textContent = 'OPERATOR 使用指定门店范围时至少选择一家门店';
      return;
    }
    busy(submit, '发送中…');
    try {
      const invitation = await adapter.createInvitation({ email: email.value.trim(), role: roleSel.value, storeScope: scopeValue }, idem.current());
      modal.close();
      toast(invitation.deliveryStatus === 'UNAVAILABLE'
        ? '邀请已创建，但邮件服务当前不可用，未能投递'
        : '邀请已创建并进入发送队列（不代表邮件已送达）', invitation.deliveryStatus === 'UNAVAILABLE' ? 'error' : 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '发送邀请');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

function openMemberModal(member) {
  const roleSel = el('select', { class: 'input' },
    ['OWNER', 'OPERATOR', 'FINANCE'].map(role => el('option', { value: role, selected: member.role === role }, ROLE_LABEL[role])));
  const statusSel = el('select', { class: 'input' },
    el('option', { value: 'ACTIVE', selected: member.status === 'ACTIVE' }, 'ACTIVE · 启用'),
    el('option', { value: 'SUSPENDED', selected: member.status === 'SUSPENDED' }, 'SUSPENDED · 停用'));
  const scope = storeScopeEditor(member.storeScope);
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '保存');
  const modal = openModal({
    title: `编辑成员 · ${member.displayName}`,
    body: [
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '角色'), roleSel),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '状态'), statusSel)),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '门店范围'), scope.node),
      el('p', { class: 'field-hint' }, `携带版本 v${member.version}；最后一位 OWNER 不能被停用或降级（服务器 409）。`),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    const scopeValue = scope.collect();
    if (roleSel.value === 'OPERATOR' && scopeValue.mode === 'SELECTED' && !scopeValue.storeIds.length) {
      errorNode.textContent = 'OPERATOR 使用指定门店范围时至少选择一家门店';
      return;
    }
    busy(submit, '保存中…');
    try {
      await adapter.updateMember(member.id, { role: roleSel.value, status: statusSel.value, storeScope: scopeValue, version: member.version });
      modal.close();
      toast('成员信息已更新', 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '保存');
      if (isVersionConflict(error)) { showConflictRetry(errorNode, error, () => { modal.close(); reloadView(); }); return; }
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
    }
  });
}

async function revokeInvitationFlow(invitation) {
  const confirmed = await confirmModal({
    title: `撤销邀请 · ${invitation.email}`,
    message: '撤销后该邀请链接立即失效，成员将无法通过它加入组织。',
    confirmText: '撤销', danger: true,
  });
  if (!confirmed) return;
  try {
    await adapter.revokeInvitation(invitation.id);
    toast('邀请已撤销', 'success');
    reloadView();
  } catch (error) { toast(describeMerchantError(error), 'error'); }
}

/* ============================================================
   视图十一：收款账户
   ============================================================ */

const PROVIDER_LABEL = { alipay: '支付宝', alipay_mock: '支付宝（模拟渠道）' };
const ACCOUNT_ENV = {
  LIVE: { label: '正式', kind: 'green' }, SANDBOX: { label: '沙箱', kind: 'amber' }, MOCK: { label: '模拟', kind: 'blue' },
};

function renderAccountsView(root) {
  const region = el('section', { class: 'card' });
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '收款账户'),
        el('span', { class: 'field-hint' }, '正式 / 沙箱 / 模拟渠道明确区分；每笔支付固定账户快照，退款沿原账户处理。')),
      can(PERM.paymentsManage)
        ? el('div', { class: 'toolbar-actions' }, el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新增账户</span>', onclick: openAccountModal }))
        : null),
    el('p', { class: 'field-hint' }, '切换默认账户只影响新支付；历史订单的退款仍沿原支付账户处理。'),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, loadAccounts);
}

async function loadAccounts(container) {
  const { items } = await adapter.listPaymentAccounts();
  clearNode(container);
  if (!items.length) { container.append(emptyState('还没有收款账户', can(PERM.paymentsManage) ? '使用「新增账户」录入商户账户信息' : '需要 payments.manage 权限')); return; }
  const rows = items.map(account => {
    const actions = [];
    if (can(PERM.paymentsManage)) {
      actions.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => validateAccountFlow(account) }, '校验'));
      if (!account.isDefault && account.status === 'ACTIVE') actions.push(el('button', { class: 'btn secondary small', type: 'button', onclick: () => setDefaultAccountFlow(account) }, '设为默认'));
      if (account.status === 'ACTIVE' && !account.isDefault) actions.push(el('button', { class: 'btn ghost small', type: 'button', onclick: () => disableAccountFlow(account) }, '停用'));
    }
    return el('tr', null,
      tdl(el('div', null,
        el('div', { class: 'cell-strong' }, account.label),
        el('div', { class: 'cell-sub mono' }, `${PROVIDER_LABEL[account.provider] || account.provider} · appId ${account.appIdMasked || '—'} · 商户 ${account.merchantIdMasked || '—'}`)), '账户'),
      tdl(statusBadge(ACCOUNT_ENV, account.environment), '环境'),
      tdl(account.status === 'ACTIVE' ? badge('green', '启用') : badge('gray', '停用'), '状态'),
      tdl(account.isDefault ? badge('blue', '默认收款') : el('span', { class: 'muted' }, '—'), '默认'),
      tdl(fmtDateTime(account.configuredAt, tz()), '配置时间'),
      tdl(actions.length ? el('div', { class: 'action-row' }, actions) : el('span', { class: 'muted' }, '只读'), '操作'));
  });
  container.append(makeTable({ headers: ['账户', '环境', '状态', '默认', '配置时间', '操作'], rows, minTable: 820 }));
}

function openAccountModal() {
  const label = el('input', { class: 'input', required: true, maxlength: '60', placeholder: '例如 支付宝·主账户' });
  const provider = el('select', { class: 'input' },
    el('option', { value: 'alipay' }, 'alipay · 支付宝'),
    el('option', { value: 'alipay_mock' }, 'alipay_mock · 支付宝模拟渠道'));
  const environment = el('select', { class: 'input' },
    el('option', { value: 'LIVE' }, 'LIVE · 正式'),
    el('option', { value: 'SANDBOX' }, 'SANDBOX · 沙箱'),
    el('option', { value: 'MOCK' }, 'MOCK · 模拟'));
  const appId = el('input', { class: 'input mono', required: true, autocomplete: 'off' });
  const merchantId = el('input', { class: 'input mono', required: true, autocomplete: 'off' });
  const appPrivateKey = el('textarea', { class: 'input mono', rows: '4', autocomplete: 'off', spellcheck: 'false', placeholder: '应用私钥（粘贴后提交，不在页面保留）' });
  const providerPublicKey = el('textarea', { class: 'input mono', rows: '3', autocomplete: 'off', spellcheck: 'false', placeholder: '渠道公钥（可选）' });
  const errorNode = el('p', { class: 'form-error', role: 'alert' });
  const submit = el('button', { class: 'btn primary', type: 'button' }, '保存账户');
  const idem = newIdemScope();
  const modal = openModal({
    title: '新增收款账户',
    wide: true,
    body: [
      el('p', { class: 'field-hint' }, '密钥仅用于本次提交：通过加密通道发送给服务器加密保存，页面离开或提交后立即清空，不回显、不记录。不能通过填写任意网关地址绕过服务端校验。'),
      el('div', { class: 'kv-grid' },
        el('div', { class: 'field', 'data-field': 'label' }, el('span', { class: 'field-label' }, '账户标签 *'), label),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '渠道'), provider),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '环境'), environment),
        el('div', { class: 'field', 'data-field': 'appId' }, el('span', { class: 'field-label' }, 'App ID *'), appId),
        el('div', { class: 'field', 'data-field': 'merchantId' }, el('span', { class: 'field-label' }, '商户 ID *'), merchantId),
        el('div', { class: 'field', 'data-field': 'appPrivateKey' }, el('span', { class: 'field-label' }, '应用私钥 *'), appPrivateKey),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '渠道公钥'), providerPublicKey)),
      errorNode,
    ],
    footer: [el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'), submit],
    onClose: () => { appPrivateKey.value = ''; providerPublicKey.value = ''; },
  });
  submit.addEventListener('click', async () => {
    clearFieldErrors(modal.card);
    errorNode.textContent = '';
    if (!label.value.trim()) { showFieldErrors(modal.card, { label: '请填写账户标签' }); return; }
    if (!appId.value.trim() || !merchantId.value.trim()) { showFieldErrors(modal.card, { appId: '请填写 App ID 与商户 ID' }); return; }
    if (!appPrivateKey.value.trim()) { showFieldErrors(modal.card, { appPrivateKey: '请填写应用私钥' }); return; }
    busy(submit, '保存中…');
    try {
      const account = await adapter.createPaymentAccount({
        label: label.value.trim(), provider: provider.value, environment: environment.value,
        appId: appId.value.trim(), merchantId: merchantId.value.trim(),
        appPrivateKey: appPrivateKey.value, providerPublicKey: providerPublicKey.value.trim() || undefined,
      }, idem.current());
      appPrivateKey.value = ''; providerPublicKey.value = '';
      modal.close();
      toast(`账户「${account.label}」已保存（密钥已加密，页面不回显）`, 'success');
      reloadView();
    } catch (error) {
      unbusy(submit, '保存账户');
      showFieldErrors(modal.card, error.fields, errorNode, describeMerchantError(error));
      idem.reset();
    }
  });
}

async function validateAccountFlow(account) {
  try {
    const result = await adapter.validatePaymentAccount(account.id, { version: account.version });
    const body = el('div', null,
      el('p', { class: 'field-hint' }, `账户「${account.label}」校验结果：${result.status === 'PASS' ? '通过' : result.status}`),
      el('div', { class: 'plain-list' }, (result.checks || []).map(check => el('div', { class: 'plain-item' },
        el('span', null, check.name),
        el('span', null, check.status === 'PASS' ? badge('green', '通过') : check.status === 'FAIL' ? badge('red', '失败') : badge('gray', check.status), ` ${check.message || ''}`)))));
    const modal = openModal({ title: '账户校验', body, footer: [el('button', { class: 'btn primary', type: 'button', onclick: () => modal.close() }, '知道了')] });
    void modal;
  } catch (error) {
    toast(describeMerchantError(error), 'error');
  }
}

async function setDefaultAccountFlow(account) {
  const confirmed = await confirmModal({
    title: `设为默认收款 · ${account.label}`,
    message: '切换默认账户只影响之后的新支付；历史订单退款仍沿原支付账户处理。校验未通过的账户不能设为默认。',
    confirmText: '设为默认',
  });
  if (!confirmed) return;
  try {
    await adapter.setDefaultPaymentAccount(account.id, { version: account.version });
    toast('默认收款账户已切换', 'success');
    reloadView();
  } catch (error) { toast(describeMerchantError(error), 'error'); }
}

async function disableAccountFlow(account) {
  const confirmed = await confirmModal({
    title: `停用账户 · ${account.label}`,
    message: '停用后新支付不再使用该账户；历史退款仍沿该账户处理。默认账户需先切换默认后才能停用。',
    confirmText: '停用', danger: true,
  });
  if (!confirmed) return;
  try {
    await adapter.disablePaymentAccount(account.id, { version: account.version });
    toast('账户已停用', 'success');
    reloadView();
  } catch (error) { toast(describeMerchantError(error), 'error'); }
}

/* ============================================================
   视图十二：组织设置
   ============================================================ */

function renderSettingsView(root) {
  const region = el('section', { class: 'card' });
  root.append(
    el('p', { class: 'field-hint' }, '报表账期始终按组织时区计算；已产生交易后时区变更可能被服务器拒绝（409），不会仅因浏览器格式变化而改变账期归属。'),
    region);
  region.append(skeletonRows(3));
  loadRegion(region, async container => {
    const tenant = await adapter.getTenant();
    clearNode(container);
    const name = el('input', { class: 'input', value: tenant.name || '', maxlength: '80' });
    const timezone = el('select', { class: 'input' },
      ['Asia/Shanghai', 'Asia/Tokyo', 'Asia/Singapore', 'Europe/London', 'America/New_York', 'UTC'].map(tzValue =>
        el('option', { value: tzValue, selected: (tenant.timezone || 'Asia/Shanghai') === tzValue }, tzValue)));
    const errorNode = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '保存');
    container.append(
      el('div', { class: 'card-head' }, el('h3', null, '组织信息'), el('span', { class: 'muted mono' }, tenant.id || '')),
      el('div', { class: 'card-body' },
        el('div', { class: 'kv-grid' },
          el('div', { class: 'field', 'data-field': 'name' }, el('span', { class: 'field-label' }, '组织名称'), name),
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, '时区'), timezone)),
        el('p', { class: 'field-hint' }, `携带版本 v${tenant.version}；时区变更影响日结账期边界，服务器可能在存在交易后拒绝。`),
        errorNode,
        el('div', { class: 'toolbar-actions' }, submit)));
    submit.addEventListener('click', async () => {
      clearFieldErrors(container);
      errorNode.textContent = '';
      if (!name.value.trim()) { showFieldErrors(container, { name: '请填写组织名称' }); return; }
      busy(submit, '保存中…');
      try {
        await adapter.updateTenant({ name: name.value.trim(), timezone: timezone.value, version: tenant.version });
        toast('组织信息已更新', 'success');
        await refreshStores();
        route();
      } catch (error) {
        unbusy(submit, '保存');
        if (isVersionConflict(error)) { showConflictRetry(errorNode, error, () => route()); return; }
        showFieldErrors(container, error.fields, errorNode, describeMerchantError(error));
      }
    });
  });
}

/* ============================================================
   视图十三：审计日志
   ============================================================ */

function renderAuditView(root) {
  const action = el('input', { class: 'input mono', placeholder: '按动作过滤，例如 refund' });
  const region = el('section', { class: 'card' });
  const moreBar = el('div', { class: 'load-more hidden', id: 'audit-more' });
  state.auditFilters = { action: '', cursor: null, items: [] };
  const refresh = reset => {
    state.auditFilters.action = action.value.trim();
    if (reset) state.auditFilters.cursor = null;
    loadRegion(region, loadAuditPage);
  };
  action.addEventListener('change', () => refresh(true));
  root.append(
    el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '动作'), action),
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '日期'),
        el('span', { class: 'field-hint' }, `使用顶栏区间 ${state.period.from} ~ ${state.period.to}`)),
      el('div', { class: 'toolbar-actions' },
        el('button', { class: 'btn secondary small', type: 'button', html: icon.refresh + '<span>查询</span>', onclick: () => refresh(true) }))),
    region, moreBar);
  region.append(skeletonRows(6));
  refresh(true);
}

async function loadAuditPage(container) {
  const filters = state.auditFilters;
  const { items, nextCursor } = await adapter.listAudit({
    ...periodToApiParams(state.period),
    action: filters.action || undefined,
    cursor: filters.cursor || undefined,
  });
  filters.items = filters.cursor ? filters.items.concat(items) : items;
  filters.cursor = nextCursor;
  clearNode(container);
  if (!filters.items.length) {
    container.append(el('div', { class: 'card-body' }, emptyState('没有符合条件的审计记录', '调整动作或日期区间后重试')));
    $('audit-more')?.classList.add('hidden');
    return;
  }
  const rows = filters.items.map(log => el('tr', null,
    tdl(fmtDateTime(log.createdAt, tz()), '时间'),
    tdl(el('div', null, el('div', { class: 'cell-strong' }, log.actorName || '—'), el('div', { class: 'cell-sub mono' }, log.requestId || '')), '操作者'),
    tdl(el('code', { class: 'mono' }, log.action || '—'), '动作'),
    tdl(el('div', null, el('div', null, log.resourceType || '—'), el('div', { class: 'cell-sub' }, log.resourceLabel || '')), '资源'),
    tdl(log.outcome === 'SUCCESS' ? badge('green', '成功') : badge('red', log.outcome || '失败'), '结果')));
  container.append(makeTable({ headers: ['时间', '操作者', '动作', '资源', '结果'], rows, minTable: 760 }));
  const more = $('audit-more');
  if (nextCursor && more) {
    more.classList.remove('hidden');
    clearNode(more);
    const btn = el('button', { class: 'btn secondary block', type: 'button' }, '加载更多');
    btn.addEventListener('click', () => loadRegion(container, loadAuditPage));
    more.append(btn);
  } else if (more) {
    more.classList.add('hidden');
  }
}

/* ============================================================
   演示工具（仅 ?demo=1）
   ============================================================ */

function initDemoTools() {
  if (!state.demo) return;
  const bar = $('demo-tools');
  bar.classList.remove('hidden');
  const panel = el('div', { class: 'demo-panel hidden' });
  const roleRow = el('div', { class: 'demo-row' }, el('strong', null, '切换角色'),
    DEMO_ROLES.map(role => el('button', {
      class: 'btn secondary small', type: 'button', 'data-role': role,
      onclick: async () => {
        if (!state.session) { toast('请先登录演示会话后再切换角色', 'error'); return; }
        const session = adapter.demoSetRole(role);
        applySession(session);
        state.storeId = '';
        buildShell();
        await refreshStores();
        buildShellControls();
        route();
        syncDemoTools();
      },
    }, ROLE_LABEL[role])));
  const faultDefs = [['empty', '列表返回空数据'], ['forbidden', '读取返回 403'], ['network', '网络失败'], ['slow', '慢响应（约 1.3 秒）']];
  const faultRow = el('div', { class: 'demo-row' }, el('strong', null, '故障模拟'),
    faultDefs.map(([name, label]) => {
      const checkbox = el('input', { type: 'checkbox', 'data-fault': name });
      checkbox.addEventListener('change', () => { adapter.demoToggleFault(name); });
      return el('label', { class: 'check-row' }, checkbox, el('span', null, label));
    }));
  const emailRow = el('div', { class: 'demo-row' }, el('strong', null, '邮件服务'),
    (() => {
      const checkbox = el('input', { type: 'checkbox' });
      checkbox.addEventListener('change', () => { state.demoEmailUnavailable = adapter.demoToggleEmailUnavailable(); });
      return el('label', { class: 'check-row' }, checkbox, el('span', null, '标记为不可用（新邀请 deliveryStatus=UNAVAILABLE）'));
    })());
  const actionRow = el('div', { class: 'demo-row' }, el('strong', null, '内存交互'),
    el('button', {
      class: 'btn secondary small', type: 'button',
      onclick: () => { const r = adapter.demoAdvanceRefunds(); toast(`已将 ${r.advanced} 笔演示退款置为成功并更新订单`, 'success'); reloadView(); },
    }, '模拟退款成功'),
    el('button', {
      class: 'btn secondary small', type: 'button',
      onclick: () => { adapter.demoReset(); toast('演示数据已重置（会话保留）', 'info'); reloadView(); },
    }, '重置演示数据'));
  const hints = adapter.demoHints();
  panel.append(
    el('p', { class: 'field-hint' }, '以下工具仅存在于演示模式；真实模式不会出现，也不会发送任何请求。'),
    roleRow, faultRow, emailRow, actionRow,
    el('div', { class: 'demo-row' }, el('strong', null, '固定值'),
      el('span', { class: 'field-hint' }, `认领码 ${hints.claimCode}；验证 token ${hints.verifyToken}；重置 token ${hints.resetToken}；邀请 token ${hints.inviteToken}`)));
  const toggle = el('button', { class: 'btn small demo-toggle', type: 'button', 'aria-expanded': 'false' }, '演示工具');
  toggle.addEventListener('click', () => {
    const hidden = panel.classList.toggle('hidden');
    toggle.setAttribute('aria-expanded', String(!hidden));
  });
  bar.append(toggle, panel);
}

function syncDemoTools() {
  if (!state.demo) return;
  const role = roleNow();
  for (const btn of document.querySelectorAll('[data-role]')) btn.classList.toggle('active', btn.dataset.role === role);
}

/* ============================================================
   启动
   ============================================================ */

function boot() {
  if (state.demo) {
    document.body.classList.add('demo-mode');
    $('demo-banner').classList.remove('hidden');
  }
  readFragmentToken();
  initDemoTools();
  startWithAuthConfig();
}

/** 初始化第一步：先取非敏感认证配置；失败时诚实展示错误，不回退演示、不假定认证可用。 */
async function startWithAuthConfig() {
  try {
    state.authConfig = await adapter.authConfig();
    state.authConfigError = null;
  } catch (error) {
    state.authConfig = null;
    state.authConfigError = error;
    renderAuthConfigError(error);
    return;
  }
  if (state.demo) {
    renderAuth();
    return;
  }
  adapter.getSession().then(session => { enterShell(session); }).catch(() => { renderAuth(); });
}

$('logout-btn')?.addEventListener('click', doLogout);
$('hamburger')?.addEventListener('click', () => {
  document.body.classList.add('nav-open');
  $('nav-veil')?.classList.remove('hidden');
});
$('nav-veil')?.addEventListener('click', closeMobileNav);
$('refresh-btn')?.addEventListener('click', reloadView);

boot();
