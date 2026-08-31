'use strict';

/* ============================================================
   Woodbridge Coffee · 扫码下单 / 订单状态页
   - 无框架、无构建、无外部依赖。
   - 接口、鉴权头、幂等键与轮询规则与后端契约严格一致：
       GET  /api/v1/public/devices/{deviceId}/menu
       POST /api/v1/public/devices/{deviceId}/orders        (Idempotency-Key)
       POST /api/v1/orders/{orderId}/payments               (Idempotency-Key + X-Order-Access-Token)
       GET  /api/v1/public/orders/{orderId}                 (X-Order-Access-Token)
       GET  /api/v1/payments/{paymentId}/qr                 (X-Order-Access-Token)
   - 同一 paymentId 的二维码 DOM / Blob URL 不因轮询被替换；
     初次加载失败至少 20 秒后才重试。
   ============================================================ */

const app = document.getElementById('app');
const qs = new URLSearchParams(location.search);
const deviceId = qs.get('device_id') || '';

const PAYMENT_QR_REFRESH_MS = 20000;  // 二维码加载失败后的最短重试间隔

let menu = null;
let selected = null;
let submitting = false;
let orderStreamAbort = null;
let orderStreamReconnectTimer = null;
let orderStreamTerminal = false;
let artSeq = 0;
let paymentQrCache = { paymentId: null, url: null, loadedAt: 0, loading: false };

const TERMINAL_STATUSES = ['READY', 'FAILED', 'CANCELLED', 'EXPIRED'];
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]
));

/* ---------- 基础请求 ---------- */

async function request(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  let data = {};
  try { data = await response.json(); } catch (_) { /* 非 JSON 响应 */ }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : (data.detail?.code || '请求失败');
    throw new Error(detail);
  }
  return data;
}

/* ---------- 展示辅助 ---------- */

function profile(value) {
  return ['americano', 'espresso', 'iced-latte', 'hazelnut-special'].includes(value) ? value : 'generic';
}

function duration(product) {
  const range = product.durationRangeSeconds || {};
  const min = Math.max(1, Math.ceil((range.min || product.estimatedDurationSeconds || 60) / 60));
  const max = Math.max(min, Math.ceil((range.max || product.estimatedDurationSeconds || 60) / 60));
  return min === max ? `${min} 分钟` : `${min}–${max} 分钟`;
}

function statusText(reason) {
  return ({
    DEVICE_OFFLINE: '设备离线', DEVICE_NOT_ACTIVE: '设备未启用',
    MATERIAL_INSUFFICIENT: '原料不足', DISABLED: '暂停售卖', LOW_STOCK: '余量不足',
  })[reason] || '暂不可售';
}

function money(item) {
  const minor = item.priceMinor ?? item.totalAmountMinor;
  if (minor === null || minor === undefined || !Number.isFinite(Number(minor))) return '—';
  const amount = (Number(minor) / 100).toFixed(2);
  const currency = item.currency || 'CNY';
  return currency === 'CNY' ? `¥${amount}` : `${amount} ${esc(currency)}`;
}

function orderLabel(status) {
  return ({
    CREATED: '订单已创建', AWAITING_PAYMENT: '等待付款', PAID: '支付成功，正在排队',
    QUEUED: '已进入制作队列', DISPATCHED: '正在连接咖啡机器人', ACCEPTED: '设备已预留原料',
    MAKING: '咖啡正在制作', HOLD: '设备结果待确认', READY: '制作完成，请取杯',
    FAILED: '本次制作未完成', REFUNDED: '退款已完成', CANCELLED: '订单已取消',
    EXPIRED: '制作指令已超时',
  })[status] || status;
}

/* ---------- 品牌与图形 ---------- */

