# Open Design 前端改版交付说明（2026-09-01）

改版分支：`open-design-revamp`（基于 `2d1e13c`，其父链含基线 `8ab07a7` / 标签 `b2b-username-release-20260831`）。
工作副本位于 Open Design 项目目录，原仓库 `/Users/alex/Downloads/armaster/coffee-cloud-mvp` 未做任何修改。
原有未提交内容（`.gitignore` 修改、`docs/system-architecture/`）保持原样，未纳入本次提交。

## 一、修改文件清单

| 文件 | 类型 | 变更摘要 |
|---|---|---|
| `public/shared/coffee-ui.css` | 新增 | 三套前端唯一视觉令牌源头（`--cc-*` 命名空间）+ `cc-` 工具类 + 统一 reduced-motion |
| `public/admin-format.js` | 新增 | 平台后台纯展示函数（fmtMoney/fmtTime/fmtAgo/fmtPercent），可被 Node 回归测试导入 |
| `public/merchant.html` | 修改 | 引入共享令牌；主要区域补 `data-od-id` |
| `public/merchant.css` | 修改 | 令牌改别名映射；数值列右对齐规则 |
| `public/merchant.js` | 修改 | ① `tdl`/`makeTable` 数值列自动标记（表头同步右对齐）；② 总览 4 次 `/dashboard` 请求合并为单快照（失败清缓存可重试）；③ 退款可退上限遇 `receivedMinor/refundedMinor` 缺失按「待补全」禁用提交，不再 `\|\| 0`；④ 采购合计缺失明细金额标「＊待补全」不按 0 累加 |
| `public/admin.html` | 修改 | 引入共享令牌；脚本改 ES Module；版本号 `?v=20260827→20260901`；补 `data-od-id` |
| `public/admin.css` | 修改 | 令牌别名映射；数值列右对齐；≤720px 表格卡片化（data-label） |
| `public/admin.js` | 修改 | 展示函数抽入 `admin-format.js`（未知金额显示「—」）；全部表格补 `data-label` 与 `responsive` 类；金额/Token 数列右对齐 |
| `public/order.html` | 修改 | 引入共享令牌；theme-color 对齐 `#f6f2ec`；版本号 bump；补 `data-od-id` |
| `public/order.css` | 修改 | 令牌别名映射；圆角/阴影/边框并入统一标度；保留消费者专属展示字体与深色文字变体 |
| `public/order.js` | 修改 | `money()` 缺失金额返回「—」，不再兜底 `¥0.00` |
| `tests/admin-format.test.mjs` | 新增 | 4 项回归：未知金额≠¥0.00、整数算术换算、百分比缺失≠0%、相对时间 |
| `tests/merchant-ui-smoke.test.mjs` | 修改 | 补数值列 num 标记与 data-label 覆盖断言（原有断言未删改） |

## 二、统一设计规范（落成于 `shared/coffee-ui.css`）

- **色彩**：暖白底 `#f6f2ec`、卡片白、墨色三级文字（`#261a11 / #4d3c2d / #7d6e5f`）；品牌 espresso `#35241a`（主按钮）、caramel `#a3652c`（强调/焦点，每屏 ≤2 处）；状态色 sage/danger/amber/azure 均配同色系 soft 底。
- **字体**：UI 为系统栈（PingFang SC 优先）；数字一律 `font-variant-numeric: tabular-nums`；消费者页标题用宋体系展示字体（`--cc-font-display`），两个运营后台为数据密集界面不使用展示字体。
- **圆角**：16 / 12 / 9 三级；**阴影**：卡片 `0 1px 3px`、浮层 `0 18px 44px`；**焦点环**：`0 0 0 3px rgba(163,101,44,.35)`。
- **组件规则**：按钮高度统一（默认 38px / small 30px）；金额列右对齐 + 等宽数字；表格 ≤720px 转「标签—值」卡片（`data-label`）；弹窗/抽屉/Toast 三套同规格；危险操作红色实底且与普通操作分离。
- **命名空间**：共享层只暴露 `--cc-*` 令牌与 `cc-mono/cc-num` 工具类；页面级派生值（如 `--danger-deep` 文字变体）仅存在于各自文件，互不污染。
- **缓存**：`/assets/shared/coffee-ui.css` 不在 no-store 中间件清单内，统一走 `?v=20260901` 版本化引用；admin/order 既有版本号已同步 bump。

## 三、逐页验收矩阵

图例：✅ = 代码级验证（静态走查 + Node 测试）；⏳ = 需真实浏览器/后端验收，本次未执行。

