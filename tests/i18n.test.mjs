import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../public/shared/i18n.js', import.meta.url), 'utf8');

function runtime({ language = 'zh-CN', stored = null } = {}) {
  const values = new Map(stored ? [['test.locale', stored]] : []);
  const context = {
    Intl,
    Date,
    console,
    navigator: { language, languages: [language] },
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return { i18n: context.CoffeeI18n, values };
}

test('locale canonicalization distinguishes simplified, traditional and both Korean locales', () => {
  const { i18n } = runtime();
  assert.equal(i18n.canonicalLocale('zh-Hans'), 'zh-CN');
  assert.equal(i18n.canonicalLocale('zh-HK'), 'zh-TW');
  assert.equal(i18n.canonicalLocale('ko-KR'), 'ko-KR');
  assert.equal(i18n.canonicalLocale('ko-KP'), 'ko-KP');
  assert.equal(i18n.canonicalLocale('../../en-US'), null);
});

test('configured locale uses explicit, stored, browser and fallback priority', () => {
  const { i18n } = runtime({ language: 'en-GB', stored: 'zh-CN' });
  assert.equal(i18n.configure({ storageKey: 'test.locale', initialLocale: 'en-US', translate: false }), 'en-US');
  assert.equal(i18n.configure({ storageKey: 'test.locale', translate: false }), 'zh-CN');
  assert.equal(i18n.configure({ storageKey: 'other.locale', translate: false }), 'en-US');
});

test('messages interpolate, pluralize and fall back without throwing', () => {
  const { i18n } = runtime();
  i18n.registerCatalog('zh-CN', { fallback: '回退', cups: { plural: 'count', other: '{count} 杯' } });
  i18n.registerCatalog('en-US', { hello: 'Hello, {name}', cups: { plural: 'count', one: '{count} cup', other: '{count} cups' } });
  i18n.configure({ initialLocale: 'en-US', translate: false });
  assert.equal(i18n.t('hello', { name: 'Alex' }), 'Hello, Alex');
  assert.equal(i18n.t('cups', { count: 1 }), '1 cup');
  assert.equal(i18n.t('cups', { count: 2 }), '2 cups');
  assert.equal(i18n.t('fallback'), '回退');
  assert.equal(i18n.t('missing.key'), 'missing.key');
});

test('locale-aware formatters preserve minor currency units and Gregorian Thai dates', () => {
  const { i18n } = runtime();
  i18n.configure({ initialLocale: 'en-US', translate: false });
  assert.match(i18n.formatMoney(1250, 'CNY'), /12\.50/);
  assert.match(i18n.formatDateTime('2026-09-04T00:00:00Z', { timeZone: 'UTC' }), /2026/);
  i18n.configure({ enabledLocales: ['th-TH', 'zh-CN'], initialLocale: 'th-TH', translate: false });
  assert.match(i18n.formatDateTime('2026-09-04T00:00:00Z', { timeZone: 'UTC' }), /2026/);
});

function catalogKeys(relativePath) {
  const catalog = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
  return [...catalog.matchAll(/'([^']+)'\s*:/g)].map(match => match[1]).sort();
}

test('Chinese and English catalogs keep identical keys', () => {
  assert.deepEqual(catalogKeys('../public/locales/common/zh-CN.js'), catalogKeys('../public/locales/common/en-US.js'));
  assert.deepEqual(catalogKeys('../public/locales/order/zh-CN.js'), catalogKeys('../public/locales/order/en-US.js'));
  assert.deepEqual(catalogKeys('../public/locales/merchant/zh-CN.js'), catalogKeys('../public/locales/merchant/en-US.js'));
  assert.deepEqual(catalogKeys('../public/locales/admin/zh-CN.js'), catalogKeys('../public/locales/admin/en-US.js'));
});

test('customer order code contains no user-facing hardcoded Chinese outside comments', () => {
  const orderSource = readFileSync(new URL('../public/order.js', import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
  assert.doesNotMatch(orderSource, /[\u3400-\u9fff]/);
});
