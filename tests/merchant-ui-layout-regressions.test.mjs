import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const sharedCss = readFileSync(new URL('../public/shared/coffee-ui.css', import.meta.url), 'utf8');
const merchantCss = readFileSync(new URL('../public/merchant.css', import.meta.url), 'utf8');
const merchantHtml = readFileSync(new URL('../public/merchant.html', import.meta.url), 'utf8');
const adminHtml = readFileSync(new URL('../public/admin.html', import.meta.url), 'utf8');

test('弹窗根节点使用居中遮罩，且高弹窗保持可滚动', () => {
  assert.match(merchantHtml, /id="modal-root" class="cc-overlay hidden"/);
  assert.match(adminHtml, /id="modal-root" class="cc-overlay hidden"/);
  assert.match(sharedCss, /\.cc-overlay\s*\{[^}]*align-items:\s*center/s);
  assert.match(sharedCss, /\.cc-dialog\s*\{[^}]*max-height:\s*calc\(100dvh - 32px\)[^}]*overflow-y:\s*auto/s);
});

test('日期弹层位于点击外部关闭层之上', () => {
  const menuZ = Number(sharedCss.match(/\.cc-menu\s*\{[^}]*z-index:\s*(\d+)/s)?.[1]);
  const outsideZ = Number(merchantCss.match(/\.m-pop-outside\s*\{[^}]*z-index:\s*(\d+)/s)?.[1]);
  assert.ok(Number.isFinite(menuZ) && Number.isFinite(outsideZ), '两个浮层都声明 z-index');
  assert.ok(menuZ > outsideZ, `菜单层级 ${menuZ} 应高于外部关闭层 ${outsideZ}`);
});

test('数据表格首列 Sticky 冻结与微阴影隔离样式保持有效', () => {
  assert.match(merchantCss, /\.cc-tablewrap--scroll\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(merchantCss, /\.cc-table th:first-child,\s*\.cc-table td:first-child\s*\{[^}]*position:\s*sticky/s);
  assert.match(merchantCss, /\.cc-table th:first-child,\s*\.cc-table td:first-child\s*\{[^}]*left:\s*0/s);
  assert.match(merchantCss, /\.cc-table th:first-child,\s*\.cc-table td:first-child\s*\{[^}]*box-shadow:/s);
});

test('排序列与自动刷新控件样式保持完整', () => {
  assert.match(merchantCss, /\.cc-table th\.is-sortable\s*\{[^}]*cursor:\s*pointer/s);
  assert.match(merchantCss, /\.cc-table th\.is-sortable::after\s*\{[^}]*content:\s*" ⇅"/s);
  assert.match(merchantCss, /\.cc-autorefresh\s*\{[^}]*display:\s*inline-flex/s);
});
