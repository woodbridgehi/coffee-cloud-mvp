# Open Design cc-ui 一次性移植实施计划（2026-09-02）

目标：将 `/Users/alex/Downloads/webpage` 的 Open Design 新范式页面（`cc-*` 组件体系）
**一次性整体**移植进本项目，不做新旧混排的渐进过渡。消费者端（c01–c05 / order.*）本轮不做。

## 一、范围

| 端 | 设计稿 | 现有实现 | 本轮 |
|---|---|---|---|
| 商户运营后台 | m01–m35 | `public/merchant.html/css/js`（+ demo/format/api） | ✅ 全量移植 |
| 平台运维后台 | a01–a11 | `public/admin.html/css/js` | ✅ 全量移植（espresso 主题） |
| 消费者点单页 | c01–c05 | `public/order.html/css/js` | ❌ 暂缓，保持现状可用 |

后端 Python、API 契约、鉴权、部署配置一律不动。

## 二、最终形态（文件架构）

```
public/
  shared/
    coffee-ui.css        新设计系统完整版（源自原型 802 行：全部 --cc-* 令牌 + cc-* 组件）
    coffee-ui-legacy.css 旧令牌文件改名，仅供 order.html 过渡（消费者端移植后删除）
    cc-icons.js          图标库（global.ccIcon / ccPaintIcons，源自原型）
    cc-runtime.js        从原型 cc.js 抽出的可复用交互件：chart（含数据表）、ring、
                         tabs、segmented、copy、toast、命令面板；不含外壳构建
  merchant.html          新外壳骨架（cc-shell / cc-side / cc-top / cc-content / #workspace）
  merchant.css           瘦身为页面级布局（认证分栏、dash 双栏等），只消费 cc 令牌
  merchant.js            业务逻辑层不动；DOM 构建层全量替换为 cc-* 词汇
  admin.html/css/js      同上；body[data-shell="admin"] 绑定 espresso 主操作色
  order.html             仅改一行 css 引用（→ legacy）+ 版本号
```

命名说明：新设计系统占用 `coffee-ui.css` 规范名，保证"三套前端唯一视觉源头"的最终结构；
旧文件改名 legacy 只服务 order.html，避免消费者端在本轮被波及。

## 三、总体策略

1. **单分支一次性替换**：`feat/cc-ui-port` 分支上按批次执行，main 上不出现任何中间态。
   整个商户端完成后合并一次；平台端可随同合并或紧随其后合并（一次 merge commit，可整体 revert）。
2. **同批次内不留旧皮**：merchant.css/js 的组件词汇在本轮内全量切换为 cc-*，
   完成后旧组件类（card/badge/m-cards/kv/nav-item…）全部清除，不留双体系。
3. **业务逻辑零改动红线**：
   - `merchant-api.js`（真实适配器）、`merchant-format.js`、CSRF/会话/权限/409/幂等/组织切换取消请求等逻辑不动；
   - demo 适配器数据不动，仅其 UI 断言与渲染跟随新词汇更新；
   - hash 路由与 URL 结构不变；原型中的独立页（m12–m17、m23、m31 等）对应现有抽屉/弹窗，
     **保留抽屉/弹窗形态**，不拆成多页跳转。
4. **CSP 合规**：`script-src 'self'` —— 原型 71 处内联 `onclick=` 全部转为 `addEventListener`；
   内联 `style=`（`style-src 'unsafe-inline'` 允许）可保留。不引入外链/CDN/构建步骤。
5. **数据正确性红线**（沿用 `open-design-code-to-code-brief.md` 第五节）：
   0 / null / 缺失 / 加载中 / 失败 / 无权限六态区分；金额分↔元严格转换；组织时区与右开区间口径；
   图表缺口不画 0；未知枚举不得显示为绿色成功；无权限数据不得残留在隐藏 DOM。

## 四、批次计划（AI 执行单元，每批结束必须全绿）

### Batch 0 · 分支与资产落位（~0.5 天）
- 建 `feat/cc-ui-port` 分支。
- 原型 `assets/coffee-ui.css / cc-icons.js` 落位为 `shared/coffee-ui.css / cc-icons.js`
  （清除原型专用规则，如静态 demo 数据样式；补 merchant/admin 需要的少量组件态）。
- 旧 `shared/coffee-ui.css` → `coffee-ui-legacy.css`；`order.html` 改引用 + bump 版本号。
- 新建 `shared/cc-runtime.js`（chart/ring/tabs/seg/copy/toast/palette）。
- 完成标准：`node --check` 通过；本地起服务，order 页与旧 merchant/admin 页资源加载正常（暂未换皮）；
  `node --test tests/*.mjs` 基线全绿。

### Batch 1 · 共享组件层（JS 基础件）（~1 天）
- merchant.js 的中央辅助全量换词汇：`makeTable/tdl` → `cc-table/cc-tablewrap`（保留 num 右对齐、
  data-label 响应式）；`openModal` → `cc-dialog`、`openDrawer` → `cc-drawer`、`toast` → `cc-toast`、
  popover → `cc-menu`；`badge/statusBadge` → `cc-status/cc-tag`；按钮 → `cc-btn` 系列。
- 焦点陷阱、Esc、焦点归还、aria 逻辑原样保留，只换皮。
- chart/ring 接入 cc-runtime（图表下挂 `cc-disc` 数据表）。
- 完成标准：demo 模式下弹窗/抽屉/表格可用；相关单测更新后全绿。

