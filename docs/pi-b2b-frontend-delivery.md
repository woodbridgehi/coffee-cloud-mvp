# pi 交付说明 · B 端客户运营后台前端

日期：2026-08-31。执行者：pi（前端实现轮）。本文件如实记录交付范围、验证方式与结果、未执行项和接口疑问。本轮只新增前端文件，未修改任何后端、数据库、配置、密钥、现有 admin/order 页面或其他人的文件；未连接 VPS、未部署、未执行任何 git 提交。

## 1. 文件清单（全部为新增）

| 文件 | 作用 |
| --- | --- |
| `public/merchant.html` | 客户后台入口（相对引用，支持 `/assets/merchant.html` 与 `python3 -m http.server` 直开） |
| `public/merchant.css` | 全部样式：桌面侧栏 + 顶栏筛选 + 响应式（≤920 侧栏抽屉化、≤720 表格转卡片、≤460 指标两列）、reduced-motion、focus 样式 |
| `public/merchant.js` | 应用主体：认证界面、会话/组织切换、13 个视图、弹窗/抽屉/Toast/图表/表单工具 |
| `public/merchant-api.js` | 真实 API 适配器（默认）：同源 `/api/v1/merchant`、`credentials: 'same-origin'`、CSRF 仅内存、Idempotency-Key、错误规范化（含非 JSON 响应、Retry-After、Content-Disposition 解析）、CSV 下载校验 |
| `public/merchant-format.js` | 纯工具模块（无 DOM）：金额分格式化/解析、数量十进制字符串、组织时区日期、区间换算（界面含当日 ↔ API 不含当日）、CSV 转义、niceTicks 等；供页面与 Node 测试共用 |
| `public/merchant-demo.js` | 显式演示适配器（仅 `?demo=1`）：内存双组织/四门店/8 台设备/订单/采购/费用/转让 fixture + 演示工具，不发送任何网络请求 |
| `tests/merchant-ui-format.test.mjs` | 纯逻辑测试（22 项）：金额/日期/CSV 工具 + 演示适配器行为（租户隔离、权限、确定性报表、退款 PENDING、409 保护、转让阻断） |
| `tests/merchant-ui-smoke.test.mjs` | DOM stub 冒烟测试（7 项）：真实 merchant.js 在最小 DOM shim 下登录→外壳→路由→设备抽屉→组织切换→登出→OPERATOR 权限可见性→TEST 横幅 |
| `docs/pi-b2b-frontend-delivery.md` | 本文件 |

修改范围核验：`git status --porcelain` 仅上述新文件为未跟踪；`git diff --stat` 仅有本轮开始前已存在的 `.gitignore` 未提交修改（属主代理基线，未改动）。

## 2. 预览方式

```bash
# 方式一：静态直开（接口不可用时会如实显示错误）
cd public && python3 -m http.server 8000
# 真实接口模式：http://localhost:8000/merchant.html
# 演示模式：    http://localhost:8000/merchant.html?demo=1

# 方式二：随 FastAPI（public 挂载在 /assets）
# http://<host>/assets/merchant.html[?demo=1]
```

运行测试与语法检查：

```bash
node --test tests/merchant-ui-format.test.mjs tests/merchant-ui-smoke.test.mjs
# 29 项全部通过（Node v24.20.0）
# 语法检查：将 public/merchant-*.js 复制到带 {"type":"module"} 的临时目录后
# 逐个 node --check，全部通过（结果见第 5 节）
```

## 3. 逐页完成清单

按任务文档 D 节对照。所有写入均防重复提交、以 API 返回为准、失败如实展示；所有数据区均有 loading / empty / error(重试) / permission denied 状态。

