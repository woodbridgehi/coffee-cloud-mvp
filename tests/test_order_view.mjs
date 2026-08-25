import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const app = { innerHTML: '' };
const elements = new Map([['app', app]]);
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
  setTimeout: () => 0,
  clearTimeout() {},
  alert() {},
});
vm.runInContext(fs.readFileSync(new URL('../public/order.js', import.meta.url), 'utf8'), context);

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
