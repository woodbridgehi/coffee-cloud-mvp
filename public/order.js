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
const i18n = globalThis.CoffeeI18n;
const t = (key, params, options) => i18n.t(key, params, options);
i18n.configure({
  storageKey: 'coffee-order.locale',
  initialLocale: qs.get('lang'),
  enabledLocales: ['zh-CN', 'en-US'],
  fallbackLocale: 'zh-CN',
});

const PAYMENT_QR_REFRESH_MS = 20000;  // 二维码加载失败后的最短重试间隔

let menu = null;
let selected = null;
let submitting = false;
let drinkOptions = {};
let drinkQuote = null;
const optionLabel = key => t(`order.custom.${key}`);
function customizationSummary(options) {
  return Object.entries(options || {}).map(([key, value]) => `${optionLabel(key)}：${key === 'sugar' && value === 'NONE' ? t('order.custom.noSugar') : optionLabel(value)}`).join(' · ');
}
function customizationMarkup() {
  if (!selected?.optionSchema) return '';
  return `<section class="customization-panel" aria-label="${t('order.custom.aria')}">
    <h2>${t('order.custom.title')}</h2><p>${esc(t(`order.custom.temperature.${selected.optionSchema.temperature}`))}</p>
    ${Object.entries(selected.optionSchema.options).map(([key, rule]) => `<label>${esc(optionLabel(key))}<select data-drink-option="${key}" ${submitting ? 'disabled' : ''}>${rule.values.map(value => `<option value="${value}" ${drinkOptions[key] === value ? 'selected' : ''}>${esc(key === 'sugar' && value === 'NONE' ? t('order.custom.noSugar') : optionLabel(value))}</option>`).join('')}</select></label>`).join('')}
    <p>${esc(t('order.custom.notice'))}</p>
    <p role="status">${drinkQuote ? `${esc(customizationSummary(drinkQuote.product.customization))} · ${money(drinkQuote.product)} · ${duration(drinkQuote.product)} · ${drinkQuote.available ? (t('order.custom.ready')) : (t('order.custom.unavailable'))}` : (t('order.custom.beforeQuote'))}</p>
  </section>`;
}
let orderStreamAbort = null;
let orderStreamReconnectTimer = null;
let orderStreamTerminal = false;
let readyRedirectTimer = null;
let artSeq = 0;
let paymentQrCache = { paymentId: null, url: null, loadedAt: 0, loading: false };
let hasNotifiedReady = false;

const TERMINAL_STATUSES = ['READY', 'FAILED', 'CANCELLED', 'EXPIRED'];
const orderIsFinished = order => [...TERMINAL_STATUSES, 'REFUNDED'].includes(order.status)
  && !(order.status === 'READY' && order.pickupRequired && !order.collectedAt);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]
));

/* ---------- 本地活跃订单缓存与安全恢复 ---------- */

function safeStorageGet(key) {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) return localStorage.getItem(key);
  } catch (_) {}
  return null;
}

function safeStorageSet(key, value) {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) localStorage.setItem(key, value);
  } catch (_) {}
}

function safeStorageRemove(key) {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) localStorage.removeItem(key);
  } catch (_) {}
}

function getActiveOrder(targetDeviceId) {
  if (!targetDeviceId) return null;
  const raw = safeStorageGet(`coffee_active_order:${targetDeviceId}`);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    if (!data || !data.orderId || !data.token) return null;
    if (Date.now() - (data.updatedAt || 0) > 18 * 3600 * 1000) {
      clearActiveOrder(targetDeviceId);
      return null;
    }
    if (['REFUNDED', 'CANCELLED', 'EXPIRED'].includes(data.status)) {
      clearActiveOrder(targetDeviceId);
      return null;
    }
    return data;
  } catch (_) {
    return null;
  }
}

function saveActiveOrder(order, token, targetDeviceId) {
  const dId = targetDeviceId || order?.deviceId || deviceId;
  if (!dId || !order || !order.orderId || !token) return;
  const entry = {
    orderId: order.orderId,
    orderNo: order.orderNo,
    token,
    deviceId: dId,
    status: order.status,
    collectedAt: order.collectedAt,
    productName: order.product?.name || t('order.product.generic'),
    pickupCode: pickupCodeFor(order),
    totalAmountMinor: order.totalAmountMinor,
    currency: order.currency,
    updatedAt: Date.now(),
  };
  safeStorageSet(`coffee_active_order:${dId}`, JSON.stringify(entry));
}

function clearActiveOrder(targetDeviceId) {
  const dId = targetDeviceId || deviceId;
  if (dId) safeStorageRemove(`coffee_active_order:${dId}`);
}

function notifyReadySensory() {
  if (hasNotifiedReady) return;
  hasNotifiedReady = true;

  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    try { navigator.vibrate([200, 100, 200, 100, 300]); } catch (_) {}
  }


}

/* ---------- 基础请求 ---------- */

async function request(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  let data = {};
  try { data = await response.json(); } catch (_) { /* 非 JSON 响应 */ }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : (data.detail?.code || t('order.error.request'));
    const error = new Error(detail); error.status = response.status; throw error;
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
  return min === max ? t('order.duration.single', { minutes: min }) : t('order.duration.range', { min, max });
}

function statusText(reason) {
  return t(`order.availability.${reason}`, {}, { defaultValue: t('order.availability.unknown') });
}

function money(item) {
  const minor = item.priceMinor ?? item.totalAmountMinor;
  if ((typeof minor !== 'number' && typeof minor !== 'string') ||
      (typeof minor === 'string' && minor.trim() === '') || !Number.isSafeInteger(Number(minor))) return '—';
  const currency = item.currency || 'CNY';
  return i18n.formatMoney(Number(minor), currency);
}

function orderLabel(status) {
  return t(`order.status.${status}`, {}, { defaultValue: status });
}

/* ---------- 品牌与图形 ---------- */

