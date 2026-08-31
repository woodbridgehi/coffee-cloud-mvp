/* ============================================================
   B 端客户后台 · 纯前端逻辑测试（无 DOM / 无网络）
   运行：node --test tests/merchant-ui-format.test.mjs
   说明：public/ 下的模块以 ES module 语法编写且不能在仓库内
   新增 package.json，因此测试将它们复制到带 {"type":"module"}
   的临时目录后导入，不改动项目文件。
   ============================================================ */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, copyFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const publicDir = new URL('../public/', import.meta.url);
const tmpModuleDir = mkdtempSync(join(tmpdir(), 'merchant-ui-'));
writeFileSync(join(tmpModuleDir, 'package.json'), JSON.stringify({ type: 'module' }));
for (const name of ['merchant-format.js', 'merchant-api.js', 'merchant-demo.js']) {
  copyFileSync(new URL(name, publicDir), join(tmpModuleDir, name));
}

const F = await import(pathToFileURL(join(tmpModuleDir, 'merchant-format.js')).href);
const { createDemoAdapter } = await import(pathToFileURL(join(tmpModuleDir, 'merchant-demo.js')).href);

/* ---------------- 金额 ---------------- */

test('fmtMoney：整数分转展示字符串', () => {
  assert.equal(F.fmtMoney(123456), '¥1,234.56');
  assert.equal(F.fmtMoney(5), '¥0.05');
  assert.equal(F.fmtMoney(0), '¥0.00');
  assert.equal(F.fmtMoney(-200), '-¥2.00');
  assert.equal(F.fmtMoney(100000000), '¥1,000,000.00');
});

test('fmtMoney：null/undefined 一律待补全，绝不显示为 0', () => {
  assert.equal(F.fmtMoney(null), '待补全');
  assert.equal(F.fmtMoney(undefined), '待补全');
  assert.equal(F.fmtMoney('not-a-number'), '待补全');
});

test('parseYuanToMinor：严格两位小数、非负、拒绝异常输入', () => {
  assert.deepEqual(F.parseYuanToMinor('12.5'), { ok: true, minor: 1250 });
  assert.deepEqual(F.parseYuanToMinor('12.56'), { ok: true, minor: 1256 });
  assert.deepEqual(F.parseYuanToMinor('0'), { ok: true, minor: 0 });
  assert.deepEqual(F.parseYuanToMinor(' 8 '), { ok: true, minor: 800 });
  assert.equal(F.parseYuanToMinor('12.567').ok, false);
  assert.equal(F.parseYuanToMinor('-3').ok, false);
  assert.equal(F.parseYuanToMinor('12.').ok, false);
  assert.equal(F.parseYuanToMinor('1,200').ok, false);
  assert.equal(F.parseYuanToMinor('1e3').ok, false);
  assert.equal(F.parseYuanToMinor('').ok, false);
  assert.equal(F.parseYuanToMinor('abc').ok, false);
});

/* ---------------- 数量 ---------------- */

test('parseQuantity：十进制字符串规范化，负号受开关控制', () => {
  assert.deepEqual(F.parseQuantity('12.5'), { ok: true, value: '12.5' });
  assert.deepEqual(F.parseQuantity('007'), { ok: true, value: '7' });
  assert.deepEqual(F.parseQuantity('1.50'), { ok: true, value: '1.5' });
  assert.equal(F.parseQuantity('-1').ok, false);
  assert.deepEqual(F.parseQuantity('-1', { allowNegative: true }), { ok: true, value: '-1' });
  assert.equal(F.parseQuantity('abc').ok, false);
});

test('fmtQty：按精度展示，未知显示待补全', () => {
  assert.equal(F.fmtQty('12.5', 3), '12.500');
  assert.equal(F.fmtQty(null, 3), '待补全');
});

/* ---------------- 日期与组织时区 ---------------- */

