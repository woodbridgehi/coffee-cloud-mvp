/* ============================================================
   设备运营台 · 展示层回归测试（纯函数，无 DOM）
   运行：node --test tests/admin-format.test.mjs
   背景：admin.js 曾用 Number(minor || 0) 把未知金额渲染成
   ¥0.00，违反「未知 ≠ 0」的数据正确性约束。抽出的
   admin-format.js 在此固化行为。
   ============================================================ */

import test from 'node:test';
import assert from 'node:assert/strict';
import { fmtMoney, fmtPercent, fmtAgo } from '../public/admin-format.js';

test('fmtMoney：未知金额显示「—」，绝不渲染为 ¥0.00', () => {
  assert.equal(fmtMoney(null), '—');
  assert.equal(fmtMoney(undefined), '—');
  assert.equal(fmtMoney(undefined, 'USD'), '—');
  assert.equal(fmtMoney('abc'), '—');
  assert.notEqual(fmtMoney(null), '¥0.00');
});

test('fmtMoney：分 → 元整数算术换算，含负数与千位以上金额', () => {
  assert.equal(fmtMoney(1250), '¥12.50');
  assert.equal(fmtMoney(5), '¥0.05');
  assert.equal(fmtMoney(0), '¥0.00');
  assert.equal(fmtMoney(-205), '-¥2.05');
  assert.equal(fmtMoney(123456789), '¥1234567.89');
  assert.equal(fmtMoney(980, 'CNY'), '¥9.80');
  assert.equal(fmtMoney(980, 'USD'), '9.80 USD');
});

test('fmtPercent：缺失比率显示「—」，不显示 0%', () => {
  assert.equal(fmtPercent(null), '—');
  assert.equal(fmtPercent(undefined), '—');
  assert.equal(fmtPercent(0.876), '87.6%');
  assert.equal(fmtPercent(1), '100.0%');
});

test('fmtAgo：空值显示「从未」，可注入当前时间', () => {
  assert.equal(fmtAgo(null), '从未');
  const now = Date.UTC(2026, 8, 1, 12, 0, 0);
  assert.equal(fmtAgo(new Date(now - 60_000).toISOString(), now), '1 分钟前');
  assert.equal(fmtAgo(new Date(now - 45 * 3600_000).toISOString(), now), '2 天前');
});
