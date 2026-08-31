/* ============================================================
   B 端客户后台 · 用户名模式上线前端测试（无浏览器依赖）
   运行：node --test tests/merchant-ui-auth.test.mjs
   说明：复用最小 DOM shim，在 Node 中加载真实 merchant.js
   （真实适配器 + mock fetch），覆盖：
   1. 初始化先取 /auth/config，USERNAME 模式登录/注册表单；
   2. USERNAME 注册成功显示“注册成功，可直接登录”，不伪造 session；
   3. 用户名与密码长度（15–128）校验失败不发请求；
   4. mailEnabled=false 时找回/验证/邀请/重置入口显示说明；
   5. 配置获取失败显示诚实错误（不假定认证可用），重试可恢复；
   6. 账号展示优先 username；成员邀请入口禁用；limitedRelease 说明。
   ============================================================ */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, copyFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/* ---------------- 最小 DOM shim（与 smoke 测试同构） ---------------- */

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
      if (node === null || node === undefined || node === false) continue;
      const child = node.nodeType ? node : documentStub.createTextNode(String(node));
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
      // 只要求匹配末段；其余片段沿祖先链近似匹配（后代组合器）
      if (!nodeMatchesSegs(node, parts[parts.length - 1])) continue;
      let ok = true;
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

function resetDom() {
  documentListeners.clear();
  body.replaceChildren();
  const HTML_IDS = ['demo-banner', 'env-banner', 'auth-view', 'shell', 'side-nav', 'who', 'logout-btn',
    'view-title', 'view-sub', 'top-controls', 'workspace', 'demo-tools', 'nav-veil', 'hamburger',
    'toast-root', 'drawer-root', 'modal-root'];
  for (const id of HTML_IDS) {
    const node = new StubElement('div');
    node.id = id;
    node.setAttribute('id', id);
    if (id.endsWith('banner') || id === 'auth-view' || id === 'shell' || id === 'nav-veil' || id === 'demo-tools'
      || id.endsWith('-root')) node.classList.add('hidden');
    body.append(node);
  }
  const sidebar = new StubElement('aside'); sidebar.id = 'sidebar'; body.append(sidebar);
  sidebar.append(documentStub.getElementById('side-nav'));
  documentStub.getElementById('who').parentNode.append(documentStub.getElementById('logout-btn'));
}

globalThis.document = documentStub;
globalThis.window = globalThis;
globalThis.history = { replaceState: () => {} };
globalThis.scrollTo = () => {};
globalThis.addEventListener = (type, handler) => documentStub.addEventListener(type, handler);
globalThis.removeEventListener = (type, handler) => documentStub.removeEventListener(type, handler);
window.addEventListener = globalThis.addEventListener;

/* ---------------- 工具 ---------------- */

const flush = async (times = 8) => { for (let i = 0; i < times; i += 1) await new Promise(resolve => setImmediate(resolve)); };

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

function fireHashChange() {
  for (const handler of (documentListeners.get('hashchange') || []).slice()) handler({});
}

const publicDir = new URL('../public/', import.meta.url);
let appSeq = 0;

/** 每个场景加载一份全新的 merchant.js（真实适配器），并安装 fetch mock。 */
async function loadApp(fetchHandler, { search = '', hash = '#/login' } = {}) {
  appSeq += 1;
  resetDom();
  globalThis.location = { hash, search, pathname: '/merchant.html' };
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return fetchHandler(String(url), options || {});
  };
  const tmpModuleDir = mkdtempSync(join(tmpdir(), `merchant-auth-${appSeq}-`));
  writeFileSync(join(tmpModuleDir, 'package.json'), JSON.stringify({ type: 'module' }));
  for (const name of ['merchant-format.js', 'merchant-api.js', 'merchant-demo.js', 'merchant.js']) {
    copyFileSync(new URL(name, publicDir), join(tmpModuleDir, name));
  }
  await import(pathToFileURL(join(tmpModuleDir, 'merchant.js')).href);
  return {
    calls,
    restoreFetch() { globalThis.fetch = realFetch; },
  };
}

