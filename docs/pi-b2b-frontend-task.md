# 给 pi 的完整实施任务：B 端客户运营后台

## A. 执行约束与事实

项目根目录：`/Users/alex/Downloads/armaster/coffee-cloud-mvp`。

你负责**直接实现完整客户后台前端**，不是只给建议、截图或设计稿。使用 `zai-coding-cn/glm-5.3`。主代理已保留基线，用户要求本次交付后主代理不跟进；你完成后写交付说明并退出，无需等待主代理反馈。

必须先读 `docs/b2b-implementation-plan-2026-08-31.md` 和本文件，再只读参考 `public/admin.html`、`public/admin.css`、`public/admin.js`。现有技术栈为原生 HTML/CSS/JS，FastAPI 将 `public` 挂载到 `/assets`。不要引入 React、npm 工程、第三方 CDN、外部字体、在线图片服务或改变现有构建方式。

当前新客户接口尚未实现。以下是明确的**待实现接口契约**，不能声称它们已经存在，也不能将旧 `/api/v1/admin/*` 当客户接口。你的任务是完成真实 API 适配层、页面、交互和独立演示数据适配层，后端由主代理以后实现。

### 允许修改的文件

- 新建 `public/merchant.html`、`public/merchant.css`、`public/merchant.js`。
- 新建 `public/merchant-api.js`、`public/merchant-demo.js`，必要的纯前端模块仅使用 `public/merchant-*.js` 命名。
- 新建 `docs/pi-b2b-frontend-delivery.md`；可新增 `tests/merchant-ui*.test.mjs` 的纯前端逻辑测试（有实际价值时）。
- 不修改本实施计划或交接任务；有问题在交付说明中记录建议。

### 禁止的行为

- 不改 `app/**`、数据库、migration、requirements、Docker、`.env`、密钥、支付网关、终端模拟器、现有 admin/order 页面或其他人的未提交文件。
- 不 SSH，不调用 VPS，不部署，不创建或操作真实订单、设备、商户或邮件，不调用旧管理员接口，不向其他人发消息。
- 不执行 git reset/clean/stash/commit/push；不覆盖原有 `.gitignore` 或 `docs/system-architecture/`。
- 不自行再委派其他 agent。遇到后端缺口就遵循本契约，在交付说明列出，不扩展修改范围。

入口先为 `/assets/merchant.html`，无需修改 FastAPI 路由。主代理后续可以增加 `/merchant` 别名。所有资源用相对引用，支持 `python3 -m http.server` 在 public 目录预览。

## B. 产品与视觉要求

用户是购买多台咖啡机并经营多个场所的 B 端客户。品牌 Coffee Cloud，中文界面。呈现清晰可信赖的经营后台：暖白背景、咖啡棕品牌色、深色文字，低饱和的绿/橙/红区分正常、警告、失败。相对现有后台保持品牌连贯，但不复制笨重的一屏长表单。

- 桌面左侧导航，顶部显示当前组织、门店筛选、日期区间、数据环境和个人菜单；主区域采用指标、趋势、列表和详情抽屉。
- 建议导航分组：经营（总览、订单、经营报表）；设备（我的设备、门店、商品价格）；成本（物料与采购、运营费用）；组织（成员权限、收款账户、组织设置、审计）。个人安全入口放右上角菜单。
- 390px 手机宽度不能横向溢出；导航折叠，指标两列或一列，表格必要时转卡片，抽屉改全屏。1440px 下控制阅读宽度并充分利用空间。
- 可访问性：有 label 的表单，键盘可操作，弹窗焦点圈定/关闭后归位，Escape 退出，清晰 focus，状态不能只靠颜色。尊重 reduced-motion。
- 图表用原生 SVG，提供文字摘要或数据表；不为了漂亮生成无法解释的数据。
- 每个数据区都有 loading、empty、error、permission denied 状态；请求失败保留合理的筛选条件并提供重试，不制造成功提示。
- 写入按钮防重复提交；提交中显示进行状态；成功以 API 确认后更新，不用定时器假成功。
- 原始业务字符串通过 textContent/DOM 安全插入，禁止拼接 API 内容到 innerHTML。

## C. 接口公共约定

基地址：同源 `/api/v1/merchant`。默认生产适配器 `fetch` 使用 `credentials: 'same-origin'`，不使用 admin Token。会话 Cookie 为服务端 HttpOnly，前端不可读。登录后的 CSRF token 由 session 响应返回，仅存内存；所有已登录写请求附 `X-CSRF-Token`。登录等匿名请求由后端验证 Origin，客户端不自行伪造防护。

