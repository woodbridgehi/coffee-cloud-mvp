/* ============================================================
   Coffee Cloud · 设备运营台（无框架实现）
   - Token 仅保存在页面内存变量中，不写 localStorage /
     sessionStorage / cookie / URL，也不输出到 console。
   - 登录后先请求 GET /api/v1/admin/session，按 permissions
     控制导航与操作可见性。
   - API 数据一律走 textContent / createElement；innerHTML 仅
     用于不含任何 API 数据的静态 SVG 图标。
   ============================================================ */
(() => {
  'use strict';

  /* ---------- 常量与状态 ---------- */

  const REFRESH_INTERVAL_MS = 10000; // 自动刷新间隔；页面隐藏 / 输入中 / 弹窗打开时暂停

  const PERMISSIONS = {
    dashboard: 'dashboard.read',
    devicesRead: 'devices.read',
    ordersRead: 'orders.read',
    devicesManage: 'devices.manage',
    commandsExecute: 'commands.execute',
    refundsManage: 'refunds.manage',
    accessRead: 'access.read',
    accessManage: 'access.manage',
    auditRead: 'audit.read',
  };

  const state = {
    token: '',
    principal: null,
    permissions: new Set(),
    view: '',
    devices: [],
    serverTime: '',
    selectedDeviceId: '',
    detailSeq: 0,
    expandedOrderId: null,
    expandedOperatorId: null,
    operators: [],
    filters: {
      deviceQuery: '',
      deviceConn: 'all',
      orderStatus: '',
      orderDevice: '',
      auditAction: '',
      auditResource: '',
    },
    lastRefreshAt: null,
    timer: null,
  };

  const $ = id => document.getElementById(id);

  /* ---------- 静态 SVG 图标（innerHTML 仅用于此处，无 API 数据） ---------- */

  const icon = {
    grid: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><rect x="3.5" y="3.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6" stroke="currentColor" stroke-width="1.8"/></svg>',
    device: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><rect x="4" y="3.5" width="16" height="17" rx="2.4" stroke="currentColor" stroke-width="1.8"/><path d="M9 7.5h6M9 11h6M9 14.5h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="15.4" cy="17.6" r="1.2" fill="currentColor"/></svg>',
    receipt: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M6 3h12v18l-3-1.8L12 21l-3-1.8L6 21V3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9.5 8h5M9.5 12h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    shield: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 3 5 5.8v5.4c0 4.4 3 7.9 7 9.8 4-1.9 7-5.4 7-9.8V5.8L12 3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="m9 11.8 2.2 2.2L15.4 10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    list: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M8 5.5h12M8 12h12M8 18.5h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="4.3" cy="5.5" r="1.3" fill="currentColor"/><circle cx="4.3" cy="12" r="1.3" fill="currentColor"/><circle cx="4.3" cy="18.5" r="1.3" fill="currentColor"/></svg>',
    refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 1 1-2.4-5.7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M20 3.5V7h-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    plus: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    copy: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><rect x="8.5" y="8.5" width="11" height="11" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M5 14.5A1.5 1.5 0 0 1 3.9 13V6a2 2 0 0 1 2-2H13a1.5 1.5 0 0 1 1.5 1.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M4.5 12.5 10 18 19.5 6.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    alert: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 3 2.5 20h19L12 3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 9.5v4.5M12 17.4v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 11v5.5M12 7.6v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    empty: '<svg width="42" height="42" viewBox="0 0 24 24" fill="none"><path d="M4 9h12v6.5a4.5 4.5 0 0 1-4.5 4.5h-3A4.5 4.5 0 0 1 4 15.5V9Z" stroke="currentColor" stroke-width="1.6"/><path d="M16 10.5h1.8a2.7 2.7 0 0 1 0 5.4H16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M7.5 6c0-1.2 1-1.6 1-2.8M11 6c0-1.2 1-1.6 1-2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  };

  /* ---------- DOM 辅助 ---------- */

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'html') node.innerHTML = value; // 仅静态 SVG
      else if (key === 'value') node.value = value;
      else if (key === 'disabled') node.disabled = true;
      else if (key === 'checked') node.checked = true;
      else if (key === 'selected') node.selected = true;
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function clear(node) { node.replaceChildren(); }

  function badge(kind, label, extra) {
    return el('span', { class: `badge ${kind}${extra ? ' ' + extra : ''}` }, label);
  }

  function kv(label, value, mono) {
    return el('div', { class: 'kv' },
      el('label', null, label),
      el('strong', mono ? { class: 'mono' } : null, value === null || value === undefined || value === '' ? '—' : String(value)));
  }

  /* ---------- 展示辅助 ---------- */

  function fmtTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {
      hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }

  function fmtAgo(value) {
    if (!value) return '从未';
    const ms = Date.now() - new Date(value).getTime();
    if (!Number.isFinite(ms)) return '—';
    const sec = Math.round(ms / 1000);
    if (sec < 0) return fmtTime(value);
    if (sec < 60) return `${sec} 秒前`;
    if (sec < 3600) return `${Math.round(sec / 60)} 分钟前`;
    if (sec < 86400) return `${Math.round(sec / 3600)} 小时前`;
    return `${Math.round(sec / 86400)} 天前`;
  }

  function fmtMoney(minor, currency) {
    const amount = (Number(minor || 0) / 100).toFixed(2);
    return currency === 'CNY' || !currency ? `¥${amount}` : `${amount} ${currency}`;
  }

  function fmtPercent(rate) {
    return rate === null || rate === undefined ? '—' : `${(Number(rate) * 100).toFixed(1)}%`;
  }

  const ORDER_STATUS = {
    CREATED: { label: '已创建', kind: 'gray' },
    AWAITING_PAYMENT: { label: '待支付', kind: 'amber' },
    QUEUED: { label: '排队中', kind: 'blue' },
    DISPATCHED: { label: '已派单', kind: 'blue' },
    ACCEPTED: { label: '设备已接受', kind: 'blue' },
    MAKING: { label: '制作中', kind: 'blue' },
    HOLD: { label: '待人工确认', kind: 'amber' },
    READY: { label: '已完成', kind: 'green' },
    FAILED: { label: '失败', kind: 'red' },
    REFUNDED: { label: '已退款', kind: 'gray' },
    CANCELLED: { label: '已取消', kind: 'gray' },
    EXPIRED: { label: '派单超时', kind: 'red' },
  };

  const PAYMENT_STATUS = {
    NOT_STARTED: { label: '未开始', kind: 'gray' },
    NOT_REQUIRED: { label: '无需支付', kind: 'gray' },
    PENDING: { label: '待支付', kind: 'amber' },
    PAID: { label: '已支付', kind: 'green' },
    REFUNDING: { label: '退款中', kind: 'amber' },
    REFUNDED: { label: '已退款', kind: 'gray' },
    PARTIALLY_REFUNDED: { label: '部分退款', kind: 'amber' },
    CLOSED: { label: '已关闭', kind: 'gray' },
    FAILED: { label: '支付失败', kind: 'red' },
  };

  const LIFECYCLE = {
    PENDING: { label: '待激活', kind: 'gray' },
    ACTIVE: { label: '运行中', kind: 'green' },
    SUSPENDED: { label: '已停用', kind: 'red' },
    MAINTENANCE: { label: '维护中', kind: 'amber' },
  };

  function orderBadge(status) {
    const meta = ORDER_STATUS[status] || { label: status || '—', kind: 'gray' };
    return badge(meta.kind, meta.label);
  }

  function paymentBadge(status) {
    const meta = PAYMENT_STATUS[status] || { label: status || '—', kind: 'gray' };
    return badge(meta.kind, meta.label);
  }

  function lifecycleBadge(status) {
    const meta = LIFECYCLE[status] || { label: status || '—', kind: 'gray' };
    return badge(meta.kind, meta.label);
  }

  /* ---------- 网络层 ---------- */

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  function describeError(error) {
    if (error instanceof ApiError && error.status === 403) return `权限不足：${error.message}`;
    return error.message || '请求失败';
  }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { ...options, headers, cache: 'no-store' });
    let data = {};
    try { data = await response.json(); } catch (_) { /* 非 JSON */ }
    if (response.status === 401) {
      if (state.token) forceLogout('登录已过期或 Token 已失效，请重新登录');
      throw new ApiError('未授权', 401);
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : (data.detail?.code || `HTTP ${response.status}`);
      throw new ApiError(detail, response.status);
    }
    return data;
  }

  /* ---------- Toast ---------- */

  function toast(message, kind = 'info') {
    const root = $('toast-root');
    if (!root) return;
    const node = el('div', {
      class: `toast ${kind}`,
      onclick: () => node.remove(),
    },
      el('span', { class: 't-icon', html: kind === 'success' ? icon.check : kind === 'error' ? icon.alert : icon.info, 'aria-hidden': 'true' }),
      el('span', null, message));
    root.append(node);
    setTimeout(() => {
      node.classList.add('leaving');
      setTimeout(() => node.remove(), 300);
    }, 4600);
  }

  /* ---------- 弹窗 ---------- */

  let activeModal = null;

  function modalOpen() { return activeModal !== null; }

  function openModal({ title, body, footer, wide, dismissible = true }) {
    closeModal();
    const root = $('modal-root');
    const handle = { root, card: null, onClose: null };
    const close = () => {
      if (!activeModal || activeModal.root !== root) return;
      activeModal = null;
      root.classList.add('hidden');
      root.setAttribute('aria-hidden', 'true');
      clear(root);
      if (handle.onClose) handle.onClose();
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
    root.onclick = dismissible ? close : () => {};
    activeModal = handle;
    const focusable = card.querySelector('input, select, textarea, button:not(.modal-close)');
    if (focusable) focusable.focus();
    return { ...handle, close, card };
  }

  function closeModal() {
    if (activeModal) activeModal.root.onclick = null;
    const root = $('modal-root');
    root.classList.add('hidden');
    root.setAttribute('aria-hidden', 'true');
    clear(root);
    activeModal = null;
  }

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && activeModal) {
      const root = $('modal-root');
      root.onclick?.();
    }
  });

  /* 确认弹窗；requireText 非空时需要输入指定文本才能确认（二次确认） */
  function confirmModal({ title, message, confirmText = '确认', cancelText = '取消', danger = false, requireText = '', extra = null }) {
    return new Promise(resolve => {
      let input = null;
      let confirmBtn = null;
      const body = [
        typeof message === 'string' ? el('p', { style: 'margin:0' }, message) : message,
        extra,
      ];
      if (requireText) {
        input = el('input', { class: 'input', placeholder: `输入“${requireText}”以确认`, autocomplete: 'off' });
        input.addEventListener('input', () => { confirmBtn.disabled = input.value.trim() !== requireText; });
        body.push(el('div', { class: 'field' }, el('span', { class: 'field-label' }, '请输入确认文字'), input));
      }
      const done = result => { modal.close(); resolve(result); };
      confirmBtn = el('button', {
        class: `btn ${danger ? 'danger' : 'primary'}`,
        type: 'button',
        disabled: Boolean(requireText),
        onclick: () => done(true),
      }, confirmText);
      const modal = openModal({
        title,
        body,
        footer: [
          el('button', { class: 'btn secondary', type: 'button', onclick: () => done(false) }, cancelText),
          confirmBtn,
        ],
      });
    });
  }

  /* 一次性秘密展示（激活码 / 新运营 Token），关闭后不再出现 */
  function showSecretModal({ title, label, secret, note }) {
    let codeNode = null;
    const copyBtn = el('button', { class: 'btn secondary small', type: 'button', html: icon.copy + '<span>复制</span>' });
    const modal = openModal({
      title,
      body: [
        el('div', { class: 'secret-box' },
          el('div', { class: 's-label' }, label),
          codeNode = el('code', null, secret),
          copyBtn),
        el('div', { class: 'secret-warn' },
          el('span', { html: icon.alert, 'aria-hidden': 'true' }),
          el('span', null, note || '该内容只显示这一次，云端只保存摘要。请立即复制并妥善保管。')),
      ],
      footer: [el('button', { class: 'btn primary', type: 'button', onclick: () => modal.close() }, '我已安全保存')],
    });
    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(secret);
        toast('已复制到剪贴板', 'success');
      } catch (_) {
        const range = document.createRange();
        range.selectNodeContents(codeNode);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        toast('复制失败，请手动选择文本复制', 'error');
      }
    });
    return modal;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制到剪贴板', 'success');
    } catch (_) {
      toast('复制失败，请手动复制', 'error');
    }
  }

  /* ---------- 登录 / 会话 ---------- */

  function can(permission) { return state.permissions.has(permission); }

  function setLoginBusy(busy) {
    const btn = $('login-submit');
    btn.disabled = busy;
    btn.replaceChildren(busy ? el('span', { class: 'spin', 'aria-hidden': 'true' }) : null, busy ? '正在验证…' : '登录');
  }

  async function handleLogin(event) {
    event.preventDefault();
    const input = $('login-token');
    const errorNode = $('login-error');
    const value = input.value.trim();
    if (!value) {
      errorNode.textContent = '请输入运营 Token';
      input.focus();
      return;
    }
    errorNode.textContent = '';
    setLoginBusy(true);
    state.token = value; // 仅保存在内存
    try {
      const session = await api('/api/v1/admin/session');
      state.principal = session;
      state.permissions = new Set(session.permissions || []);
      input.value = '';
      enterShell();
    } catch (error) {
      state.token = '';
      errorNode.textContent = `登录失败：${describeError(error)}`;
      input.select();
    } finally {
      setLoginBusy(false);
    }
  }

  function forceLogout(message) {
    stopAutoRefresh();
    state.token = '';
    state.principal = null;
    state.permissions = new Set();
    state.view = '';
    state.devices = [];
    state.selectedDeviceId = '';
    state.expandedOrderId = null;
    state.expandedOperatorId = null;
    closeModal();
    $('shell').classList.add('hidden');
    $('login-view').classList.remove('hidden');
    document.title = 'Coffee Cloud · 设备运营台';
    if (message) toast(message, 'error');
    const input = $('login-token');
    input.value = '';
    input.focus();
  }

  function logout() {
    forceLogout('已退出登录');
  }

  function updateWho() {
    const who = $('who');
    clear(who);
    if (!state.principal) return;
    who.append(
      el('strong', null, state.principal.displayName || state.principal.actorId || '运营员'),
      `${state.principal.role || ''} · ${state.principal.tokenLabel || 'session'}`,
    );
  }

  /* ---------- 导航 ---------- */

  const VIEW_DEFS = [
    { id: 'dashboard', label: '运营总览', title: '运营总览', sub: '设备、订单与运营积压的实时快照', perm: PERMISSIONS.dashboard, icon: icon.grid },
    { id: 'devices', label: '设备', title: '设备管理', sub: '终端连接、生命周期、能力与物料', perm: PERMISSIONS.devicesRead, icon: icon.device },
    { id: 'orders', label: '订单', title: '订单', sub: '支付、制作进度与异常处理', perm: PERMISSIONS.ordersRead, icon: icon.receipt },
    { id: 'access', label: '权限', title: '权限', sub: '运营员、角色与 API Token', perm: PERMISSIONS.accessRead, icon: icon.shield },
    { id: 'audit', label: '审计', title: '审计日志', sub: '操作者、动作与资源记录', perm: PERMISSIONS.auditRead, icon: icon.list },
  ];

  function buildNav() {
    const nav = $('side-nav');
    clear(nav);
    for (const def of VIEW_DEFS) {
      if (!can(def.perm)) continue;
      nav.append(el('button', {
        class: `nav-item${state.view === def.id ? ' active' : ''}`,
        type: 'button',
        onclick: () => { location.hash = `#/${def.id}`; },
      },
        el('span', { class: 'n-icon', html: def.icon, 'aria-hidden': 'true' }),
        el('span', null, def.label)));
    }
  }

  function currentViewDef() { return VIEW_DEFS.find(def => def.id === state.view); }

  function route() {
    if (!state.token) return;
    const target = (location.hash || '').replace(/^#\//, '').split(/[?&]/)[0];
    const def = VIEW_DEFS.find(item => item.id === target && can(item.perm));
    if (!def) {
      const fallback = VIEW_DEFS.find(item => can(item.perm));
      if (!fallback) {
        renderNoAccess();
        return;
      }
      if (fallback.id !== target) {
        location.hash = `#/${fallback.id}`;
        return;
      }
      state.view = fallback.id;
    } else {
      state.view = def.id;
    }
    const active = currentViewDef();
    document.title = `Coffee Cloud · ${active.title}`;
    $('view-title').textContent = active.title;
    $('view-sub').textContent = active.sub;
    buildNav();
    const workspace = $('workspace');
    clear(workspace);
    ({
      dashboard: renderDashboardView,
      devices: renderDevicesView,
      orders: renderOrdersView,
      access: renderAccessView,
      audit: renderAuditView,
    })[state.view](workspace);
    refreshNow();
  }

  function renderNoAccess() {
    const workspace = $('workspace');
    clear(workspace);
    buildNav();
    workspace.append(el('section', { class: 'card' },
      el('div', { class: 'empty' },
        el('span', { html: icon.shield, 'aria-hidden': 'true' }),
        el('div', { class: 'e-title' }, '当前账号没有任何可访问的视图'),
        el('div', { class: 'muted' }, '请联系 OWNER 为该账号分配角色，或使用其他 Token 登录。'))));
  }

  /* ---------- 自动刷新 ---------- */

  function isTyping() {
    const node = document.activeElement;
    if (!node) return false;
    const tag = node.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }

  function shouldSkipAutoRefresh() {
    return document.hidden || modalOpen() || isTyping();
  }

  function viewLoader() {
    return {
      dashboard: can(PERMISSIONS.dashboard) ? loadDashboard : null,
      devices: can(PERMISSIONS.devicesRead) ? loadDevices : null,
      orders: can(PERMISSIONS.ordersRead) ? loadOrders : null,
      audit: can(PERMISSIONS.auditRead) ? loadAuditLogs : null,
      access: can(PERMISSIONS.accessRead) ? loadOperators : null,
    }[state.view] || null;
  }

  function tick() {
    if (!state.token || shouldSkipAutoRefresh()) { updateRefreshNote(); return; }
    /* 高频自动刷新仅覆盖实时性要求高的视图；权限/审计为手动刷新 */
    const loader = {
      dashboard: can(PERMISSIONS.dashboard) ? loadDashboard : null,
      devices: can(PERMISSIONS.devicesRead) ? loadDevices : null,
      orders: can(PERMISSIONS.ordersRead) ? loadOrders : null,
    }[state.view] || null;
    if (loader) loader().catch(() => { });
    updateRefreshNote();
  }

  function updateRefreshNote() {
    const note = $('refresh-note');
    if (!note) return;
    const parts = [`每 ${REFRESH_INTERVAL_MS / 1000} 秒自动刷新`];
    if (document.hidden) parts.push('页面隐藏，已暂停');
    else if (modalOpen()) parts.push('弹窗打开，已暂停');
    else if (isTyping()) parts.push('输入中，已暂停');
    if (state.lastRefreshAt) parts.push(`上次 ${state.lastRefreshAt.toLocaleTimeString('zh-CN', { hour12: false })}`);
    note.textContent = parts.join(' · ');
  }

  function refreshNow() {
    const loader = viewLoader();
    if (loader) {
      loader().catch(() => { });
      state.lastRefreshAt = new Date();
      updateRefreshNote();
    }
  }

  function startAutoRefresh() {
    stopAutoRefresh();
    state.timer = setInterval(tick, REFRESH_INTERVAL_MS);
  }

  function stopAutoRefresh() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.token) tick();
    else updateRefreshNote();
  });

  function enterShell() {
    $('login-view').classList.add('hidden');
    $('shell').classList.remove('hidden');
    updateWho();
    updateRefreshNote();
    startAutoRefresh();
    if (!location.hash || !VIEW_DEFS.some(def => `#/${def.id}` === location.hash && can(def.perm))) {
      const fallback = VIEW_DEFS.find(def => can(def.perm));
      location.hash = fallback ? `#/${fallback.id}` : '';
    }
    route();
  }

  /* ---------- 骨架 / 空状态 ---------- */

  function skeleton(minRows = 4) {
    const rows = [];
    for (let i = 0; i < minRows; i += 1) {
      rows.push(el('div', { class: `skel-row ${i % 3 === 0 ? 'w60' : i % 3 === 1 ? 'w80' : 'w40'}` }));
    }
    return el('div', { class: 'skeleton', 'aria-hidden': 'true' }, rows);
  }

  function emptyState(title, hint) {
    return el('div', { class: 'empty' },
      el('span', { html: icon.empty, 'aria-hidden': 'true' }),
      el('div', { class: 'e-title' }, title),
      hint ? el('div', { class: 'muted' }, hint) : null);
  }

  /* ============================================================
     视图一：运营总览
     ============================================================ */

  function renderDashboardView(container) {
    const statDevices = el('div', { class: 'stat' },
      el('div', { class: 'stat-label' }, '设备总数'),
      el('div', { class: 'stat-value', id: 'db-devices' }, '—'),
      el('div', { class: 'stat-sub', id: 'db-devices-sub' }, '在线 — · 受限 —'));
    const statOrders = el('div', { class: 'stat' },
      el('div', { class: 'stat-label' }, '今日订单'),
      el('div', { class: 'stat-value num', id: 'db-orders' }, '—'),
      el('div', { class: 'stat-sub', id: 'db-orders-sub' }, '今日完成 —'));
    const statRate = el('div', { class: 'stat' },
      el('div', { class: 'stat-label' }, '今日完成率'),
      el('div', { class: 'stat-value green num', id: 'db-rate' }, '—'),
      el('div', { class: 'stat-sub', id: 'db-rate-sub' }, '今日异常 —'));

    const ops = ['manualReviews', 'pendingRefunds', 'pendingBusinessEvents', 'pendingCommands'].map(key => ({
      key,
      label: { manualReviews: '人工复核', pendingRefunds: '待退款', pendingBusinessEvents: '积压业务事件', pendingCommands: '待发命令' }[key],
      id: `db-ops-${key}`,
    })).map(({ label, id }) => el('div', { class: 'ops-chip', id },
      el('span', { class: 'oc-label' }, label),
      el('span', { class: 'oc-value num' }, '—')));

    const recentOrders = el('section', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h3', null, '最近订单'),
        el('span', { class: 'muted' }, can(PERMISSIONS.ordersRead) ? '最近 8 笔' : '需要 orders.read 权限')),
      can(PERMISSIONS.ordersRead)
        ? el('div', { class: 'table-scroll', id: 'db-recent' }, skeleton(4))
        : emptyState('无订单查看权限', '当前角色不包含 orders.read'));

    container.append(
      el('div', { class: 'stat-grid' }, statDevices, statOrders, statRate),
      el('div', { class: 'ops-row' }, ops),
      recentOrders,
    );
    if (!can(PERMISSIONS.dashboard)) {
      clear(container);
      container.append(el('section', { class: 'card' }, emptyState('无总览权限', '当前角色不包含 dashboard.read')));
    }
  }

  async function loadDashboard() {
    if (!can(PERMISSIONS.dashboard)) return;
    const data = await api('/api/v1/admin/dashboard');
    const devices = data.devices || {};
    const orders = data.orders || {};
    const operations = data.operations || {};
    const setText = (id, text) => { const node = $(id); if (node) node.textContent = text; };
    setText('db-devices', String(devices.total ?? '—'));
    setText('db-devices-sub', `在线 ${devices.online ?? '—'} · 受限 ${devices.restricted ?? '—'}`);
    setText('db-orders', String(orders.today ?? '—'));
    setText('db-orders-sub', `今日完成 ${orders.readyToday ?? '—'}`);
    setText('db-rate', fmtPercent(orders.successRate));
    setText('db-rate-sub', `今日异常 ${orders.exceptionsToday ?? '—'}`);
    const opsMap = { manualReviews: 'alert', pendingRefunds: 'alert', pendingBusinessEvents: 'ok', pendingCommands: 'ok' };
    for (const [key, kind] of Object.entries(opsMap)) {
      const chip = $(`db-ops-${key}`);
      if (!chip) continue;
      const value = operations[key];
      chip.className = `ops-chip ${value > 0 && kind === 'alert' ? 'alert' : 'ok'}`;
      chip.lastElementChild.textContent = String(value ?? '—');
    }
    if (can(PERMISSIONS.ordersRead)) {
      const orderData = await api('/api/v1/admin/orders?limit=8');
      renderOrderTable($('db-recent'), (orderData.orders || []).slice(0, 8), { compact: true });
    }
    state.lastRefreshAt = new Date();
  }

  /* ---------- 订单表格（总览 / 订单视图共用） ---------- */

  function renderOrderTable(container, orders, { compact = false, expandable = true } = {}) {
    if (!container) return;
    clear(container);
    if (!orders.length) {
      container.append(emptyState('还没有订单', '设备产生扫码订单后会出现在这里'));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      el('th', null, '订单'),
      el('th', null, '设备'),
      el('th', null, '饮品 / 金额'),
      el('th', null, '状态'),
      el('th', null, '支付'),
      el('th', null, '制作进度'),
      compact ? null : el('th', null, '创建时间'),
    ));
    const tbody = el('tbody');
    for (const order of orders) {
      const progress = Math.round(Math.max(0, Math.min(1, Number(order.progress || 0))) * 100);
      let expandedSlot = null;
      const colspan = compact ? 6 : 7;
      const row = el('tr', { class: expandable ? 'clickable' : '' },
        el('td', null,
          el('div', { class: 'cell-strong mono' }, order.orderNo || order.orderId),
          el('div', { class: 'cell-sub' }, order.paymentMode === 'TEST_FREE' ? '免支付联调' : order.storeId || '')),
        el('td', null,
          el('div', null, order.deviceId || '—'),
          el('div', { class: 'cell-sub' }, order.productName || '')),
        el('td', null, fmtMoney(order.totalAmountMinor, order.currency)),
        el('td', null, orderBadge(order.status)),
        el('td', null, paymentBadge(order.paymentStatus)),
        el('td', null,
          el('div', { class: 'progress-line' },
            el('div', { class: 'progress-track' }, el('div', { class: 'progress-fill', style: `width:${progress}%` })),
            el('small', null, order.currentStepName ? `${order.currentStepName} · ${progress}%` : `${progress}%`))),
        compact ? null : el('td', null, el('span', { class: 'muted' }, fmtTime(order.createdAt))),
      );
      if (expandable) {
        row.addEventListener('click', () => {
          state.expandedOrderId = state.expandedOrderId === order.orderId ? null : order.orderId;
          for (const tr of Array.from(tbody.children)) {
            if (tr.dataset.orderId) tr.classList.toggle('expanded', tr.dataset.orderId === state.expandedOrderId);
          }
          if (expandedSlot) renderOrderDetail(expandedSlot, order);
        });
        row.dataset.orderId = order.orderId;
      }
      tbody.append(row);
      if (expandable && state.expandedOrderId === order.orderId) {
        row.classList.add('expanded');
        expandedSlot = el('td', { colspan: String(colspan) });
        const detailRow = el('tr', { class: 'expanded' }, expandedSlot);
        detailRow.dataset.orderId = order.orderId;
        renderOrderDetail(expandedSlot, order);
        tbody.append(detailRow);
      }
    }
    container.append(el('table', { class: 'grid' }, thead, tbody));
  }

  function renderOrderDetail(slot, order) {
    clear(slot);
    const wrap = el('div', { class: 'order-detail' });
    wrap.append(el('div', { class: 'kv-grid' },
      kv('订单 ID', order.orderId, true),
      kv('制作状态', order.productionStatus || '—'),
      kv('失败代码', order.failureCode || '—', true),
      kv('更新时间', fmtTime(order.updatedAt)),
      kv('人工复核', order.manualReviewRequired ? '需要' : '不需要'),
      kv('HOLD 原因', order.holdReason || '—', true)));
    if (order.failureMessage) {
      wrap.append(el('div', { class: 'fail-line' },
        el('span', { html: icon.alert, 'aria-hidden': 'true' }),
        el('span', null, `失败信息：${order.failureMessage}`)));
    }
    if (order.status === 'HOLD' || order.holdReason) {
      wrap.append(el('div', { class: 'hold-line' },
        el('span', { html: icon.info, 'aria-hidden': 'true' }),
        el('span', null, '该订单处于 HOLD：设备结果待确认，需人工对账后再决定是否退款。')));
    }
    slot.append(wrap);
  }

  /* ============================================================
     视图二：设备管理
     ============================================================ */

  function renderDevicesView(container) {
    const search = el('input', {
      class: 'input', type: 'search', placeholder: '搜索设备 ID、序列号、门店或实例',
      value: state.filters.deviceQuery,
      oninput: () => { state.filters.deviceQuery = search.value; renderDeviceRows(); },
    });
    const connFilter = el('select', { class: 'input', onchange: () => { state.filters.deviceConn = connFilter.value; renderDeviceRows(); } },
      el('option', { value: 'all' }, '全部连接状态'),
      el('option', { value: 'online', selected: state.filters.deviceConn === 'online' }, '在线'),
      el('option', { value: 'offline', selected: state.filters.deviceConn === 'offline' }, '离线'),
      el('option', { value: 'never', selected: state.filters.deviceConn === 'never' }, '从未上线'),
    );

    const toolbar = el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '搜索'), search),
      el('div', { class: 'field' }, el('span', { class: 'field-label' }, '连接状态'), connFilter),
      el('div', { class: 'toolbar-actions' },
        can(PERMISSIONS.devicesManage)
          ? el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>登记设备</span>', onclick: openRegisterModal })
          : null));

    const tableCard = el('section', { class: 'card' },
      el('div', { class: 'table-scroll', id: 'device-rows' }, skeleton(5)));
    const detailCard = el('section', { class: 'card', id: 'device-detail' },
      el('div', { class: 'card-body' },
        emptyState('选择一个设备', '点击左侧列表查看详情、能力、物料与生命周期操作')));

    container.append(toolbar, el('div', { class: 'device-split' }, tableCard, detailCard));
  }

  async function loadDevices() {
    if (!can(PERMISSIONS.devicesRead)) return;
    const data = await api('/api/v1/admin/devices');
    state.devices = Array.isArray(data.devices) ? data.devices : [];
    state.serverTime = data.serverTime || '';
    renderDeviceRows();
    if (state.selectedDeviceId) {
      if (state.devices.some(device => device.deviceId === state.selectedDeviceId)) {
        await loadDeviceDetail(state.selectedDeviceId, { silent: true });
      } else {
        state.selectedDeviceId = '';
        resetDeviceDetail();
      }
    }
    state.lastRefreshAt = new Date();
  }

  function filteredDevices() {
    const query = state.filters.deviceQuery.trim().toLowerCase();
    const mode = state.filters.deviceConn;
    return state.devices.filter(device => {
      const hay = [device.deviceId, device.deviceName, device.serialNumber, device.instanceId, device.storeId, device.storeName, device.cityCode].join(' ').toLowerCase();
      const matchesQuery = !query || hay.includes(query);
      const matchesConn = mode === 'all'
        || (mode === 'online' && device.online)
        || (mode === 'offline' && !device.online && device.hasEverConnected)
        || (mode === 'never' && !device.hasEverConnected);
      return matchesQuery && matchesConn;
    });
  }

  function renderDeviceRows() {
    const container = $('device-rows');
    if (!container) return;
    clear(container);
    const devices = filteredDevices();
    if (!devices.length) {
      container.append(emptyState(
        state.devices.length ? '没有符合筛选条件的设备' : '还没有登记设备',
        state.devices.length ? '调整搜索或筛选条件后重试' : (can(PERMISSIONS.devicesManage) ? '使用「登记设备」接入新终端' : '需要 devices.manage 权限登记设备')));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      el('th', null, '连接'), el('th', null, '设备'), el('th', null, '门店 / 实例'),
      el('th', null, '生命周期'), el('th', null, '活跃订单'), el('th', null, '最近心跳')));
    const tbody = el('tbody');
    for (const device of devices) {
      const row = el('tr', {
        class: `clickable${device.deviceId === state.selectedDeviceId ? ' selected' : ''}`,
        onclick: () => selectDevice(device.deviceId),
      },
        el('td', null, badge(device.online ? 'green' : device.hasEverConnected ? 'red' : 'gray',
          device.online ? '在线' : device.hasEverConnected ? '离线' : '从未上线')),
        el('td', null,
          el('div', { class: 'cell-strong mono' }, device.deviceId),
          el('div', { class: 'cell-sub' }, `序列号 ${device.serialNumber || '—'}`)),
        el('td', null,
          el('div', null, device.storeName || device.storeId || '—'),
          el('div', { class: 'cell-sub' }, `${device.storeId || '无门店 ID'} · ${device.profileComplete ? '资料已完成' : '待首次安装'}`)),
        el('td', null, lifecycleBadge(device.lifecycleStatus)),
        el('td', null, el('span', { class: 'num' }, String(device.activeOrderCount ?? 0))),
        el('td', null,
          el('div', null, fmtAgo(device.lastHeartbeatAt)),
          el('div', { class: 'cell-sub' }, `软件 ${device.softwareVersion || '—'}`)),
      );
      tbody.append(row);
    }
    container.append(el('table', { class: 'grid' }, thead, tbody));
  }

  function resetDeviceDetail() {
    const card = $('device-detail');
    if (!card) return;
    clear(card);
    card.append(el('div', { class: 'card-body' },
      emptyState('选择一个设备', '点击左侧列表查看详情、能力、物料与生命周期操作')));
  }

  async function selectDevice(deviceId) {
    state.selectedDeviceId = deviceId;
    renderDeviceRows();
    await loadDeviceDetail(deviceId);
  }

  function deviceById(deviceId) { return state.devices.find(device => device.deviceId === deviceId); }

  async function loadDeviceDetail(deviceId, { silent = false } = {}) {
    const card = $('device-detail');
    if (!card) return;
    const seq = ++state.detailSeq;
    if (!silent) {
      clear(card);
      card.append(skeleton(6));
    }
    try {
      const [detail, inventory, capabilities] = await Promise.all([
        api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}`),
        api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/inventory`).catch(() => null),
        api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/capabilities`).catch(() => null),
      ]);
      if (seq !== state.detailSeq) return;
      renderDeviceDetail(card, deviceId, { detail, inventory, capabilities });
    } catch (error) {
      if (seq !== state.detailSeq) return;
      clear(card);
      card.append(el('div', { class: 'card-body' },
        el('div', { class: 'form-error' }, `设备详情读取失败：${describeError(error)}`)));
    }
  }

  function renderDeviceDetail(card, deviceId, { detail, inventory, capabilities }) {
    clear(card);
    const head = el('div', { class: 'card-head' },
      el('div', null,
        el('h3', { class: 'mono', style: 'font-size:14px' }, deviceId),
        el('div', { class: 'muted', style: 'font-size:12px' }, `${detail.deviceName || '未命名设备'} · 序列号 ${detail.serialNumber || '—'} · ${detail.storeName || detail.storeId || '待门店安装'}`)),
      el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' },
        badge(detail.online ? 'green' : detail.hasEverConnected ? 'red' : 'gray', detail.online ? '在线' : detail.hasEverConnected ? '离线' : '从未上线'),
        lifecycleBadge(detail.lifecycleStatus)));

    /* 基本信息 */
    const snapshots = detail.snapshots || {};
    const basic = el('div', { class: 'detail-sec' },
      el('h4', null, '基本信息'),
      el('div', { class: 'kv-grid' },
        kv('设备名称', detail.deviceName || '待首次安装'),
        kv('门店', detail.storeName || '待首次安装'),
        kv('地区 / 时区', detail.cityCode && detail.timezone ? `${detail.cityCode} · ${detail.timezone}` : '待首次安装'),
        kv('资料状态', detail.profileComplete ? `已完成 · ${detail.profileSource || '—'}` : '待设备首次安装'),
        kv('实例', detail.instanceId),
        kv('软件版本', detail.softwareVersion),
        kv('活跃启动 ID', detail.activeBootId, true),
        kv('最近序列号', detail.lastSequence),
        kv('心跳 / 事件 / 命令', `${detail.heartbeatCount ?? 0} / ${detail.eventCount ?? 0} / ${detail.commandCount ?? 0}`),
        kv('活跃订单', String(detail.activeOrderCount ?? 0)),
        kv('能力快照', snapshots.capabilities ? `v${snapshots.capabilities.version || '?'} · ${fmtAgo(snapshots.capabilities.receivedAt)}` : '未上报'),
        kv('物料快照', snapshots.inventory ? `v${snapshots.inventory.version || '?'} · ${fmtAgo(snapshots.inventory.receivedAt)}` : '未上报'),
        kv('最近心跳', fmtTime(detail.lastHeartbeatAt)),
        kv('最近错误', detail.lastErrorSummary || '无')),
    );

    /* 能力清单 */
    const recipes = (capabilities && (capabilities.products || capabilities.recipes)) || [];
    const capSec = el('div', { class: 'detail-sec' },
      el('h4', null, '能力清单（设备上报）'),
      recipes.length
        ? el('div', { class: 'recipe-list' }, recipes.map(recipe => el('div', { class: 'recipe-item' },
            el('div', null,
              el('div', { class: 'r-name' }, recipe.name || recipe.recipeId),
              el('div', { class: 'r-meta' }, `${recipe.recipeId || '—'} · v${recipe.version || '?'} · 预计 ${Math.ceil((recipe.estimatedDurationSeconds || 60) / 60)} 分钟`)),
            el('div', { style: 'display:grid;gap:4px;justify-items:end' },
              el('span', { class: 'cell-strong' }, fmtMoney(recipe.priceMinor, recipe.currency || 'CNY')),
              el('span', null, recipe.available === false ? badge('red', '不可售') : badge('green', '可售')))))
          )
        : emptyState('尚未上报能力快照', '设备激活并上报 capabilities 后显示'));

    /* 物料余量 */
    const materials = (inventory && inventory.materials) || [];
    const invSec = el('div', { class: 'detail-sec' },
      el('h4', null, '物料余量（实时快照）'),
      materials.length
        ? el('div', { class: 'material-list' }, materials.map(material => {
            const capacity = Math.max(1, Number(material.capacity || 0));
            const available = Math.max(0, Number(material.available || 0));
            const ratio = Math.min(1, available / capacity);
            const level = material.status === 'CRITICAL' ? 'crit' : material.status === 'LOW' ? 'low' : 'ok';
            return el('div', { class: 'material-item' },
              el('div', { class: 'm-row' },
                el('strong', null, material.name || material.materialId || '物料'),
                badge(level === 'crit' ? 'red' : level === 'low' ? 'amber' : 'green',
                  material.status === 'CRITICAL' ? '危急' : material.status === 'LOW' ? '偏低' : material.status === 'OK' ? '正常' : material.status || '—')),
              el('div', { class: 'material-bar' }, el('i', { class: level, style: `width:${Math.round(ratio * 100)}%` })),
              el('div', { class: 'm-row' },
                el('span', { class: 'muted' }, `${material.materialId || ''}`),
                el('span', { class: 'muted num' }, `${available} / ${capacity} ${material.unit || ''}`)));
          }))
        : emptyState('尚未上报物料快照', '设备上报 inventory 后显示'));

    /* 操作区 */
    const actions = el('div', { class: 'detail-sec' },
      el('h4', null, '运营操作'),
      el('div', { class: 'action-row' },
        can(PERMISSIONS.devicesManage)
          ? el('button', {
              class: 'btn secondary small', type: 'button',
              disabled: detail.lifecycleStatus === 'PENDING',
              title: detail.lifecycleStatus === 'PENDING' ? '待激活设备必须先完成激活' : '',
              onclick: () => openLifecycleModal(deviceId),
            }, detail.lifecycleStatus === 'PENDING' ? '等待设备激活' : '变更生命周期')
          : null,
        can(PERMISSIONS.devicesManage)
          ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => createActivationCode(deviceId) }, '生成激活码')
          : null,
        can(PERMISSIONS.commandsExecute) ? el('span', { class: 'muted', style: 'align-self:center;font-size:12px' }, '远程命令：') : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => sendDeviceCommand(deviceId, 'RELOAD_CONFIG') }, '重载配置')
          : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'btn secondary small', type: 'button', onclick: () => sendDeviceCommand(deviceId, 'SYNC_CONFIG') }, '同步配置')
          : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'btn danger small', type: 'button', onclick: () => confirmRestart(deviceId) }, '重启应用')
          : null,
        !can(PERMISSIONS.devicesManage) && !can(PERMISSIONS.commandsExecute)
          ? el('span', { class: 'muted' }, '当前角色为只读（需要 devices.manage / commands.execute）')
          : null,
      ),
      can(PERMISSIONS.commandsExecute)
        ? el('p', { class: 'field-hint', style: 'margin:8px 0 0' }, '远程命令通过设备命令通道下发；重启会中断进行中的制作，需二次确认。')
        : null,
    );

    card.append(head, basic, capSec, invSec, actions);
  }

  /* ----- 生命周期变更（必须填写原因） ----- */

  function openLifecycleModal(deviceId) {
    const device = deviceById(deviceId) || {};
    const statusSelect = el('select', { class: 'input' },
      el('option', { value: 'ACTIVE', selected: device.lifecycleStatus !== 'SUSPENDED' && device.lifecycleStatus !== 'MAINTENANCE' }, 'ACTIVE · 运行中（恢复接单）'),
      el('option', { value: 'SUSPENDED', selected: device.lifecycleStatus === 'SUSPENDED' }, 'SUSPENDED · 停用（停止派单与售卖）'),
      el('option', { value: 'MAINTENANCE', selected: device.lifecycleStatus === 'MAINTENANCE' }, 'MAINTENANCE · 维护中（暂停派单）'));
    const reason = el('textarea', { class: 'input', placeholder: '填写变更原因（至少 3 个字符），会写入审计日志', maxlength: '500' });
    const error = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '提交变更');
    const modal = openModal({
      title: `变更生命周期 · ${deviceId}`,
      body: [
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '目标状态'), statusSelect),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '变更原因（必填）'), reason, error),
        el('p', { class: 'field-hint' }, 'SUSPENDED / MAINTENANCE 会立即停止向该设备派发新制作任务；已在制作的订单不受影响。'),
      ],
      footer: [
        el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'),
        submit,
      ],
    });
    submit.addEventListener('click', async () => {
      const value = reason.value.trim();
      if (value.length < 3) {
        error.textContent = '原因至少需要 3 个字符';
        reason.focus();
        return;
      }
      submit.disabled = true;
      submit.replaceChildren(el('span', { class: 'spin', 'aria-hidden': 'true' }), '提交中…');
      try {
        await api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/lifecycle`, {
          method: 'PATCH',
          body: JSON.stringify({ status: statusSelect.value, reason: value }),
        });
        modal.close();
        toast(`设备 ${deviceId} 生命周期已更新为 ${statusSelect.value}`, 'success');
        await loadDevices();
      } catch (error2) {
        submit.disabled = false;
        submit.replaceChildren('提交变更');
        error.textContent = describeError(error2);
      }
    });
  }

  /* ----- 激活码（一次性展示） ----- */

  async function createActivationCode(deviceId) {
    const confirmed = await confirmModal({
      title: '生成一次性激活码',
      message: `为设备 ${deviceId} 生成新的激活码？旧激活码保持原有效期，新激活码默认 24 小时内有效。`,
      confirmText: '生成',
    });
    if (!confirmed) return;
    try {
      const result = await api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/activation-codes`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      showSecretModal({
        title: '激活码已生成',
        label: `一次性激活码（${fmtTime(result.expiresAt)} 过期）`,
        secret: result.activationCode,
        note: '激活码只显示这一次。请交给对应的设备安装人员，用于终端激活接口。',
      });
    } catch (error) {
      toast(describeError(error), 'error');
    }
  }

  /* ----- 远程命令（仅安全命令，重启二次确认） ----- */

  const COMMAND_LABELS = {
    RELOAD_CONFIG: '重载配置',
    SYNC_CONFIG: '同步配置',
    RESTART_APP: '重启应用',
  };

  async function sendDeviceCommand(deviceId, type) {
    try {
      const result = await api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/commands`, {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ type }),
      });
      toast(`命令已下发：${COMMAND_LABELS[type] || type}（${result.messageId}）`, 'success');
      loadDevices().catch(() => { });
    } catch (error) {
      toast(describeError(error), 'error');
    }
  }

  async function confirmRestart(deviceId) {
    const first = await confirmModal({
      title: '重启设备应用',
      message: `即将向 ${deviceId} 发送 RESTART_APP。重启会中断进行中的制作，进行中订单可能进入 HOLD 状态等待人工对账。`,
      confirmText: '继续',
      danger: true,
    });
    if (!first) return;
    const second = await confirmModal({
      title: '二次确认',
      message: '请再次确认重启操作。输入「重启」后才会真正下发命令。',
      requireText: '重启',
      confirmText: '确认重启',
      danger: true,
    });
    if (!second) return;
    sendDeviceCommand(deviceId, 'RESTART_APP');
  }

  /* ----- 登记新设备 ----- */

  function openRegisterModal() {
    const deviceIdInput = el('input', { class: 'input mono', placeholder: 'coffee-bot-003（3–6 位编号）', autocomplete: 'off', pattern: '^coffee-bot-[0-9]{3,6}$' });
    const serialInput = el('input', { class: 'input mono', placeholder: 'CB-2026-003', autocomplete: 'off', pattern: '^CB-[0-9]{4}-[0-9]{3,6}$' });
    const instanceInput = el('input', { class: 'input', placeholder: '可选', autocomplete: 'off' });
    const storeInput = el('input', { class: 'input', placeholder: '可选', autocomplete: 'off' });
    const error = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '登记并生成激活码');
    const modal = openModal({
      title: '登记新设备',
      wide: true,
      body: [
        el('p', { class: 'field-hint' }, '先预登记受约束的设备 ID 与出厂序列号，再把一次性激活码交给设备端。门店资料在设备首次安装时补齐；deviceId 格式为 coffee-bot-003，序列号格式为 CB-2026-003。'),
        el('div', { class: 'kv-grid' },
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, 'deviceId *'), deviceIdInput),
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, '序列号 *'), serialInput),
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, 'instanceId'), instanceInput),
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, 'storeId'), storeInput)),
        error,
      ],
      footer: [
        el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'),
        submit,
      ],
    });
    submit.addEventListener('click', async () => {
      const deviceId = deviceIdInput.value.trim();
      const serialNumber = serialInput.value.trim();
      if (!/^coffee-bot-[0-9]{3,6}$/.test(deviceId) || !/^CB-[0-9]{4}-[0-9]{3,6}$/.test(serialNumber)) {
        error.textContent = '请填写受约束的 deviceId（coffee-bot-003）和序列号（CB-2026-003）';
        return;
      }
      submit.disabled = true;
      submit.replaceChildren(el('span', { class: 'spin', 'aria-hidden': 'true' }), '登记中…');
      try {
        const registered = await api('/api/v1/admin/devices', {
          method: 'POST',
          body: JSON.stringify({
            deviceId, serialNumber,
            instanceId: instanceInput.value.trim() || null,
            storeId: storeInput.value.trim() || null,
          }),
        });
        const activation = await api(`/api/v1/admin/devices/${encodeURIComponent(deviceId)}/activation-codes`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
        modal.close();
        if (registered.duplicate) toast('设备已存在，已复用现有记录并生成新激活码', 'info');
        else toast(`设备 ${deviceId} 登记成功`, 'success');
        showSecretModal({
          title: '激活码已生成',
          label: `一次性激活码（${fmtTime(activation.expiresAt)} 过期）`,
          secret: activation.activationCode,
          note: '激活码只显示这一次，请立即复制并交给设备安装人员。',
        });
        await loadDevices();
        selectDevice(deviceId).catch(() => { });
      } catch (error2) {
        submit.disabled = false;
        submit.replaceChildren('登记并生成激活码');
        error.textContent = describeError(error2);
      }
    });
  }

  /* ============================================================
     视图三：订单
     ============================================================ */

  const ORDER_STATUS_OPTIONS = ['', 'CREATED', 'AWAITING_PAYMENT', 'QUEUED', 'DISPATCHED', 'ACCEPTED', 'MAKING', 'HOLD', 'READY', 'FAILED', 'REFUNDED', 'CANCELLED', 'EXPIRED'];

  function renderOrdersView(container) {
    const statusSelect = el('select', { class: 'input', onchange: () => { state.filters.orderStatus = statusSelect.value; loadOrders().catch(() => { }); } },
      ORDER_STATUS_OPTIONS.map(value => el('option', {
        value,
        selected: state.filters.orderStatus === value,
      }, value ? `${ORDER_STATUS[value]?.label || value}（${value}）` : '全部状态')));
    const deviceInput = el('input', {
      class: 'input mono', placeholder: '按 deviceId 过滤', value: state.filters.orderDevice,
      oninput: () => { state.filters.orderDevice = deviceInput.value.trim(); },
      onkeydown: event => { if (event.key === 'Enter') loadOrders().catch(() => { }); },
    });
    container.append(
      el('div', { class: 'card toolbar' },
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '订单状态'), statusSelect),
        el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '设备'), deviceInput),
        el('div', { class: 'toolbar-actions' },
          el('button', { class: 'btn secondary small', type: 'button', html: icon.refresh + '<span>查询</span>', onclick: () => loadOrders().catch(() => { }) }))),
      el('section', { class: 'card' },
        el('div', { class: 'table-scroll', id: 'order-rows' }, skeleton(6))),
    );
  }

  async function loadOrders() {
    if (!can(PERMISSIONS.ordersRead)) return;
    const container = $('order-rows');
    const params = new URLSearchParams({ limit: '100' });
    if (state.filters.orderStatus) params.set('status', state.filters.orderStatus);
    if (state.filters.orderDevice) params.set('deviceId', state.filters.orderDevice);
    const data = await api(`/api/v1/admin/orders?${params.toString()}`);
    const orders = Array.isArray(data.orders) ? data.orders : [];
    if (container) renderOrderTable(container, orders);
    state.lastRefreshAt = new Date();
  }

  /* ============================================================
     视图四：权限（运营员 / 角色 / Token）
     ============================================================ */

  function renderAccessView(container) {
    const toolbar = el('div', { class: 'card toolbar' },
      el('div', { class: 'field grow' },
        el('span', { class: 'field-label' }, '运营员'),
        el('span', { class: 'field-hint' }, '角色决定权限集合；Token 只在创建时显示一次。')),
      el('div', { class: 'toolbar-actions' },
        can(PERMISSIONS.accessManage)
          ? el('button', { class: 'btn primary small', type: 'button', html: icon.plus + '<span>新建运营员</span>', onclick: openCreateOperatorModal })
          : el('span', { class: 'muted' }, '只读模式（需要 access.manage 才能编辑）')));
    container.append(toolbar,
      el('section', { class: 'card' },
        el('div', { class: 'table-scroll', id: 'operator-rows' }, skeleton(4))));
  }

  async function loadOperators() {
    if (!can(PERMISSIONS.accessRead)) return;
    const container = $('operator-rows');
    const data = await api('/api/v1/admin/operators');
    state.operators = Array.isArray(data.operators) ? data.operators : [];
    if (container) renderOperators(container);
    state.lastRefreshAt = new Date();
  }

  function renderOperators(container) {
    clear(container);
    if (!state.operators.length) {
      container.append(emptyState('还没有运营员', can(PERMISSIONS.accessManage) ? '使用「新建运营员」创建第一个账号' : '需要 OWNER 创建运营员'));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      el('th', null, '运营员'), el('th', null, '角色'), el('th', null, '状态'),
      el('th', null, '有效 Token'), el('th', null, '最近使用'), el('th', null, '操作')));
    const tbody = el('tbody');
    for (const operator of state.operators) {
      const row = el('tr', { class: 'clickable' },
        el('td', null,
          el('div', { class: 'cell-strong' }, operator.displayName),
          el('div', { class: 'cell-sub mono' }, operator.operatorId)),
        el('td', null, badge(operator.role === 'OWNER' ? 'blue' : operator.role === 'MANAGER' ? 'green' : 'gray', operator.role)),
        el('td', null, badge(operator.status === 'ACTIVE' ? 'green' : 'red', operator.status === 'ACTIVE' ? '启用' : '停用')),
        el('td', null, el('span', { class: 'num' }, String(operator.activeTokenCount ?? 0))),
        el('td', null, el('span', { class: 'muted' }, fmtAgo(operator.lastUsedAt))),
        el('td', null,
          can(PERMISSIONS.accessManage)
            ? el('button', { class: 'btn secondary small', type: 'button', onclick: event => { event.stopPropagation(); openEditOperatorModal(operator); } }, '编辑')
            : el('span', { class: 'muted' }, '只读')),
      );
      row.addEventListener('click', () => {
        state.expandedOperatorId = state.expandedOperatorId === operator.operatorId ? null : operator.operatorId;
        renderOperators(container);
      });
      tbody.append(row);
      if (state.expandedOperatorId === operator.operatorId) {
        row.classList.add('selected');
        const slot = el('td', { colspan: '6' });
        const detailRow = el('tr', { class: 'expanded' }, slot);
        renderOperatorTokens(slot, operator);
        tbody.append(detailRow);
      }
    }
    container.append(el('table', { class: 'grid' }, thead, tbody));
  }

  function renderOperatorTokens(slot, operator) {
    clear(slot);
    const wrap = el('div', { class: 'order-detail', id: `tokens-${operator.operatorId}` },
      el('p', { class: 'muted', style: 'font-size:12.5px;margin:10px 0 4px' }, '加载 Token 列表…'));
    slot.append(wrap);
    api(`/api/v1/admin/operators/${encodeURIComponent(operator.operatorId)}/tokens`)
      .then(data => {
        const list = Array.isArray(data.tokens) ? data.tokens : [];
        clear(wrap);
        const tokenRows = list.length
          ? list.map(token => el('tr', null,
              el('td', null, el('span', { class: 'cell-strong' }, token.label || '—'), el('div', { class: 'cell-sub mono' }, token.tokenId)),
              el('td', null, badge(token.status === 'ACTIVE' ? 'green' : token.status === 'REVOKED' ? 'red' : 'gray',
                token.status === 'ACTIVE' ? '有效' : token.status === 'REVOKED' ? '已撤销' : token.status)),
              el('td', null, token.expiresAt ? fmtTime(token.expiresAt) : '永不'),
              el('td', null, el('span', { class: 'muted' }, fmtAgo(token.lastUsedAt))),
              el('td', null, el('span', { class: 'muted' }, fmtTime(token.createdAt))),
              el('td', null,
                can(PERMISSIONS.accessManage) && token.status === 'ACTIVE'
                  ? el('button', {
                      class: 'btn danger small', type: 'button',
                      onclick: () => revokeToken(operator, token),
                    }, '撤销')
                  : el('span', { class: 'muted' }, '—')),
            ))
          : [el('tr', null, el('td', { colspan: '6' }, emptyState('还没有 Token', '为该运营员创建 API Token 后用于登录运营台')))];
        const tokenTable = el('table', { class: 'grid', style: 'min-width:640px;margin-top:10px' },
          el('thead', null, el('tr', null,
            el('th', null, '标签'), el('th', null, '状态'), el('th', null, '过期时间'),
            el('th', null, '最近使用'), el('th', null, '创建时间'), el('th', null, '操作'))),
          el('tbody', null, tokenRows));
        const section = el('div', { style: 'display:grid;gap:4px' },
          el('h4', { style: 'font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-top:10px' }, `API Token · ${operator.displayName}`),
          tokenTable);
        if (can(PERMISSIONS.accessManage)) {
          const label = el('input', { class: 'input', placeholder: 'Token 标签，例如「值班平板」', maxlength: '120' });
          const expires = el('input', { class: 'input', type: 'datetime-local' });
          const createBtn = el('button', {
            class: 'btn primary small', type: 'button',
            onclick: async () => {
              const labelValue = label.value.trim();
              if (!labelValue) { toast('请填写 Token 标签', 'error'); label.focus(); return; }
              createBtn.disabled = true;
              try {
                const body = { label: labelValue };
                if (expires.value) {
                  const ms = Date.parse(expires.value);
                  if (Number.isFinite(ms)) body.expiresAt = new Date(ms).toISOString();
                }
                const created = await api(`/api/v1/admin/operators/${encodeURIComponent(operator.operatorId)}/tokens`, {
                  method: 'POST',
                  body: JSON.stringify(body),
                });
                showSecretModal({
                  title: '新运营 Token 已创建',
                  label: `Token「${created.label}」${created.expiresAt ? ` · ${fmtTime(created.expiresAt)} 过期` : ' · 永不过期'}`,
                  secret: created.token,
                  note: '完整 Token 只显示这一次，云端只保存 SHA-256 摘要。请立即复制到密码管理器。',
                });
                label.value = '';
                expires.value = '';
                loadOperators().catch(() => { });
              } catch (error) {
                toast(describeError(error), 'error');
              } finally {
                createBtn.disabled = false;
              }
            },
          },
          el('span', { html: icon.plus, 'aria-hidden': 'true' }),
          el('span', null, '创建 Token'));
          section.append(el('div', { class: 'toolbar', style: 'border:1px solid var(--line);border-radius:12px;margin-top:10px' },
            el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, '新 Token 标签 *'), label),
            el('div', { class: 'field' }, el('span', { class: 'field-label' }, '过期时间（可选）'), expires),
            el('div', { class: 'toolbar-actions', style: 'align-self:end' }, createBtn)));
        }
        wrap.append(section);
      })
      .catch(error => {
        clear(wrap);
        wrap.append(el('p', { class: 'form-error' }, `Token 列表读取失败：${describeError(error)}`));
      });
  }

  async function revokeToken(operator, token) {
    const confirmed = await confirmModal({
      title: '撤销 Token',
      message: `撤销「${token.label || token.tokenId}」？使用该 Token 的会话将立即失效，且无法恢复。`,
      confirmText: '撤销',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api(`/api/v1/admin/operators/${encodeURIComponent(operator.operatorId)}/tokens/${encodeURIComponent(token.tokenId)}`, { method: 'DELETE' });
      toast('Token 已撤销', 'success');
      loadOperators().catch(() => { });
    } catch (error) {
      toast(describeError(error), 'error');
    }
  }

  function openCreateOperatorModal() {
    const availableRoles = (state.principal && state.principal.availableRoles) || [];
    const nameInput = el('input', { class: 'input', placeholder: '运营员名称，例如「张三 / 值班组」', maxlength: '120' });
    const roleSelect = el('select', { class: 'input' },
      availableRoles.length
        ? availableRoles.map(role => el('option', { value: role.role }, `${role.role} · ${role.permissions.length} 项权限`))
        : ['VIEWER', 'OPERATOR', 'MANAGER', 'OWNER'].map(role => el('option', { value: role }, role)));
    const permPreview = el('div', { class: 'perm-list' });
    const syncPreview = () => {
      clear(permPreview);
      const role = availableRoles.find(item => item.role === roleSelect.value);
      for (const permission of role ? role.permissions : []) permPreview.append(el('span', { class: 'perm-tag' }, permission));
    };
    roleSelect.addEventListener('change', syncPreview);
    syncPreview();
    const error = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '创建运营员');
    const modal = openModal({
      title: '新建运营员',
      body: [
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '名称 *'), nameInput),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '角色'), roleSelect),
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '该角色权限'), permPreview),
        error,
      ],
      footer: [
        el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'),
        submit,
      ],
    });
    submit.addEventListener('click', async () => {
      const displayName = nameInput.value.trim();
      if (!displayName) { error.textContent = '请填写运营员名称'; nameInput.focus(); return; }
      submit.disabled = true;
      try {
        await api('/api/v1/admin/operators', {
          method: 'POST',
          body: JSON.stringify({ displayName, role: roleSelect.value }),
        });
        modal.close();
        toast('运营员已创建，可为该账号签发 Token', 'success');
        await loadOperators();
      } catch (error2) {
        submit.disabled = false;
        error.textContent = describeError(error2);
      }
    });
  }

  function openEditOperatorModal(operator) {
    const nameInput = el('input', { class: 'input', value: operator.displayName || '', maxlength: '120' });
    const roleSelect = el('select', { class: 'input' },
      ((state.principal && state.principal.availableRoles) || []).map(role =>
        el('option', { value: role.role, selected: operator.role === role.role }, role.role)));
    const statusSelect = el('select', { class: 'input' },
      el('option', { value: 'ACTIVE', selected: operator.status === 'ACTIVE' }, 'ACTIVE · 启用'),
      el('option', { value: 'SUSPENDED', selected: operator.status === 'SUSPENDED' }, 'SUSPENDED · 停用'));
    const error = el('p', { class: 'form-error', role: 'alert' });
    const submit = el('button', { class: 'btn primary', type: 'button' }, '保存修改');
    const modal = openModal({
      title: `编辑运营员 · ${operator.displayName}`,
      body: [
        el('div', { class: 'field' }, el('span', { class: 'field-label' }, '名称'), nameInput),
        el('div', { class: 'kv-grid' },
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, '角色'), roleSelect),
          el('div', { class: 'field' }, el('span', { class: 'field-label' }, '状态'), statusSelect)),
        el('p', { class: 'field-hint' }, '停用后该运营员全部 Token 立即失效；变更会写入审计日志。'),
        error,
      ],
      footer: [
        el('button', { class: 'btn secondary', type: 'button', onclick: () => modal.close() }, '取消'),
        submit,
      ],
    });
    submit.addEventListener('click', async () => {
      const displayName = nameInput.value.trim();
      if (!displayName) { error.textContent = '名称不能为空'; nameInput.focus(); return; }
      submit.disabled = true;
      try {
        await api(`/api/v1/admin/operators/${encodeURIComponent(operator.operatorId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ displayName, role: roleSelect.value, status: statusSelect.value }),
        });
        modal.close();
        toast('运营员已更新', 'success');
        await loadOperators();
      } catch (error2) {
        submit.disabled = false;
        error.textContent = describeError(error2);
      }
    });
  }

  /* ============================================================
     视图五：审计日志
     ============================================================ */

  function renderAuditView(container) {
    const actionInput = el('input', { class: 'input mono', placeholder: '例如 device.lifecycle.update', value: state.filters.auditAction });
    const resourceInput = el('input', { class: 'input mono', placeholder: '例如 terminal', value: state.filters.auditResource });
    const apply = () => {
      state.filters.auditAction = actionInput.value.trim();
      state.filters.auditResource = resourceInput.value.trim();
      loadAuditLogs().catch(() => { });
    };
    actionInput.addEventListener('keydown', event => { if (event.key === 'Enter') apply(); });
    resourceInput.addEventListener('keydown', event => { if (event.key === 'Enter') apply(); });
    container.append(
      el('div', { class: 'card toolbar' },
        el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, 'action'), actionInput),
        el('div', { class: 'field grow' }, el('span', { class: 'field-label' }, 'resourceType'), resourceInput),
        el('div', { class: 'toolbar-actions', style: 'align-self:end' },
          el('button', { class: 'btn secondary small', type: 'button', html: icon.refresh + '<span>查询</span>', onclick: apply }))),
      el('section', { class: 'card' },
        el('div', { class: 'table-scroll', id: 'audit-rows' }, skeleton(6))),
    );
  }

  async function loadAuditLogs() {
    if (!can(PERMISSIONS.auditRead)) return;
    const container = $('audit-rows');
    const params = new URLSearchParams({ limit: '200' });
    if (state.filters.auditAction) params.set('action', state.filters.auditAction);
    if (state.filters.auditResource) params.set('resourceType', state.filters.auditResource);
    const data = await api(`/api/v1/admin/audit-logs?${params.toString()}`);
    const logs = Array.isArray(data.auditLogs) ? data.auditLogs : [];
    if (!container) return;
    clear(container);
    if (!logs.length) {
      container.append(emptyState('没有符合条件的审计记录', '调整 action / resourceType 后重试'));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      el('th', null, '时间'), el('th', null, '操作者'), el('th', null, '动作'),
      el('th', null, '资源'), el('th', null, '请求 ID')));
    const tbody = el('tbody');
    for (const log of logs) {
      const row = el('tr', { class: 'clickable' },
        el('td', null, el('span', { class: 'muted' }, fmtTime(log.createdAt))),
        el('td', null,
          el('div', { class: 'cell-strong' }, log.actorName || log.actorId || '—'),
          el('div', { class: 'cell-sub' }, `${log.actorType || ''}${log.actorId ? ' · ' + log.actorId : ''}`)),
        el('td', null, el('code', { class: 'mono' }, log.action || '—')),
        el('td', null,
          el('div', null, log.resourceType || '—'),
          el('div', { class: 'cell-sub mono' }, log.resourceId || '')),
        el('td', null, el('span', { class: 'muted mono' }, log.requestId || '—')),
      );
      row.addEventListener('click', () => showAuditDetail(log));
      tbody.append(row);
    }
    container.append(el('table', { class: 'grid' }, thead, tbody));
    state.lastRefreshAt = new Date();
  }

  function showAuditDetail(log) {
    const body = el('div', { class: 'audit-detail' },
      el('div', { class: 'kv-grid' },
        kv('时间', fmtTime(log.createdAt)),
        kv('操作者', `${log.actorName || '—'}（${log.actorType || '—'}）`),
        kv('动作', log.action, true),
        kv('资源', `${log.resourceType || '—'} ${log.resourceId || ''}`, true),
        kv('请求 ID', log.requestId, true)),
      el('div', { class: 'field', style: 'margin-top:4px' },
        el('span', { class: 'field-label' }, '详情'),
        el('pre', null, JSON.stringify(log.detail ?? {}, null, 2))));
    const modal = openModal({ title: '审计记录', body, wide: true });
    const closeBtn = el('button', { class: 'btn secondary', type: 'button' }, '关闭');
    closeBtn.addEventListener('click', () => modal.close());
    modal.card.append(el('div', { class: 'modal-foot' }, closeBtn));
  }

  /* ---------- 事件绑定与启动 ---------- */

  $('login-form').addEventListener('submit', handleLogin);
  $('logout-btn').addEventListener('click', logout);
  $('refresh-btn').addEventListener('click', refreshNow);
  window.addEventListener('hashchange', () => { if (state.token) route(); });
})();