const jsonResponse = (data, init = {}) => new Response(JSON.stringify({ data }), {
  headers: { 'Content-Type': 'application/json' }, ...init,
});
const errorResponse = (status, code, message) => new Response(JSON.stringify({ error: { code, message } }), {
  status, headers: { 'Content-Type': 'application/json' },
});

const USERNAME_CONFIG = {
  registrationMode: 'USERNAME',
  passwordMinLength: 15,
  passwordMaxLength: 128,
  usernamePattern: '^[a-z][a-z0-9_.-]{2,31}$',
  mailEnabled: false,
  limitedRelease: true,
};
const EMAIL_CONFIG = {
  registrationMode: 'EMAIL',
  passwordMinLength: 15,
  passwordMaxLength: 128,
  usernamePattern: '^[a-z][a-z0-9_.-]{2,31}$',
  mailEnabled: true,
  limitedRelease: false,
};

/* ============================================================
   场景 A：USERNAME 模式 · 登录/注册/mailDisabled 入口
   ============================================================ */

test('USERNAME：初始化先取 /auth/config，登录栏为用户名 text 输入且不出现邮件入口', async () => {
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  });
  try {
    await flush();
    assert.equal(app.calls[0].url, '/api/v1/merchant/auth/config', '第一个请求必须是认证配置');
    const authView = documentStub.getElementById('auth-view');
    assert.equal(authView.classList.contains('hidden'), false, '登录界面可见');
    const inputs = findAll(authView, n => n.tagName === 'INPUT');
    assert.equal(inputs.length, 2, '用户名 + 密码两个输入');
    assert.equal(inputs[0].getAttribute('type'), 'text', '用户名输入为 text');
    assert.equal(inputs[0].getAttribute('autocomplete'), 'username');
    const authText = textOf(authView);
    assert.ok(authText.includes('用户名'), '登录栏标签为“用户名”');
    assert.ok(authText.includes('已注册邮箱账号仍可用邮箱登录'), '提示邮箱账号仍可用邮箱登录');
    assert.ok(!authText.includes('忘记密码'), 'mailEnabled=false 隐藏找回邮箱入口');
    assert.ok(!authText.includes('验证邮箱') && !authText.includes('使用邀请链接'), '隐藏验证/邀请入口');
    assert.ok(authText.includes('创建组织账号'), '注册入口保留');
  } finally { app.restoreFetch(); }
});

test('USERNAME：注册校验用户名与密码长度（15–128），校验失败不发请求', async () => {
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  }, { hash: '#/register' });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    const form = findAll(authView, n => n.tagName === 'FORM')[0];
    assert.ok(form, '注册表单存在');
    const fields = {};
    for (const wrap of findAll(form, n => Boolean(n.getAttribute && n.getAttribute('data-field')))) {
      fields[wrap.getAttribute('data-field')] = wrap;
    }
    assert.deepEqual(Object.keys(fields).sort(), ['displayName', 'password', 'tenantName', 'username'], '注册必填四项');
    const username = fields.username.querySelector('input');
    const password = fields.password.querySelector('input');
    const displayName = fields.displayName.querySelector('input');
    const tenantName = fields.tenantName.querySelector('input');
    assert.equal(password.getAttribute('minlength'), '15', '密码最小长度来自配置');
    assert.equal(password.getAttribute('maxlength'), '128');
    const fieldError = name => textOf(fields[name]);

    /* 用户名过短 */
    username.value = 'ab';
    password.value = 'a-good-15chars-pw';
    displayName.value = '店长';
    tenantName.value = '晨光咖啡';
    form.dispatch('submit');
    await flush();
    assert.ok(fieldError('username').includes('3–32'), '用户名行内错误');
    assert.ok(!app.calls.some(c => c.url.includes('/auth/register')), '未发送注册请求');

    /* 用户名含非法字符 */
    username.value = 'Own Er';
    form.dispatch('submit');
    await flush();
    assert.ok(fieldError('username').length > 0, '非法字符被拦截');
    assert.ok(!app.calls.some(c => c.url.includes('/auth/register')), '仍未发送注册请求');

    /* 密码 14 位不足 */
    username.value = 'Owner.User';
    password.value = 'only14chars--';
    form.dispatch('submit');
    await flush();
    assert.ok(fieldError('password').includes('15–128'), '密码长度行内错误');
    assert.ok(!app.calls.some(c => c.url.includes('/auth/register')), '仍未发送注册请求');

    /* 缺组织名 */
    password.value = 'a-good-15chars-pw';
    tenantName.value = ' ';
    form.dispatch('submit');
    await flush();
    assert.ok(fieldError('tenantName').length > 0, '组织名必填');
    assert.ok(!app.calls.some(c => c.url.includes('/auth/register')), '仍未发送注册请求');
  } finally { app.restoreFetch(); }
});

