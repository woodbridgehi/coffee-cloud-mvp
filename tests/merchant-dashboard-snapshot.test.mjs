import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../public/merchant.js', import.meta.url), 'utf8');
const binding = source.slice(source.indexOf('let dashboardMemo ='), source.indexOf('function statCard('));

test('dashboard shares a pending request, retries failure and isolates new renders', async () => {
  let calls = 0;
  let reject;
  const context = vm.createContext({
    dashboardParams: () => ({ environment: 'TEST' }),
    adapter: { dashboard: () => { calls++; return new Promise((resolve, fail) => { reject = fail; }); } },
  });
  vm.runInContext(binding, context);
  const snapshots = Array.from({ length: 4 }, () => context.fetchDashboardSnapshot());
  assert.equal(calls, 1);
  assert.ok(snapshots.every(p => p === snapshots[0]));
  reject(new Error('temporary network failure'));
  await Promise.all(snapshots.map(p => assert.rejects(p)));
  context.adapter.dashboard = async () => { calls++; return { tenant: calls }; };
  assert.equal((await context.fetchDashboardSnapshot()).tenant, 2);
  vm.runInContext("dashboardMemo = { key: '', promise: null };", context);
  assert.equal((await context.fetchDashboardSnapshot()).tenant, 3);
  context.dashboardParams = () => ({ environment: 'LIVE' });
  assert.equal((await context.fetchDashboardSnapshot()).tenant, 4);
});