### Batch 2 · 商户端外壳 + 认证流（m01–m09）（~1–1.5 天）
- `merchant.html` 骨架重写；`buildShell()` → `cc-side`（分组导航+门控标记）/ `cc-top`
  （组织切换菜单、账号菜单）/ `cc-scopebar`（门店 + 日期段 + LIVE/TEST 从现有 top-controls 迁入，
  绑定既有 state）/ `cc-bottomnav` + 更多 Sheet / 命令面板（⌘K，索引=有权限视图）。
- `renderAuth` 9 种模式（登录/注册/找回/重置/验证/邀请/结果/工作区说明/重验 m09）按原型重排，
  保留 auth config 加载、邮件关闭禁用态、用户名规则校验。
- 完成标准：merchant-ui-auth / smoke 测试更新后全绿；demo 模式走通登录→外壳→登出。

### Batch 3 · 商户端核心三视图（~2–3 天）
- **m10 总览**：状态摘要条 + 指标网格（cc-metricgrid，保留 OPERATOR 视角降级）+
  告警工作队列 + 趋势图（数据表）+ 最近订单；单快照请求逻辑不动。
- **m11–m17 设备**：列表（cc-toolbar 搜索/筛选）+ 详情抽屉 + 认领/编辑/生命周期/解绑/转让弹窗；
  allowedActions 门控不动。
- **m21–m23 订单**：列表筛选/分页 + 详情抽屉 + 退款弹窗（未知上限禁用提交逻辑不动）。
- 完成标准：三视图 + 全部二级交互在 demo 与真实测试环境可用；smoke/api/snapshot 测试全绿。

### Batch 4 · 商户端其余视图（m18–m20、m24–m35）（~1.5–2 天）
转让 / 门店 / 价格 / 物料·采购·库存·出入库 4 Tab / 费用 / 报表+CSV / 成员+邀请 /
收款账户 / 组织设置 / 审计 / 演示工具（m35）。逻辑与门控全部沿用，仅重排。
完成标准：13 视图全部换皮完毕；merchant.css 旧组件规则清零。

### Batch 5 · 平台端（a01–a11）（~1.5–2 天）
admin 外壳+登录（a01–a02）、总览、设备+详情+激活码（a04–a06）、订单+详情（a07–a08）、
权限+Token（a09–a10）、审计（a11）；espresso 主题经 `body[data-shell="admin"]`。
保留：自动刷新焦点保持（data-row-key）、键盘行导航、一次性秘密展示逻辑。
完成标准：admin-keyboard 等测试更新后全绿。

### Batch 6 · 清理、验收与发布（~1 天）
- 删除 merchant.css/admin.css 中被 cc-ui 覆盖的全部死规则；三入口资源版本统一 bump `?v=20260902-cc1`。
- 全部 `node --test tests/*.mjs` 通过；`node --check` 全部 JS。
- 浏览器验收：demo 模式 + 本地真实后端，视口 320/390/768/1440，逐页核对
  100 个 `data-od-id` 区域（标记随移植带入 SPA DOM，供后续 Open Design 迭代 diff）。
- 产出发布文档：变更清单、逐页验收矩阵、未验证项如实声明（沿用历轮格式）。
- 合并方式：独立 merge commit；不部署 VPS，由人工审查后决定。

## 五、设计稿 ↔ 实现映射（验收对照）

| 设计稿 | 现有实现（形态保留） |
|---|---|
| m01–m07 | renderAuth 各模式（找回/验证/邀请为邮件关闭禁用态） |
| m08 工作区说明 | 登录后组织选择/说明（现顶栏组织菜单） |
| m09 重新验证 | reauthModal |
| m10 总览 | renderDashboardView |
| m11/m12 | 设备列表 / 认领弹窗 |
| m13–m17 | 设备详情抽屉、编辑、生命周期、解绑、转让弹窗 |
| m18 转让 | renderTransfersView |
| m19/m20 | 门店 / 价格 |
| m21–m23 | 订单列表 / 详情抽屉 / 退款弹窗 |
| m24–m27 | 物料 4 Tab（materials/purchases/inventory/movements） |
| m28–m34 | 费用 / 报表 / 成员+邀请 / 收款账户 / 设置 / 审计 |
| m35 | demo 工具 |
| a01–a02 | admin 登录 / 工作区说明 |
| a03–a11 | admin 总览 / 设备+激活码 / 订单 / 权限+Token / 审计 |

## 六、测试策略

- 行为断言（金额≠0 兜底、退款门控、总览单请求、键盘冒泡、焦点归还等）**一律保留**；
  仅结构类断言（旧类名）按新 DOM 更新，每处注明变更依据（brief 第七节许可）。
- 涉及文件：`merchant-ui-{smoke,api,auth,format}.test.mjs`、`merchant-dashboard-snapshot.test.mjs`、
  `admin-format.test.mjs`、`admin-keyboard.test.mjs`。
- DOM stub 按新骨架同步扩展；不为通过测试放宽 stub 行为。

## 七、风险与回滚

| 风险 | 缓解 |
|---|---|
| 单分支体量大，review 困难 | 每批次独立可运行、测试全绿才进下一批；合并用独立 merge commit，可整体 revert |
| 视觉细节与原型偏差 | data-od-id 逐区对照 + 浏览器逐视口截图验收 |
| 测试大面积更新引入回归 | 行为断言清单化，逐条迁移核对 |
| 消费者端被波及 | Batch 0 只改 order.html 一行引用；每批回归打开 order 页冒烟 |
| 部署遗漏 shared 新文件 | 发布文档明确"整目录同步"；版本号统一 bump |

## 八、工作量汇总（AI 执行 + 人工验收）

Batch 0–6 合计约 **8–10 个工作日**（其中 AI 编码可压缩至 2–3 个工作会话，
浏览器逐页验收与人工 review 为主要耗时，不可省）。