正常响应统一 `{data: ..., meta?: ...}`；列表 `{data: [...], meta: {nextCursor: string|null, total?: number}}`。错误 `{error: {code, message, fields?: {[field]: string}, requestId?: string}}`。需兼容非 JSON 网络/代理错误，显示有限通用说明，不将 HTML 错误页注入 DOM。

状态处理：401 清理全部客户数据并显示登录；403 显示无权限；404 显示不存在或无访问权限；409 根据阻断原因引导刷新/处理；422 绑定表单字段；429 尊重 Retry-After；503 显示服务暂不可用或尚未配置，不自动进入演示。

金额字段以整数 `*Minor` 表示人民币分，展示用格式化工具，不用浮点做结算。未知金额为 null，必须显示“待补全”，不能转换成 0。数量为十进制字符串；日期 UTC ISO，展示使用 `tenant.timezone`，默认 Asia/Shanghai。分页 cursor 不作为可计算偏移量。

所有写入返回权威资源；有业务重复风险的 POST 使用 `Idempotency-Key`，一次用户提交的重试复用同一键；再次新操作新建键。需要乐观锁的表单携带 `version`，409 后先重新读取，不静默覆盖。

当前组织通过 `POST /session/tenant` 切换，服务端验证 membership；不能简单往请求拼 `tenant_id` 当授权。切换时 AbortController 取消旧请求，增加组织 epoch，任何旧 epoch 响应都不能覆盖新组织状态；清空详情、图表、筛选结果和导出对象 URL，再加载。

### 权限字符串

`dashboard.read`、`devices.read`、`devices.manage`、`devices.claim`、`devices.transfer`、`commands.execute`、`stores.read`、`stores.manage`、`orders.read`、`refunds.manage`、`prices.read`、`prices.manage`、`inventory.read`、`inventory.manage`、`costs.read`、`costs.manage`、`reports.read`、`reports.export`、`members.read`、`members.manage`、`payments.read`、`payments.manage`、`tenant.manage`、`audit.read`。

OWNER 全部；FINANCE 只读订单、成本、报表/导出、门店与设备概要；OPERATOR 仅授权门店设备、订单、库存运维，不显示利润与采购价格。按 session.permissions 判断，不在各页面复制角色硬编码。

## D. 逐页流程与接口

### 1. 注册、登录、找回密码和个人安全

页面含邮箱/密码登录、创建组织账号、接受邀请、邮箱验证结果、发送找回链接、设置新密码、注销和撤销其他会话。

- `POST /auth/register {email,password,displayName,tenantName}` → `{status:'VERIFICATION_PENDING'}`。
- `POST /auth/verify-email {token}` → `{status:'VERIFIED'}`；必须由用户主动确认触发，不在页面加载时自动消费链接。
- `POST /auth/login {email,password}` → 与 session 相同结构。
- `POST /auth/forgot-password {email}` → 通用 `{status:'ACCEPTED'}`，不泄露账号存在。
- `POST /auth/reset-password {token,password}` → `{status:'UPDATED'}`。
- `POST /auth/accept-invitation {token,displayName,password}` → `{status:'ACCEPTED'}`；已有账号走登录确认后接受，不强制改已有密码。
- `GET /session` → `{user:{id,email,displayName},tenant:{id,name,timezone,environment},memberships:[{id,tenantId,tenantName,role}],permissions:[],storeScope:{mode:'ALL'|'SELECTED',storeIds:[]},csrfToken}`。
- `POST /session/tenant {membershipId}` → 新 session。
- `POST /auth/logout {}` → `{status:'SIGNED_OUT'}`；`POST /auth/revoke-other-sessions {}` → `{revokedCount}`。
- `POST /auth/reauthenticate {password}` → `{validUntil}`，高风险接口若返回 `REAUTH_REQUIRED` 展示重新验证再由用户确认操作。

密码不记录、不输出 console、不进入浏览器存储。链接 token 可从 URL fragment 读取，立即清理地址栏并仅存内存，避免 Referer 泄露。注册成功只显示等待验证；邮件服务不可用时明确显示，不假装已发送。

### 2. 经营总览