function baseHeader(pillClass, pillText) {
  return `<header class="brand-row">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M4 9h12v6.5a4.5 4.5 0 0 1-4.5 4.5h-3A4.5 4.5 0 0 1 4 15.5V9Z" fill="currentColor" opacity=".92"/>
          <path d="M16 10.5h1.8a2.7 2.7 0 0 1 0 5.4H16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M7.5 6c0-1.2 1-1.6 1-2.8M11 6c0-1.2 1-1.6 1-2.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
        </svg>
      </div>
      <div>
        <div class="eyebrow">Robot Coffee</div>
        <h1>Woodbridge Coffee</h1>
      </div>
    </div>
    <div class="live-pill ${pillClass}"><span class="dot" aria-hidden="true"></span><span class="lp-text">${esc(pillText)}</span></div>
  </header>`;
}

/* 杯型 SVG：按设备上报的 visual.profile 绘制，纯装饰 */
function drinkArt(profileId) {
  const uid = `dg-${profileId}-${++artSeq}`;
  const themes = {
    americano: { c1: '#7a4c2c', c2: '#412314', surface: '#5d3a21', scale: 1, deco: '' },
    espresso: { c1: '#4c2a17', c2: '#2a1409', surface: '#3a1e0f', scale: 0.8, deco: '' },
    'iced-latte': {
      c1: '#c9a279', c2: '#8a5c39', surface: '#dcc3a4', scale: 1,
      deco: `<g opacity=".85">
        <rect x="30" y="42" width="13" height="13" rx="3" fill="#ffffff" opacity=".75" transform="rotate(12 36 48)"/>
        <rect x="42" y="52" width="12" height="12" rx="3" fill="#ffffff" opacity=".6" transform="rotate(-14 48 58)"/>
      </g>`,
    },
    'hazelnut-special': {
      c1: '#9c6236', c2: '#5a3418', surface: '#b07a48', scale: 1,
      deco: `<g>
        <ellipse cx="44" cy="27" rx="16" ry="6" fill="#f7ead8"/>
        <path d="M32 25c4 3 9 3 13 1s9-2 12 1" stroke="#c98d4e" stroke-width="2.2" fill="none" stroke-linecap="round"/>
      </g>`,
    },
    generic: { c1: '#8a6a4e', c2: '#4e3421', surface: '#6d5136', scale: 1, deco: '' },
  };
  const t = themes[profileId] || themes.generic;
  const w = Math.round(62 * t.scale), h = Math.round(84 * t.scale);
  return `<svg width="${w}" height="${h}" viewBox="0 0 88 118" aria-hidden="true">
    <defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${t.c1}"/><stop offset="1" stop-color="${t.c2}"/>
    </linearGradient></defs>
    <ellipse cx="44" cy="109" rx="27" ry="4.5" fill="#00000014"/>
    <g transform="translate(${44 - 44 * t.scale} ${109 - 109 * t.scale}) scale(${t.scale})">
      <path d="M67 44c13 0 15 17 2 22" fill="none" stroke="#f3e7d6" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M20 30h48v60a10 10 0 0 1-10 10H30a10 10 0 0 1-10-10V30Z" fill="url(#${uid})"/>
      <path d="M20 30h48v8H20z" fill="#fdf8f0" opacity=".92"/>
      <ellipse cx="44" cy="30" rx="24" ry="6.5" fill="#fffdf8"/>
      <ellipse cx="44" cy="30" rx="18.5" ry="4.4" fill="${t.surface}"/>
      ${t.deco}
    </g>
  </svg>`;
}

const iconClock = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <circle cx="12" cy="13" r="8" stroke="currentColor" stroke-width="2"/>
  <path d="M12 9.5V13l2.5 1.8M9 2.5h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

const iconCheck = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <path d="M4.5 12.5 10 18 19.5 6.5" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const iconAlert = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <path d="M12 3 2.5 20h19L12 3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <path d="M12 9.5v4.5M12 17.4v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

const iconInfo = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/>
  <path d="M12 11v5.5M12 7.6v.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