test('USERNAME：注册成功显示“注册成功，可直接登录”，提交前 trim + lowercase，不伪造 session', async () => {
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    if (url === '/api/v1/merchant/auth/register') return jsonResponse({ status: 'REGISTERED' });
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  }, { hash: '#/register' });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    const form = findAll(authView, n => n.tagName === 'FORM')[0];
    const pick = name => form.querySelector(`[data-field="${name}"] input`);
    pick('username').value = '  Owner.User  ';
    pick('password').value = 'a-good-15chars-pw';
    pick('displayName').value = '店长';
    pick('tenantName').value = '晨光咖啡';
    form.dispatch('submit');
    await flush();

    const registerCall = app.calls.find(c => c.url.endsWith('/auth/register'));
    assert.ok(registerCall, '注册请求已发送');
    const body = JSON.parse(registerCall.options.body);
    assert.equal(body.username, 'owner.user', '提交前 trim + lowercase');
    assert.equal(body.password, 'a-good-15chars-pw');
    assert.equal(body.displayName, '店长');
    assert.equal(body.tenantName, '晨光咖啡');
    assert.equal(body.email, undefined, 'USERNAME 模式不提交 email');

    const resultText = textOf(authView);
    assert.ok(resultText.includes('注册成功，可直接登录'), '显示注册成功可直接登录');
    assert.ok(!resultText.includes('等待邮箱验证'), '不再提示验证邮箱');
    assert.ok(!app.calls.some(c => c.url.endsWith('/auth/login')), '不自动伪造登录 session');
    assert.equal(documentStub.getElementById('shell').classList.contains('hidden'), true, '外壳保持隐藏');
    assert.ok(resultText.includes('去登录'), '提供去登录入口');
  } finally { app.restoreFetch(); }
});

test('mailDisabled：直接访问找回/验证/邀请/重置显示统一说明并保留返回登录', async () => {
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    for (const route of ['forgot', 'verify', 'invite', 'reset']) {
      globalThis.location.hash = `#/${route}`;
      fireHashChange();
      await flush();
      const text = textOf(authView);
      assert.ok(text.includes('邮件服务未配置，此功能暂未开放'), `${route} 显示统一说明`);
      assert.ok(text.includes('忘记密码请联系平台管理员'), `${route} 提示联系管理员`);
      assert.ok(text.includes('返回登录'), `${route} 保留返回登录`);
      assert.equal(findAll(authView, n => n.tagName === 'FORM').length, 0, `${route} 不渲染可提交表单`);
    }
  } finally { app.restoreFetch(); }
});

/* ============================================================
   场景 B：配置获取失败 → 诚实错误 + 重试恢复
   ============================================================ */