test('addDays：跨月与闰年边界', () => {
  assert.equal(F.addDays('2026-02-28', 1), '2026-03-01');
  assert.equal(F.addDays('2028-02-28', 1), '2028-02-29');
  assert.equal(F.addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(F.addDays('2026-01-01', -1), '2025-12-31');
});

test('区间换算：界面含当日 ↔ API 不含当日', () => {
  assert.equal(F.inclusiveEndToExclusive('2026-08-31'), '2026-09-01');
  assert.equal(F.exclusiveEndToInclusive('2026-09-01'), '2026-08-31');
});

test('rangeShortcut：今天 / 近7天 / 本月 / 本年', () => {
  assert.deepEqual(F.rangeShortcut('today', '2026-08-31'), { from: '2026-08-31', to: '2026-08-31' });
  assert.deepEqual(F.rangeShortcut('last7', '2026-08-31'), { from: '2026-08-25', to: '2026-08-31' });
  assert.deepEqual(F.rangeShortcut('thisMonth', '2026-08-31'), { from: '2026-08-01', to: '2026-08-31' });
  assert.deepEqual(F.rangeShortcut('thisYear', '2026-08-31'), { from: '2026-01-01', to: '2026-08-31' });
});

test('isValidRange 与 grainKey', () => {
  assert.equal(F.isValidRange('2026-08-01', '2026-08-31'), true);
  assert.equal(F.isValidRange('2026-08-31', '2026-08-01'), false);
  assert.equal(F.isValidRange('', '2026-08-01'), false);
  assert.equal(F.grainKey('2026-08-31', 'MONTH'), '2026-08');
  assert.equal(F.grainKey('2026-08-31', 'YEAR'), '2026');
  assert.equal(F.grainKey('2026-08-31', 'DAY'), '2026-08-31');
});

test('fmtDateTime：按组织时区展示 UTC ISO', () => {
  assert.equal(F.fmtDateTime('2026-08-31T16:00:00Z', 'Asia/Shanghai'), '2026/09/01 00:00');
  assert.equal(F.fmtDateTime(null), '—');
});

/* ---------------- CSV ---------------- */

test('csvEscape / buildCsv：引号、逗号、换行正确转义', () => {
  assert.equal(F.csvEscape('plain'), 'plain');
  assert.equal(F.csvEscape('a,b'), '"a,b"');
  assert.equal(F.csvEscape('say "hi"'), '"say ""hi"""');
  assert.equal(F.csvEscape('line1\nline2'), '"line1\nline2"');
  assert.equal(F.csvEscape(null), '');
  assert.equal(
    F.buildCsv(['a', 'b'], [['1', 'x,y'], ['2', 'q"z']]),
    'a,b\r\n1,"x,y"\r\n2,"q""z"',
  );
});

/* ---------------- 数值辅助 ---------------- */

test('percent：缺失返回 null 而不是 0%', () => {
  assert.equal(F.percent(1, 4), '25.0%');
  assert.equal(F.percent(null, 4), null);
  assert.equal(F.percent(1, 0), null);
});

test('sumMinor：未知记为 hasUnknown，不并入 0', () => {
  assert.deepEqual(F.sumMinor([{ v: 100 }, { v: 50 }], 'v'), { sum: 150, hasUnknown: false, count: 2 });
  assert.deepEqual(F.sumMinor([{ v: 100 }, { v: null }], 'v'), { sum: 100, hasUnknown: true, count: 1 });
  assert.deepEqual(F.sumMinor([{ v: null }], 'v'), { sum: 0, hasUnknown: true, count: 0 });
});

test('niceTicks：生成从 0 递增的整齐刻度', () => {
  const ticks = F.niceTicks(9500, 4);
  assert.equal(ticks[0], 0);
  for (let i = 1; i < ticks.length; i += 1) assert.ok(ticks[i] > ticks[i - 1]);
  assert.ok(ticks[ticks.length - 1] >= 9500);
});

/* ---------------- 演示适配器（内存行为，与真实适配器同形） ---------------- */

async function demoLogin(role) {
  const adapter = createDemoAdapter();
  const session = await adapter.login({ email: 'owner@demo.local', password: 'secret123' });
  if (role && role !== 'OWNER') adapter.demoSetRole(role);
  return { adapter, session };
}

test('demo：登录返回 OWNER 会话与完整权限，且不触发网络', async () => {
  const { session } = await demoLogin();
  assert.equal(session.tenant.name, '晨光咖啡');
  assert.ok(session.permissions.includes('refunds.manage'));
  assert.ok(session.permissions.includes('tenant.manage'));
  assert.equal(session.csrfToken.length > 0, true);
});

test('demo：OPERATOR 角色看不到利润 / 成员 / 收款账户权限', async () => {
  const { adapter } = await demoLogin('OPERATOR');
  const session = await adapter.getSession();
  assert.equal(session.permissions.includes('costs.read'), false);
  assert.equal(session.permissions.includes('members.read'), false);
  assert.equal(session.permissions.includes('payments.read'), false);
  assert.equal(session.permissions.includes('reports.read'), false);
  assert.equal(session.storeScope.mode, 'SELECTED');
});

test('demo：组织切换后设备按租户隔离，旧组织资源 404', async () => {
  const { adapter, session } = await demoLogin();
  const morning = await adapter.listDevices();
  assert.ok(morning.items.length >= 4);
  const harborMembership = session.memberships.find(m => m.tenantId === 't-harbor');
  await adapter.switchTenant(harborMembership.id);
  const harbor = await adapter.listDevices();
  assert.ok(harbor.items.length >= 2);
  const overlap = harbor.items.filter(d => morning.items.some(m => m.id === d.id));
  assert.equal(overlap.length, 0);
  const morningDevice = morning.items[0];
  await assert.rejects(() => adapter.getDevice(morningDevice.id), err => err.status === 404);
});

test('demo：报表确定性生成 —— 两次调用结果一致，缺成本不补零', async () => {
  const { adapter } = await demoLogin();
  const params = { grain: 'DAY', from: '2026-08-01', to: '2026-08-20', environment: 'LIVE' };
  const a = await adapter.operatingReport(params);
  const b = await adapter.operatingReport(params);
  assert.deepEqual(a.rows, b.rows);
  assert.deepEqual(a.totals, b.totals);
  const missingRows = a.rows.filter(r => r.materialCostMinor === null);
  assert.ok(missingRows.length > 0, 'fixture 应包含缺成本样例');
  assert.equal(a.completeness.status, 'INCOMPLETE');
  assert.equal(a.totals.materialCostMinor, null, '合计遇未知保持未知');
  assert.equal(a.totals.estimatedProfitMinor, null);
  assert.equal(typeof a.totals.receivedMinor, 'number');
});

test('demo：CSV 导出包含界面演示标记与表头', async () => {
  const { adapter } = await demoLogin();
  const { blob, filename } = await adapter.operatingCsv({ grain: 'DAY', from: '2026-08-01', to: '2026-08-05', environment: 'LIVE' });
  const text = await blob.text();
  assert.ok(text.includes('界面演示'));
  assert.ok(text.includes('receivedMinor'));
  assert.ok(filename.startsWith('demo-operating-'));
});

test('demo：退款进入申请中状态，不伪造成功', async () => {
  const { adapter } = await demoLogin();
  const { items } = await adapter.listOrders({ status: 'PAID' });
  const order = items.find(o => o.allowedActions.includes('REFUND'));
  const refund = await adapter.createRefund(order.id, { amountMinor: 100, reason: 'test' }, 'idem-1');
  assert.equal(refund.status, 'PENDING');
  const detail = await adapter.getOrder(order.id);
  assert.equal(detail.paymentStatus, 'REFUNDING');
  assert.equal(detail.refunds.some(r => r.status === 'PENDING'), true);
  const advanced = adapter.demoAdvanceRefunds();
  assert.ok(advanced.advanced >= 1);
  const after = await adapter.getOrder(order.id);
  assert.equal(after.refundedMinor, order.refundedMinor + 100);
});

test('demo：版本冲突返回 409，最后一位 OWNER 保护返回 409', async () => {
  const { adapter } = await demoLogin();
  const { items } = await adapter.listMembers();
  const owner = items.find(m => m.role === 'OWNER' && m.displayName === '演示用户');
  await assert.rejects(
    () => adapter.updateMember(owner.id, { role: 'FINANCE', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: owner.version }),
    err => err.status === 409 && err.code === 'LAST_OWNER',
  );
  const device = (await adapter.listDevices()).items[0];
  await assert.rejects(
    () => adapter.updateDevice(device.id, { name: 'x', version: device.version + 5 }),
    err => err.status === 409 && err.code === 'VERSION_CONFLICT',
  );
});

test('demo：转让阻断展示 blockingReasons，不显示为完成', async () => {
  const { adapter } = await demoLogin();
  const devices = await adapter.listDevices();
  const blocked = devices.items.find(d => d.deviceId === 'CC-BOT-0101');
  const result = await adapter.createTransferRequest(blocked.id, { targetTenantReference: 'partner-org', reason: 'test', ownershipVersion: blocked.ownershipVersion }, 'idem-2');
  assert.equal(result.status, 'BLOCKED');
  assert.ok(result.blockingReasons.length >= 1);
  assert.ok(result.blockingReasons.some(r => r.includes('在途生产')));
});

/* ---------------- 用户名模式（USERNAME）纯逻辑 ---------------- */

test('normalizeUsername：trim + lowercase，不区分大小写', () => {
  assert.equal(F.normalizeUsername('  Owner.User  '), 'owner.user');
  assert.equal(F.normalizeUsername('ABC'), 'abc');
  assert.equal(F.normalizeUsername(''), '');
  assert.equal(F.normalizeUsername(null), '');
});

test('validateUsername：默认规则 3–32 位、字母开头、仅小写字母数字点下划线连字符', () => {
  assert.deepEqual(F.validateUsername('owner1'), { ok: true, value: 'owner1' });
  assert.deepEqual(F.validateUsername('  Owner.One-2 '), { ok: true, value: 'owner.one-2' });
  assert.equal(F.validateUsername('ab').ok, false, '至少 3 位');
  assert.equal(F.validateUsername('a'.repeat(33)).ok, false, '最多 32 位');
  assert.equal(F.validateUsername('1owner').ok, false, '必须字母开头');
  assert.equal(F.validateUsername('own er').ok, false, '不允许空格');
  assert.equal(F.validateUsername('ownér').ok, false, '不允许非 ASCII');
  assert.equal(F.validateUsername('owner@x').ok, false, '不允许 @');
  assert.equal(F.validateUsername('   ').ok, false, '空值不放行');
  const empty = F.validateUsername('');
  assert.equal(empty.reason, '请输入用户名');
});

test('validateUsername：非法 pattern 回退默认规则而不是放行', () => {
  assert.equal(F.validateUsername('owner1', '[broken').ok, true, '回退后仍按默认规则校验');
  assert.equal(F.validateUsername('1owner', '[broken').ok, false);
});

test('validateNewPassword：默认 15–128 个字符，配置可覆盖', () => {
  assert.equal(F.validateNewPassword('a'.repeat(14)).ok, false, '14 位不足');
  assert.equal(F.validateNewPassword('a'.repeat(15)).ok, true);
  assert.equal(F.validateNewPassword('a'.repeat(128)).ok, true);
  assert.equal(F.validateNewPassword('a'.repeat(129)).ok, false, '129 位超限');
  assert.equal(F.validateNewPassword('').ok, false);
  assert.equal(F.validateNewPassword(null).ok, false);
  assert.equal(F.validateNewPassword('x', { passwordMinLength: 8, passwordMaxLength: 64 }).ok, false);
  assert.equal(F.validateNewPassword('x'.repeat(8), { passwordMinLength: 8, passwordMaxLength: 64 }).ok, true);
  assert.ok(F.validateNewPassword('a'.repeat(14)).reason.includes('15–128'), '错误文案包含长度区间');
});

/* ---------------- 认证配置（/auth/config） ---------------- */

test('demo：authConfig 返回 EMAIL 演示配置，与真实适配器同形', async () => {
  const adapter = createDemoAdapter();
  const cfg = await adapter.authConfig();
  assert.equal(cfg.registrationMode, 'EMAIL');
  assert.equal(cfg.mailEnabled, true);
  assert.equal(cfg.passwordMinLength, 15);
  assert.equal(cfg.passwordMaxLength, 128);
  assert.ok(cfg.usernamePattern.length > 0);
  assert.equal(typeof cfg.limitedRelease, 'boolean');
});