1. **注册 / 登录 / 找回 / 重置 / 邮箱验证 / 接受邀请**：六种认证视图（hash 路由 `#/login|register|forgot|reset|verify|invite`）。链接 token 从 URL fragment 读取后立即 `history.replaceState` 清理、仅存内存；验证邮箱必须用户点击「确认验证邮箱」主动触发；注册成功只显示等待验证；找回密码显示通用受理文案（防枚举）；密码不记录、不进存储。
2. **会话与组织切换**：登录后构建外壳；顶栏含组织切换（`POST /session/tenant`）、门店筛选、日期区间（今天/近7天/本月/本年/自定义，界面含当日、适配层转 API 不含当日右边界，显示组织时区）、数据环境 LIVE/TEST（TEST 时持续显示「测试数据，不计入正式经营」横幅）、个人菜单（重新验证身份、撤销其他会话、退出登录）。切换组织时：epoch 递增 + AbortController 取消在途请求 + 清空抽屉/弹窗/导出 URL/筛选，再按新会话重建导航并重载视图。
3. **经营总览**：OWNER/FINANCE 视角展示设备、营业净收入、净收款、经营利润（估算）卡片 + 实收/退款/成本/损耗/手续费/费用/杯数 chips + completeness 提示 + SVG 双序列趋势图（附文字摘要与数据表）+ 告警列表 + 最近订单；OPERATOR 视角仅设备/在线率/杯数/告警，无任何财务卡片。
4. **我的设备**：门店/生命周期/搜索筛选；行点击开详情抽屉（基本信息、能力清单、物料余量、告警、当前任务、归属/数据版本）；操作完全由服务端 `allowedActions` 驱动：编辑资料（PATCH+version）、生命周期变更（SUSPEND/RESUME/ARCHIVE，必填原因，ARCHIVE 二次确认输入「归档」）、远程命令（确认弹窗显示设备与门店；受理后轮询状态，PENDING/EXECUTING/SUCCEEDED/FAILED 与查询超时分别展示）、申请解绑、发起转让；认领设备（claimCode+门店+名称，Idempotency-Key）。
5. **设备转让**：列表展示状态流与阻断原因；接收方确认 / 发起方取消（均携带 version，409 提示刷新）。
6. **门店**：列表/新增/编辑（名称、地址、状态归档）；有设备门店归档 409 时展示服务端指引文案。
7. **商品价格**：按门店/设备筛选；区分「当前价 / 计划生效」徽标；新增价格（元→分严格两位小数、拒绝负值/NaN、生效时间可选）；提示不改变历史订单。
8. **订单与退款**：全局日期/门店/环境 + 状态/设备筛选，cursor 分页「加载更多」；详情抽屉含商品明细、支付（渠道/账户标签/环境）、退款（申请中/成功分开展示）、时间线、成本摘要（MISSING 显示待补全）；退款弹窗显示可退上限、部分退款以服务端为准、超限前端即拦截并显示服务端 422 字段错误；提交后状态为「退款申请中」，不显示成功。
9. **物料 / 采购 / 库存 / 出入库**（四标签页）：物料档案（单位/精度/平均成本，无成本显示待补全；OPERATOR 不显示成本列）；采购（草稿创建/编辑/入账，明细行动态增删，已入账不可改的提示）；库存（在存/占用/可用/成本状态）；出入库流水（类型筛选、事件 ID、正负号数量），新增出入库按类型显隐字段，ADJUSTMENT 允许带负号差额、其余类型强制正数，提交前确认弹窗说明数量语义。
10. **运营费用**：类别/金额/归属/发生日/分摊方式；DAILY_EQUAL 显示区间与「仅预览、以服务器为准」的日均估算；草稿入账、已入账冲正（必填原因，不删除历史）。
11. **经营报表**：日/月/年粒度、指标切换柱状图（缺成本区间画缺口标记不画 0）、汇总卡片与合计行（未知显示待补全）、completeness 横幅、口径说明（净收款/营业收入/毛利/经营利润定义）；CSV 导出（`reports.export` 权限，校验响应与 Content-Type，下载后 revokeObjectURL；演示导出带「界面演示」标记）。
12. **成员权限**：成员列表（角色/门店范围/状态）+ 编辑（角色、状态、门店范围 ALL/SELECTED+勾选，version，最后一位 OWNER 409 提示）；邀请列表（deliveryStatus 区分「已进入发送队列 / 邮件服务不可用」）+ 新邀请 + 撤销；角色能力说明文案。
13. **收款账户**：列表（渠道/正式/沙箱/模拟徽标、脱敏 appId/商户号、默认标记）；新增（密钥用 textarea/密码控件，提交或关闭立即清空，不回显不记录）；校验（checks 明细弹窗）；设为默认（确认提示只影响新支付、校验未通过 409）；停用（默认账户 409 指引）。
14. **组织设置**：名称 + 时区（version），时区变更被 409 拒绝时展示账期说明。
15. **审计**：日期/动作筛选 + 分页；展示操作者、动作、资源、结果、requestId；不整段展示原始 JSON。