const brandCoffeeSvg = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <path d="M4 9h12v6.5a4.5 4.5 0 0 1-4.5 4.5h-3A4.5 4.5 0 0 1 4 15.5V9Z" fill="currentColor" opacity=".92"/>
  <path d="M16 10.5h1.8a2.7 2.7 0 0 1 0 5.4H16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M7.5 6c0-1.2 1-1.6 1-2.8M11 6c0-1.2 1-1.6 1-2.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
</svg>`;

const orderSoundControls=document.getElementById('sound-controls');
function mountHeaderControls(){
  const header=document.querySelector?.('.devicebar');
  if(!header || !orderSoundControls?.querySelector)return;
  if(!orderSoundControls.querySelector('details')){
    const volume=orderSoundControls.querySelector('input[type=range]'),voice=orderSoundControls.querySelector('label');
    const details=document.createElement('details'),summary=document.createElement('summary'),panel=document.createElement('div');
    summary.textContent='•••';panel.className='sound-options';details.append(summary,panel);
    if(volume)panel.append(volume);if(voice)panel.append(voice);orderSoundControls.append(details);
  }
  orderSoundControls.querySelector('button').dataset.label=t('order.sound.label');
  orderSoundControls.querySelector('summary').setAttribute('aria-label',t('order.sound.settings'));
  header.querySelector('.order-language').before(orderSoundControls);orderSoundControls.hidden=false;
}
let pickupDialog=null,pickupDialogOrder=null;
const dismissedPickup=new Set();
function showPickup(order){
  if(!document.createElement || !document.body)return;
  const code=pickupCodeFor(order),id=order.orderId || order.orderNo;
  if(!code){if(pickupDialog?.open)pickupDialog.close();return;}
  if(dismissedPickup.has(id))return;
  if(!pickupDialog){
    pickupDialog=document.createElement('dialog');pickupDialog.className='pickup-dialog';
    pickupDialog.setAttribute('aria-labelledby','pickup-dialog-title');
    pickupDialog.innerHTML='<button type="button" class="pickup-card pickup-action"><span id="pickup-dialog-title" class="pc-label"></span><strong class="pc-code"></strong><span class="pc-sub"></span></button>';
    pickupDialog.addEventListener('close',()=>{if(pickupDialogOrder)dismissedPickup.add(pickupDialogOrder);});
    document.body.append(pickupDialog);
  }
  pickupDialogOrder=id;
  pickupDialog.querySelector('.pc-label').textContent=t('order.status.pickupLabel');
  pickupDialog.querySelector('.pc-code').textContent=code;
  pickupDialog.querySelector('.pc-sub').textContent=t('order.pickup.returnMenu');
  pickupDialog.querySelector('button').onclick=()=>{
    dismissedPickup.add(id);pickupDialog.close();
    location.href=`/order?device_id=${encodeURIComponent(order.deviceId || deviceId || '')}`;
  };
  if(!pickupDialog.open)pickupDialog.showModal();
}

function baseHeader(pillClass, pillText, sub) {
  return `<header class="devicebar">
    <span class="db-logo" aria-hidden="true">${brandCoffeeSvg}</span>
    <div class="db-info">
      <strong>Woodbridge Coffee</strong>
      <span class="db-sub">${sub ? sub : t('order.header.default')}</span>
    </div>
    <label class="order-language">
      <select id="order-language" aria-label="${esc(t('common.language.label'))}">
        <option value="zh-CN" ${i18n.getLocale() === 'zh-CN' ? 'selected' : ''}>${t('order.language.short')}</option>
        <option value="en-US" ${i18n.getLocale() === 'en-US' ? 'selected' : ''}>EN</option>
      </select>
    </label>
    <span class="db-pill ${pillClass}"><span class="dot" aria-hidden="true"></span><span class="lp-text">${esc(pillText)}</span></span>
  </header>`;
}

if (typeof document.addEventListener === 'function') {
  document.addEventListener('change', event => {
    if (event.target?.id !== 'order-language') return;
    i18n.setLocale(event.target.value);
    if (location.pathname === '/order/status') loadOrder();
    else renderMenu();
  });
}

/* 杯型 SVG：按设备上报的 visual.profile 绘制，富有层次与微质感 */
function drinkArt(profileId) {
  const uid = `dg-${profileId}-${++artSeq}`;
  const themes = {
    americano: {
      c1: '#6f3d1b', c2: '#351a0b', surface: '#542d13', scale: 1,
      crema: '<ellipse cx="44" cy="30" rx="19.5" ry="4.5" fill="#a47148" opacity=".7"/>',
      deco: '<path d="M24 38v44" stroke="rgba(255,255,255,.2)" stroke-width="2.5" stroke-linecap="round"/>',
    },
    espresso: {
      c1: '#442211', c2: '#220e05', surface: '#36190a', scale: 0.82,
      crema: '<ellipse cx="44" cy="30" rx="17" ry="4" fill="#915b32" opacity=".85"/>',
      deco: '<ellipse cx="44" cy="30" rx="9" ry="2.2" fill="#c38852" opacity=".6"/>',
    },
    'iced-latte': {
      c1: '#ba8e63', c2: '#784c2a', surface: '#cda882', scale: 1,
      crema: '<ellipse cx="44" cy="30" rx="19.5" ry="4.5" fill="#f5ede3" opacity=".95"/>',
      deco: `<g opacity=".9">
        <rect x="29" y="40" width="13" height="13" rx="3.5" fill="#ffffff" opacity=".8" transform="rotate(12 35 46)"/>
        <rect x="43" y="52" width="13" height="13" rx="3.5" fill="#ffffff" opacity=".7" transform="rotate(-15 49 58)"/>
        <path d="M24 38v48" stroke="rgba(255,255,255,.28)" stroke-width="2.5" stroke-linecap="round"/>
        <ellipse cx="44" cy="30" rx="12" ry="2.6" fill="#8e5a32" opacity=".4"/>
      </g>`,
    },
    'hazelnut-special': {
      c1: '#8c5328', c2: '#4a250c', surface: '#a36d3b', scale: 1,
      crema: '<ellipse cx="44" cy="30" rx="19.5" ry="4.5" fill="#f8eedf"/>',
      deco: `<g>
        <path d="M30 29c4 3 9 3 14 1s9-2 13 1" stroke="#b87b3a" stroke-width="2.2" fill="none" stroke-linecap="round"/>
        <circle cx="44" cy="27" r="2" fill="#834617" opacity=".7"/>
        <path d="M24 38v48" stroke="rgba(255,255,255,.24)" stroke-width="2.5" stroke-linecap="round"/>
      </g>`,
    },
    generic: {
      c1: '#7d5c3f', c2: '#422815', surface: '#63472c', scale: 1,
      crema: '<ellipse cx="44" cy="30" rx="19.5" ry="4.5" fill="#dfcfbe" opacity=".8"/>',
      deco: '<path d="M24 38v48" stroke="rgba(255,255,255,.2)" stroke-width="2.5" stroke-linecap="round"/>',
    },
  };
  const t = themes[profileId] || themes.generic;
  const w = Math.round(64 * t.scale), h = Math.round(86 * t.scale);
  return `<svg width="${w}" height="${h}" viewBox="0 0 88 118" aria-hidden="true">
    <defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${t.c1}"/><stop offset="1" stop-color="${t.c2}"/>
    </linearGradient></defs>
    <ellipse cx="44" cy="109" rx="27" ry="4.5" fill="#00000014"/>
    <g transform="translate(${44 - 44 * t.scale} ${109 - 109 * t.scale}) scale(${t.scale})">
      <path d="M67 44c13 0 15 17 2 22" fill="none" stroke="#e8dcce" stroke-width="6.5" stroke-linecap="round"/>
      <path d="M20 30h48v60a10 10 0 0 1-10 10H30a10 10 0 0 1-10-10V30Z" fill="url(#${uid})"/>
      <path d="M20 30h48v8H20z" fill="#fdf8f0" opacity=".92"/>
      <ellipse cx="44" cy="30" rx="24" ry="6.5" fill="#fffdf8"/>
      <ellipse cx="44" cy="30" rx="18.5" ry="4.4" fill="${t.surface}"/>
      ${t.crema || ''}
      ${t.deco || ''}
    </g>
  </svg>`;
}

function pickupCodeFor(order) {
  if (order?.status !== 'READY' || order?.collectedAt) return '';
  const raw = String(order?.orderNo || order?.orderId || '').trim();
  if (!raw) return '—';
  const hyphenParts = raw.split('-');
  if (hyphenParts.length >= 2) {
    const last = hyphenParts[hyphenParts.length - 1];
    return last.length >= 4 ? last.slice(0, 4).toUpperCase() : last.toUpperCase();
  }
  const digits = raw.match(/\d{3,4}$/);
  if (digits) return digits[0];
  return raw.slice(-4).toUpperCase();
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
    renderError(t('order.error.deviceMissing'));
    return;
  }
  try {
    menu = await request(`/api/v1/public/devices/${encodeURIComponent(deviceId)}/menu`);
    renderMenu();
  } catch (error) {
    renderError(t('order.error.menu', { message: error.message }));
  }
}

function renderMenu(menuData) {
  if (menuData) menu = menuData;
  if (!menu) return;
  document.title = t('order.title.menu');
  const online = menu.paymentMode === 'ONLINE';
  const available = (menu.products || []).filter(p => p.available);
  const availableDrinkTypes = available.length;
  const sellable = menu.salesEnabled && available.length > 0;
  const targetDeviceId = (menu && (menu.deviceId || menu.storeId)) || deviceId;
  const activeOrder = getActiveOrder(targetDeviceId);
  const activeBannerHtml = activeOrder ? `
    <aside class="active-order-banner" aria-label="${esc(t('order.active.aria'))}">
      <div class="aob-main">
        <div class="aob-header">
          <span class="aob-pulse-dot" aria-hidden="true"></span>
          <span class="aob-tag">${t('order.active.label')}</span>
        </div>
        <strong class="aob-code">${esc(activeOrder.status === 'READY' ? pickupCodeFor(activeOrder) : orderLabel(activeOrder.status))}</strong>
        <span class="aob-sub">${esc(activeOrder.productName || t('order.product.generic'))} · ${orderLabel(activeOrder.status)}</span>
      </div>
      <a class="aob-btn" href="/order/status#order=${encodeURIComponent(activeOrder.orderId)}&token=${encodeURIComponent(activeOrder.token)}">${t('order.active.view')}</a>
    </aside>` : '';

  app.innerHTML = `
    ${baseHeader(menu.online ? '' : 'warn', menu.online ? t('order.header.online') : t('order.header.offline'), esc(menu.storeId || menu.deviceId || ''))}
    <main class="page-main has-checkout">
      ${activeBannerHtml}
      <section class="hero">
        <div class="hero-kicker">${t('order.menu.kicker')}</div>
        <h1>${t('order.menu.title')}</h1>

      </section>
      <section class="machine-card" aria-label="${esc(t('order.menu.machineAria'))}">
        <div class="machine-meta">
          <span class="status-dot ${menu.online ? 'online' : ''}" aria-hidden="true"></span>
          <div>
            <strong>${menu.online ? t('order.menu.online') : t('order.menu.offline')}</strong>
            <small>${t('order.menu.deviceStatus', { status: esc(menu.deviceStatus || 'UNKNOWN') })}</small>
          </div>
        </div>
        <div class="stock-summary">
          <strong>${availableDrinkTypes}</strong>
          <small>${t('order.menu.availableDrinkTypes')}</small>
        </div>
      </section>
      <div class="section-title">
        <h2>${t('order.menu.available')}</h2>
        <span>${menu.materialAlertCount ? t('order.menu.materialAlert') : t('order.menu.materialOk')}</span>
      </div>
      ${menu.products.length ? `<section class="drink-list">${menu.products.map(card).join('')}</section>`
        : `<section class="center-state" style="min-height:32vh"><p>${t('order.menu.noProducts')}</p></section>`}
      ${customizationMarkup()}

      ${online ? '' : `<div class="notice">${t('order.menu.testNotice')}</div>`}

    </main>
    <section class="checkout" aria-label="${esc(t('order.menu.checkoutAria'))}">
      <div class="checkout-copy">
        <strong>${selected ? esc(selected.name) : t('order.menu.selectDrink')}</strong>
        <small>${selected ? (online ? money(drinkQuote?.product || selected) : t('order.menu.testFree')) : (online ? t('order.menu.alipay') : t('order.menu.testPayment'))}</small>
      </div>
      <button id="submit" class="btn-primary" ${selected && !submitting ? '' : 'disabled'}>
        ${submitting ? '<span class="btn-spinner" aria-hidden="true"></span>' : ''}
        ${selected?.optionSchema && !drinkQuote && !submitting ? (t('order.custom.getQuote')) : submitting ? (online ? t('order.menu.creatingPayment') : t('order.menu.submitting')) : (online ? t('order.menu.confirmPay') : t('order.menu.confirm'))}
      </button>
    </section>`;

  document.querySelectorAll('.drink-card').forEach(node => {
    node.onclick = () => selectDrink(node.dataset.id);
  });
  document.querySelectorAll('[data-drink-option]').forEach(node => {
    node.onchange = () => { drinkOptions[node.dataset.drinkOption] = node.value; drinkQuote = null; renderMenu(); };
  });
  mountHeaderControls();
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
    <button class="drink-card ${isSelected ? 'selected' : ''}" data-id="${esc(item.recipeId)}" ${item.available && !submitting ? '' : 'disabled'} aria-pressed="${isSelected ? 'true' : 'false'}">
      <div class="drink-art">${drinkArt(profile(item.visual?.profile))}</div>
      <div class="drink-copy">
        <h4>${esc(item.name || item.recipeId)}</h4>
        <p class="desc">${esc(item.description || t('order.product.localRecipe'))}</p>
        <div class="drink-facts">
          <span class="fact time">${iconClock}${t('order.menu.estimated', { duration: duration(item) })}</span>
          ${item.available
            ? `<span class="fact price">${money(item)}</span>`
            : `<span class="fact block">${statusText(unavailable)}</span>`}
        </div>
      </div>
      <div class="drink-side">
        <span class="remaining">${item.remainingServings ?? 0}</span>
        <small class="unit">${t('order.menu.remaining')}</small>
        <span class="select-ring" aria-hidden="true">${iconCheck}</span>
      </div>
    </button>`;
}