- `GET /dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD&storeId=&environment=LIVE|TEST`。
- 响应 `{period:{from,to,timezone},environment,metrics:{deviceCount,onlineCount,paidOrderCount,deliveredCupCount,receivedMinor,refundedMinor,netCashMinor,recognizedRevenueMinor,materialCostMinor,wasteCostMinor,paymentFeeMinor,operatingExpenseMinor,estimatedProfitMinor},completeness:{status:'COMPLETE'|'ESTIMATED'|'INCOMPLETE',missing:[]},trend:[{date,receivedMinor,estimatedProfitMinor}],alerts:[{id,severity,title,description,deviceId}],recentOrders:[]}`。
- 经营者看设备、营业净收入、净收款、估算利润等卡片，资金与经营口径分开展示；OPERATOR 用设备、在线率、完成杯数和待处理告警，不出现财务卡片。
- 日期快捷项今天/近7天/本月/本年/自定义，显示组织时区。`to` 为不含当日的右边界；界面结束日期为包含当日，适配层转换，不额外减一天误显示。

### 3. 我的设备与详情

- `GET /devices?storeId=&status=&q=&cursor=` → `{id,deviceId,name,serialNumber,storeId,storeName,lifecycle,online,lastSeenAt,ownershipVersion,version}` 列表。
- `GET /devices/{id}` → 上述 + `{capabilities:[],inventory:[],currentJob:null|{id,status},alerts:[],allowedActions:[]}`。
- `POST /devices/claim {claimCode,storeId,name}`。录入的是资产认领码，不是设备 HTTP/MQTT 激活凭据。
- `PATCH /devices/{id} {name,storeId,version}`；`POST /devices/{id}/lifecycle {action:'SUSPEND'|'RESUME'|'ARCHIVE',reason,version}`。
- `POST /devices/{id}/commands {command,parameters,ownershipVersion}` → `{id,status:'PENDING'}`；`GET /devices/{id}/commands/{commandId}` → `{id,status,resultMessage}`。
- 命令只有服务端 `allowedActions` 返回时才能出现，不能发任意命令文本。高风险需确认、显示设备和门店；发送成功只意味着已受理，必须分开显示完成/失败/超时。
- `POST /devices/{id}/unbind-requests {reason,ownershipVersion}` → `{id,status:'PENDING_APPROVAL'}`。
- `POST /devices/{id}/transfer-requests {targetTenantReference,reason,ownershipVersion}` → `{id,status,blockingReasons:[]}`；`GET /transfers`、`POST /transfers/{id}/accept {version}`、`POST /transfers/{id}/cancel {version}`。
- 转让状态 `PENDING_RECIPIENT` → `PENDING_PLATFORM` → `COMPLETED`，或 `BLOCKED`/`CANCELLED`/`REJECTED`；真实提交由后端决定。显示在途生产、退款、人工审核等阻断；不能直接把按钮提示改为“转让完成”。历史数据不跟设备转移。

### 4. 门店与商品价格

- `GET /stores`、`POST /stores {name,address}`、`PATCH /stores/{id} {name,address,status,version}`；门店资源 `{id,name,address,status,deviceCount,version}`。
- 有设备/在途订单的门店归档若返回409，显示处理指引，不擅自转移设备。
- `GET /prices?storeId=&deviceId=` → `{id,sku,name,storeId,deviceId,priceMinor,effectiveAt,version}`。
- `POST /prices {sku,storeId,deviceId,priceMinor,effectiveAt}`。明确当前价与计划生效价，提示不改变历史订单；输入元转分需严格最多两位小数，不接受负值/NaN。

### 5. 订单、退款与详情

- `GET /orders?from=&to=&storeId=&deviceId=&status=&environment=&cursor=`。
- 订单 `{id,orderNo,createdAt,paidAt,deliveredAt,storeNameSnapshot,deviceNameSnapshot,items:[{name,quantity,unitPriceMinor}],totalMinor,receivedMinor,refundedMinor,paymentStatus,productionStatus,environment,allowedActions:[]}`。
- `GET /orders/{id}` → 订单 + `{timeline:[],payments:[{id,provider,accountLabel,environment,status,amountMinor}],refunds:[],costSummary:{status,materialCostMinor}}`。
- `POST /orders/{id}/refunds {amountMinor,reason}` → `{id,status,amountMinor}`。只在 `refunds.manage` 和 allowedActions 均允许时出现。
- 区分支付成功、制作完成、退款申请中与退款成功。退款弹窗显示可退上限，允许的部分退款以服务端限制为准；拒绝重复提交，确认后展示真实状态。

