import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../public/merchant.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('async function refreshedPages('), source.indexOf('async function loadOrdersPage(')), context);
test('background refresh restarts at first page and retains loaded depth without appending duplicates', async () => {
  const seen = [];
  const result = await context.refreshedPages(async p => {
    seen.push(p.cursor);
    assert.equal(p.status, 'RUNNING');
    return p.cursor ? { items: ['c', 'd'], nextCursor: 'page3' } : { items: ['a', 'b'], nextCursor: 'page2' };
  }, { cursor: 'old-next-page', status: 'RUNNING' }, 4);
  assert.deepEqual(seen, [undefined, 'page2']);
  assert.deepEqual([...result.items], ['a', 'b', 'c', 'd']);
  assert.equal(result.nextCursor, 'page3');
});
test('a shortened or empty result terminates safely', async () => {
  let calls = 0;
  const result = await context.refreshedPages(async () => { calls++; return { items: [], nextCursor: null }; }, {}, 100);
  assert.equal(calls, 1);
  assert.equal(result.items.length, 0);
  assert.equal(result.nextCursor, null);
});
