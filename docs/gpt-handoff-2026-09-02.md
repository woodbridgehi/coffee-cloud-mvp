# 交接说明 · cc-ui 移植分支（给后续 AI / 开发者，2026-09-02）

## 当前状态

- 分支：`feat/cc-ui-port`（基于 main `60a3d41`），4 个提交，工作区干净：
  1. `f1855ad` 商户端一次性移植（m01–m35 → merchant.html/css/js）
  2. `12babb4` 平台端移植（a01–a11 → admin.html/css/js）+ 发布说明
  3. `587623a` `?demoAuto=1` 演示直达（仅 demo 模式）
- 消费者端（order.*）**未移植**，仅把 CSS 引用改为 `shared/coffee-ui-legacy.css` 过渡。
- 前端测试：`node --test tests/*.mjs` → **61 passed / 0 failed**。
- 详细变更：`docs/releases/2026-09-02-cc-ui-port.md`；实施计划与验收清单：`docs/open-design-cc-port-plan-2026-09-02.md`。

## 架构约定（改动前必读）

1. **组件体系唯一来源**：`public/shared/coffee-ui.css`（Open Design cc-* 系统，802 行）。
   页面级补充只在 `merchant.css` / `admin.css`，禁止在里面加品牌色值。
2. **图标**：`public/shared/cc-icons.js`（`global.ccIcon(name,size)` / `<i data-cc-icon>`，注意 paint 只匹配 `<i>` 标签）。JS 建 DOM 用 `svgIcon()` 辅助。
3. **CSP**：`app/merchant/http.py` 为 `script-src 'self'` —— 禁止内联事件处理器（`onclick=` 属性），一律 `addEventListener`；内联 `style=` 允许。
4. **测试锚点（改名会破坏测试，勿动）**：
   - `merchant.js` 中 `let dashboardMemo =` … `function statCard(` 之间的源码段被 `tests/merchant-dashboard-snapshot.test.mjs` 用字符串切片执行，必须保持自包含；
   - `admin.js` 中 `function rowActivate(` 与 `function captureRowFocus(` 相邻，被 `tests/admin-keyboard.test.mjs` 切片执行；
   - 元素 id（`side-nav` / `workspace` / `modal-root` / `drawer-root` / `top-controls` / `who` 等）被 DOM 桩测试引用。
5. **数据正确性红线**（沿用 `docs/open-design-code-to-code-brief.md` 第五节）：0/null/缺失/加载/失败/无权限六态区分；金额分↔元；图表缺口不画 0；未知枚举不得显示成功色；退款上限缺失禁用提交。
6. **响应式断点来自设计稿**：≥1024 完整侧栏 / 768–1023 72px 图标栏 / <768 侧栏隐藏+底部导航。用户曾因窗口 <1024 误判“样式丢失”；如需调整须用户拍板。

## 本地起服务（含冒烟环境复原）

```bash
brew services start postgresql@17          # 数据库（冒烟库 coffee_smoke 与角色 coffee_merchant 已建好）
cd /Users/alex/Downloads/armaster/coffee-cloud-mvp
set -a; source /tmp/coffee-smoke.env; set +a   # 若文件已删见下方最小 env
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

最小 env（如 /tmp/coffee-smoke.env 不存在）：
```
DATABASE_URL=postgresql://alex@127.0.0.1:5432/coffee_smoke
ADMIN_TOKEN=<任意≥24字符>
MERCHANT_ENABLED=true
MERCHANT_REGISTRATION_MODE=USERNAME
MERCHANT_LIMITED_RELEASE=true
MERCHANT_COOKIE_SECURE=false
MERCHANT_ENCRYPTION_KEY=<Fernet key>
PUBLIC_BASE_URL=http://127.0.0.1:8790    # 关键：API 有 Origin 校验
PUBLIC_PAYMENT_MODE=TEST_FREE
ALLOW_MOCK_PAYMENT=true
RUN_ORDER_SSE_LISTENER=false
```
注意：`.venv` 已按 README 用 uv 重建为 Python 3.12（旧 3.9 无 scrypt）。首次启动顺序：先跑迁移（默认启动即迁移）→ `.venv/bin/python -m app.merchant.provision`（仅需一次，已完成）→ 起服务。

入口：
- 商户端 `http://127.0.0.1:8790/assets/merchant.html`（演示直达加 `?demo=1&demoAuto=1`）
- 平台端 `/admin`（Token = ADMIN_TOKEN）
- 消费者 `/order`

设计稿原型（纯静态，可双击对照）：`/Users/alex/Downloads/webpage/`（m\* 商户 / a\* 平台 / c\* 消费者 / index.html 规范）。

## 待办（按优先级）

1. **浏览器逐屏验收**（用户进行中）：视口 1440/768/390（补 320），逐 `data-od-id` 对照原型；问题反馈格式=截图+视口+路径。
2. 验收修复后合并回 main（独立 merge commit，可整体 revert）。
3. 消费者端 c01–c05 移植（第二批）：order.\* 切到规范 `coffee-ui.css` 后删除 `coffee-ui-legacy.css`。
4. VPS 部署：整目录同步 `public/`（新增 `shared/cc-icons.js`），版本号已统一 `?v=20260902-cc1`。
