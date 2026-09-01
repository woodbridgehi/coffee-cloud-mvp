/* ============================================================
   Coffee Cloud · 设备运营台（无框架实现，ES Module）
   - Token 仅保存在页面内存变量中，不写 localStorage /
     sessionStorage / cookie / URL，也不输出到 console。
   - 登录后先请求 GET /api/v1/admin/session，按 permissions
     控制导航与操作可见性。
   - API 数据一律走 textContent / createElement；innerHTML 仅
     用于不含任何 API 数据的静态 SVG 图标（cc-icons.js）。
   - 纯展示函数抽到 admin-format.js（可被 Node 回归测试导入）。
   - 视觉体系：shared/coffee-ui.css（Open Design cc-* 组件系统，
     body[data-shell="admin"] 绑定 espresso 主操作色）。
   ============================================================ */
import { fmtMoney, fmtTime, fmtAgo, fmtPercent } from './admin-format.js';

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

  const svgIcon = (name, size = 17) => (typeof globalThis.ccIcon === 'function' ? globalThis.ccIcon(name, size) : '');
  const SPINNER = '<svg class="cc-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';

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

  function clear(node) { node.replaceChildren(); }

  /* 状态 → cc 组件变体（流程态 cc-status / 分类态 cc-tag） */
  const STATUS_VARIANT = { green: 'success', amber: 'warning', red: 'error', blue: 'info', gray: 'neutral' };
  const TAG_VARIANT = { green: 'green', amber: 'yellow', red: 'pink', blue: 'blue', gray: '' };

  function statusPill(kind, label) {
    return el('span', { class: `cc-status cc-status--${STATUS_VARIANT[kind] || 'neutral'}` }, label);
  }

  function tagPill(kind, label) {
    const variant = TAG_VARIANT[kind] || '';
    return el('span', { class: `cc-tag${variant ? ` cc-tag--${variant}` : ''}` }, label);
  }

  function kv(label, value, mono) {
    return el('div', { class: 'cc-kv-item' },
      el('dt', null, label),
      el('dd', { class: mono ? 'u-mono' : null }, value === null || value === undefined || value === '' ? '—' : String(value)));
  }

  /* 表格单元格：data-label 供辅助技术与窄屏展示列名；
     cls 含 num 时金额 / 数量列右对齐（与 th 的 cc-money 对应）。 */
  function td(content, label, cls) {
    const numeric = Boolean(cls && cls.split(/\s+/).includes('num'));
    return el('td', { 'data-label': label, class: numeric ? 'cc-money' : (cls || null) }, content);
  }

  /* 计数字段缺失时显示「—」，不默认成 0 */
  function fmtCount(value) {
    return value === null || value === undefined ? '—' : String(value);
  }

  /* 表单行：<label for> 与控件关联，保证可访问名称 */
  let fieldSeq = 0;
  function field(labelText, control, cls, ...extra) {
    const id = control.id || `admin-field-${++fieldSeq}`;
    if (!control.id) control.id = id;
    return el('div', { class: `cc-field${cls ? ' ' + cls : ''}` },
      el('label', { class: 'cc-label', for: id }, labelText),
      control, ...extra);
  }

  /* 键盘行激活 + 跨重渲染保持焦点（自动刷新会整体重建表格行） */
  function rowActivate(row, handler) {
    row.tabIndex = 0;
    row.addEventListener('keydown', event => {
      // Nested controls retain their native Enter/Space behavior.
      if (event.target !== row || event.repeat) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        handler();
      }
    });
  }

  function captureRowFocus() {
    const active = document.activeElement;
    return active && active.tagName === 'TR' ? String(active.dataset.rowKey || '') : '';
  }

  function restoreRowFocus(container, key) {
    if (!key) return;
    const next = container.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
    if (next) next.focus({ preventScroll: true });
  }

  function th(label, cls) {
    const numeric = Boolean(cls && cls.split(/\s+/).includes('num'));
    return el('th', { scope: 'col', class: numeric ? 'cc-money' : (cls || null) }, label);
  }

  /* 视图标题行（cc-titlebar） */
  function viewHead(title, desc, actions) {
    return el('div', { class: 'cc-titlebar' },
      el('div', null,
        el('h1', { class: 'cc-h1' }, title),
        desc ? el('div', { class: 'cc-title-desc' }, desc) : null),
      actions ? el('div', { class: 'cc-title-actions' }, actions) : null);
  }

  /* 内容分节（设备 / 订单详情） */
  function sec(title, ...children) {
    return el('div', { class: 'cc-stack', style: 'gap:12px' },
      el('h4', { class: 'cc-h4' }, title),
      ...children);
  }

  /* ---------- 展示辅助（纯函数在 admin-format.js，可回归测试） ---------- */

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
    return statusPill(meta.kind, meta.label);
  }

  function paymentBadge(status) {
    const meta = PAYMENT_STATUS[status] || { label: status || '—', kind: 'gray' };
    return statusPill(meta.kind, meta.label);
  }

  function lifecycleBadge(status) {
    const meta = LIFECYCLE[status] || { label: status || '—', kind: 'gray' };
    return tagPill(meta.kind, meta.label);
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

  /* ---------- Toast（cc-toast） ---------- */

  function toast(message, kind = 'info') {
    const root = $('toast-root');
    if (!root) return;
    const iconName = kind === 'success' ? 'check' : kind === 'error' ? 'alert-circle' : 'info';
    const node = el('div', {
      class: `cc-toast${kind ? ` cc-toast--${kind}` : ''}`,
      role: kind === 'error' ? 'alert' : 'status',
      onclick: () => node.remove(),
    },
      el('span', { html: svgIcon(iconName, 16), 'aria-hidden': 'true' }),
      el('span', null, message),
      el('button', {
        class: 'cc-toast-close', type: 'button', 'aria-label': '关闭提示',
        onclick: event => { event.stopPropagation(); node.remove(); },
        html: svgIcon('close', 16),
      }));
    root.append(node);
    setTimeout(() => node.remove(), 4600);
    while (root.children.length > 3) root.firstElementChild.remove();
  }

  /* ---------- 弹窗（cc-dialog：焦点圈定 + Escape + 焦点归还） ---------- */

  let activeModal = null;

  function modalOpen() { return activeModal !== null; }

  const MODAL_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function openModal({ title, body, footer, wide, size, dismissible = true }) {
    closeModal();
    const root = $('modal-root');
    const lastActive = document.activeElement;
    const handle = { root, card: null, onClose: null, lastActive };
    const close = () => {
      if (!activeModal || activeModal.root !== root) return;
      activeModal = null;
      root.classList.add('hidden');
      root.classList.remove('is-open');
      root.setAttribute('aria-hidden', 'true');
      root.onclick = null;
      clear(root);
      if (handle.onClose) handle.onClose();
      /* 关闭后把焦点还给触发元素（若仍在文档中） */
      const previous = handle.lastActive;
      if (previous && previous.isConnected && typeof previous.focus === 'function') {
        previous.focus({ preventScroll: true });
      }
    };
    const widthClass = size ? `cc-dialog--${size}` : wide ? 'cc-dialog--720' : 'cc-dialog--520';
    const card = el('div', { class: `cc-dialog ${widthClass}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
    card.append(
      el('div', { class: 'cc-dialog-head' },
        el('div', { class: 'cc-dialog-title' }, title),
        dismissible ? el('button', {
          class: 'cc-btn cc-btn--icon cc-layer-close', type: 'button', 'aria-label': '关闭',
          html: svgIcon('close', 20), onclick: close,
        }) : null),
      el('div', { class: 'cc-dialog-body' }, body),
      footer ? el('div', { class: 'cc-dialog-foot' }, footer) : null,
    );
    card.addEventListener('click', event => event.stopPropagation());
    root.classList.remove('hidden');
    root.classList.add('is-open');
    root.setAttribute('aria-hidden', 'false');
    root.replaceChildren(card);
    root.onclick = dismissible ? close : () => {};
    handle.card = card;
    activeModal = handle;
    const focusable = card.querySelector('input, select, textarea, button:not(.cc-layer-close)') || card.querySelector('button');
    if (focusable) focusable.focus({ preventScroll: true });
    return { ...handle, close, card };
  }

  function closeModal() {
    if (activeModal) activeModal.root.onclick = null;
    const root = $('modal-root');
    root.classList.add('hidden');
    root.classList.remove('is-open');
    root.setAttribute('aria-hidden', 'true');
    clear(root);
    activeModal = null;
  }

  document.addEventListener('keydown', event => {
    if (!activeModal) return;
    if (event.key === 'Escape') {
      $('modal-root').onclick?.();
      return;
    }
    /* Tab 焦点圈定：焦点始终留在弹窗内 */
    if (event.key !== 'Tab' || !activeModal.card) return;
    const focusables = Array.from(activeModal.card.querySelectorAll(MODAL_FOCUSABLE))
      .filter(node => node.getClientRects().length > 0);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;
    if (!activeModal.card.contains(current)) { event.preventDefault(); first.focus(); return; }
    if (event.shiftKey && current === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && current === last) { event.preventDefault(); first.focus(); }
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
        input = el('input', { class: 'cc-input', placeholder: `输入“${requireText}”以确认`, autocomplete: 'off' });
        input.addEventListener('input', () => { confirmBtn.disabled = input.value.trim() !== requireText; });
        body.push(field('请输入确认文字', input));
      }
      const done = result => { modal.close(); resolve(result); };
      confirmBtn = el('button', {
        class: `cc-btn ${danger ? 'cc-btn--danger' : 'cc-btn--primary'}`,
        type: 'button',
        disabled: Boolean(requireText),
        onclick: () => done(true),
      }, confirmText);
      const modal = openModal({
        title, body, size: '440',
        footer: [
          el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: () => done(false) }, cancelText),
          confirmBtn,
        ],
      });
    });
  }

  /* 一次性秘密展示（激活码 / 新运营 Token）：暗色控制台域，关闭后不再出现 */
  function showSecretModal({ title, label, secret, note }) {
    let codeNode = null;
    const copyBtn = el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm cc-copybtn', type: 'button' },
      el('span', { html: svgIcon('copy', 16), 'aria-hidden': 'true' }), '复制');
    const modal = openModal({
      title, size: '560',
      body: [
        el('div', { class: 'cc-secret' },
          el('code', null, secret),
          copyBtn),
        el('div', { class: 'cc-caption', style: 'margin-top:6px' }, label),
        el('div', { class: `cc-alert cc-alert--warning`, style: 'margin-top:12px' },
          el('span', { html: svgIcon('alert-triangle', 16), 'aria-hidden': 'true' }),
          el('div', { class: 'cc-alert-body' }, el('div', { class: 'cc-alert-desc' }, note || '该内容只显示这一次，云端只保存摘要。请立即复制并妥善保管。'))),
      ],
      footer: [el('button', { class: 'cc-btn cc-btn--primary', type: 'button', onclick: () => modal.close() }, '我已安全保存')],
    });
    codeNode = modal.card.querySelector('.cc-secret code');
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
    btn.replaceChildren(busy ? el('span', { html: SPINNER, 'aria-hidden': 'true' }) : null, busy ? '正在验证…' : '登录');
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
    $('bottom-nav')?.classList.add('hidden');
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
      el('span', null, `${state.principal.role || ''} · ${state.principal.tokenLabel || 'session'}`),
    );
  }

  /* ---------- 导航 ---------- */

  const VIEW_DEFS = [
    { id: 'dashboard', label: '运营总览', title: '运营总览', sub: '设备、订单与运营积压的实时快照', perm: PERMISSIONS.dashboard, iconName: 'dashboard' },
    { id: 'devices', label: '设备', title: '设备管理', sub: '终端连接、生命周期、能力与物料', perm: PERMISSIONS.devicesRead, iconName: 'device' },
    { id: 'orders', label: '订单', title: '订单', sub: '支付、制作进度与异常处理', perm: PERMISSIONS.ordersRead, iconName: 'orders' },
    { id: 'access', label: '权限', title: '权限', sub: '运营员、角色与 API Token', perm: PERMISSIONS.accessRead, iconName: 'shield' },
    { id: 'audit', label: '审计', title: '审计日志', sub: '操作者、动作与资源记录', perm: PERMISSIONS.auditRead, iconName: 'audit' },
  ];

  function buildNav() {
    const nav = $('side-nav');
    clear(nav);
    const group = el('div', { class: 'cc-navgroup' },
      el('div', { class: 'cc-navgroup-title' }, '平台运维'));
    for (const def of VIEW_DEFS) {
      if (!can(def.perm)) continue;
      group.append(el('button', {
        class: 'cc-navitem',
        type: 'button',
        title: def.label,
        'aria-current': state.view === def.id ? 'page' : null,
        onclick: () => { location.hash = `#/${def.id}`; },
      },
        el('span', { class: 'n-icon', html: svgIcon(def.iconName, 20), 'aria-hidden': 'true' }),
        el('span', { class: 'cc-nav-label' }, def.label)));
    }
    if (group.querySelector('.cc-navitem')) nav.append(group);
    buildBottomNav();
  }

  /* Mobile 底部导航：视图数量 ≤5，全部纳入；账号与退出在侧栏底部 */
  function buildBottomNav() {
    const bar = $('bottom-nav');
    if (!bar) return;
    clear(bar);
    const defs = VIEW_DEFS.filter(def => can(def.perm));
    if (!state.token || !defs.length) {
      bar.classList.add('hidden');
      return;
    }
    const grid = el('div', { class: 'cc-bottomnav-grid' }, defs.map(def => el('button', {
      type: 'button',
      'aria-current': state.view === def.id ? 'page' : null,
      onclick: () => { location.hash = `#/${def.id}`; },
    },
      el('span', { html: svgIcon(def.iconName, 20), 'aria-hidden': 'true' }),
      el('span', null, def.label))));
    bar.append(grid);
    bar.classList.remove('hidden');
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
    buildNav();
    const workspace = $('workspace');
    clear(workspace);
    ({...{
      dashboard: renderDashboardView,
      devices: renderDevicesView,
      orders: renderOrdersView,
      access: renderAccessView,
      audit: renderAuditView,
    }})[state.view](workspace);
    refreshNow();
  }

  function renderNoAccess() {
    const workspace = $('workspace');
    clear(workspace);
    buildNav();
    workspace.append(el('section', { class: 'cc-card' },
      el('div', { class: 'cc-empty' },
        el('span', { html: svgIcon('shield', 40), 'aria-hidden': 'true' }),
        el('div', { class: 'cc-empty-title' }, '当前账号没有任何可访问的视图'),
        el('div', { class: 'cc-empty-desc' }, '请联系 OWNER 为该账号分配角色，或使用其他 Token 登录。'))));
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
      rows.push(el('div', { class: `m-skel-row ${i % 3 === 0 ? 'w60' : i % 3 === 1 ? 'w80' : 'w40'}` }));
    }
    return el('div', { class: 'm-skel', 'aria-hidden': 'true', role: 'status' }, rows);
  }

  function emptyState(title, hint) {
    return el('div', { class: 'cc-empty' },
      el('span', { html: svgIcon('coffee', 40), 'aria-hidden': 'true' }),
      el('div', { class: 'cc-empty-title' }, title),
      hint ? el('div', { class: 'cc-empty-desc' }, hint) : null);
  }

  /* ============================================================
     视图一：运营总览（a03）
     ============================================================ */

  function metricCard(label, { id, subId, valueKind } = {}) {
    return el('div', { class: 'cc-metric' },
      el('div', { class: 'cc-metric-label' }, label),
      el('div', { class: `cc-metric-value u-num${valueKind ? ` ${valueKind}` : ''}`, id }, '—'),
      el('div', { class: 'cc-metric-note', id: subId }, '—'));
  }

  function renderDashboardView(container) {
    const opsDefs = [
      ['manualReviews', '人工复核'], ['pendingRefunds', '待退款'],
      ['pendingBusinessEvents', '积压业务事件'], ['pendingCommands', '待发命令'],
    ];
    const ops = el('div', { class: 'm-opsrow' }, opsDefs.map(([key, label]) => el('div', { class: 'm-opschip', id: `db-ops-${key}` },
      el('span', null, label),
      el('span', { class: 'm-ops-value num' }, '—'))));

    const recentOrders = el('section', { class: 'cc-section' },
      el('div', { class: 'cc-section-head' },
        el('h2', { class: 'cc-h3' }, '最近订单'),
        el('span', { class: 'cc-caption' }, can(PERMISSIONS.ordersRead) ? '最近 8 笔' : '需要 orders.read 权限')),
      can(PERMISSIONS.ordersRead)
        ? el('div', { id: 'db-recent' }, skeleton(4))
        : el('div', { class: 'cc-tablewrap' }, emptyState('无订单查看权限', '当前角色不包含 orders.read')));

    container.append(
      viewHead('运营总览', '设备、订单与运营积压的实时快照；每 10 秒自动刷新。'),
      el('div', { class: 'cc-card' },
        el('div', { class: 'cc-metricgrid' },
          metricCard('设备总数', { id: 'db-devices', subId: 'db-devices-sub' }),
          metricCard('今日订单', { id: 'db-orders', subId: 'db-orders-sub' }),
          metricCard('今日完成率', { id: 'db-rate', subId: 'db-rate-sub', valueKind: 'm-green' })),
        ops),
      recentOrders,
    );
    if (!can(PERMISSIONS.dashboard)) {
      clear(container);
      container.append(viewHead('运营总览', '设备、订单与运营积压的实时快照。'),
        el('section', { class: 'cc-card' }, emptyState('无总览权限', '当前角色不包含 dashboard.read')));
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
      chip.className = `m-opschip${value > 0 && kind === 'alert' ? ' is-alert' : ''}`;
      chip.lastElementChild.textContent = String(value ?? '—');
    }
    if (can(PERMISSIONS.ordersRead)) {
      const orderData = await api('/api/v1/admin/orders?limit=8');
      renderOrderTable($('db-recent'), (orderData.orders || []).slice(0, 8), { compact: true });
    }
    state.lastRefreshAt = new Date();
  }

  /* ---------- 订单表格（总览 / 订单视图共用，行展开详情） ---------- */

  function renderOrderTable(container, orders, { compact = false, expandable = true } = {}) {
    if (!container) return;
    const focusKey = captureRowFocus();
    clear(container);
    if (!orders.length) {
      container.append(el('div', { class: 'cc-tablewrap' }, emptyState('还没有订单', '设备产生扫码订单后会出现在这里')));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      th('订单'),
      th('设备'),
      th('金额', 'num'),
      th('状态'),
      th('支付'),
      th('制作进度'),
      compact ? null : th('创建时间'),
    ));
    const tbody = el('tbody');
    const toggleOrderRow = orderId => {
      state.expandedOrderId = state.expandedOrderId === orderId ? null : orderId;
      renderOrderTable(container, orders, { compact, expandable });
    };
    for (const order of orders) {
      const progress = Math.round(Math.max(0, Math.min(1, Number(order.progress || 0))) * 100);
      const colspan = compact ? 6 : 7;
      const row = el('tr', { class: expandable ? 'is-clickable' : '' },
        td(el('div', null,
          el('div', { class: 'cell-main u-mono' }, order.orderNo || order.orderId),
          el('div', { class: 'cell-sub' }, order.paymentMode === 'TEST_FREE' ? '免支付联调' : order.storeId || '')), '订单'),
        td(el('div', null,
          el('div', null, order.deviceId || '—'),
          el('div', { class: 'cell-sub' }, order.productName || '')), '设备'),
        td(el('span', { class: 'num' }, fmtMoney(order.totalAmountMinor, order.currency)), '金额', 'num'),
        td(orderBadge(order.status), '状态'),
        td(paymentBadge(order.paymentStatus), '支付'),
        td(el('div', { class: 'm-progress' },
          el('div', { class: 'cc-progress-track' }, el('div', { class: 'cc-progress-fill', style: `width:${progress}%` })),
          el('small', null, order.currentStepName ? `${order.currentStepName} · ${progress}%` : `${progress}%`)), '制作进度'),
        compact ? null : td(el('span', { class: 'u-muted' }, fmtTime(order.createdAt)), '创建时间'),
      );
      if (expandable) {
        row.dataset.rowKey = order.orderId;
        row.setAttribute('aria-expanded', String(state.expandedOrderId === order.orderId));
        row.addEventListener('click', () => toggleOrderRow(order.orderId));
        rowActivate(row, () => toggleOrderRow(order.orderId));
      }
      tbody.append(row);
      if (expandable && state.expandedOrderId === order.orderId) {
        const expandedSlot = el('td', { colspan: String(colspan) });
        const hold = order.status === 'HOLD' || Boolean(order.holdReason);
        const detailRow = el('tr', { class: `cc-rowdetail${hold ? ' cc-rowdetail--hold' : ''}` }, expandedSlot);
        detailRow.dataset.rowKey = `${order.orderId}:detail`;
        renderOrderDetail(expandedSlot, order);
        tbody.append(detailRow);
      }
    }
    container.append(el('div', { class: 'cc-tablewrap cc-tablewrap--scroll' },
      el('table', { class: 'cc-table', style: compact ? 'min-width:760px' : 'min-width:880px' }, thead, tbody)));
    restoreRowFocus(container, focusKey);
  }

  function renderOrderDetail(slot, order) {
    clear(slot);
    const wrap = el('div', { class: 'cc-stack', style: 'gap:12px' });
    wrap.append(el('dl', { class: 'cc-kv--2col' },
      kv('订单 ID', order.orderId, true),
      kv('制作状态', order.productionStatus || '—'),
      kv('失败代码', order.failureCode || '—', true),
      kv('更新时间', fmtTime(order.updatedAt)),
      kv('人工复核', order.manualReviewRequired ? '需要' : '不需要'),
      kv('HOLD 原因', order.holdReason || '—', true)));
    if (order.failureMessage) {
      wrap.append(el('div', { class: 'm-factline m-factline--fail' },
        el('span', { html: svgIcon('alert-circle', 16), 'aria-hidden': 'true' }),
        el('span', null, `失败信息：${order.failureMessage}`)));
    }
    if (order.status === 'HOLD' || order.holdReason) {
      wrap.append(el('div', { class: 'm-factline m-factline--hold' },
        el('span', { html: svgIcon('info', 16), 'aria-hidden': 'true' }),
        el('span', null, '该订单处于 HOLD：设备结果待确认，需人工对账后再决定是否退款。')));
    }
    slot.append(wrap);
  }

  /* ============================================================
     视图二：设备管理（a04–a06）
     ============================================================ */

  function renderDevicesView(container) {
    const search = el('input', {
      class: 'cc-input', type: 'search', placeholder: '搜索设备 ID、序列号、门店或实例', 'aria-label': '搜索设备',
      value: state.filters.deviceQuery,
      oninput: () => { state.filters.deviceQuery = search.value; renderDeviceRows(); },
    });
    const connFilter = el('select', { class: 'cc-select', 'aria-label': '连接状态筛选', style: 'width:170px', onchange: () => { state.filters.deviceConn = connFilter.value; renderDeviceRows(); } },
      el('option', { value: 'all' }, '全部连接状态'),
      el('option', { value: 'online', selected: state.filters.deviceConn === 'online' }, '在线'),
      el('option', { value: 'offline', selected: state.filters.deviceConn === 'offline' }, '离线'),
      el('option', { value: 'never', selected: state.filters.deviceConn === 'never' }, '从未上线'),
    );

    container.append(
      viewHead('设备管理', '终端连接、生命周期、能力与物料；点击行查看详情与运营操作。',
        can(PERMISSIONS.devicesManage)
          ? el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: openRegisterModal },
              el('span', { html: svgIcon('plus', 16), 'aria-hidden': 'true' }), '登记设备')
          : null),
      el('div', { class: 'cc-toolbar' },
        el('div', { class: 'cc-search' },
          el('span', { html: svgIcon('search', 18), 'aria-hidden': 'true', style: 'position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--cc-text-2)' }),
          search),
        connFilter),
      el('div', { class: 'm-device-split' },
        el('div', { id: 'device-rows' }, skeleton(5)),
        el('section', { class: 'cc-card', id: 'device-detail' },
          emptyState('选择一个设备', '点击左侧列表查看详情、能力、物料与生命周期操作'))));
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
    const focusKey = captureRowFocus();
    clear(container);
    const devices = filteredDevices();
    if (!devices.length) {
      container.append(el('div', { class: 'cc-tablewrap' },
        emptyState(
          state.devices.length ? '没有符合筛选条件的设备' : '还没有登记设备',
          state.devices.length ? '调整搜索或筛选条件后重试' : (can(PERMISSIONS.devicesManage) ? '使用「登记设备」接入新终端' : '需要 devices.manage 权限登记设备'))));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      th('连接'), th('设备'), th('门店 / 实例'),
      th('生命周期'), th('活跃订单', 'num'), th('最近心跳')));
    const tbody = el('tbody');
    for (const device of devices) {
      const row = el('tr', {
        class: `is-clickable${device.deviceId === state.selectedDeviceId ? ' is-selected' : ''}`,
        onclick: () => selectDevice(device.deviceId),
      },
        td(statusPill(device.online ? 'green' : device.hasEverConnected ? 'red' : 'gray',
          device.online ? '在线' : device.hasEverConnected ? '离线' : '从未上线'), '连接'),
        td(el('div', null,
          el('div', { class: 'cell-main u-mono' }, device.deviceId),
          el('div', { class: 'cell-sub' }, `序列号 ${device.serialNumber || '—'}`)), '设备'),
        td(el('div', null,
          el('div', null, device.storeName || device.storeId || '—'),
          el('div', { class: 'cell-sub' }, `${device.storeId || '无门店 ID'} · ${device.profileComplete ? '资料已完成' : '待首次安装'}`)), '门店 / 实例'),
        td(lifecycleBadge(device.lifecycleStatus), '生命周期'),
        td(el('span', { class: 'num' }, fmtCount(device.activeOrderCount)), '活跃订单', 'num'),
        td(el('div', null,
          el('div', null, fmtAgo(device.lastHeartbeatAt)),
          el('div', { class: 'cell-sub' }, `软件 ${device.softwareVersion || '—'}`)), '最近心跳'),
      );
      row.dataset.rowKey = device.deviceId;
      if (device.deviceId === state.selectedDeviceId) row.setAttribute('aria-current', 'true');
      rowActivate(row, () => selectDevice(device.deviceId));
      tbody.append(row);
    }
    container.append(el('div', { class: 'cc-tablewrap cc-tablewrap--scroll' },
      el('table', { class: 'cc-table', style: 'min-width:760px' }, thead, tbody)));
    restoreRowFocus(container, focusKey);
  }

  function resetDeviceDetail() {
    const card = $('device-detail');
    if (!card) return;
    clear(card);
    card.append(emptyState('选择一个设备', '点击左侧列表查看详情、能力、物料与生命周期操作'));
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
      card.append(el('div', { class: 'cc-alert cc-alert--error' },
        el('span', { html: svgIcon('alert-circle', 16), 'aria-hidden': 'true' }),
        el('div', { class: 'cc-alert-body' }, el('div', { class: 'cc-alert-desc' }, `设备详情读取失败：${describeError(error)}`))));
    }
  }

  function renderDeviceDetail(card, deviceId, { detail, inventory, capabilities }) {
    clear(card);

    const head = el('div', { style: 'display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start' },
      el('div', null,
        el('h2', { class: 'cc-h4 u-mono' }, deviceId),
        el('div', { class: 'cc-caption' }, `${detail.deviceName || '未命名设备'} · 序列号 ${detail.serialNumber || '—'} · ${detail.storeName || detail.storeId || '待门店安装'}`)),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
        statusPill(detail.online ? 'green' : detail.hasEverConnected ? 'red' : 'gray', detail.online ? '在线' : detail.hasEverConnected ? '离线' : '从未上线'),
        lifecycleBadge(detail.lifecycleStatus)));

    /* 基本信息 */
    const snapshots = detail.snapshots || {};
    const basic = sec('基本信息', el('dl', { class: 'cc-kv--2col' },
      kv('设备名称', detail.deviceName || '待首次安装'),
      kv('门店', detail.storeName || '待首次安装'),
      kv('地区 / 时区', detail.cityCode && detail.timezone ? `${detail.cityCode} · ${detail.timezone}` : '待首次安装'),
      kv('资料状态', detail.profileComplete ? `已完成 · ${detail.profileSource || '—'}` : '待设备首次安装'),
      kv('实例', detail.instanceId),
      kv('软件版本', detail.softwareVersion),
      kv('活跃启动 ID', detail.activeBootId, true),
      kv('最近序列号', detail.lastSequence),
      kv('心跳 / 事件 / 命令', `${fmtCount(detail.heartbeatCount)} / ${fmtCount(detail.eventCount)} / ${fmtCount(detail.commandCount)}`),
      kv('活跃订单', fmtCount(detail.activeOrderCount)),
      kv('能力快照', snapshots.capabilities ? `v${snapshots.capabilities.version || '?'} · ${fmtAgo(snapshots.capabilities.receivedAt)}` : '未上报'),
      kv('物料快照', snapshots.inventory ? `v${snapshots.inventory.version || '?'} · ${fmtAgo(snapshots.inventory.receivedAt)}` : '未上报'),
      kv('最近心跳', fmtTime(detail.lastHeartbeatAt)),
      kv('最近错误', detail.lastErrorSummary || '无')));

    /* 能力清单 */
    const recipes = (capabilities && (capabilities.products || capabilities.recipes)) || [];
    const capSec = sec('能力清单（设备上报）',
      recipes.length
        ? el('ul', { class: 'cc-list' }, recipes.map(recipe => el('li', null,
            el('span', { style: 'flex:1' },
              el('strong', null, recipe.name || recipe.recipeId),
              el('div', { class: 'cc-caption u-mono' }, `${recipe.recipeId || '—'} · v${recipe.version || '?'} · 预计 ${Math.ceil((recipe.estimatedDurationSeconds || 60) / 60)} 分钟`)),
            el('span', { style: 'display:flex;gap:8px;align-items:center' },
              el('strong', { class: 'u-num u-mono' }, fmtMoney(recipe.priceMinor, recipe.currency || 'CNY')),
              recipe.available === false ? statusPill('red', '不可售') : statusPill('green', '可售')))))
        : emptyState('尚未上报能力快照', '设备激活并上报 capabilities 后显示'));

    /* 物料余量（实时快照；契约含 capacity 字段才画比例条） */
    const materials = (inventory && inventory.materials) || [];
    const invSec = sec('物料余量（实时快照）',
      materials.length
        ? el('ul', { class: 'cc-list' }, materials.map(material => {
            const capacity = Math.max(1, Number(material.capacity || 0));
            const available = Math.max(0, Number(material.available || 0));
            const ratio = Math.min(1, available / capacity);
            const level = material.status === 'CRITICAL' ? 'crit' : material.status === 'LOW' ? 'low' : 'ok';
            return el('li', null,
              el('span', { style: 'flex:1' },
                el('strong', null, material.name || material.materialId || '物料'),
                el('div', { class: 'cc-caption u-mono' }, `${material.materialId || ''} · ${available} / ${capacity} ${material.unit || ''}`),
                el('div', { class: 'm-matbar' }, el('i', { class: level === 'crit' ? 'crit' : level === 'low' ? 'low' : '', style: `width:${Math.round(ratio * 100)}%` }))),
              statusPill(level === 'crit' ? 'red' : level === 'low' ? 'amber' : 'green',
                material.status === 'CRITICAL' ? '危急' : material.status === 'LOW' ? '偏低' : material.status === 'OK' ? '正常' : material.status || '—'));
          }))
        : emptyState('尚未上报物料快照', '设备上报 inventory 后显示'));

    /* 操作区 */
    const actions = sec('运营操作',
      el('div', { class: 'm-row-actions' },
        can(PERMISSIONS.devicesManage)
          ? el('button', {
              class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button',
              disabled: detail.lifecycleStatus === 'PENDING',
              title: detail.lifecycleStatus === 'PENDING' ? '待激活设备必须先完成激活' : '',
              onclick: () => openLifecycleModal(deviceId),
            }, detail.lifecycleStatus === 'PENDING' ? '等待设备激活' : '变更生命周期')
          : null,
        can(PERMISSIONS.devicesManage)
          ? el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: () => createActivationCode(deviceId) }, '生成激活码')
          : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: () => sendDeviceCommand(deviceId, 'RELOAD_CONFIG') }, '重载配置')
          : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: () => sendDeviceCommand(deviceId, 'SYNC_CONFIG') }, '同步配置')
          : null,
        can(PERMISSIONS.commandsExecute)
          ? el('button', { class: 'cc-btn cc-btn--danger cc-btn--sm', type: 'button', onclick: () => confirmRestart(deviceId) }, '重启应用')
          : null,
        !can(PERMISSIONS.devicesManage) && !can(PERMISSIONS.commandsExecute)
          ? el('span', { class: 'cc-caption' }, '当前角色为只读（需要 devices.manage / commands.execute）')
          : null),
      can(PERMISSIONS.commandsExecute)
        ? el('p', { class: 'cc-help' }, '远程命令通过设备命令通道下发；重启会中断进行中的制作，需二次确认。')
        : null);

    card.append(head, basic, capSec, invSec, actions);
  }

  /* ----- 生命周期变更（必须填写原因） ----- */

  function openLifecycleModal(deviceId) {
    const device = deviceById(deviceId) || {};
    const statusSelect = el('select', { class: 'cc-select' },
      el('option', { value: 'ACTIVE', selected: device.lifecycleStatus !== 'SUSPENDED' && device.lifecycleStatus !== 'MAINTENANCE' }, 'ACTIVE · 运行中（恢复接单）'),
      el('option', { value: 'SUSPENDED', selected: device.lifecycleStatus === 'SUSPENDED' }, 'SUSPENDED · 停用（停止派单与售卖）'),
      el('option', { value: 'MAINTENANCE', selected: device.lifecycleStatus === 'MAINTENANCE' }, 'MAINTENANCE · 维护中（暂停派单）'));
    const reason = el('textarea', { class: 'cc-textarea', placeholder: '填写变更原因（至少 3 个字符），会写入审计日志', maxlength: '500' });
    const error = el('p', { class: 'cc-error-text', role: 'alert' });
    const submit = el('button', { class: 'cc-btn cc-btn--primary', type: 'button' }, '提交变更');
    const modal = openModal({
      title: `变更生命周期 · ${deviceId}`, size: '520',
      body: [
        field('目标状态', statusSelect),
        field('变更原因（必填）', reason, null, error),
        el('p', { class: 'cc-help' }, 'SUSPENDED / MAINTENANCE 会立即停止向该设备派发新制作任务；已在制作的订单不受影响。'),
      ],
      footer: [
        el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: () => modal.close() }, '取消'),
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
      submit.replaceChildren(el('span', { html: SPINNER, 'aria-hidden': 'true' }), '提交中…');
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
    const deviceIdInput = el('input', { class: 'cc-input u-mono', placeholder: 'coffee-bot-003（3–6 位编号）', autocomplete: 'off', pattern: '^coffee-bot-[0-9]{3,6}$' });
    const serialInput = el('input', { class: 'cc-input u-mono', placeholder: 'CB-2026-003', autocomplete: 'off', pattern: '^CB-[0-9]{4}-[0-9]{3,6}$' });
    const instanceInput = el('input', { class: 'cc-input', placeholder: '可选', autocomplete: 'off' });
    const storeInput = el('input', { class: 'cc-input', placeholder: '可选', autocomplete: 'off' });
    const error = el('p', { class: 'cc-error-text', role: 'alert' });
    const submit = el('button', { class: 'cc-btn cc-btn--primary', type: 'button' }, '登记并生成激活码');
    const modal = openModal({
      title: '登记新设备', size: '560',
      body: [
        el('p', { class: 'cc-help' }, '先预登记受约束的设备 ID 与出厂序列号，再把一次性激活码交给设备端。门店资料在设备首次安装时补齐；deviceId 格式为 coffee-bot-003，序列号格式为 CB-2026-003。'),
        el('div', { style: 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 24px' },
          field('deviceId *', deviceIdInput),
          field('序列号 *', serialInput),
          field('instanceId', instanceInput),
          field('storeId', storeInput)),
        error,
      ],
      footer: [
        el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: () => modal.close() }, '取消'),
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
      submit.replaceChildren(el('span', { html: SPINNER, 'aria-hidden': 'true' }), '登记中…');
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
     视图三：订单（a07–a08）
     ============================================================ */

  const ORDER_STATUS_OPTIONS = ['', 'CREATED', 'AWAITING_PAYMENT', 'QUEUED', 'DISPATCHED', 'ACCEPTED', 'MAKING', 'HOLD', 'READY', 'FAILED', 'REFUNDED', 'CANCELLED', 'EXPIRED'];

  function renderOrdersView(container) {
    const statusSelect = el('select', { class: 'cc-select', 'aria-label': '订单状态筛选', style: 'width:190px', onchange: () => { state.filters.orderStatus = statusSelect.value; loadOrders().catch(() => { }); } },
      ORDER_STATUS_OPTIONS.map(value => el('option', {
        value,
        selected: state.filters.orderStatus === value,
      }, value ? `${ORDER_STATUS[value]?.label || value}（${value}）` : '全部状态')));
    const deviceInput = el('input', {
      class: 'cc-input u-mono', placeholder: '按 deviceId 过滤', 'aria-label': '设备过滤', style: 'width:200px', value: state.filters.orderDevice,
      oninput: () => { state.filters.orderDevice = deviceInput.value.trim(); },
      onkeydown: event => { if (event.key === 'Enter') loadOrders().catch(() => { }); },
    });
    container.append(
      viewHead('订单', '支付、制作进度与异常处理；点击行展开详情。'),
      el('div', { class: 'cc-toolbar' },
        statusSelect, deviceInput,
        el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: () => loadOrders().catch(() => { }) },
          el('span', { html: svgIcon('refresh', 14), 'aria-hidden': 'true' }), '查询')),
      el('div', { id: 'order-rows' }, skeleton(6)),
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
     视图四：权限（a09–a10）
     ============================================================ */

  function renderAccessView(container) {
    container.append(
      viewHead('权限', '角色决定权限集合；Token 只在创建时显示一次，云端只保存摘要。',
        can(PERMISSIONS.accessManage)
          ? el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: openCreateOperatorModal },
              el('span', { html: svgIcon('plus', 16), 'aria-hidden': 'true' }), '新建运营员')
          : null),
      can(PERMISSIONS.accessManage)
        ? null
        : el('p', { class: 'cc-caption', style: 'margin:0 0 16px' }, '只读模式（需要 access.manage 才能编辑）'),
      el('div', { id: 'operator-rows' }, skeleton(4)),
    );
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
    const focusKey = captureRowFocus();
    clear(container);
    if (!state.operators.length) {
      container.append(el('div', { class: 'cc-tablewrap' }, emptyState('还没有运营员', can(PERMISSIONS.accessManage) ? '使用「新建运营员」创建第一个账号' : '需要 OWNER 创建运营员')));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      th('运营员'), th('角色'), th('状态'),
      th('有效 Token', 'num'), th('最近使用'), th('操作')));
    const tbody = el('tbody');
    for (const operator of state.operators) {
      const row = el('tr', { class: 'is-clickable' },
        td(el('div', null,
          el('div', { class: 'cell-main' }, operator.displayName),
          el('div', { class: 'cell-sub' }, operator.operatorId)), '运营员'),
        td(tagPill(operator.role === 'OWNER' ? 'blue' : operator.role === 'MANAGER' ? 'green' : 'gray', operator.role), '角色'),
        td(operator.status === 'ACTIVE' ? statusPill('green', '启用') : statusPill('red', '停用'), '状态'),
        td(el('span', { class: 'num' }, fmtCount(operator.activeTokenCount)), '有效 Token', 'num'),
        td(el('span', { class: 'u-muted' }, fmtAgo(operator.lastUsedAt)), '最近使用'),
        td(can(PERMISSIONS.accessManage)
          ? el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: event => { event.stopPropagation(); openEditOperatorModal(operator); } }, '编辑')
          : el('span', { class: 'u-muted' }, '只读'), '操作'),
      );
      row.dataset.rowKey = operator.operatorId;
      row.setAttribute('aria-expanded', String(state.expandedOperatorId === operator.operatorId));
      const toggleOperatorRow = () => {
        state.expandedOperatorId = state.expandedOperatorId === operator.operatorId ? null : operator.operatorId;
        renderOperators(container);
      };
      row.addEventListener('click', toggleOperatorRow);
      rowActivate(row, toggleOperatorRow);
      tbody.append(row);
      if (state.expandedOperatorId === operator.operatorId) {
        row.classList.add('is-selected');
        const slot = el('td', { colspan: '6' });
        const detailRow = el('tr', { class: 'cc-rowdetail' }, slot);
        renderOperatorTokens(slot, operator);
        tbody.append(detailRow);
      }
    }
    container.append(el('div', { class: 'cc-tablewrap cc-tablewrap--scroll' },
      el('table', { class: 'cc-table', style: 'min-width:800px' }, thead, tbody)));
    restoreRowFocus(container, focusKey);
  }

  function renderOperatorTokens(slot, operator) {
    clear(slot);
    const wrap = el('div', { id: `tokens-${operator.operatorId}` }, skeleton(3));
    slot.append(wrap);
    api(`/api/v1/admin/operators/${encodeURIComponent(operator.operatorId)}/tokens`)
      .then(data => {
        const list = Array.isArray(data.tokens) ? data.tokens : [];
        clear(wrap);
        const tokenRows = list.length
          ? list.map(token => el('tr', null,
              td(el('span', null,
                el('span', { class: 'cell-main' }, token.label || '—'),
                el('div', { class: 'cell-sub' }, token.tokenId)), '标签'),
              td(token.status === 'ACTIVE' ? statusPill('green', '有效')
                : token.status === 'REVOKED' ? statusPill('red', '已撤销')
                : statusPill('gray', token.status), '状态'),
              td(el('span', { class: 'u-mono' }, token.expiresAt ? fmtTime(token.expiresAt) : '永不'), '过期时间'),
              td(el('span', { class: 'u-muted' }, fmtAgo(token.lastUsedAt)), '最近使用'),
              td(el('span', { class: 'u-muted u-mono' }, fmtTime(token.createdAt)), '创建时间'),
              td(can(PERMISSIONS.accessManage) && token.status === 'ACTIVE'
                ? el('button', {
                    class: 'cc-btn cc-btn--danger-outline cc-btn--sm', type: 'button',
                    onclick: () => revokeToken(operator, token),
                  }, '撤销')
                : el('span', { class: 'u-muted' }, '—'), '操作'),
            ))
          : [el('tr', null, el('td', { colspan: '6' }, emptyState('还没有 Token', '为该运营员创建 API Token 后用于登录运营台')))];
        const tokenTable = el('table', { class: 'cc-table cc-table--dense', style: 'min-width:640px' },
          el('thead', null, el('tr', null,
            th('标签'), th('状态'), th('过期时间'),
            th('最近使用'), th('创建时间'), th('操作'))),
          el('tbody', null, tokenRows));
        const section = el('div', { class: 'cc-stack', style: 'gap:12px' },
          el('h4', { class: 'cc-h4' }, `API Token · ${operator.displayName}`),
          el('div', { class: 'cc-tablewrap cc-tablewrap--scroll' }, tokenTable));
        if (can(PERMISSIONS.accessManage)) {
          const label = el('input', { class: 'cc-input', placeholder: 'Token 标签，例如「值班平板」', maxlength: '120' });
          const expires = el('input', { class: 'cc-input', type: 'datetime-local' });
          const createBtn = el('button', {
            class: 'cc-btn cc-btn--primary cc-btn--sm', type: 'button',
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
          el('span', { html: svgIcon('plus', 14), 'aria-hidden': 'true' }),
          el('span', null, '创建 Token'));
          section.append(el('div', { class: 'cc-card cc-card--pad16', style: 'display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end' },
            el('div', { style: 'flex:1;min-width:200px' }, field('新 Token 标签 *', label)),
            el('div', { style: 'min-width:200px' }, field('过期时间（可选）', expires)),
            createBtn));
        }
        wrap.append(section);
      })
      .catch(error => {
        clear(wrap);
        wrap.append(el('div', { class: 'cc-alert cc-alert--error' },
          el('span', { html: svgIcon('alert-circle', 16), 'aria-hidden': 'true' }),
          el('div', { class: 'cc-alert-body' }, el('div', { class: 'cc-alert-desc' }, `Token 列表读取失败：${describeError(error)}`))));
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
    const nameInput = el('input', { class: 'cc-input', placeholder: '运营员名称，例如「张三 / 值班组」', maxlength: '120' });
    const roleSelect = el('select', { class: 'cc-select' },
      availableRoles.length
        ? availableRoles.map(role => el('option', { value: role.role }, `${role.role} · ${role.permissions.length} 项权限`))
        : ['VIEWER', 'OPERATOR', 'MANAGER', 'OWNER'].map(role => el('option', { value: role }, role)));
    const permPreview = el('div', { class: 'm-permlist' });
    const syncPreview = () => {
      clear(permPreview);
      const role = availableRoles.find(item => item.role === roleSelect.value);
      for (const permission of role ? role.permissions : []) permPreview.append(el('span', { class: 'm-permtag' }, permission));
    };
    roleSelect.addEventListener('change', syncPreview);
    syncPreview();
    const error = el('p', { class: 'cc-error-text', role: 'alert' });
    const submit = el('button', { class: 'cc-btn cc-btn--primary', type: 'button' }, '创建运营员');
    const modal = openModal({
      title: '新建运营员', size: '520',
      body: [
        field('名称 *', nameInput),
        field('角色', roleSelect),
        el('div', { class: 'cc-field' }, el('label', { class: 'cc-label' }, '该角色权限'), permPreview),
        error,
      ],
      footer: [
        el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: () => modal.close() }, '取消'),
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
    const nameInput = el('input', { class: 'cc-input', value: operator.displayName || '', maxlength: '120' });
    const roleSelect = el('select', { class: 'cc-select' },
      ((state.principal && state.principal.availableRoles) || []).map(role =>
        el('option', { value: role.role, selected: operator.role === role.role }, role.role)));
    const statusSelect = el('select', { class: 'cc-select' },
      el('option', { value: 'ACTIVE', selected: operator.status === 'ACTIVE' }, 'ACTIVE · 启用'),
      el('option', { value: 'SUSPENDED', selected: operator.status === 'SUSPENDED' }, 'SUSPENDED · 停用'));
    const error = el('p', { class: 'cc-error-text', role: 'alert' });
    const submit = el('button', { class: 'cc-btn cc-btn--primary', type: 'button' }, '保存修改');
    const modal = openModal({
      title: `编辑运营员 · ${operator.displayName}`, size: '560',
      body: [
        field('名称', nameInput),
        el('div', { style: 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 24px;margin-top:16px' },
          field('角色', roleSelect),
          field('状态', statusSelect)),
        el('p', { class: 'cc-help', style: 'margin-top:16px' }, '停用后该运营员全部 Token 立即失效；变更会写入审计日志。'),
        error,
      ],
      footer: [
        el('button', { class: 'cc-btn cc-btn--secondary', type: 'button', onclick: () => modal.close() }, '取消'),
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
     视图五：审计日志（a11）
     ============================================================ */

  function renderAuditView(container) {
    const actionInput = el('input', { class: 'cc-input u-mono', placeholder: '例如 device.lifecycle.update', 'aria-label': 'action 过滤', style: 'width:240px', value: state.filters.auditAction });
    const resourceInput = el('input', { class: 'cc-input u-mono', placeholder: '例如 terminal', 'aria-label': 'resourceType 过滤', style: 'width:200px', value: state.filters.auditResource });
    const apply = () => {
      state.filters.auditAction = actionInput.value.trim();
      state.filters.auditResource = resourceInput.value.trim();
      loadAuditLogs().catch(() => { });
    };
    actionInput.addEventListener('keydown', event => { if (event.key === 'Enter') apply(); });
    resourceInput.addEventListener('keydown', event => { if (event.key === 'Enter') apply(); });
    container.append(
      viewHead('审计日志', '操作者、动作与资源记录；点击行查看详情。'),
      el('div', { class: 'cc-toolbar' },
        actionInput, resourceInput,
        el('button', { class: 'cc-btn cc-btn--secondary cc-btn--sm', type: 'button', onclick: apply },
          el('span', { html: svgIcon('refresh', 14), 'aria-hidden': 'true' }), '查询')),
      el('div', { id: 'audit-rows' }, skeleton(6)),
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
      container.append(el('div', { class: 'cc-tablewrap' }, emptyState('没有符合条件的审计记录', '调整 action / resourceType 后重试')));
      return;
    }
    const thead = el('thead', null, el('tr', null,
      th('时间'), th('操作者'), th('动作'),
      th('资源'), th('请求 ID')));
    const tbody = el('tbody');
    for (const log of logs) {
      const row = el('tr', { class: 'is-clickable' },
        td(el('span', { class: 'u-mono' }, fmtTime(log.createdAt)), '时间'),
        td(el('div', null,
          el('div', { class: 'cell-main' }, log.actorName || log.actorId || '—'),
          el('div', { class: 'cell-sub' }, `${log.actorType || ''}${log.actorId ? ' · ' + log.actorId : ''}`)), '操作者'),
        td(el('code', { class: 'u-mono' }, log.action || '—'), '动作'),
        td(el('div', null,
          el('div', null, log.resourceType || '—'),
          el('div', { class: 'cell-sub' }, log.resourceId || '')), '资源'),
        td(el('span', { class: 'u-muted u-mono' }, log.requestId || '—'), '请求 ID'),
      );
      row.setAttribute('aria-haspopup', 'dialog');
      rowActivate(row, () => showAuditDetail(log));
      row.addEventListener('click', () => showAuditDetail(log));
      tbody.append(row);
    }
    container.append(el('div', { class: 'cc-tablewrap cc-tablewrap--scroll' },
      el('table', { class: 'cc-table', style: 'min-width:820px' }, thead, tbody)));
    state.lastRefreshAt = new Date();
  }

  function showAuditDetail(log) {
    const body = el('div', { class: 'cc-stack', style: 'gap:16px' },
      el('dl', { class: 'cc-kv--2col' },
        kv('时间', fmtTime(log.createdAt)),
        kv('操作者', `${log.actorName || '—'}（${log.actorType || '—'}）`),
        kv('动作', log.action, true),
        kv('资源', `${log.resourceType || '—'} ${log.resourceId || ''}`, true),
        kv('请求 ID', log.requestId, true)),
      el('div', { class: 'cc-field' },
        el('label', { class: 'cc-label' }, '详情'),
        el('div', { class: 'cc-code' },
          el('pre', null, JSON.stringify(log.detail ?? {}, null, 2)))));
    const modal = openModal({ title: '审计记录', body, size: '640' });
  }

  /* ---------- 事件绑定与启动 ---------- */

  $('login-form').addEventListener('submit', handleLogin);
  $('logout-btn').addEventListener('click', logout);
  $('refresh-btn').addEventListener('click', refreshNow);
  window.addEventListener('hashchange', () => { if (state.token) route(); });
})();
