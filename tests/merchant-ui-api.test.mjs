import test from 'node:test';
import assert from 'node:assert/strict';
import { createRealAdapter } from '../public/merchant-api.js';

test('CSV download retains the response stream and attachment name', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('date,amount\n2026-08-31,100', {
    headers: { 'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="operating.csv"' },
  }));
  const result = await createRealAdapter().operatingCsv({ grain: 'DAY' });
  assert.equal(result.filename, 'operating.csv');
  assert.equal(await result.blob.text(), 'date,amount\n2026-08-31,100');
});

test('successful HTML proxy response cannot masquerade as an empty API result', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Sign in</html>'));
  await assert.rejects(createRealAdapter().getSession(), { code: 'BAD_RESPONSE' });
});

test('session CSRF is carried on writes without an administrator credential', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    return Response.json({ data: { csrfToken: 'test-csrf' } });
  });
  const api = createRealAdapter();
  await api.getSession();
  await api.createStore({ name: 'Store' });
  assert.equal(calls[1].options.headers['X-CSRF-Token'], 'test-csrf');
  assert.equal(calls[1].options.headers.Authorization, undefined);
  assert.equal(calls[1].options.credentials, 'same-origin');
});

test('authConfig fetches the public auth configuration without a session', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    return Response.json({ data: {
      registrationMode: 'USERNAME',
      passwordMinLength: 15,
      passwordMaxLength: 128,
      usernamePattern: '^[a-z][a-z0-9_.-]{2,31}$',
      mailEnabled: false,
      limitedRelease: true,
    } });
  });
  const cfg = await createRealAdapter().authConfig();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/v1/merchant/auth/config');
  assert.equal((calls[0].options.method || 'GET'), 'GET');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.equal(cfg.registrationMode, 'USERNAME');
  assert.equal(cfg.mailEnabled, false);
  assert.equal(cfg.passwordMinLength, 15);
});