function selectDrink(id) {
  selected = menu.products.find(p => p.recipeId === id && p.available) || null;
  drinkOptions = Object.fromEntries(Object.entries(selected?.optionSchema?.options || {}).map(([key, rule]) => [key, rule.default]));
  drinkQuote = null;
  renderMenu();
}

async function submitOrder() {
  if (!selected || submitting) return;
  if (drinkQuote && !drinkQuote.available) drinkQuote = null;
  if (selected.optionSchema && !drinkQuote) {
    submitting = true; renderMenu();
    try {
      const draftKey = `coffee-quote:${deviceId}:${selected.recipeId}:${selected.recipeVersion}:${JSON.stringify(drinkOptions)}`;
      let savedQuote = null;
      try { savedQuote = JSON.parse(sessionStorage.getItem(draftKey) || 'null'); } catch (_) {}
      drinkQuote = (savedQuote?.available ? savedQuote : null) || await request(`/api/v1/public/devices/${encodeURIComponent(deviceId)}/quotes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipeId: selected.recipeId, recipeVersion: selected.recipeVersion, customization: drinkOptions, paymentMode: menu.paymentMode }),
      });
      sessionStorage.setItem(draftKey, JSON.stringify(drinkQuote));
    } catch (error) { toast(error.message, 'error'); }
    submitting = false; renderMenu(); return;
  }
  if (drinkQuote && !drinkQuote.available) return;
  submitting = true;
  renderMenu();
  /* 幂等键与会话共存：重试不会重复创建订单 */
  const storageKey = `coffee-order-request:${deviceId}:${selected.recipeId}:${JSON.stringify(drinkOptions)}:${drinkQuote?.quoteId || "legacy"}`;
  let key = sessionStorage.getItem(storageKey);
  if (!key) {
    key = crypto.randomUUID();
    sessionStorage.setItem(storageKey, key);
  }
  let orderCreated = false;
  try {
    const paymentMode = menu.paymentMode === 'ONLINE' ? 'ONLINE' : 'TEST_FREE';
    const order = await request(`/api/v1/public/devices/${encodeURIComponent(deviceId)}/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify({ recipeId: selected.recipeId, recipeVersion: selected.recipeVersion, quantity: 1, paymentMode, ...(drinkQuote ? { customization: drinkOptions, quoteId: drinkQuote.quoteId } : {}) }),
    });
    orderCreated = true;
    saveActiveOrder(order, order.accessToken, deviceId);
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
    sessionStorage.removeItem(`coffee-quote:${deviceId}:${selected.recipeId}:${selected.recipeVersion}:${JSON.stringify(drinkOptions)}`);
    saveActiveOrder(order, order.accessToken, deviceId);
    location.href = `/order/status#order=${encodeURIComponent(order.orderId)}&token=${encodeURIComponent(order.accessToken)}${payment ? `&payment=${encodeURIComponent(payment.paymentId)}` : ''}`;
  } catch (error) {
    submitting = false;
    if (!orderCreated && error.status === 409) {
      sessionStorage.removeItem(`coffee-quote:${deviceId}:${selected.recipeId}:${selected.recipeVersion}:${JSON.stringify(drinkOptions)}`);
      drinkQuote = null;
    }
    renderMenu();
    toast(t('order.error.submit', { message: error.message }), 'error');
  }
}

