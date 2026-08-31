import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Execute the actual row binding in isolation; the event target represents
// bubbling from a native button without requiring a synthetic browser DOM.
const source = fs.readFileSync(new URL('../public/admin.js', import.meta.url), 'utf8');
const binding = source.slice(source.indexOf('  function rowActivate('), source.indexOf('  function captureRowFocus('));
const context = vm.createContext({});
vm.runInContext(binding, context);

test('row keyboard activation preserves nested controls and ignores key repeat', () => {
  let listener;
  let activated = 0;
  let prevented = 0;
  const row = { addEventListener(type, handler) { assert.equal(type, 'keydown'); listener = handler; } };
  context.rowActivate(row, () => activated++);
  assert.equal(row.tabIndex, 0);
  const send = (key, target = row, repeat = false) => listener({ key, target, repeat, preventDefault() { prevented++; } });
  send('Enter'); send(' ');
  assert.equal(activated, 2);
  assert.equal(prevented, 2);
  send('Enter', { tagName: 'BUTTON' }); send(' ', { tagName: 'BUTTON' });
  send('Enter', row, true); send('Tab');
  assert.equal(activated, 2);
  assert.equal(prevented, 2);
});