### 6. 物料、采购、库存

- `GET /materials` → `{id,name,unit,unitPrecision,status,averageUnitCostMinor:null|string}`；`POST /materials {name,unit,unitPrecision}`。
- `GET /purchases?from=&to=&storeId=&cursor=`；`POST /purchases {storeId,purchasedOn,supplier,note,lines:[{materialId,quantity,totalCostMinor}]}` → `{id,status:'DRAFT',version,...}`。
- `POST /purchases/{id}/post {version}` → 入账后的资源；草稿可编辑，已入账不可直接修改历史；更正走后续调整，不伪造撤回。
- `GET /inventory?storeId=&deviceId=` → `{materialId,name,unit,onHandQuantity,reservedQuantity,availableQuantity,costStatus}`。
- `POST /inventory/movements {type:'RESTOCK'|'WASTE'|'ADJUSTMENT'|'TRANSFER',materialId,quantity,sourceStoreId,sourceDeviceId,targetStoreId,targetDeviceId,reason,version}`。
- `GET /inventory/movements?...` 展示事件流水、来源和时间。按 type 只显示相关字段。库存调整语义为带正负号差额，RESTOCK/WASTE/TRANSFER 数量必须为正，提交确认注明含义。
- OPERATOR 可按权限做补货/盘点，但不能读取采购成本；数量、单位、预计库存显示清楚，服务端校验实际库存与并发版本。

### 7. 运营费用

- `GET /expenses?from=&to=&storeId=&cursor=` → `{id,category,amountMinor,storeId,deviceId,occurredOn,allocationStart,allocationEnd,allocationMethod,status,note,version}`。
- `POST /expenses {category:'RENT'|'LABOR'|'UTILITIES'|'MAINTENANCE'|'OTHER',amountMinor,storeId,deviceId,occurredOn,allocationStart,allocationEnd,allocationMethod:'ONCE'|'DAILY_EQUAL',note}`。
- `POST /expenses/{id}/post {version}`，`POST /expenses/{id}/reversals {reason}`；不直接删除已经入账事实。
- 展示费用归属、一次性或按日均摊区间、预览说明；金额分摊由服务器确定，前端不得把近似预览当账本。

### 8. 日/月/年经营报表与 CSV

- `GET /reports/operating?grain=DAY|MONTH|YEAR&from=&to=&storeId=&deviceId=&environment=LIVE|TEST`。
- `{period:{from,to,timezone},grain,environment,rows:[{period,receivedMinor,refundedMinor,netCashMinor,recognizedRevenueMinor,materialCostMinor,wasteCostMinor,paymentFeeMinor,operatingExpenseMinor,estimatedProfitMinor,deliveredCupCount,completeness}],totals:{...},completeness:{status,missing:[]}}`。
- `GET /reports/operating.csv` 同样筛选，服务器响应 CSV。前端按当前权限与筛选下载 Blob，验证响应成功和类型，下载后 revokeObjectURL。不能抓全平台数据在浏览器过滤后导出。
- 图表按粒度切换，表格与卡片同筛选；展示净收款/营业收入/毛利/经营利润（估算）的解释。数据缺失时未知值是缺口，不绘制为零。
- LIVE 默认，TEST 必须用户主动切换，并持续显示“测试数据，不计入正式经营”；不得合并 mock 和真实交易。

### 9. 成员和邀请

- `GET /members` → `{id,displayName,email,role,status,storeScope,version}`；`GET /invitations` → `{id,email,role,status,expiresAt}`。
- `POST /invitations {email,role,storeScope:{mode,storeIds}}` → `{id,status:'PENDING',deliveryStatus:'QUEUED'|'UNAVAILABLE',expiresAt}`。
- `PATCH /members/{id} {role,status,storeScope,version}`；`POST /invitations/{id}/revoke {}`。
- 展示 OWNER/OPERATOR/FINANCE 权限说明；没有门店授权的 OPERATOR 不应默认全部门店。最后一位 OWNER 不能被停用/降级，以服务器409为准。
- 邀请成功不代表邮件已送达，明确发送队列/不可用；不在页面显示或复制服务器密钥与会话 token。

### 10. 收款账户

