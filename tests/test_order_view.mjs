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
for (const file of [
  '../public/shared/i18n.js',
  '../public/locales/common/zh-CN.js',
  '../public/locales/common/en-US.js',
  '../public/locales/order/zh-CN.js',
  '../public/locales/order/en-US.js',
]) {
  vm.runInContext(fs.readFileSync(new URL(file, import.meta.url), 'utf8'), context);
}
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
  assert.equal(active.pickupCode, '');

  const testMenu = {
    deviceId: 'coffee-bot-test',
    online: true,
    paymentMode: 'ONLINE',
    salesEnabled: true,
    products: [{ recipeId: 'latte', name: '冰拿铁', available: true, priceMinor: 1800 }],
  };
  context.renderMenu(testMenu);
  assert.match(app.innerHTML, /我的订单/);
  assert.doesNotMatch(app.innerHTML, /8E1A/);
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

test('English locale renders the customer menu and status without changing order data', () => {
  context.CoffeeI18n.setLocale('en-US', { translate: false });
  context.renderMenu({
    deviceId: 'coffee-bot-test', online: true, paymentMode: 'TEST_FREE', salesEnabled: true,
    products: [{ recipeId: 'latte', name: 'Store Latte', available: true, priceMinor: 1800 }],
  });
  assert.match(app.innerHTML, /Today's menu/);
  assert.match(app.innerHTML, /Choose a drink/);
  context.renderOrder({
    orderNo: 'QA-READY-EN', status: 'READY', paymentMode: 'TEST_FREE', deviceId: 'coffee-bot-test',
    totalAmountMinor: 1800, currency: 'CNY', product: { name: 'Store Latte' },
    production: { overallProgress: 1, plannedDurationSeconds: 10 },
  });
  assert.match(app.innerHTML, /Ready for pickup/);
  assert.match(app.innerHTML, /PICKUP CODE/);
  assert.match(app.innerHTML, /Store Latte/);
});


test('only an uncollected READY order exposes a pickup code; failure survives refunds', () => {
  context.CoffeeI18n.setLocale('zh-CN', { translate: false });
  for (const status of ['QUEUED','MAKING','HOLD','FAILED','REFUNDED','CANCELLED','EXPIRED']) {
    context.renderOrder({orderNo:'QA-FAIL-ABCD',status,product:{name:'拉花拿铁'},
      failure:status==='FAILED'||status==='REFUNDED'?{code:'COMPILED_RECIPE_MISMATCH',message:'指令缺少配方指纹 <script>bad()</script>'}:null});
    assert.doesNotMatch(app.innerHTML,/class="pickup-card"|class="pc-code"|ticket-barcode/);
    if(status==='FAILED'||status==='REFUNDED') {
      assert.match(app.innerHTML,/COMPILED_RECIPE_MISMATCH/);
      assert.match(app.innerHTML,/失败原因/);
      assert.doesNotMatch(app.innerHTML,/<script>bad/);
    }
  }
  context.renderOrder({orderNo:'QA-READY-ABCD',status:'READY',collectedAt:'2026-09-11T10:00:00Z',product:{name:'拿铁'}});
  assert.doesNotMatch(app.innerHTML,/class="pickup-card"/);
});


test('rejection stops milestones before making and does not wait for a duration', () => {
  context.renderOrder({orderNo:'QA-REJECTED',status:'FAILED',product:{name:'拉花拿铁'},
    production:{status:'REJECTED',overallProgress:0},failure:{code:'COMPILED_RECIPE_MISMATCH',message:'指纹缺失'}});
  const milestones=context.milestoneMarkup({status:'FAILED',production:{status:'REJECTED'}});
  assert.equal((milestones.match(/class="milestone done"/g)||[]).length,3);
  assert.equal((milestones.match(/class="milestone error"/g)||[]).length,1);
  assert.doesNotMatch(app.innerHTML,/等待设备返回计划时长/);
});
