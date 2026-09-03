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

test('OpenDesign 品牌基底、设备状态呼吸光晕与物料斜纹预占条样式就绪', () => {
  assert.match(merchantHtml, /data-cc-icon="brand-symbol"/);
  assert.match(adminHtml, /data-cc-icon="brand-symbol"/);
  assert.match(sharedCss, /@keyframes breathConn/);
  assert.match(sharedCss, /\.inv-track\s*\{[^}]*height:\s*7px/s);
  assert.match(sharedCss, /\.inv-rsv\s*\{[^}]*repeating-linear-gradient/s);
  assert.match(sharedCss, /\.ro-tag\s*\{[^}]*font-family:\s*var\(--cc-mono\)/s);
});

test('OpenDesign 设备抽屉深色控制台域与物料卡片精密排版就绪', () => {
  assert.match(merchantCss, /\.console-dark\s*\{[^}]*background:\s*var\(--cc-k-bg,\s*#0D1713\)/s);
  assert.match(merchantCss, /\.console-meta-grid\s*\{[^}]*grid-template-columns:\s*1fr\s+1fr/s);
  assert.match(merchantCss, /\.event-log-container\s*\{[^}]*background:\s*#09110E/s);
  assert.match(merchantCss, /\.m-inv-card\s*\{[^}]*display:\s*flex/s);
  assert.match(merchantCss, /\.sw-rsv\s*\{[^}]*repeating-linear-gradient/s);
});

test('OpenDesign 两段式布防按钮（Armed Buttons）样式与脉冲动画就绪', () => {
  assert.match(sharedCss, /\.cc-btn-armed\s*\{[^}]*display:\s*inline-flex/s);
  assert.match(sharedCss, /\.cc-btn-armed--warn\.is-armed\s*\{[^}]*background:\s*var\(--cc-k-warn/s);
  assert.match(sharedCss, /\.cc-btn-armed--crit\.is-armed\s*\{[^}]*background:\s*var\(--cc-k-crit/s);
  assert.match(sharedCss, /@keyframes armedPulseWarn/);
  assert.match(sharedCss, /@keyframes armedPulseCrit/);
});

test('OpenDesign 品牌标志（brand-symbol）在侧栏与登录页容器中正确挂载 SVG', () => {
  const iconsJs = readFileSync(new URL('../public/shared/cc-icons.js', import.meta.url), 'utf8');
  assert.match(iconsJs, /querySelectorAll\('\[data-cc-icon\]'\)/);
  assert.match(iconsJs, /el\.innerHTML\s*=\s*html/);
  assert.match(merchantHtml, /<span class="cc-logo"[^>]*data-cc-icon="brand-symbol"/);
  assert.match(adminHtml, /<span class="cc-logo"[^>]*data-cc-icon="brand-symbol"/);
});

test('OpenDesign 侧栏与顶栏豆格阵列（bean-grid）品牌水印底纹就绪', () => {
  const sharedCssCurrent = readFileSync(new URL('../public/shared/coffee-ui.css', import.meta.url), 'utf8');
  assert.match(sharedCssCurrent, /--cc-watermark-bean:\s*url\("data:image\/svg\+xml/);
  assert.match(sharedCssCurrent, /\.cc-side::before\s*\{[^}]*background-image:\s*var\(--cc-watermark-bean\)/s);
  assert.match(sharedCssCurrent, /\.cc-side::before\s*\{[^}]*pointer-events:\s*none/s);
  assert.match(sharedCssCurrent, /\.cc-top::before\s*\{[^}]*background-image:\s*var\(--cc-watermark-bean\)/s);
  assert.match(sharedCssCurrent, /\.cc-top::before\s*\{[^}]*pointer-events:\s*none/s);
  assert.match(sharedCssCurrent, /\.cc-side > \*\s*\{[^}]*z-index:\s*1/s);
  assert.match(sharedCssCurrent, /\.cc-top > \*\s*\{[^}]*z-index:\s*1/s);
});