test('配置获取失败：显示诚实错误，不出登录表单、不假定认证可用；重试成功后恢复', async () => {
  let configBroken = true;
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') {
      return configBroken ? errorResponse(503, 'CONFIG_UNAVAILABLE', '服务暂不可用') : jsonResponse(USERNAME_CONFIG);
    }
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    const text = textOf(authView);
    assert.ok(text.includes('无法加载登录配置'), '显示诚实错误标题');
    assert.ok(text.includes('不会假定认证可用'), '明确不假定认证可用');
    assert.ok(text.includes('服务暂不可用'), '透出服务端错误信息');
    assert.equal(findAll(authView, n => n.tagName === 'FORM').length, 0, '不渲染登录表单');
    assert.equal(findAll(authView, n => n.tagName === 'INPUT').length, 0, '不渲染任何输入框');
    assert.equal(documentStub.getElementById('demo-banner').classList.contains('hidden'), true, '不回退演示模式');

    /* 重试：配置恢复后出现 USERNAME 登录表单 */
    configBroken = false;
    const retry = findAll(authView, n => n.tagName === 'BUTTON' && textOf(n).includes('重试'))[0];
    assert.ok(retry, '提供重试按钮');
    retry.dispatch('click');
    await flush();
    const textAfter = textOf(authView);
    assert.ok(textAfter.includes('用户名'), '重试后出现 USERNAME 登录表单');
    assert.equal(findAll(authView, n => n.tagName === 'INPUT').length, 2);
  } finally { app.restoreFetch(); }
});

/* ============================================================
   场景 C：USERNAME 登录成功 → 外壳 / 账号展示 / 上线说明
   ============================================================ */

test('USERNAME：登录成功进入外壳，账号优先展示 username，总览出现紧凑上线说明', async () => {
  const session = {
    user: { id: 'u-1', username: 'owner.user', email: null, displayName: null },
    tenant: { id: 't-1', name: '晨光咖啡', timezone: 'Asia/Shanghai' },
    memberships: [{ id: 'mb-1', tenantId: 't-1', tenantName: '晨光咖啡', role: 'OWNER' }],
    permissions: ['dashboard.read'],
    csrfToken: 'test-csrf',
  };
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    if (url === '/api/v1/merchant/auth/login') return jsonResponse(session);
    if (url.startsWith('/api/v1/merchant/dashboard')) {
      return jsonResponse({
        period: { from: '2026-08-25', to: '2026-09-01', timezone: 'Asia/Shanghai' },
        metrics: null, completeness: { status: 'COMPLETE', missing: [] },
        trend: [], alerts: [], recentOrders: [],
      });
    }
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    const inputs = findAll(authView, n => n.tagName === 'INPUT');
    inputs[0].value = 'Owner.User';
    inputs[1].value = 'a-good-15chars-pw';
    findAll(authView, n => n.tagName === 'FORM')[0].dispatch('submit');
    await flush(12);

    const loginCall = app.calls.find(c => c.url.endsWith('/auth/login'));
    assert.ok(loginCall, '登录请求已发送');
    assert.deepEqual(JSON.parse(loginCall.options.body), { username: 'owner.user', password: 'a-good-15chars-pw' }, '提交 {username,password} 且已 lowercase');

    const shell = documentStub.getElementById('shell');
    assert.equal(shell.classList.contains('hidden'), false, '登录后外壳可见');
    const whoText = textOf(documentStub.getElementById('who'));
    assert.ok(whoText.includes('owner.user'), '账号优先展示 username');
    assert.ok(!whoText.includes('null'), '不展示 null');

    const workspaceText = textOf(documentStub.getElementById('workspace'));
    assert.ok(workspaceText.includes('上线说明'), '总览出现上线说明');
    assert.ok(workspaceText.includes('设备转让、商户收款配置暂未开放'), '说明转让/收款未开放');
    assert.ok(workspaceText.includes('不代表设备实时可用量'), '说明账面库存口径');
    /* 仅总览一处说明：切到其他页面不重复堆叠 */
    assert.equal(workspaceText.includes('待补全') && workspaceText.split('上线说明').length - 1, 1, '说明只出现一次');
  } finally { app.restoreFetch(); }
});

/* ============================================================
   场景 D：EMAIL 模式回归（真实适配器）
   ============================================================ */