</svg>`;

/* ---------- Toast ---------- */

function toast(message, kind = 'info') {
  const root = document.getElementById('toast-root');
  if (!root || typeof document.createElement !== 'function') return;
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  const icon = document.createElement('span');
  icon.className = 't-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = kind === 'error' ? iconAlert : iconInfo;
  const text = document.createElement('span');
  text.textContent = message;
  node.append(icon, text);
  root.append(node);
  setTimeout(() => {
    node.classList.add('leaving');
    setTimeout(() => node.remove(), 320);
  }, 4600);
}

/* ---------- 菜单页 ---------- */

async function loadMenu() {
  if (!deviceId) {
    renderError('二维码缺少设备标识，请重新扫描终端屏幕上的二维码。');
    return;
  }
  try {
    menu = await request(`/api/v1/public/devices/${encodeURIComponent(deviceId)}/menu`);
    renderMenu();
  } catch (error) {
    renderError(`无法读取设备菜单：${error.message}`);
  }
}

function renderMenu() {
  document.title = 'Woodbridge Coffee · 选择饮品';
  const online = menu.paymentMode === 'ONLINE';
  const available = menu.products.filter(p => p.available);
  const totalRemaining = available.reduce((sum, p) => sum + (p.remainingServings || 0), 0);
  const sellable = menu.salesEnabled && available.length > 0;

  app.innerHTML = `
    ${baseHeader(menu.online ? '' : 'warn', menu.online ? '设备在线' : '设备离线')}
    <section class="hero">
      <div class="eyebrow">${esc(menu.storeId || menu.deviceId || '')}</div>
      <h2>现在，来一杯<br>机器人现磨咖啡</h2>
      <p>饮品、余量与时长由设备实时上报，云端逐单确认。</p>
    </section>
    <section class="machine-card" aria-label="设备状态">
      <div class="machine-meta">
        <span class="status-dot ${menu.online ? 'online' : ''}" aria-hidden="true"></span>
        <div>
          <strong>${menu.online ? '设备在线 · 可以下单' : '设备离线 · 暂停接单'}</strong>
          <small>设备状态 ${esc(menu.deviceStatus || 'UNKNOWN')}</small>
        </div>
      </div>
      <div class="stock-summary">
        <strong>${totalRemaining}</strong>
        <small>预计可售杯数</small>
      </div>
    </section>
    <div class="section-title">
      <h3>今日可售</h3>
      <span>${menu.materialAlertCount ? '有物料待补充' : '共享原料状态正常'}</span>
    </div>
    ${menu.products.length ? `<section class="drink-list">${menu.products.map(card).join('')}</section>`
      : `<section class="center-state" style="min-height:32vh"><p>设备尚未上报可售饮品，请稍后重试。</p></section>`}
    <div class="notice">${online
      ? '付款由支付宝处理，云端确认支付成功后才会向设备派发制作任务。支付完成后请保持订单状态页打开，直到取杯。'
      : '当前为内部联调模式（免支付），下单会真实触发模拟终端制作，仅供验收使用。'}</div>
    <section class="checkout" aria-label="结算栏">
      <div class="checkout-copy">
        <strong>${selected ? esc(selected.name) : '请选择一款饮品'}</strong>
        <small>${selected ? (online ? money(selected) : '免支付联调') : (online ? '支付宝安全支付' : '测试免支付')}</small>
      </div>
      <button id="submit" class="btn-primary" ${selected && !submitting ? '' : 'disabled'}>
        ${submitting ? '<span class="btn-spinner" aria-hidden="true"></span>' : ''}
        ${submitting ? (online ? '正在创建支付…' : '正在下单…') : (online ? '确认并支付' : '确认下单')}
      </button>
    </section>`;

  document.querySelectorAll('.drink-card').forEach(node => {
    node.onclick = () => selectDrink(node.dataset.id);
  });
  const submit = document.getElementById('submit');
  if (submit) submit.onclick = submitOrder;
  if (!sellable && menu.products.length) {
    /* 全部不可售时按钮保持禁用，原因已逐卡展示 */
  }
}

function card(item) {
  const unavailable = item.unavailableReasons?.[0];
  const isSelected = selected?.recipeId === item.recipeId;
  return `
    <button class="drink-card ${isSelected ? 'selected' : ''}" data-id="${esc(item.recipeId)}" ${item.available ? '' : 'disabled'} aria-pressed="${isSelected ? 'true' : 'false'}">
      <div class="drink-art">${drinkArt(profile(item.visual?.profile))}</div>
      <div class="drink-copy">
        <h4>${esc(item.name || item.recipeId)}</h4>
        <p class="desc">${esc(item.description || '设备本地特制配方')}</p>
        <div class="drink-facts">
          <span class="fact time">${iconClock}预计 ${duration(item)}</span>
          ${item.available
            ? `<span class="fact price">${money(item)}</span>`
            : `<span class="fact block">${statusText(unavailable)}</span>`}
        </div>
      </div>
      <div class="drink-side">
        <span class="remaining">${item.remainingServings ?? 0}</span>
        <small class="unit">剩余杯数</small>
        <span class="select-ring" aria-hidden="true">${iconCheck}</span>
      </div>
    </button>`;
}

function selectDrink(id) {
  selected = menu.products.find(p => p.recipeId === id && p.available) || null;
  renderMenu();
}

async function submitOrder() {
  if (!selected || submitting) return;
  submitting = true;
  renderMenu();
  /* 幂等键与会话共存：重试不会重复创建订单 */
  const storageKey = `coffee-order-request:${deviceId}:${selected.recipeId}`;
  let key = sessionStorage.getItem(storageKey);
  if (!key) {
    key = crypto.randomUUID();
    sessionStorage.setItem(storageKey, key);
  }
  try {
    const paymentMode = menu.paymentMode === 'ONLINE' ? 'ONLINE' : 'TEST_FREE';
    const order = await request(`/api/v1/public/devices/${encodeURIComponent(deviceId)}/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify({ recipeId: selected.recipeId, recipeVersion: selected.recipeVersion, quantity: 1, paymentMode }),
    });
    let payment = null;
    if (paymentMode === 'ONLINE') {
      payment = await request(`/api/v1/orders/${encodeURIComponent(order.orderId)}/payments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': `payment:${key}`,
          'X-Order-Access-Token': order.accessToken,
        },
        body: JSON.stringify({}),
      });
    }
    sessionStorage.removeItem(storageKey);
    location.href = `/order/status#order=${encodeURIComponent(order.orderId)}&token=${encodeURIComponent(order.accessToken)}${payment ? `&payment=${encodeURIComponent(payment.paymentId)}` : ''}`;
  } catch (error) {
    submitting = false;
    renderMenu();
    toast(`下单或支付创建未完成：${error.message}。同一页面重试不会重复创建订单。`, 'error');
  }
}