## 4. 真实 / 演示边界

- 默认真实适配器；仅 URL 显式 `?demo=1` 启用演示适配器，任何失败都不会、也不能自动转入演示（已用真实模式冒烟验证：后端缺失时登录显示「网络请求失败，请检查网络连接后重试」并停留在登录页）。
- 演示模式全程固定顶部横幅「界面演示 · 数据仅存在当前页面内存 · 不操作真实设备/支付」，登录页展示演示 token 提示；左下角「演示工具」面板仅演示模式存在：切换角色（OWNER/OPERATOR/FINANCE）、故障模拟（空数据 / 403 / 网络失败 / 慢响应 1.3s）、邮件服务不可用、模拟退款成功、重置演示数据。
- 演示数据：两组织、四门店、8 台设备（在线/离线/停用/待激活/归档）、近 30 天混合状态订单（含部分退款/全额退款/退款中/HOLD/测试环境）、缺成本订单、采购草稿与已入账、费用分摊、出入库流水、转让（待接收/阻断）、成员与邀请、三类收款账户、审计事件。报表与趋势由确定性公式按日期生成（同日期结果恒定，测试断言两次调用 deepEqual 一致）；缺成本日期 materialCostMinor 为 null，合计保持 null 显示「待补全」。
- 演示适配器与真实适配器导出同名同形方法，业务视图不区分两套流程；演示适配器不发送任何 merchant/admin 请求。

## 5. 验证命令与结果

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| ESM 语法检查 | 复制到 `{"type":"module"}` 临时目录逐个 `node --check`（merchant-format/api/demo/merchant.js 及两个测试文件） | 全部通过 |
| 纯逻辑测试 | `node --test tests/merchant-ui-format.test.mjs` | 22/22 通过 |
| DOM stub 冒烟测试 | `node --test tests/merchant-ui-smoke.test.mjs` | 7/7 通过 |
| 全视图巡检（临时脚本，未入库） | 登录 OWNER 后遍历 13 个 hash 路由 | 13 视图全部渲染、0 error-box/0 denied；订单抽屉打开且 OWNER 可见「发起退款」 |
| 退款交互巡检（临时脚本） | 超限金额提交 / 合法部分退款 | 超限被拒并显示「超过可退上限 ¥24.00」；成功后抽屉显示「退款申请中」 |
| 故障模拟巡检（临时脚本） | 403/网络失败/慢响应/空数据 | 403→无权限态；网络失败→错误态+重试；重试在慢响应下恢复；空数据→空态文案 |
| 真实模式巡检（临时脚本） | 无 `?demo=1` 启动 | 显示诚实网络错误、停留登录、无演示横幅与工具 |
| 静态服务 | `python3 -m http.server` 后 curl 六个文件 | 全部 200，相对路径解析正确 |
| 注入安全 | `grep innerHTML/html:` | 仅静态 SVG 图标；API 字符串全部 textContent/DOM 节点 |
| 密钥/存储 | `grep console./localStorage/sessionStorage/document.cookie` | 无 |
| 修改范围 | `git status --porcelain` / `git diff --stat` | 仅新增本清单文件；tracked diff 仅本轮前已存在的 `.gitignore` 修改 |

## 6. 未执行项（如实记录）