test('EMAIL：配置为 EMAIL 时维持邮箱登录与邮件入口（旧流程不回退）', async () => {
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(EMAIL_CONFIG);
    if (url === '/api/v1/merchant/session') return errorResponse(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  });
  try {
    await flush();
    const authView = documentStub.getElementById('auth-view');
    const inputs = findAll(authView, n => n.tagName === 'INPUT');
    assert.equal(inputs[0].getAttribute('type'), 'email', 'EMAIL 模式登录栏为邮箱输入');
    const text = textOf(authView);
    assert.ok(text.includes('忘记密码'), 'mailEnabled=true 保留找回入口');
    assert.ok(text.includes('验证邮箱') && text.includes('使用邀请链接'), '保留验证/邀请入口');

    globalThis.location.hash = '#/register';
    fireHashChange();
    await flush();
    const regText = textOf(authView);
    assert.ok(regText.includes('工作邮箱'), '注册表单为邮箱字段');
    const pw = findAll(authView, n => n.tagName === 'INPUT' && n.getAttribute('type') === 'password')[0];
    assert.equal(pw.getAttribute('minlength'), '15', 'EMAIL 新密码同样按 15–128');
    assert.ok(regText.includes('15–128'), '文案标注 15–128');
  } finally { app.restoreFetch(); }
});

/* ============================================================
   场景 E：mailDisabled 下的成员页（邀请禁用 + 账号展示）
   ============================================================ */

test('mailDisabled：成员列表仍可用，邀请按钮禁用且说明，不出现可用邀请表单', async () => {
  const session = {
    user: { id: 'u-1', username: 'owner.user', email: null, displayName: '老板' },
    tenant: { id: 't-1', name: '晨光咖啡', timezone: 'Asia/Shanghai' },
    memberships: [{ id: 'mb-1', tenantId: 't-1', tenantName: '晨光咖啡', role: 'OWNER' }],
    permissions: ['members.read', 'members.manage'],
    csrfToken: 'test-csrf',
  };
  const app = await loadApp(url => {
    if (url === '/api/v1/merchant/auth/config') return jsonResponse(USERNAME_CONFIG);
    if (url === '/api/v1/merchant/session') return jsonResponse(session);
    if (url.startsWith('/api/v1/merchant/members')) {
      return jsonResponse([
        { id: 'mb-2', displayName: '王店长', username: 'wang', email: null, role: 'OPERATOR', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 1 },
        { id: 'mb-3', displayName: '李财务', username: null, email: 'fin@company.com', role: 'FINANCE', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 1 },
      ]);
    }
    if (url.startsWith('/api/v1/merchant/invitations')) return jsonResponse([]);
    return errorResponse(404, 'NOT_FOUND', '未预期的请求');
  }, { hash: '#/members' });
  try {
    await flush(12);
    const workspace = documentStub.getElementById('workspace');
    const shellText = textOf(workspace);

    /* 成员列表可用，账号展示优先 username，其次 email，不出现 null */
    assert.ok(shellText.includes('王店长') && shellText.includes('wang'), 'username 成员展示 wang');
    assert.ok(shellText.includes('fin@company.com'), 'email 成员展示 email');
    assert.ok(!shellText.includes('null'), '不展示 null');

    /* 邀请按钮禁用 + 说明（按钮文本经 innerHTML 注入静态 SVG+文字） */
    const inviteBtn = findAll(workspace, n => n.tagName === 'BUTTON' && String(n.innerHTML || '').includes('邀请新成员'))[0];
    assert.ok(inviteBtn, '邀请按钮存在（禁用态）');
    assert.equal(inviteBtn.disabled, true, '邀请按钮被禁用');
    assert.ok(shellText.includes('邮件服务未配置，此功能暂未开放'), '按钮旁给出说明');
    assert.ok(!app.calls.some(c => c.url.includes('/invitations') && (c.options.method || 'GET') !== 'GET'), '未发送任何创建邀请请求');
  } finally { app.restoreFetch(); }
});