/* ---------- 订单状态页 ---------- */

function fragment() {
  return new URLSearchParams(location.hash.replace(/^#/, ''));
}

async function loadOrder() {
  const params = fragment();
  const orderId = params.get('order');
  const token = params.get('token');
  if (!orderId || !token) {
    renderError('订单状态链接不完整。请从下单成功的页面进入，或重新扫码下单。');
    return;
  }
  try {
    const order = await request(`/api/v1/public/orders/${encodeURIComponent(orderId)}`, {
      headers: { 'X-Order-Access-Token': token },
    });
    renderOrder(order);
    orderStreamTerminal = [...TERMINAL_STATUSES, 'REFUNDED'].includes(order.status);
    if (!orderStreamTerminal) startOrderStream(orderId, token);
  } catch (error) {
    renderError(`订单状态暂时不可用：${error.message}`, true);
  }
}

async function startOrderStream(orderId, token) {
  if (orderStreamTerminal) return;
  if (orderStreamAbort) orderStreamAbort.abort();
  clearTimeout(orderStreamReconnectTimer);
  const controller = new AbortController();
  orderStreamAbort = controller;
  try {
    const response = await fetch(`/api/v1/public/orders/${encodeURIComponent(orderId)}/events`, {
      headers: { 'Accept': 'text/event-stream', 'X-Order-Access-Token': token },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error(`SSE HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (!orderStreamTerminal) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replaceAll('\r\n', '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split('\n')
          .filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trimStart())
          .join('\n');
        if (!data) continue;
        const order = JSON.parse(data);
        renderOrder(order);
        orderStreamTerminal = [...TERMINAL_STATUSES, 'REFUNDED'].includes(order.status);
        if (orderStreamTerminal) {
          controller.abort();
          return;
        }
      }
    }
  } catch (error) {
    if (controller.signal.aborted || orderStreamTerminal) return;
  }
  if (!orderStreamTerminal && document.visibilityState === 'visible') {
    orderStreamReconnectTimer = setTimeout(() => startOrderStream(orderId, token), 3000);
  }
}

/* 设备权威的步骤计划：优先使用设备上报的 stepName */
function productionSteps(order) {
  const planned = order.production?.stepPlan || order.production?.stepDurations || [];
  if (planned.length) {
    return planned.map((step, index) => ({
      id: step.stepId,
      name: step.stepName || step.stepId?.replaceAll('-', ' ') || '制作步骤',
      index: Number.isInteger(step.stepIndex) ? step.stepIndex : index,
      duration: step.durationSeconds,
    }));
  }
  const visual = order.product?.visual?.profile;
  return visual === 'iced-latte' ? [
    { id: 'prepare-cup', name: '准备杯子', index: 0 },
    { id: 'add-ice', name: '加入冰块', index: 1 },
    { id: 'extract-coffee', name: '萃取咖啡', index: 2 },
    { id: 'add-milk', name: '添加牛奶', index: 3 },
    { id: 'seal-and-serve', name: '封杯并出杯', index: 4 },
  ] : [
    { id: 'prepare-cup', name: '准备杯子', index: 0 },
    { id: 'extract-coffee', name: '萃取咖啡', index: 1 },
    { id: 'finish', name: '调制与出杯', index: 2 },
  ];
}

const MILESTONE_DEFS = [
  { key: 'pay', at: ['CREATED', 'AWAITING_PAYMENT'] },
  { key: 'queue', at: ['QUEUED'] },
  { key: 'dispatch', at: ['DISPATCHED'] },
  { key: 'accept', at: ['ACCEPTED'] },
  { key: 'make', at: ['MAKING', 'HOLD'] },
  { key: 'done', at: ['READY', 'FAILED', 'REFUNDED', 'CANCELLED', 'EXPIRED'] },
];

function milestoneMarkup(order) {
  const labels = ['支付', '排队', '派单', '设备接受', '制作', '完成'];
  if (order.paymentMode === 'TEST_FREE') labels[0] = '下单';
  const current = Math.max(0, MILESTONE_DEFS.findIndex(m => m.at.includes(order.status)));
  const failed = ['FAILED', 'CANCELLED', 'EXPIRED'].includes(order.status);
  return `<ol class="milestones" aria-label="订单里程碑">${labels.map((label, index) => {
    let state = '';
    if (index < current) state = 'done';
    else if (index === current) state = failed ? 'error' : order.status === 'READY' || order.status === 'REFUNDED' ? 'done' : 'active';
    return `<li class="milestone ${state}"><span class="m-dot" aria-hidden="true"></span><span>${label}</span></li>`;
  }).join('')}</ol>`;
}

function statusNote(order) {
  switch (order.status) {
    case 'CREATED': return '订单已创建，完成支付后才会进入制作队列。';
    case 'AWAITING_PAYMENT': return '请使用支付宝扫码完成付款。';
    case 'QUEUED': return `前方还有 ${Math.max(0, (order.queuePosition || 1) - 1)} 杯，制作按队列顺序自动派发。`;
    case 'DISPATCHED': return '制作指令已派发，正在等待设备接收。';
    case 'ACCEPTED': return '设备已接受任务并预留整杯原料，即将开始制作。';
    case 'MAKING': return '机器人正在制作，请保持页面打开，完成后及时取杯。';
    case 'HOLD': return '设备回报结果待确认。系统不会在物理结果不确定时自动退款，运营人员正在对账。';
    case 'READY': return '请前往设备取杯，共享物料余量已同步扣减。';
    case 'FAILED': return order.failure?.message || '设备未能完成本次制作，系统将按明确失败策略处理退款。';
    case 'REFUNDED': return '款项已按原路退回支付账户，到账时间以支付平台记录为准。';
    case 'CANCELLED': return '订单已取消，未产生扣款。';
    case 'EXPIRED': return '设备未在时限内接收制作指令，订单已安全终止。';
    default: return '订单状态由云端与终端共同确认。';
  }
}

function bannerFor(order) {
  if (order.status === 'READY') {
    return `<div class="banner ready"><span class="b-icon">${iconCheck}</span><div>
      <strong>制作完成</strong><p>请前往设备取杯。设备中的共享物料余量已同步扣减。</p></div></div>`;
  }
  if (order.status === 'FAILED') {
    return `<div class="banner failed"><span class="b-icon">${iconAlert}</span><div>
      <strong>制作失败</strong><p>${esc(order.failure?.message || '设备未能完成本次制作，系统将按明确失败策略发起退款。')}</p></div></div>`;
  }
  if (order.status === 'HOLD') {
    return `<div class="banner hold"><span class="b-icon">${iconAlert}</span><div>
      <strong>设备结果待确认</strong><p>系统不会在物理结果不确定时自动退款，运营人员正在对账，请留意本页状态更新。</p></div></div>`;
  }
  if (order.status === 'REFUNDED') {
    return `<div class="banner info"><span class="b-icon">${iconInfo}</span><div>
      <strong>退款已完成</strong><p>款项将按原路退回，无需额外操作。</p></div></div>`;
  }
  if (order.status === 'CANCELLED' || order.status === 'EXPIRED') {
    return `<div class="banner failed"><span class="b-icon">${iconAlert}</span><div>
      <strong>${orderLabel(order.status)}</strong><p>${esc(statusNote(order))}</p></div></div>`;
  }
  return '';
}

function renderOrder(order) {
  const params = fragment();
  const token = params.get('token');
  const terminal = [...TERMINAL_STATUSES, 'REFUNDED'].includes(order.status);

  if (['CREATED', 'AWAITING_PAYMENT'].includes(order.status)) {
    /* 支付等待页文案：按 order.payment.provider 区分独立模拟（alipay_mock）与支付宝。
       未拿到 provider 时用中性文案，避免误导；仅文案差异，不改布局、href 与二维码行为。 */
    const provider = order.payment?.provider || '';
    const isMockProvider = provider === 'alipay_mock';
    const payTitle = isMockProvider ? '请完成模拟付款' : provider ? '请完成支付宝付款' : '请完成付款';
    const payLead = isMockProvider ? '仅为模拟付款，不产生真实扣款；确认后后台会按订单流程处理。' : '支付成功前，不会向设备派发制作任务。';
    const payQrAlt = isMockProvider ? '模拟付款二维码' : provider ? '支付宝付款二维码' : '付款二维码';
    const payButton = isMockProvider ? '打开模拟付款页' : provider ? '打开支付宝付款' : '打开付款页';
    document.title = 'Woodbridge Coffee · 等待支付';
    app.innerHTML = `
      ${baseHeader('warn', '等待支付确认')}
      <section class="order-head">
        <div>
          <div class="eyebrow">Secure payment</div>
          <div class="order-no">订单号 ${esc(order.orderNo)}</div>
        </div>
      </section>
      <section class="status-hero">
        <div class="eyebrow">${esc(order.product?.name || '饮品')}</div>
        <h1>${payTitle}</h1>
        <p class="lead">${payLead}</p>
        ${milestoneMarkup(order)}
        <div class="pay-card">
          <div class="pay-amount"><strong>${money({ priceMinor: order.totalAmountMinor, currency: order.currency })}</strong><small>合计</small></div>
          <div class="qr-frame"><img id="payment-qr" alt="${payQrAlt}"></div>
          <p class="qr-note" id="payment-qr-note">二维码加载后保持不变，刷新不会导致重复支付</p>
          <div class="pay-actions">
            ${order.payment?.qrCode
              ? `<a class="btn-primary" href="${esc(order.payment.qrCode)}">${payButton}</a>`
              : '<span class="pay-hint">正在获取付款方式…</span>'}
            <span class="pay-hint">支付状态由服务端实时推送</span>
          </div>
        </div>
      </section>
      <footer class="status-foot">
        <span>支付状态由服务端实时推送，二维码加载后保持不变</span>
        <button class="btn-secondary" id="refresh">刷新状态</button>
      </footer>`;
    document.getElementById('refresh').onclick = loadOrder;
    attachPaymentQr(order, token);
    return;
  }

  document.title = 'Woodbridge Coffee · 订单状态';
  const making = order.status === 'MAKING';
  const overall = order.production?.overallProgress ?? order.production?.progress ?? 0;
  const percent = order.status === 'READY' ? 100 : Math.round(Math.max(0, Math.min(1, overall)) * 100);
  const currentStepId = order.production?.currentStepId;
  const steps = productionSteps(order).slice().sort((a, b) => a.index - b.index);
  const currentIndex = steps.findIndex(step => step.id === currentStepId);

  const timeline = steps.map((step, index) => {
    let state = '';
    if (index === currentIndex && making) state = 'active';
    else if ((currentIndex >= 0 && index < currentIndex && making) || order.status === 'READY') state = 'done';
    return `<li class="${state}">
      <span class="step-dot" aria-hidden="true"></span>
      <div><strong>${esc(step.name)}</strong><small>${state === 'active' ? '正在进行' : state === 'done' ? '已完成' : '待开始'}</small></div>
      <small class="step-sec">${step.duration ? Math.round(step.duration) + ' 秒' : ''}</small>
    </li>`;
  }).join('');

  const remaining = order.production?.remainingSeconds;
  const timing = Number.isFinite(remaining)
    ? `预计还需 ${Math.max(0, Math.ceil(remaining))} 秒`
    : order.production?.plannedDurationSeconds
      ? `单杯计划约 ${Math.ceil(order.production.plannedDurationSeconds / 60)} 分钟`
      : '等待设备返回计划时长';

  app.innerHTML = `
    ${baseHeader(terminal ? 'idle' : '', terminal ? '状态已确认' : '实时同步中')}
    <section class="order-head">
      <div>
        <div class="eyebrow">Live order</div>
        <div class="order-no">订单号 ${esc(order.orderNo)}</div>
      </div>
    </section>
    <section class="status-hero">
      <div class="eyebrow">${esc(order.product?.name || '饮品')}</div>
      <h1>${orderLabel(order.status)}</h1>
      <p class="lead">${esc(statusNote(order))}</p>
      ${milestoneMarkup(order)}
      <div class="progress-wrap">
        <div class="progress-ring" style="--progress:${percent * 3.6}deg" role="img" aria-label="整杯进度 ${percent}%">
          <div><strong>${percent}%</strong><small>整杯进度</small></div>
        </div>
        <div class="now-step">
          <strong>${esc(order.production?.currentStepName || orderLabel(order.status))}</strong>
          <span>${timing}</span>
        </div>
      </div>
    </section>
    ${bannerFor(order)}
    <ol class="timeline" aria-label="制作步骤">${timeline}</ol>
    <div class="ops-card">
      <strong>支付、原料与设备分层确认</strong>
      <p>支付结果由支付平台确认；设备接受任务后才预留整杯物料；制作终态以设备持久化事件为准。</p>
    </div>
    <footer class="status-foot">
      <span>${terminal ? '最终状态已存档' : '制作状态实时刷新'}</span>
      <button class="btn-secondary" id="refresh">刷新状态</button>
    </footer>`;
  document.getElementById('refresh').onclick = loadOrder;
}

function renderError(message, retry = false) {
  document.title = 'Woodbridge Coffee · 出错了';
  app.innerHTML = `
    ${baseHeader('idle', '连接中断')}
    <section class="center-state">
      <div class="error-box">
        <strong>暂时无法继续</strong>
        <p>${esc(message)}</p>
        ${retry ? '<button class="btn-secondary" id="retry">重新连接</button>' : ''}
      </div>
    </section>`;
  if (retry) {
    const node = document.getElementById('retry');
    if (node) node.onclick = () => location.reload();
  }
}

/* 二维码稳定性：同一 paymentId 的 DOM 与 Blob URL 只生成一次；
   初次加载失败后至少 PAYMENT_QR_REFRESH_MS 才允许重试。 */
async function attachPaymentQr(order, token) {
  const image = document.getElementById('payment-qr');
  const paymentId = order.payment?.paymentId;
  if (!image || !paymentId) return;
  const samePayment = paymentQrCache.paymentId === paymentId;
  if (samePayment && paymentQrCache.url) {
    image.src = paymentQrCache.url;
    return;
  }
  const now = Date.now();
  if (samePayment && (paymentQrCache.loading || now - paymentQrCache.loadedAt < PAYMENT_QR_REFRESH_MS)) return;
  paymentQrCache = { paymentId, url: null, loadedAt: now, loading: true };
  setQrNote('正在加载付款二维码…');
  try {
    const response = await fetch(`/api/v1/payments/${encodeURIComponent(paymentId)}/qr`, {
      headers: { 'X-Order-Access-Token': token },
      cache: 'no-store',
    });
    if (!response.ok) {
      paymentQrCache.loading = false;
      setQrNote('二维码暂时无法加载，稍后自动重试');
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    paymentQrCache = { paymentId, url, loadedAt: Date.now(), loading: false };
    const current = document.getElementById('payment-qr');
    if (current) current.src = url;
    setQrNote('二维码加载后保持不变，刷新不会导致重复支付');
  } catch (_) {
    paymentQrCache.loading = false;
    setQrNote('二维码暂时无法加载，稍后自动重试');
  }
}

function setQrNote(text) {
  const note = document.getElementById('payment-qr-note');
  if (note) note.textContent = text;
}

/* 轮询期间：同一 paymentId 且 #payment-qr 仍在文档中时，
   跳过整页重渲染，只补挂二维码，避免 DOM 与 Blob URL 被替换。 */
const renderOrderContent = renderOrder;
let renderedPaymentId = null;
renderOrder = function (order) {
  const paymentWaiting = ['CREATED', 'AWAITING_PAYMENT'].includes(order.status);
  const paymentId = order.payment?.paymentId || null;
  if (paymentWaiting && renderedPaymentId === paymentId && document.getElementById('payment-qr')) {
    attachPaymentQr(order, fragment().get('token'));
    return;
  }
  renderedPaymentId = paymentWaiting ? paymentId : null;
  renderOrderContent(order);
};

/* 页面隐藏时释放 SSE 连接，回到前台时重新加载并订阅。 */
if (typeof document.addEventListener === 'function') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && location.pathname === '/order/status') {
      loadOrder();
    } else if (orderStreamAbort) {
      orderStreamAbort.abort();
    }
  });
}

if (location.pathname === '/order/status') loadOrder();
else loadMenu();