- **真实浏览器视觉验证未执行**：本机无 headless 浏览器/Playwright/jsdom，未实际打开 Safari 截图核对 1440px 与 390px 布局。断点已按规范编写（≤1180 单列、≤920 侧栏抽屉+表格卡片化准备、≤720 表格转卡片、≤460 指标两列），但视觉效果未经人眼确认。
- **键盘走查与读屏器实测未执行**：已实现 label 关联、focus 圈定（弹窗/抽屉 Tab 循环、Escape 关闭、关闭后焦点归位）、skip-link、aria 属性、状态非仅颜色（徽标带文字），但未用真实辅助技术验证。
- **真实后端联调未执行**：后端 `/api/v1/merchant/*` 尚未实现（本轮边界如此）；真实模式下所有页面将显示错误态与重试，属预期行为。
- **命令轮询真实超时路径**：演示适配器下命令 2~3 次轮询成功；真实超时/FINAL 分支仅代码路径存在，未实测。

## 7. 接口疑问与后续联调项

1. **`PATCH /purchases/{id}`**：契约只列了 `POST /purchases` 与 `POST /purchases/{id}/post`，但任务要求「草稿可编辑」。前端已实现草稿编辑并调用 `PATCH /purchases/{id} {storeId,purchasedOn,supplier,note,lines,version}`（与其他资源 PATCH 一致）。**后端需补充该端点或给出替代契约。**
2. **`GET /session` 缺当前 membershipId**：契约的 session 无 `membershipId` 字段，前端以 `memberships[].tenantId === tenant.id` 推断当前成员关系（演示会话额外返回了 membershipId 不影响）。建议后端显式返回。
3. **`GET /transfers` 条目字段**：契约未给列表字段。前端假设 `{id, deviceId, deviceName, direction:'OUT'|'IN', counterpartName, status, blockingReasons, version, createdAt, reason}`；`accept/cancel` 响应为更新后的 transfer。请对齐。
4. **命令状态枚举**：假设 `PENDING → EXECUTING → SUCCEEDED|FAILED`，前端另有本地「查询超时」态（8 次轮询约 20 秒后停止自动轮询，保留手动入口）。若后端枚举不同请告知。
5. **设备库存无容量字段**：契约 inventory 无 capacity，抽屉中的余量条按状态分级长度展示，未臆造百分比。
6. **订单列表 `status` 过滤语义**：前端把支付与制作状态共用一个下拉，demo 适配器两种都匹配；后端请明确该参数匹配哪组枚举（或拆成 `paymentStatus`/`productionStatus`）。
7. **409 错误码**：前端将 `VERSION_CONFLICT`/`CONFLICT`/`STALE_VERSION` 视为版本冲突并给出「重新读取」按钮；`LAST_OWNER`、`STORE_HAS_DEVICES`、`TIMEZONE_LOCKED`、`VALIDATION_REQUIRED`、`IS_DEFAULT`、`NOT_DRAFT`/`ALREADY_POSTED`、`BAD_STATE`、`REFUND_NOT_ALLOWED`、`COMMAND_NOT_ALLOWED`、`CLAIM_INVALID`、`TOKEN_INVALID` 等按服务端 message 展示。请后端保持 message 可直接面向客户展示（或提供 code→文案表）。
8. **CSV 文件名**：从 `Content-Disposition` 解析 filename/filename*，缺省回退 `operating-<grain>-<from>_<to>.csv`；若后端固定附件名请确认。
9. **`REAUTH_REQUIRED`**：已实现捕获后弹重新验证弹窗、验证通过后自动重试一次原操作（退款、生命周期变更等写路径已包裹）；请后端在高风险接口返回该 code。
10. **邮件不可用**：注册与邀请处依赖 503/`deliveryStatus:'UNAVAILABLE'` 语义展示「邮件服务不可用」，未伪造已发送。

## 8. 已知前端取舍

- 401 统一处理为清空全部客户状态并回到登录页（含 toast 说明）；403 在数据区显示无权限态（无重试按钮，符合契约「显示无权限」）；其余错误保留筛选条件并提供重试。
- 图表均为原生 SVG，附文字摘要与 `<details>` 数据表；缺值画缺口不画 0。
- 移动端表格通过 `td::before { content: attr(data-label) }` 转卡片，避免双份 DOM。
- 演示工具的「切换角色」直接改写内存会话角色并重建权限与导航，仅用于审阅不同角色视图。