| 范围 | 项目 | 状态 |
|---|---|---|
| 客户后台·认证 | USERNAME 注册/登录、配置失败重试页、邮件关闭入口（找回/验证/邀请统一禁用说明） | ✅（冒烟测试） |
| 客户后台·总览 | 指标卡、趋势图（缺口不画 0）、告警、最近订单；单快照合并后四块一致 | ✅ |
| 客户后台·订单 | 列表筛选/分页/详情抽屉/退款弹窗（未知上限禁用）；金额列右对齐 | ✅ |
| 客户后台·设备 | 列表/详情抽屉/认领/生命周期/解绑/转让/命令轮询；allowedActions 门控未改 | ✅ |
| 客户后台·其余 | 转让、门店、价格、物料/采购/库存/出入库、费用、报表+CSV、成员、收款账户、组织设置、审计 | ✅（行为未改，仅对齐与缺失值） |
| 平台后台 | 登录、总览、设备（详情/命令/激活码）、订单（含 HOLD/失败展开）、权限/Token、审计；未知金额「—」 | ✅（格式化函数回归测试） |
| 消费者页 | 菜单/选购/结算栏、支付等待（二维码稳定性）、SSE 状态流、里程碑/进度/时间线、失败/取消/退款横幅 | ✅（test_order_view） |
| 视口 390/768/1440/320 | 三套页面无页面级横向溢出（表格为局部滚动或卡片化） | ⏳ 静态走查通过，待浏览器实测 |
| 真实后端联调 | Cookie/CSRF/409/权限差异/组织切换 | ⏳ 未动契约，待隔离环境验收 |

**测试结果**：`node --test tests/merchant-ui-*.test.mjs tests/test_order_view.mjs tests/admin-format.test.mjs` → **53 passed / 0 failed**（基线 49 + 新增 4）。`node --check` 全部前端 JS 语法通过。

## 四、未验证项与已知限制

1. 未启动真实浏览器逐视口截图验收（本环境无浏览器）；390px/320px 结论基于响应式规则的静态推演。
2. 未连接真实后端/隔离环境做联调；未执行任何真实支付、退款或设备命令。
3. `/assets/admin.js` 由 classic script 改为 ES Module（defer 语义不变）；如部署层有 script 类型相关 CSP 需同步（当前代码库未发现 CSP 头）。
4. openapi 快照不含商户接口，未据此改动（按后端实现为准）。

## 五、后端契约观察（未改 Python，仅记录）

- 平台 admin API 错误体为 `detail` 字符串/对象，商户 API 为 `{error:{code,message,...}}`，两套形状不同；前端已分别适配，建议后续统一。
- 客户后台总览原实现每次渲染请求 `/dashboard` 4 次，属前端问题，已在本次合并为单请求；后端无需变更。
- 设备物料余量契约无容量字段，余量条按状态分级展示（不臆造百分比），维持现状。

## 六、打磨批次（2026-09-02 · 平台后台 admin.html）

范围：`admin.html / admin.css / admin.js / shared/coffee-ui.css`（merchant/order 仅同步 coffee-ui 版本号）。测试：`node --test tests/*.mjs` → 53 passed / 0 failed。

**交互修复（P0）**
- 订单表格行点击后现在立即插入/移除详情行（原实现只切换高亮，要等 10s 自动刷新才出现详情）；键盘 Enter/Space 同样可展开。
- 弹窗补焦点圈定（Tab 循环）、Esc 关闭、关闭后焦点归还触发元素。
- 四类可点击行（订单/设备/运营员/审计）全部可键盘操作，带 `aria-expanded` / `aria-current` / `aria-haspopup`；自动刷新重渲染后焦点保持在原行（`data-row-key` 机制）。
- 17 处 JS 生成表单改为 `<label for>` 关联（`field()` 辅助函数）。

**可访问性（P0）**
- 焦点环令牌改为「白色间隔 + 实色焦糖环」，白底对比度 ≥3:1（原 35% 透明环约 1.5:1）；merchant 同步受益。
- 键盘聚焦行显示内侧 caramel 描边，与悬停/选中区分。
- 错误 Toast 改 `role=alert`（assertive），信息/成功保持 status。
- 导航当前项补 `aria-current="page"`；视图切换后焦点移至视图标题（可被屏幕阅读器播报）。

**排版与响应式（P1）**
- CJK 标题移除负字距（登录 h1、顶栏 h2）；表头大写间距 0.05→0.06em；side-eyebrow 10→11px。
- secondary 按钮 hover：加深文字色（≥5.8:1）并加浅底，不再降低对比度。
- `kv-grid` 改 `auto-fit minmax(200px,1fr)`：320px 下登记弹窗与详情面板自动单列。
- 手机端（≤720px）按钮/导航/弹窗关闭触控目标 ≥44px；工具栏按钮组等宽铺满。
- 统计卡 3→2 列时第三张整行展开，消除孤行；订单详情内边距 18→14px 与表格列对齐。

**数据正确性（P1）**
- 活跃订单、心跳/事件/命令计数、Token 数在字段缺失时显示「—」，不再 `?? 0`。

**缓存**：admin 三资源与三页 coffee-ui 引用统一 `?v=20260902`。

**未验证项**：弹窗焦点圈定、行键盘导航、触控目标为静态走查 + 语法/单测验证；真实浏览器逐视口交互仍待实测（本环境无浏览器，导出渲染器无法解析 `/assets` 绝对路径映射，不做误导性截图）。
