import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

let html = '';
let htmlWrites = 0;
const app = {
  get innerHTML() { return html; },
  set innerHTML(value) { html = value; htmlWrites += 1; },
  get writes() { return htmlWrites; },
};
const elements = new Map([['app', app]]);
const localMap = new Map();
const localStorage = {
  getItem: (k) => localMap.get(k) ?? null,
  setItem: (k, v) => localMap.set(k, String(v)),
  removeItem: (k) => localMap.delete(k),
  clear: () => localMap.clear(),
};
const context = vm.createContext({
  URLSearchParams,
  crypto: { randomUUID: () => 'qa-id' },
  document: {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
    querySelectorAll() { return []; },
  },
  location: { pathname: '/order', search: '', hash: '', href: '' },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  localStorage,
  setTimeout: () => 0,
  setInterval: () => 0,
  clearTimeout() {},
  clearInterval() {},
  alert() {},
});
const source = fs.readFileSync(new URL('../public/order.js', import.meta.url), 'utf8');
vm.runInContext(source, context);

test('renders device-authoritative step names and overall progress', () => {
  const order = {
    orderNo: 'QA-001', status: 'MAKING', queuePosition: 0, product: { name: '热美式' },
    production: {
      overallProgress: 0.61, stepProgress: 0.45,
      currentStepId: 'add-hot-water', currentStepName: '添加热水',
      plannedDurationSeconds: 46, elapsedSeconds: 28.1, remainingSeconds: 17.9,
      stepPlan: [
        { stepId: 'prepare-cup', stepName: '准备杯子', stepIndex: 0, durationSeconds: 5 },
        { stepId: 'extract-coffee', stepName: '萃取咖啡', stepIndex: 1, durationSeconds: 25 },
        { stepId: 'add-hot-water', stepName: '添加热水', stepIndex: 2, durationSeconds: 10 },
        { stepId: 'seal-and-serve', stepName: '封杯并出杯', stepIndex: 3, durationSeconds: 6 },
      ],
    },
  };
  const steps = context.productionSteps(order);
  assert.deepEqual(Array.from(steps, step => step.name), ['准备杯子', '萃取咖啡', '添加热水', '封杯并出杯']);
  context.renderOrder(order);
  assert.match(app.innerHTML, /61%/);
  assert.match(app.innerHTML, /整杯进度/);
  assert.match(app.innerHTML, /添加热水/);
  assert.match(app.innerHTML, /预计还需 18 秒/);
});

test('keeps the payment DOM and QR node stable across status polls', () => {
  const order = {
    orderNo: 'QA-PAY-001', status: 'AWAITING_PAYMENT', totalAmountMinor: 1000, currency: 'CNY',
    product: { name: '浓缩咖啡' }, payment: { paymentId: 'payment-1', qrCode: 'alipay://sandbox' },
  };
  const before = app.writes;
  context.renderOrder(order);
  const afterFirst = app.writes;
  context.renderOrder(order);
  assert.equal(afterFirst, before + 1);
  assert.equal(app.writes, afterFirst);
  assert.match(app.innerHTML, /二维码加载后保持不变/);
});

test('customer order ready state retains details and provides manual reorder without auto redirect', () => {
  context.renderOrder({
    orderNo: 'QA-READY-001', status: 'READY', paymentMode: 'TEST_FREE', deviceId: 'coffee-bot-003',
    totalAmountMinor: 1000, currency: 'CNY', product: { name: '美式' },
    production: { overallProgress: 1, plannedDurationSeconds: 10 },
  });
  assert.match(app.innerHTML, /制作完成/);
  assert.match(app.innerHTML, /取杯口令/);
  assert.match(app.innerHTML, /再点一杯/);
  assert.doesNotMatch(app.innerHTML, /6 秒后自动返回/);
});

test('uses one SSE stream instead of production status polling', () => {
  assert.match(source, /\/api\/v1\/public\/orders\/\$\{encodeURIComponent\(orderId\)\}\/events/);
  assert.match(source, /Accept': 'text\/event-stream'/);
  assert.doesNotMatch(source, /setTimeout\(loadOrder/);
  assert.doesNotMatch(source, /PRODUCTION_POLL_MS/);
});


test('unknown or malformed prices never appear as free products', () => {
  for (const priceMinor of [null, undefined, '', ' ', false, [], 'bad', 0.5, Infinity]) {
    assert.equal(context.money({ priceMinor }), '—');
  }
  assert.equal(context.money({ priceMinor: 0 }), '¥0.00');
  assert.equal(context.money({ priceMinor: '1250' }), '¥12.50');
  assert.equal(context.money({ totalAmountMinor: 1250 }), '¥12.50');
});

test('persists active order and renders recovery banner on menu view', () => {
  const order = {
    orderId: 'qa-order-123',
    orderNo: 'C0903-8E1A0F',
    status: 'MAKING',
    product: { name: '冰拿铁' },
    totalAmountMinor: 1800,
    currency: 'CNY',
    deviceId: 'coffee-bot-test',
  };
  context.saveActiveOrder(order, 'token-xyz', 'coffee-bot-test');
  const active = context.getActiveOrder('coffee-bot-test');
  assert.equal(active.orderId, 'qa-order-123');
  assert.equal(active.pickupCode, '8E1A');

  const testMenu = {
    deviceId: 'coffee-bot-test',
    online: true,
    paymentMode: 'ONLINE',
    salesEnabled: true,
    products: [{ recipeId: 'latte', name: '冰拿铁', available: true, priceMinor: 1800 }],
  };
  context.renderMenu(testMenu);
  assert.match(app.innerHTML, /进行中订单 · 取杯口令/);
  assert.match(app.innerHTML, /8E1A/);
  assert.match(app.innerHTML, /查看进度/);
});

test('mobile payment waiting view renders prominent direct payment button', () => {
  const order = {
    orderNo: 'QA-PAY-002',
    status: 'AWAITING_PAYMENT',
    totalAmountMinor: 1500,
    currency: 'CNY',
    product: { name: '美式咖啡' },
    payment: { paymentId: 'pay-2', qrCode: 'https://qr.alipay.com/bax01', provider: 'alipay' },
  };
  context.renderOrder(order);
  assert.match(app.innerHTML, /打开支付宝付款/);
  assert.match(app.innerHTML, /btn-alipay-cta/);
  assert.match(app.innerHTML, /二维码加载后保持不变/);
});