/* ---------- 订单状态页 ---------- */

function fragment() {
  return new URLSearchParams(location.hash.replace(/^#/, ''));
}

async function loadOrder() {
  const params = fragment();
  let orderId = params.get('order');
  let token = params.get('token');
  if (!orderId || !token) {
    const cached = getActiveOrder(deviceId);
    if (cached && cached.orderId && cached.token) {
      location.hash = `#order=${encodeURIComponent(cached.orderId)}&token=${encodeURIComponent(cached.token)}`;
      orderId = cached.orderId;
      token = cached.token;
    } else {
      renderError(t('order.error.link'));
      return;
    }
  }
  try {
    const order = await request(`/api/v1/public/orders/${encodeURIComponent(orderId)}`, {
      headers: { 'X-Order-Access-Token': token },
    });
    saveActiveOrder(order, token, order.deviceId || deviceId);
    renderOrder(order);
    orderStreamTerminal = orderIsFinished(order);
    if (!orderStreamTerminal) startOrderStream(orderId, token);
  } catch (error) {
    globalThis.CoffeeRobotIntegration?.disconnected();
    globalThis.CoffeeSound?.disconnect();
    renderError(t('order.error.status', { message: error.message }), true);
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
        orderStreamTerminal = orderIsFinished(order);
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
    globalThis.CoffeeRobotIntegration?.disconnected();
    globalThis.CoffeeSound?.disconnect();
    orderStreamReconnectTimer = setTimeout(() => startOrderStream(orderId, token), 3000);
  }
}

/* 设备权威的步骤计划：优先使用设备上报的 stepName */
function productionSteps(order) {
  const planned = order.production?.stepPlan || order.production?.stepDurations || [];
  if (planned.length) {
    return planned.map((step, index) => ({
      id: step.stepId,
      name: step.stepName || step.stepId?.replaceAll('-', ' ') || t('order.step.generic'),
      index: Number.isInteger(step.stepIndex) ? step.stepIndex : index,
      duration: step.durationSeconds,
    }));
  }
  const visual = order.product?.visual?.profile;
  return visual === 'iced-latte' ? [
    { id: 'prepare-cup', name: t('order.step.prepare-cup'), index: 0 },
    { id: 'add-ice', name: t('order.step.add-ice'), index: 1 },
    { id: 'extract-coffee', name: t('order.step.extract-coffee'), index: 2 },
    { id: 'add-milk', name: t('order.step.add-milk'), index: 3 },
    { id: 'seal-and-serve', name: t('order.step.seal-and-serve'), index: 4 },
  ] : [
    { id: 'prepare-cup', name: t('order.step.prepare-cup'), index: 0 },
    { id: 'extract-coffee', name: t('order.step.extract-coffee'), index: 1 },
    { id: 'finish', name: t('order.step.finish'), index: 2 },
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
  const labels = ['pay', 'queue', 'dispatch', 'accept', 'make', 'done'].map(key => t(`order.milestone.${key}`));
  if (order.paymentMode === 'TEST_FREE') labels[0] = t('order.milestone.submit');
  const failed = ['FAILED', 'CANCELLED', 'EXPIRED'].includes(order.status) || (order.status === 'REFUNDED' && !!order.failure);
  let current = Math.max(0, MILESTONE_DEFS.findIndex(m => m.at.includes(order.status)));
  if (failed) {
    const reached = (order.timeline || []).map(event => MILESTONE_DEFS.findIndex(m => m.at.includes(event.to))).filter(i => i >= 0 && i < 5);
    current = Math.max(0, ...reached);
    if (order.production?.startedAt || (order.production?.overallProgress || 0) > 0) current = 4;
    else if (order.production?.acceptedAt || order.production?.status === 'REJECTED') current = Math.max(current, 3);
  }
  return `<ol class="milestones" aria-label="${esc(t('order.milestone.aria'))}">${labels.map((label, index) => {
    let state = '';
    if (index < current) state = 'done';
    else if (index === current) state = failed ? 'error' : order.status === 'READY' || order.status === 'REFUNDED' ? 'done' : 'active';
    return `<li class="milestone ${state}"><span class="m-dot" aria-hidden="true"></span><span>${label}</span></li>`;
  }).join('')}</ol>`;
}

function statusNote(order) {
  if (order.status === 'FAILED' && order.failure?.message) return order.failure.message;
  const params = order.status === 'QUEUED' ? { count: order.queue?.aheadCount ?? Math.max(0, (order.queuePosition || 1) - 1) } : {};
  return t(`order.note.${order.status}`, params, { defaultValue: t('order.note.default') });
}

function bannerFor(order) {
  if (order.status === 'READY') {
    return `<div class="banner ready"><span class="b-icon">${iconCheck}</span><div>
      <strong>${t(order.collectedAt ? 'order.pickup.collected' : 'order.banner.readyTitle')}</strong><p>${t(order.collectedAt ? 'order.pickup.collected' : 'order.note.READY')}</p></div></div>`;
  }
  if (order.status === 'FAILED') {
    return `<div class="banner failed"><span class="b-icon">${iconAlert}</span><div>
      <strong>${t('order.banner.failedTitle')}</strong><p>${esc(order.failure?.message || t('order.banner.failedBody'))}</p></div></div>`;
  }
  if (order.status === 'HOLD') {
    return `<div class="banner hold"><span class="b-icon">${iconAlert}</span><div>
      <strong>${t('order.banner.holdTitle')}</strong><p>${t('order.banner.holdBody')}</p></div></div>`;
  }
  if (order.status === 'REFUNDED') {
    return `<div class="banner info"><span class="b-icon">${iconInfo}</span><div>
      <strong>${t('order.status.REFUNDED')}</strong><p>${t('order.banner.refundedBody')}</p></div></div>`;
  }
  if (order.status === 'CANCELLED' || order.status === 'EXPIRED') {
    return `<div class="banner failed"><span class="b-icon">${iconAlert}</span><div>
      <strong>${orderLabel(order.status)}</strong><p>${esc(statusNote(order))}</p></div></div>`;
  }
  return '';
}

function scheduleReadyRedirect(order) {
  if (readyRedirectTimer) {
    clearInterval(readyRedirectTimer);
    readyRedirectTimer = null;
  }
  // 不定时跳转；由顾客点击取杯码返回菜单，订单取杯状态由设备确认
}

function renderOrder(order) {
  const params = fragment();
  const token = params.get('token');
  const terminal = orderIsFinished(order);

  if (['CREATED', 'AWAITING_PAYMENT'].includes(order.status)) {
    /* 支付等待页文案：按 order.payment.provider 区分独立模拟（alipay_mock）与支付宝。
       未拿到 provider 时用中性文案，避免误导；仅文案差异，不改布局、href 与二维码行为。 */
    const provider = order.payment?.provider || '';
    const isMockProvider = provider === 'alipay_mock';
    const isAlipayProvider = provider === 'alipay';
    const payTitle = isMockProvider ? t('order.payment.mockTitle') : isAlipayProvider ? t('order.payment.alipayTitle') : t('order.payment.title');
    const payLead = isMockProvider ? t('order.payment.mockLead') : t('order.payment.lead');
    const payQrAlt = isMockProvider ? t('order.payment.mockQr') : isAlipayProvider ? t('order.payment.alipayQr') : t('order.payment.qr');
    const payButton = isMockProvider ? t('order.payment.openMock') : isAlipayProvider ? t('order.payment.openAlipay') : t('order.payment.open');
    const payTag = isMockProvider ? `<span class="pay-tag mock">${t('order.payment.mockTag')}</span>`
      : isAlipayProvider ? `<span class="pay-tag live">${t('order.payment.alipayTag')}</span>` : '';
    document.title = t('order.title.payment');
    app.innerHTML = `
      ${baseHeader('warn', t('order.header.paymentWaiting'), t('order.header.order', { orderNo: esc(order.orderNo) }))}
      <main class="page-main">
        <div class="pay-grid">
          <section class="pay-order-card" aria-label="${esc(t('order.payment.orderAria'))}">
            <h1>${payTitle}</h1>
            ${isMockProvider ? `<p class="lead">${payLead}</p>` : ''}
            <div class="pay-product-row">
              <span class="pp-name">
                <strong>${esc(order.product?.name || t('order.product.drink'))} × 1</strong>

              </span>
              <span class="pay-amount"><strong>${money({ priceMinor: order.totalAmountMinor, currency: order.currency })}</strong><small>${t('order.payment.total')}</small></span>
            </div>
            ${milestoneMarkup(order)}
            <div class="pay-side-actions">
              <button class="btn-secondary" id="refresh">${t('order.payment.refresh')}</button>

            </div>
          </section>
          <aside class="pay-panel" aria-label="${esc(t('order.payment.panelAria'))}">
            <div class="pay-panel-head"><strong>${t('order.payment.method')}</strong>${payTag}</div>
            <div class="pay-mobile-cta">
              ${order.payment?.qrCode
                ? `<a class="btn-primary btn-alipay-cta" href="${esc(order.payment.qrCode)}">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15-5-5 1.41-1.41L11 14.17l7.59-7.59L20 8l-9 9z"/></svg>
                    <span>${payButton}</span>
                  </a>
`
                : `<span class="pay-hint">${t('order.payment.loadingMethod')}</span>`}
            </div>
            <details class="pay-qr-accordion" open>
              <summary class="pay-qr-summary">${t('order.payment.otherDevice')}</summary>
              <div class="pay-qr-body">
                <div class="qr-frame"><img id="payment-qr" alt="${payQrAlt}"></div>
                <p class="qr-note" id="payment-qr-note">${t('order.payment.qrStable')}</p>
              </div>
            </details>
          </aside>
        </div>
      </main>`;
    document.getElementById('refresh').onclick = loadOrder;
    attachPaymentQr(order, token);
    return;
  }

  document.title = t('order.title.status');
  const making = order.status === 'MAKING';
  const failed = order.status === 'FAILED' || (order.status === 'REFUNDED' && !!order.failure);
  const overall = order.production?.overallProgress ?? order.production?.progress ?? 0;
  const percent = order.status === 'READY' ? 100 : Math.round(Math.max(0, Math.min(1, overall)) * 100);
  const currentStepId = order.production?.currentStepId;
  const steps = productionSteps(order).slice().sort((a, b) => a.index - b.index);
  const currentIndex = steps.findIndex(step => step.id === currentStepId);

  const timeline = steps.map((step, index) => {
    let state = '';
    if (index === currentIndex && making) state = 'active';
    else if (index === currentIndex && failed) state = 'error';
    else if ((currentIndex >= 0 && index < currentIndex && (making || failed)) || order.status === 'READY') state = 'done';
    return `<li class="${state}">
      <span class="step-dot" aria-hidden="true"></span>
      <div><strong>${esc(step.name)}</strong><small>${state === 'active' ? t('order.step.active') : state === 'done' ? t('order.step.done') : state === 'error' ? t('order.step.failed') : t('order.step.pending')}</small></div>
      <small class="step-sec">${step.duration ? t('order.step.seconds', { seconds: Math.round(step.duration) }) : ''}</small>
    </li>`;
  }).join('');

  const remaining = order.production?.remainingSeconds;
  const timing = terminal && order.status !== 'READY' ? t('order.timing.stopped') : Number.isFinite(remaining)
    ? t('order.timing.remaining', { seconds: Math.max(0, Math.ceil(remaining)) })
    : order.production?.plannedDurationSeconds
      ? t('order.timing.planned', { minutes: Math.ceil(order.production.plannedDurationSeconds / 60) })
      : t('order.timing.waiting');

function flavorPillsFor(product) {
  if (product?.customization) return `<div class="customization-panel">${esc(customizationSummary(product.customization))}</div>`;
  const visualProfile = profile(product?.visual?.profile);
  if (visualProfile === 'iced-latte') {
    return `<div class="flavor-pills">
      <span class="flavor-pill">${t('order.flavor.latte1')}</span>
      <span class="flavor-pill">${t('order.flavor.latte2')}</span>
      <span class="flavor-pill">${t('order.flavor.latte3')}</span>
    </div>
    <div class="recipe-bar-wrap">
      <div class="recipe-bar-label"><span>${t('order.flavor.ratio')}</span><span>${t('order.flavor.latteRatio')}</span></div>
      <div class="recipe-bar"><div class="recipe-bar-part espresso" style="width:25%"></div><div class="recipe-bar-part milk" style="width:60%"></div><div class="recipe-bar-part foam" style="width:15%"></div></div>
    </div>`;
  }
  if (visualProfile === 'americano') {
    return `<div class="flavor-pills">
      <span class="flavor-pill">${t('order.flavor.americano1')}</span>
      <span class="flavor-pill">${t('order.flavor.americano2')}</span>
      <span class="flavor-pill">${t('order.flavor.americano3')}</span>
    </div>
    <div class="recipe-bar-wrap">
      <div class="recipe-bar-label"><span>${t('order.flavor.ratio')}</span><span>${t('order.flavor.americanoRatio')}</span></div>
      <div class="recipe-bar"><div class="recipe-bar-part espresso" style="width:35%"></div><div class="recipe-bar-part water" style="width:65%"></div></div>
    </div>`;
  }
  if (visualProfile === 'espresso') {
    return `<div class="flavor-pills">
      <span class="flavor-pill">${t('order.flavor.espresso1')}</span>
      <span class="flavor-pill">${t('order.flavor.espresso2')}</span>
      <span class="flavor-pill">${t('order.flavor.espresso3')}</span>
    </div>`;
  }
  return `<div class="flavor-pills">
    <span class="flavor-pill">${t('order.flavor.generic1')}</span>
    <span class="flavor-pill">${t('order.flavor.generic2')}</span>
    <span class="flavor-pill">${t('order.flavor.generic3')}</span>
  </div>`;
}

function barcodeMarkup() {
  const widths = [2, 1, 3, 1, 2, 4, 1, 2, 1, 3, 2, 1, 4, 1, 2, 3, 1, 2, 1, 3, 2, 1, 4, 1, 2];
  return `<div class="ticket-barcode" aria-hidden="true">${widths.map(w => `<span style="width:${w}px"></span>`).join('')}</div>`;
}

  app.innerHTML = `
    ${baseHeader(terminal ? 'idle' : '', terminal ? t('order.header.confirmed') : t('order.header.syncing'), t('order.header.order', { orderNo: esc(order.orderNo) }))}
    <main class="page-main">
      ${bannerFor(order)}
      ${order.status !== 'QUEUED' ? `<div class="scene-toolbar"><div id="view-mode" class="view-segment" role="group" aria-label="${esc(t('order.view.label'))}"><button type="button" data-order-view="3d">3D</button><button type="button" data-order-view="2d">2D</button></div></div><div id="order-scene"></div>` : ''}
      <div class="status-grid">
        <section class="status-card ticket-card" aria-label="${esc(t('order.status.progressAria'))}">
          <div class="ticket-header-ribbon">
            <span>WOODBRIDGE ROASTERY</span>
            <span>ORDER NO. ${esc(order.orderNo)}</span>
          </div>
          ${pickupCodeFor(order) ? `<div class="pickup-card" aria-label="${esc(t('order.status.pickupAria'))}">
            <span class="pc-label">${t('order.status.pickupLabel')}</span>
            <strong class="pc-code">${esc(pickupCodeFor(order))}</strong>
            <span class="pc-sub">${t('order.status.pickupHelp')}</span>
          </div>` : ''}
          ${order.failure ? `<div class="order-failure" role="status"><strong>${t('order.failure.title')}</strong><p>${esc(order.failure.message || t('order.banner.failedBody'))}</p><small>${t('order.failure.code')}: ${esc(order.failure.code || 'PRODUCTION_FAILED')}</small></div>` : ''}
          ${flavorPillsFor(order.product)}
          <p class="ticket-product">${esc(order.product?.name || t('order.product.drink'))} × 1 · ${money({ priceMinor: order.totalAmountMinor, currency: order.currency })}</p>
          ${order.status !== 'QUEUED' ? `<div class="progress-wrap">
            <div class="progress-ring" style="--progress:${percent * 3.6}deg" role="img" aria-label="${esc(t('order.status.progressPercent', { percent }))}">
              <div><strong>${percent}%</strong><small>${t('order.status.wholeProgress')}</small></div>
            </div>
            <div class="now-step">
              <strong>${esc(order.production?.currentStepName || orderLabel(order.status))}</strong>
              <span>${timing}</span>

            </div>
          </div>` : ''}
          <strong>${orderLabel(order.status)}</strong>
          ${statusNote(order) ? `<div class="status-meta">${esc(statusNote(order))}</div>` : ''}
          ${milestoneMarkup(order)}
          <button class="btn-secondary" id="refresh">${t('order.status.refresh')}</button>
          ${order.status === 'QUEUED' ? `<div class="queue-info" role="status"><p>${order.queue?.estimatedWaitSeconds != null ? t('order.queue.estimate', {minutes: Math.max(1,Math.ceil(order.queue.estimatedWaitSeconds/60))}) : t('order.queue.uncertain')}</p>${order.queue?.watchAvailable ? `<button id="watch-machine" class="rv-launch">${t('order.queue.watch')}</button>` : ''}</div>` : ''}

          ${order.status === 'READY' && (!order.pickupRequired || order.collectedAt) ? `<a href="/order?device_id=${encodeURIComponent(order.deviceId || '')}" class="btn-primary" style="text-decoration:none;display:flex;align-items:center;justify-content:center;margin-top:10px">${t('order.status.another')}</a>` : ''}
          ${pickupCodeFor(order) ? barcodeMarkup() : ''}

        </section>
        <section class="status-steps">
          <div class="steps-card">
            <h2>${t('order.status.steps')}</h2>
            <ol class="timeline" aria-label="${esc(t('order.status.steps'))}">${timeline}</ol>
          </div>

        </section>
      </div>

    </main>`;
  const refreshBtn = document.getElementById('refresh');
  if (refreshBtn) refreshBtn.onclick = loadOrder;
  scheduleReadyRedirect(order);
  const currentToken = fragment().get('token');
  if (currentToken) saveActiveOrder(order, currentToken, order.deviceId || deviceId);
  if (order.collectedAt || ['REFUNDED', 'CANCELLED', 'EXPIRED'].includes(order.status)) {
    clearActiveOrder(order.deviceId || deviceId);
  }
  if (order.status === 'READY' && !order.collectedAt) {
    notifyReadySensory();
  }
}

function renderError(message, retry = false) {
  globalThis.CoffeeRobotIntegration?.inline(null,false);
  document.title = t('order.title.error');
  app.innerHTML = `
    ${baseHeader('idle', t('order.error.interrupted'))}
    <main class="page-main">
      <section class="center-state">
        <div class="brew-loader" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="error-box">
          <strong>${t('order.error.cannotContinue')}</strong>
          <p>${esc(message)}</p>
          ${retry ? `<button class="btn-secondary" id="retry">${t('order.error.retry')}</button>` : ''}
        </div>
      </section>
    </main>`;
  mountHeaderControls();
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
  setQrNote(t('order.payment.qrLoading'));
  try {
    const response = await fetch(`/api/v1/payments/${encodeURIComponent(paymentId)}/qr`, {
      headers: { 'X-Order-Access-Token': token },
      cache: 'no-store',
    });
    if (!response.ok) {
      paymentQrCache.loading = false;
      setQrNote(t('order.payment.qrUnavailable'));
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    paymentQrCache = { paymentId, url, loadedAt: Date.now(), loading: false };
    const current = document.getElementById('payment-qr');
    if (current) current.src = url;
    setQrNote(t('order.payment.qrStable'));
  } catch (_) {
    paymentQrCache.loading = false;
    setQrNote(t('order.payment.qrUnavailable'));
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
let orderViewMode='3d', latestSceneOrder=null, watchTimer=null, watchController=null, watchGeneration=0;
function stopWatching(){watchGeneration++;clearTimeout(watchTimer);watchController?.abort();watchController=null;}
function applyOrderView(){
  const host=document.getElementById('order-scene');
  const show=orderViewMode==='3d' && !!host;
  globalThis.CoffeeRobotIntegration?.inline(host,show);
  const progress=document.querySelector?.('.progress-wrap');if(progress)progress.hidden=show;
  const button=document.getElementById('view-mode');
  if(button?.querySelectorAll)for(const item of button.querySelectorAll('[data-order-view]')){item.setAttribute('aria-pressed',String(item.dataset.orderView===orderViewMode));item.onclick=()=>{orderViewMode=item.dataset.orderView;applyOrderView();};}
}
async function watchMachine(){
  stopWatching();const generation=watchGeneration;
  const order=latestSceneOrder,token=fragment().get('token');
  if(order?.status!=='QUEUED' || !token)return;
  async function poll(){
    if(generation!==watchGeneration || document.hidden)return;
    watchController=new AbortController();
    try{
      const response=await fetch(`/api/v1/public/orders/${encodeURIComponent(order.orderId)}/scene`,{headers:{'X-Order-Access-Token':token},signal:watchController.signal,cache:'no-store'});
      if(!response.ok)throw Error('scene unavailable');
      const data=await response.json();if(generation!==watchGeneration)return;
      await globalThis.CoffeeRobotIntegration?.watch(data.scene);
      if(!data.scene){stopWatching();toast(t("order.queue.unavailable"));return;}
      watchTimer=setTimeout(poll,4000);
    }catch{if(generation===watchGeneration){stopWatching();globalThis.CoffeeRobotIntegration?.watch(null);toast(t("order.queue.unavailable"));}}
  }
  await poll();
}
globalThis.addEventListener?.('coffee-watch-closed',stopWatching);
globalThis.addEventListener?.('pagehide',stopWatching);
renderOrder = function (order) {
  globalThis.CoffeeRobotIntegration?.order(order);
  globalThis.CoffeeSound?.update({ id: order.orderId, status: ['PAUSED', 'RETRY_WAIT', 'HOLD'].includes(order.production?.status) ? order.production.status : order.status, revision: order.production?.deviceRevision, collected: !!order.collectedAt });
  const paymentWaiting = ['CREATED', 'AWAITING_PAYMENT'].includes(order.status);
  const paymentId = order.payment?.paymentId || null;
  if (paymentWaiting && renderedPaymentId === paymentId && document.getElementById('payment-qr')) {
    attachPaymentQr(order, fragment().get('token'));
    return;
  }
  renderedPaymentId = paymentWaiting ? paymentId : null;
  latestSceneOrder=order;
  if(order.status!=='QUEUED'){stopWatching();globalThis.CoffeeRobotIntegration?.watch(null);}
  renderOrderContent(order);
  mountHeaderControls();
  applyOrderView();
  showPickup(order);
  const watch=document.getElementById('watch-machine');if(watch)watch.onclick=watchMachine;
};

/* 页面隐藏时释放 SSE 连接，回到前台时重新加载并订阅。 */
if (typeof document.addEventListener === 'function') {
  document.addEventListener('visibilitychange', () => {
    if(document.hidden){stopWatching();globalThis.CoffeeRobotIntegration?.watch(null);}
    if (document.visibilityState === 'visible' && location.pathname === '/order/status') {
      loadOrder();
    } else if (orderStreamAbort) {
      stopWatching();globalThis.CoffeeRobotIntegration?.watch(null);
      globalThis.CoffeeRobotIntegration?.disconnected();
    globalThis.CoffeeSound?.disconnect();
      orderStreamAbort.abort();
    }
  });
}

if (location.pathname === '/order/status') loadOrder();
else loadMenu();