- `GET /payment-accounts` → `{id,label,provider:'alipay'|'alipay_mock',environment:'LIVE'|'SANDBOX'|'MOCK',appIdMasked,merchantIdMasked,status,isDefault,version,configuredAt,checks:[]}`。
- `POST /payment-accounts {label,provider,environment,appId,merchantId,appPrivateKey,providerPublicKey}` → 脱敏账户。密钥用临时密码/textarea控件，不持久化、不 console、不回显；离开/提交后立即清空。
- `POST /payment-accounts/{id}/validate {version}` → `{status,checks:[{name,status,message}]}`；`POST /payment-accounts/{id}/set-default {version}`；`POST /payment-accounts/{id}/disable {version}`。
- 正式/沙箱/模拟明显区分；校验失败不可设默认；切换提醒只影响新支付，历史退款沿原账户。不允许输入任意网关地址绕过后端 SSRF 防护，不访问 mock 网关管理员 token。

### 11. 组织设置与审计

- `GET /tenant`、`PATCH /tenant {name,timezone,version}`。已发生交易后时区变更可能被服务器拒绝，明确说明报表按组织时区，不能仅改变浏览器格式伪装账期已迁移。
- `GET /audit?from=&to=&action=&cursor=` → `{id,createdAt,actorName,action,resourceType,resourceLabel,outcome,requestId}`。
- 显示分页、时间筛选、动作与结果，敏感字段不能直接整段原始 JSON 展示。

## E. 显式演示适配器

用于在新接口尚未实现时审阅前端交互，**不是支付网关，也不是业务系统实现**。

- 仅当 URL 显式含 `?demo=1` 才启用 demo adapter；默认真实 API，错误不能回退 demo。
- 页面全程醒目标记“界面演示 · 数据仅存在当前页面内存 · 不操作真实设备/支付”。
- demo adapter 和真实 adapter 导出相同方法；业务视图不判断 `demo` 来写两套流程。demo 不发送 merchant 或 admin API 请求。
- 内存数据至少两组织、两门店、8台设备（在线/离线/停用/未激活）、不同状态订单、退款、缺成本、采购/费用及转让阻断样例。
- 提供演示工具切换角色与组织、模拟空数据/403/网络失败/慢响应；工具不能在正常模式出现。
- 内存交互支持：登录/组织切换、门店新增、认领结果、设备改名/暂停、转让阻断和申请、采购草稿/入账、费用新增、退款状态、成员邀请/停用、模拟账户校验、报表筛选。刷新清空演示更改。
- 演示报表由明确 fixture 或内存事实一致生成，不随机生成每次变化的数字；缺成本不补零；导出加“界面演示”标记。演示数据隔离仅用于交互，不作为后端隔离证据。

## F. 建议实施顺序

1. 创建三个主静态文件和 API adapter，建立 DOM/表单/Toast/弹窗/日期金额/权限等复用工具。
2. 登录/会话状态/组织切换/侧栏与移动导航；确认默认真实 API 不掩盖未实现接口。
3. 总览、设备和门店、订单详情及退款/转让交互。
4. 价格、物料采购、库存、运营费用。
5. 报表图表/粒度/筛选/导出，成员、收款账户、组织设置、审计。
6. 演示所有状态、权限显示、响应式和可访问性；有意义的纯函数测试与语法检查。
7. 写交付说明后退出。不要等待或轮询主代理。

## G. 自检与交付

- 对每个新增 JS 文件执行 Node 语法检查（ES module 采用相应模式），相对 import 和 HTML 资源路径必须存在。
- 自查桌面1440与手机390布局；若能使用本地浏览器能力则执行，否则如实记录未执行，不能声称截图验证通过。
- 检查 DOM 文本注入安全、无 secret 持久化、无默认演示、组织切换旧响应屏蔽、401清理、403重试、重复提交和金额 null。
- 场景：OWNER完整导航；OPERATOR看不到利润和账户；FINANCE只读；组织切换详情清空；缺成本显示待补全；退款中不显示成功；转让阻断提示；TEST醒目标记；真实 API 未接通显示错误。
- `git diff --stat` 与新文件列表确认修改范围；不要提交。
- 在 `docs/pi-b2b-frontend-delivery.md` 写：文件列表、预览命令与URL、已完成逐页清单、真实/演示边界、验证命令和结果、未执行项、接口疑问与后续联调项。任何缺口必须明确，不用占位“待后端接入”代替应已完成的前端表单/交互。

完成后退出。主代理不会在本轮查看结果，用户后续会再次调用其进行审查、后端实现、联调与部署。
