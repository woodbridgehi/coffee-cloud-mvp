/* ============================================================
   B 端客户后台 · DOM stub 冒烟测试（无浏览器依赖）
   运行：node --test tests/merchant-ui-smoke.test.mjs
   说明：用最小 DOM shim 在 Node 中加载真实 merchant.js（演示
   适配器），验证登录 → 外壳渲染 → 路由 → 设备详情抽屉 →
   组织切换 → 登出等关键链路。样式与真实排版不在本测试范围。
   ============================================================ */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, copyFileSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/* ---------------- 最小 DOM shim ---------------- */

class StubElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.children = [];
    this.attributes = {};
    this.listeners = new Map();
    this.parentNode = null;
    this.style = {};
    this.dataset = {};
    this.value = '';
    this.checked = false;
    this.selected = false;
    this.disabled = false;
    this._text = '';
    this.id = '';
    this.offsetParent = null;
    Object.defineProperty(this, 'textContent', {
      get() { return this._text; },
      set(value) {
        this._text = String(value ?? '');
        for (const old2 of this.children) old2.parentNode = null;
        this.children = [];
        if (this._text !== '') {
          const text = new StubText(this._text);
          text.parentNode = this;
          this.children.push(text);
        }
      },
    });
    Object.defineProperty(this, 'className', {
      get() { return this.attributes.class || ''; },
      set(value) { this.attributes.class = String(value); },
    });
  }
  get classList() {
    const self = this;
    const read = () => new Set(String(self.attributes.class || '').split(/\s+/).filter(Boolean));
    return {
      add(...names) { const s = read(); names.forEach(n => s.add(n)); self.attributes.class = Array.from(s).join(' '); },
      remove(...names) { const s = read(); names.forEach(n => s.delete(n)); self.attributes.class = Array.from(s).join(' '); },
      toggle(name, force) { const s = read(); const target = force === undefined ? !s.has(name) : force; if (target) s.add(name); else s.delete(name); self.attributes.class = Array.from(s).join(' '); return target; },
      contains(name) { return read().has(name); },
    };
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'id') this.id = String(value);
    if (name === 'class') this.className = String(value);
  }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  append(...nodes) {
    for (const node of nodes) {
      const child = node?.nodeType ? node : documentStub.createTextNode(String(node));
      child.parentNode = this;
      this.children.push(child);
    }
  }
  replaceChildren(...nodes) {
    for (const old of this.children) old.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }
  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  removeEventListener(type, handler) {
    const list = this.listeners.get(type) || [];
    const index = list.indexOf(handler);
    if (index >= 0) list.splice(index, 1);
  }
  dispatch(type, event = {}) {
    const list = (this.listeners.get(type) || []).slice();
    const wrapped = { preventDefault: () => {}, stopPropagation: () => {}, ...event };
    for (const handler of list) handler(wrapped);
  }
  requestSubmit() { this.dispatch('submit'); }
  focus() { documentStub.activeElement = this; }
  click() { this.dispatch('click'); }
  matches(selector) { return matchesSelector(this, selector); }
  get firstElementChild() { return this.children.find(c => c.nodeType === 1) || null; }
  get lastElementChild() {
    for (let i = this.children.length - 1; i >= 0; i -= 1) if (this.children[i].nodeType === 1) return this.children[i];
    return null;
  }
  * walk() {
    for (const child of this.children) {
      yield child;
      if (child.nodeType === 1) yield* child.walk();
    }
  }
  querySelector(selector) { return querySelectorAll(this, selector)[0] || null; }
  querySelectorAll(selector) { return querySelectorAll(this, selector); }
}

class StubText {
  constructor(text) { this.nodeType = 3; this.data = String(text); this.parentNode = null; this.children = []; }
  get textContent() { return this.data; }
}

function parseSimpleSelector(selector) {
  const cleaned = selector.replace(/:not\([^)]*\)/g, '').trim();
  if (!cleaned) return null;
  return cleaned.split(/\s+/).map(part => {
    const segs = [];
    const re = /([#.]?[\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
    let m;
    while ((m = re.exec(part))) {
      if (m[1]) {
        if (m[1][0] === '#') segs.push({ id: m[1].slice(1) });
        else if (m[1][0] === '.') segs.push({ class: m[1].slice(1) });
        else segs.push({ tag: m[1].toUpperCase() });
      } else if (m[2]) segs.push({ attr: m[2], value: m[3] });
    }
    return segs;
  });
}

function nodeMatchesSegs(node, segs) {
  for (const seg of segs) {
    if (seg.tag && node.tagName !== seg.tag) return false;
    if (seg.id && node.id !== seg.id) return false;
    if (seg.class && !(node.attributes.class || '').split(/\s+/).includes(seg.class)) return false;
    if (seg.attr && !(seg.attr in node.attributes)) return false;
    if (seg.attr && seg.value !== undefined && node.attributes[seg.attr] !== seg.value) return false;
  }
  return true;
}

function matchesSelector(node, selector) {
  const parts = parseSimpleSelector(selector);
  if (!parts) return false;
  return nodeMatchesSegs(node, parts[parts.length - 1]);
}

function querySelectorAll(root, selector) {
  const cleaned = String(selector);
  const out = [];
  const orParts = cleaned.includes(',') ? cleaned.split(',') : [cleaned];
  for (const part of orParts) {
    const parts = parseSimpleSelector(part);
    if (!parts) continue;
    for (const node of root.walk()) {
      if (node.nodeType !== 1) continue;
      let ok = true;
      for (const segs of parts) if (!nodeMatchesSegs(node, segs)) { ok = false; break; }
      if (!ok) continue;
      // 后代组合器近似：要求其余片段能沿祖先链匹配（简化为只校验末段 + 任意祖先含其余段）
      let cursor = node.parentNode;
      for (let i = parts.length - 2; i >= 0; i -= 1) {
        const segs = parts[i];
        while (cursor && !nodeMatchesSegs(cursor, segs)) cursor = cursor.parentNode;
        if (!cursor) { ok = false; break; }
        cursor = cursor.parentNode;
      }
      if (ok) out.push(node);
    }
  }
  return out;
}

const documentListeners = new Map();
const body = new StubElement('body');

const documentStub = {
  nodeType: 9,
  body,
  activeElement: null,
  createElement(tag) { return new StubElement(tag); },
  createElementNS(ns, tag) { return new StubElement(tag); },
  createTextNode(text) { return new StubText(text); },
  getElementById(id) {
    for (const node of body.walk()) if (node.nodeType === 1 && node.id === id) return node;
    return null;
  },
  querySelector(selector) { return querySelectorAll(body, selector)[0] || null; },
  querySelectorAll(selector) { return querySelectorAll(body, selector); },
  addEventListener(type, handler) {
    if (!documentListeners.has(type)) documentListeners.set(type, []);
    documentListeners.get(type).push(handler);
  },
  removeEventListener(type, handler) {
    const list = documentListeners.get(type) || [];
    const index = list.indexOf(handler);
    if (index >= 0) list.splice(index, 1);
  },
};

const HTML_IDS = ['demo-banner', 'env-banner', 'auth-view', 'shell', 'side-nav', 'who', 'logout-btn',
  'view-title', 'view-sub', 'top-controls', 'workspace', 'demo-tools', 'nav-veil', 'hamburger',
  'toast-root', 'drawer-root', 'modal-root'];
for (const id of HTML_IDS) {
  const node = new StubElement('div');
  node.id = id;
  node.setAttribute('id', id);
  if (id.endsWith('banner') || id === 'auth-view' || id === 'shell' || id === 'nav-veil' || id === 'demo-tools'
    || id.endsWith('-root')) node.classList.add('hidden');
  if (id === 'demo-banner') node.classList.remove('hidden'), node.classList.add('demo-banner');
  if (id === 'demo-tools') node.classList.remove('hidden');
  body.append(node);
}
documentStub.getElementById('hamburger').classList.remove('hidden');
const sidebar = new StubElement('aside'); sidebar.id = 'sidebar'; body.append(sidebar);
const nav = documentStub.getElementById('side-nav'); sidebar.append(nav);
documentStub.getElementById('who').parentNode.append(documentStub.getElementById('logout-btn'));

globalThis.document = documentStub;
globalThis.window = globalThis;
globalThis.location = { hash: '#/login', search: '?demo=1', pathname: '/merchant.html' };
globalThis.history = { replaceState: () => {} };
globalThis.addEventListener = (type, handler) => documentStub.addEventListener(type, handler);
globalThis.removeEventListener = (type, handler) => documentStub.removeEventListener(type, handler);
globalThis.scrollTo = () => {};
window.addEventListener = globalThis.addEventListener;

/* ---------------- 工具 ---------------- */

const flush = async (times = 6) => { for (let i = 0; i < times; i += 1) await new Promise(resolve => setImmediate(resolve)); };

function textOf(node) {
  const parts = [];
  for (const child of node.walk ? node.walk() : []) {
    if (child.nodeType === 3) parts.push(child.data);
  }
  return parts.join(' ');
}

function findAll(root, predicate) {
  const out = [];
  for (const node of root.walk()) if (node.nodeType === 1 && predicate(node)) out.push(node);
  return out;
}

function findButtonByText(root, text) {
  return findAll(root, n => n.tagName === 'BUTTON' && textOf(n).includes(text))[0] || null;
}

function fireHashChange() {
  for (const handler of (documentListeners.get('hashchange') || []).slice()) handler({});
}

/* ---------------- 加载真实 merchant.js（演示模式） ---------------- */

const publicDir = new URL('../public/', import.meta.url);
const tmpModuleDir = mkdtempSync(join(tmpdir(), 'merchant-smoke-'));
writeFileSync(join(tmpModuleDir, 'package.json'), JSON.stringify({ type: 'module' }));
for (const name of ['merchant-format.js', 'merchant-api.js', 'merchant-demo.js', 'merchant.js']) {
  copyFileSync(new URL(name, publicDir), join(tmpModuleDir, name));
}
// Expose private view functions only in the disposable test copy.
const entry = join(tmpModuleDir, 'merchant.js');
writeFileSync(entry, readFileSync(entry, 'utf8') + '\nexport { paintOrderDrawer, openDrawer, openRefundModal };\n');
const views = await import(pathToFileURL(entry).href);

/* ---------------- 场景 ---------------- */

test('冒烟：演示模式横幅显示，登录表单可提交', async () => {
  const authView = documentStub.getElementById('auth-view');
  assert.equal(authView.classList.contains('hidden'), false, '登录界面可见');
  assert.equal(documentStub.getElementById('demo-banner').classList.contains('hidden'), false, '演示横幅常显');
  const inputs = findAll(authView, n => n.tagName === 'INPUT');
  assert.equal(inputs.length, 2, '邮箱 + 密码输入');
  inputs[0].value = 'owner@demo.local';
  inputs[1].value = 'secret123';
  const form = findAll(authView, n => n.tagName === 'FORM')[0];
  const submitBtn = findButtonByText(authView, '登录');
  assert.ok(form && submitBtn, '登录按钮存在');
  form.dispatch('submit');
  await flush();
});

test('冒烟：登录后外壳与 OWNER 全量导航渲染，总览加载', async () => {
  const shell = documentStub.getElementById('shell');
  assert.equal(shell.classList.contains('hidden'), false, '外壳可见');
  const navItems = findAll(documentStub.getElementById('side-nav'), n => n.classList.contains('cc-navitem'));
  assert.equal(navItems.length, 13, 'OWNER 可见 13 个导航项');
  const sideNav = documentStub.getElementById('side-nav');
  const navText = textOf(sideNav);
  for (const label of ['经营', '资产', '成本与商品', '组织']) assert.ok(navText.includes(label), `分组 ${label}`);
  const navGroups = findAll(sideNav, n => n.classList.contains('cc-navgroup'));
  assert.deepEqual(navGroups.map(group => findAll(group, n => n.classList.contains('cc-navitem')).length), [3, 3, 3, 4], '导航项归属于对应分组');
  const workspace = documentStub.getElementById('workspace');
  assert.ok(documentStub.getElementById('dash-cards'), '总览卡片区域存在');
  await flush(10);
  const cardsText = textOf(workspace);
  assert.ok(cardsText.includes('净收款'), '财务卡片渲染');
  assert.ok(cardsText.includes('经营利润（估算）'), '利润卡片渲染');
});

test('冒烟：日期快捷项、手动日期与经营报表筛选只刷新当前视图', async () => {
  const controls = documentStub.getElementById('top-controls');
  const initialDateButton = findAll(controls, n => n.tagName === 'BUTTON' && textOf(n).includes('~'))[0];
  assert.ok(initialDateButton, '日期区间按钮存在');
  const initialLabel = textOf(initialDateButton);
  initialDateButton.dispatch('click');
  const todayButton = findButtonByText(controls, '今天');
  assert.ok(todayButton, '日期弹层提供今天快捷项');
  todayButton.dispatch('click');
  await flush(10);
  const refreshedControls = documentStub.getElementById('top-controls');
  const refreshedDateButton = findAll(refreshedControls, n => n.tagName === 'BUTTON' && textOf(n).includes('~'))[0];
  assert.notEqual(textOf(refreshedDateButton), initialLabel, '点击今天后日期标签更新');
  refreshedDateButton.dispatch('click');
  assert.equal(findButtonByText(refreshedControls, '今天').getAttribute('aria-pressed'), 'true', '重新打开后今天保持选中');

  globalThis.location.hash = '#/reports';
  fireHashChange();
  await flush(10);
  const workspace = documentStub.getElementById('workspace');
  const reportControls = () => findAll(workspace, n => n.getAttribute('aria-label') === '统计粒度');
  assert.equal(reportControls().length, 1, '初始只有一组报表控件');
  findButtonByText(reportControls()[0], '月').dispatch('click');
  await flush(10);
  assert.equal(reportControls().length, 1, '切换粒度不会追加第二份报表');
  assert.equal(findButtonByText(reportControls()[0], '月').getAttribute('aria-pressed'), 'true', '月粒度切换生效');

  const metricSelect = findAll(workspace, n => n.tagName === 'SELECT' && n.getAttribute('aria-label') === '图表指标')[0];
  metricSelect.value = 'materialCostMinor';
  metricSelect.dispatch('change');
  await flush(10);
  assert.equal(reportControls().length, 1, '切换材料成本不会追加报表');

  const reportStore = findAll(workspace, n => n.tagName === 'SELECT' && n.getAttribute('aria-label') === '门店筛选')[0];
  reportStore.value = '';
  reportStore.dispatch('change');
  await flush(10);
  assert.equal(reportControls().length, 1, '切换门店不会追加报表');
});

test('冒烟：设备列表渲染并可打开详情抽屉', async () => {
  globalThis.location.hash = '#/devices';
  fireHashChange();
  await flush(8);
  const list = documentStub.getElementById('device-list');
  assert.ok(list, '设备列表区域存在');
  const rows = findAll(list, n => n.tagName === 'TR' && n.classList.contains('is-clickable'));
  assert.ok(rows.length >= 4, `晨光咖啡演示设备 ≥4 台（实际 ${rows.length}）`);
  /* 数值列（版本）右对齐：th 与 td 均带 cc-money 类 */
  const deviceTable = findAll(list, n => n.tagName === 'TABLE')[0];
  const versionTh = findAll(deviceTable, n => n.tagName === 'TH').find(h => textOf(h) === '版本');
  assert.ok(versionTh, '版本列表头存在');
  assert.ok(versionTh.classList.contains('cc-money'), '数值列表头同步 cc-money 类（右对齐）');
  const versionTd = findAll(deviceTable, n => n.tagName === 'TD' && n.attributes['data-label'] === '版本')[0];
  assert.ok(versionTd.classList.contains('cc-money'), '数值单元格带 cc-money 类（等宽数字 + 右对齐）');
  /* 辅助技术 / 窄屏：每个单元格都携带 data-label 列名 */
  const labeledCells = findAll(deviceTable, n => n.tagName === 'TD' && n.attributes['data-label']);
  assert.ok(labeledCells.length >= rows.length * 6, 'data-label 覆盖全部数据单元格');
  const drawerRoot = documentStub.getElementById('drawer-root');
  rows[0].dispatch('click');
  await flush(8);
  assert.equal(drawerRoot.classList.contains('hidden'), false, '抽屉打开');
  const drawerText = textOf(drawerRoot);
  for (const label of ['概览', '能力与物料', '技术信息']) assert.ok(drawerText.includes(label), `抽屉包含 ${label}`);
  assert.ok(drawerText.includes('重载配置'), '在线设备展示服务器允许的命令入口');
  // 关闭抽屉
  const closeBtn = findAll(drawerRoot, n => n.classList.contains('cc-layer-close'))[0];
  closeBtn.dispatch('click');
  await flush();
  assert.equal(drawerRoot.classList.contains('hidden'), true, '抽屉关闭');
});

test('冒烟：切换组织后导航与门店按新组织重载', async () => {
  const orgSelect = documentStub.querySelector('[aria-label="当前组织"]');
  assert.ok(orgSelect, '组织切换控件存在');
  const harborOption = (orgSelect.children || []).find(c => c.value && c.value.includes && c.value.startsWith('mb-demo-2'));
  assert.ok(harborOption, '存在第二个组织的成员关系选项');
  orgSelect.value = harborOption.value;
  orgSelect.dispatch('change');
  await flush(12);
  const whoText = textOf(documentStub.getElementById('who'));
  assert.ok(whoText.includes('临港商务中心'), `who 区域显示新组织（${whoText}）`);
  globalThis.location.hash = '#/devices';
  fireHashChange();
  await flush(8);
  const rows = findAll(documentStub.getElementById('device-list'), n => n.tagName === 'TR' && n.classList.contains('is-clickable'));
  assert.equal(rows.length, 2, '新组织设备 2 台（租户隔离）');
});

test('冒烟：退出登录回到认证界面并清理外壳', async () => {
  const logoutBtn = documentStub.getElementById('logout-btn');
  logoutBtn.dispatch('click');
  await flush(8);
  assert.equal(documentStub.getElementById('shell').classList.contains('hidden'), true, '外壳隐藏');
  assert.equal(documentStub.getElementById('auth-view').classList.contains('hidden'), false, '回到登录');
});

test('冒烟：注册 / 找回 / 验证入口可达且邮箱验证需主动确认', async () => {
  globalThis.location.hash = '#/verify';
  fireHashChange();
  await flush();
  const authText = textOf(documentStub.getElementById('auth-view'));
  assert.ok(authText.includes('确认验证邮箱'), '验证页提供主动确认按钮');
  assert.ok(authText.includes('验证不会自动执行'), '明确提示不自动消费链接');
  globalThis.location.hash = '#/register';
  fireHashChange();
  await flush();
  assert.ok(textOf(documentStub.getElementById('auth-view')).includes('组织名称'), '注册表单包含组织名称');
});

test('冒烟：OPERATOR 看不到利润与退款入口，订单抽屉正常打开', async () => {
  // 先回到登录页再登录（上一测试停留在注册页）
  globalThis.location.hash = '#/login';
  fireHashChange();
  await flush();
  const authView = documentStub.getElementById('auth-view');
  const inputs = findAll(authView, n => n.tagName === 'INPUT');
  assert.equal(inputs.length, 2, '登录表单两个输入');
  inputs[0].value = 'ops@demo.local';
  inputs[1].value = 'secret123';
  findAll(authView, n => n.tagName === 'FORM')[0].dispatch('submit');
  await flush(8);
  // 通过演示工具切换为 OPERATOR（先打开演示面板）
  const demoFab = findButtonByText(documentStub.getElementById('demo-tools'), '演示工具');
  assert.ok(demoFab, '演示工具浮动按钮存在');
  demoFab.dispatch('click');
  await flush();
  const roleBtn = documentStub.querySelector('[data-role="OPERATOR"]');
  assert.ok(roleBtn, '演示面板提供角色切换');
  roleBtn.dispatch('click');
  await flush(10);
  const navItems = findAll(documentStub.getElementById('side-nav'), n => n.classList.contains('cc-navitem'));
  assert.equal(navItems.length, 6, `OPERATOR 仅见 6 个导航项（实际 ${navItems.length}）`);
  const navText = textOf(documentStub.getElementById('side-nav'));
  assert.ok(!navText.includes('经营报表') && !navText.includes('收款账户') && !navText.includes('成员权限'), '无报表/账户/成员导航');
  globalThis.location.hash = '#/dashboard';
  fireHashChange();
  await flush(10);
  const dashText = textOf(documentStub.getElementById('workspace'));
  assert.ok(dashText.includes('在线率'), '运维视角展示设备卡片');
  assert.ok(!dashText.includes('净收款') && !dashText.includes('经营利润'), '运维视角无财务卡片');
  // 订单列表 + 抽屉
  globalThis.location.hash = '#/orders';
  fireHashChange();
  await flush(10);
  const orderRows = findAll(documentStub.getElementById('workspace'), n => n.tagName === 'TR' && n.classList.contains('is-clickable'));
  assert.ok(orderRows.length >= 3, `订单行 ≥3（实际 ${orderRows.length}）`);
  orderRows[0].dispatch('click');
  await flush(8);
  const drawerRoot = documentStub.getElementById('drawer-root');
  const drawerText = textOf(drawerRoot);
  assert.ok(drawerText.includes('商品明细'), '订单抽屉包含商品明细');
  assert.ok(drawerText.includes('支付与退款'), '订单抽屉包含支付与退款');
  assert.ok(!drawerText.includes('发起退款'), 'OPERATOR 无退款入口');
  const closeBtn = findAll(drawerRoot, n => n.classList.contains('cc-layer-close'))[0];
  closeBtn.dispatch('click');
  await flush();
  // 切换 TEST 环境 → 横幅显示
  const testBtn = findButtonByText(documentStub.getElementById('top-controls'), '测试');
  assert.ok(testBtn, '环境切换控件存在');
  testBtn.dispatch('click');
  await flush(8);
  assert.equal(documentStub.getElementById('env-banner').classList.contains('hidden'), false, 'TEST 横幅持续显示');
  // 登出收尾
  documentStub.getElementById('logout-btn').dispatch('click');
  await flush(8);
  assert.equal(documentStub.getElementById('shell').classList.contains('hidden'), true, '登出后外壳隐藏');
});


test('真实订单契约：退款成功、时间线字段与 DOM 节点正确渲染，无 null 占位', () => {
  const drawer = views.openDrawer({ title: '契约测试订单' });
  views.paintOrderDrawer(drawer, {
    id: 'contract-order', paymentStatus: 'NOT_REQUIRED', productionStatus: 'READY',
    totalMinor: 1200, receivedMinor: 1200, refundedMinor: 300, allowedActions: [],
    payments: [{ provider: 'alipay_mock', status: 'PAID', amountMinor: 1200 }],
    refunds: [{ status: 'SUCCEEDED', amountMinor: 300 }],
    timeline: [{ status: 'READY', description: '设备确认完成', createdAt: '2026-08-31T12:00:00Z' }],
  });
  const content = textOf(documentStub.getElementById('drawer-root'));
  for (const expected of ['无需支付', '已交付', '已支付', '退款成功', '设备确认完成', '2026/08/31']) assert.ok(content.includes(expected), expected);
  assert.doesNotMatch(content, /\[object |\bnull\b|\bundefined\b|退款失败/);
  assert.ok(findAll(drawer.body, n => n.classList.contains('cc-status')).length >= 4, '支付/制作/退款状态节点存在');
  drawer.close();
});


test('退款上限缺失或异常时禁用金额与提交，不能把非法金额当作零', () => {
  for (const [receivedMinor, refundedMinor] of [[null, 0], [100, undefined], ['', 0], [false, 0], [100, NaN], [100, 101]]) {
    views.openRefundModal({ id: 'refund-contract', receivedMinor, refundedMinor }, {});
    const root = documentStub.getElementById('modal-root');
    assert.ok(root.classList.contains('cc-overlay'), '弹窗根节点始终具备居中遮罩类');
    assert.ok(textOf(root).includes('无法计算可退上限'));
    assert.equal(findButtonByText(root, '确认退款').disabled, true);
    assert.equal(findAll(root, n => n.tagName === 'INPUT')[0].disabled, true);
    findAll(root, n => n.classList.contains('cc-layer-close'))[0].click();
  }
});
