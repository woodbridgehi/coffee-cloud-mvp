# Coffee Cloud 全量 UI/UX 重设计需求文档

快速定位：[页面盘点](#2-existing-ui-audit) · [视觉体系](#5-visual-design-language) · [组件规范](#7-component-system) · [逐页设计](#10-page-by-page-redesign) · [OpenDesign执行计划](#14-opendesign-implementation-instructions) · [覆盖矩阵](#15-ui-migration-coverage-matrix)。

版本：1.0 · 审计基线：`e66dd053c6d63a3725e25489cf4c526114d96278`（`main`，标签 `vps-sync-20260831-2249`）。
交付性质：设计需求与实施规范，未实施界面、未改变后端、未部署。本文件和 [design-tokens.json](design-tokens.json) 可直接随项目交给 OpenDesign。视觉方案由本地 pi（GLM-5.3）参与提出，业务盘点、契约校正和最终规范由主代理完成。

## 1. Executive Summary

目标是让经营者迅速回答“我的设备能否营业、订单是否正常、收了多少钱、成本是否完整”，让平台运维快速定位设备和异常，让消费者顺利下单、支付、等待并取杯。采用 **Light + Fresh + Dopamine Accent**，重新组织导航、信息密度和跨屏交互，不沿用旧棕色主题与现有卡片排列作为设计边界。

> 唯一通用完整性约束：不能遗漏当前项目已存在的任何有效业务信息、字段、功能入口和关键操作能力；低优先级信息可通过 Tooltip、Popover、Detail Drawer、展开区、高级设置或上下文菜单渐进披露，不能直接删除。

取舍顺序：业务功能完整 → 信息完整 → 核心任务效率 → 信息层级 → 响应式 → 一致性 → 美感 → 动画装饰。

### 1.1 技术栈与可实现性

| 项目 | 当前代码事实 | 本方案执行方式 |
| --- | --- | --- |
| 页面 | 三个 HTML：merchant、admin、order | 三端统一基础规范，保留独立入口/鉴权 |
| 框架 | 原生 JS/DOM；商户、平台使用 ES Modules；order 为普通脚本 | 不引入 React/Vue，不增加构建链 |
| 样式 | 原生 CSS；共享 `public/shared/coffee-ui.css` 与各端 CSS | 共享 Token + 页面布局 CSS，保持 `--cc-` 命名与兼容别名 |
| 组件库 | 无第三方组件库；现有 DOM 构造、Modal、Drawer、表格、Toast | 复用行为并重绘；新增 Sheet/命令面板等是自定义扩展 |
| 图标/图表 | 内联 SVG；自绘 SVG 图表 | 统一 SVG 线宽；可访问数据表作为图表替代 |
| 服务端 | Python/FastAPI；`/assets` 静态资源；商户与平台 API | API、鉴权和状态机作为既有契约 |
| 样式依赖 | 无 Tailwind、无 CSS-in-JS、无动效库 | CSS transition 与原生 JS 足够；默认零新增依赖 |
| 字体 | 可使用系统字体 | 不默认联网下载字体，不以外部 CDN 作为登录可用性前提 |

本方案没有技术栈迁移授权。Lucide 包、图表库、弹簧动效库等若未来选用，须单列“新增依赖项、体积、许可、集成方式、降级方案”；它们不是本规范的执行前提。没有现成组件库不代表每个新增交互都无成本，§7 明确标出扩展工作。

### 1.2 范围与证据边界

审计基于本地基线源码、API 投影、权限与格式化逻辑，不声称本次已对所有线上页面做浏览器实测。51 个编号指页面、弹层或独立流程，不是51个独立URL。当前服务端有限发布配置必须在运行时读取，本文记录的关闭状态不是永远固定。

本仓库不含原生咖啡机屏幕/QML UI；设备首次安装属于服务端接口边界，不能凭本仓库虚构终端页面。独立 mock-alipay-gateway 的买家确认页不在本项目中，不与咖啡系统合并；本次只设计从咖啡订单页跳转、回跳和状态说明。根路径JSON、OpenAPI文档不是业务页面。

## 2. Existing UI Audit

### 2.1 Current UI Inventory

下表为页面设计与迁移矩阵的事实索引。每条字段组对应 §10 同编号 Content；每个操作有独立矩阵行。“新增纯前端便利”“真实API兼容字段”“CSV独有字段”明确标记，不能据此宣称当前UI已实现。表内状态包含审计发现的分支与新设计需补足的表现；现有行为与新增表现以“问题/建议”和 §14 分类为准。页内技术字段可放二级详情；密钥等敏感值遵循当前只写/一次性展示策略，不将后端隐藏值变成可读字段。

| 页面/模块 | 当前用途/入口 | 核心信息字段 | 操作/交互入口 | 状态种类 | 存在问题 | 重设计建议 |
| --- | --- | --- | --- | --- | --- | --- |
| M01 商户登录 | 让客户进入自己的组织，不把平台 Token 登录与商户账号混为一谈。<br>`/assets/merchant.html#/login`<br>来源：public/merchant.js:renderAuth(login)<br>可用性：开放，跟随 auth/config | M01-F01 registrationMode<br>M01-F02 mailEnabled<br>M01-F03 passwordMinLength/passwordMaxLength<br>M01-F04 usernamePattern<br>M01-F05 用户名或已有已验证邮箱<br>M01-F06 密码<br>M01-F07 品牌/后台名称<br>M01-F08 会话安全说明<br>M01-F09 登录错误 | M01-A01 登录<br>M01-A02 创建组织账号<br>M01-A03 邮件开启时找回密码/邀请/验证入口 | 初始配置加载、账号密码空/格式错、登录中、401、429、网络断开、成功进入组织。 | 原界面与旧版几乎相同，技术安全说明抢占核心任务，Label与输入关联不足。 | 居中1120px工作区，左侧280px轻量产品与账号类型说明，右侧420px无悬浮卡片表单，两列间64px；顶部56px品牌栏，表单标题24px，输入48px；不用旧暖棕大阴影登录卡。 详见[M01](#page-m01) |
| M02 创建组织账号 | 一次建立账号与独立组织，让用户理解注册成功仍不代表已经拥有设备。<br>`#/register`<br>来源：public/merchant.js:renderAuth(register)<br>可用性：USERNAME开放；EMAIL路径按配置 | M02-F01 USERNAME: username<br>M02-F02 displayName<br>M02-F03 tenantName<br>M02-F04 password<br>M02-F05 EMAIL: email<br>M02-F06 用户名3–32位规则<br>M02-F07 密码15–128字符配置<br>M02-F08 OWNER身份说明<br>M02-F09 REGISTERED/VERIFICATION_PENDING/未知返回状态 | M02-A01 创建账号<br>M02-A02 字段校验<br>M02-A03 返回登录<br>M02-A04 注册结果去登录 | 规则未加载、USERNAME/EMAIL两模式、字段错误、用户名占用、REGISTERED、VERIFICATION_PENDING、未知结果、禁用邮件。 | 旧表单信息层级弱；新用户容易把账号创建误认为设备已绑定。 | 延用M01外壳，表单宽480px，分账号信息/组织信息两个无边框分区；用户名与密码先显示，姓名组织随后；提交区紧邻表单。 详见[M02](#page-m02) |
| M03 找回密码 | 在不泄露账号存在性的条件下提供恢复路径。<br>`#/forgot`<br>来源：public/merchant.js:renderAuth(forgot),mailDisabledNotice<br>可用性：邮件关闭时展示不可用说明 | M03-F01 注册邮箱<br>M03-F02 邮件服务状态<br>M03-F03 统一受理结果<br>M03-F04 错误<br>M03-F05 联系平台管理员说明 | M03-A01 发送找回链接（邮件开放时）<br>M03-A02 返回登录 | 邮件关闭、提交中、统一受理结果（不泄露账号存在性）、429、网络失败。 | 关闭功能若只隐藏会让旧链接用户迷失，需要可解释的着陆页。 | 420px表单/说明区，主标题24px，邮箱输入与结果同一区域；不可用状态以说明页替代表单。 详见[M03](#page-m03) |
| M04 重置密码 | 让持有效链接的用户明确完成一次密码重置。<br>`#/reset`<br>来源：public/merchant.js:renderAuth(reset),readFragmentToken<br>可用性：邮件关闭时不可用 | M04-F01 邮件片段 token<br>M04-F02 新密码<br>M04-F03 确认密码<br>M04-F04 密码长度规则<br>M04-F05 密码更新结果<br>M04-F06 失效/已使用 token 错误 | M04-A01 设置新密码<br>M04-A02 返回登录<br>M04-A03 更新后去登录 | token缺失/过期/已用、密码规则失败、提交中、完成、邮件关闭。 | 手动token技术字段当前占主流程，且邮件未开启。 | 480px表单，密码与确认纵向；token置高级展开区但手动粘贴仍可达；结果替换正文。 详见[M04](#page-m04) |
| M05 验证邮箱 | 让用户主动确认邮箱验证，避免打开链接即改变状态。<br>`#/verify`<br>来源：public/merchant.js:renderAuth(verify),readFragmentToken<br>可用性：邮件关闭时不可用 | M05-F01 验证token<br>M05-F02 一次性链接说明<br>M05-F03 验证结果<br>M05-F04 失败原因 | M05-A01 主动确认验证邮箱<br>M05-A02 手动粘贴token<br>M05-A03 返回登录 | 验证中、无token、过期/已验证、成功、邮件关闭、失败可重试。 | 技术token抢占层级，结果状态缺少明确下一步。 | 420px确认页，清晰一句行为说明，token高级区，主确认按钮与取消并列。 详见[M05](#page-m05) |
| M06 接受成员邀请 | 让被邀请者加入正确组织，区分新账号表单与已有账号流程。<br>`#/invite`<br>来源：public/merchant.js:renderAuth(invite)<br>可用性：邮件关闭时不可用 | M06-F01 邀请token<br>M06-F02 displayName<br>M06-F03 password<br>M06-F04 密码规则<br>M06-F05 已有账号提示<br>M06-F06 接受结果 | M06-A01 接受邀请<br>M06-A02 手动输入token<br>M06-A03 返回登录 | 邀请缺失/已用/过期/撤销、账号已存在需登录路径、邮件关闭、接受成功。 | 已有账号文案与可发现入口存在差距，不能仅凭文案声明闭环。 | 480px表单，加入组织行为说明在顶部；姓名/密码主区，token高级区；已有账号提示单独一行。 详见[M06](#page-m06) |
| M07 认证配置失败与认证结果 | 避免空白页和假成功，为每次认证请求提供可操作的结果。<br>`认证启动及各认证结果页`<br>来源：public/merchant.js:renderAuthConfigError,authResultPage,mailDisabledNotice<br>可用性：开放/条件状态 | M07-F01 错误标题<br>M07-F02 详细错误信息<br>M07-F03 requestId（若返回）<br>M07-F04 配置依赖说明<br>M07-F05 结果标题/说明<br>M07-F06 注册/验证/重置/邀请状态<br>M07-F07 邮件不可用说明 | M07-A01 重试配置<br>M07-A02 去登录或返回登录（按结果）<br>M07-A03 查看失败说明 | 配置加载失败、JS模块失败时静态恢复说明、未知认证路由、认证成功结果、可恢复/不可恢复错误。 | 历史曾有模块权限导致全页空白；当前只有配置请求失败处理，启动资源失败缺兜底。 | 沿用认证外壳，图标20px+标题24px；结果说明最大60字首段，技术详情可展开。 详见[M07](#page-m07) |
| M08 商户工作区与账号菜单 | 让用户始终知道自己正操作哪个组织、时间范围和数据环境。<br>`所有商户认证后路由`<br>来源：public/merchant.js:buildShell,buildShellControls,buildUserMenu,switchOrg,setEnvironment,route<br>可用性：按permissions | M08-F01 当前组织名称/tenantId/成员关系id<br>M08-F02 组织角色<br>M08-F03 当前用户姓名/username/email<br>M08-F04 门店id/名称<br>M08-F05 日期from/to<br>M08-F06 组织timezone<br>M08-F07 LIVE/TEST<br>M08-F08 当前导航/标题/描述<br>M08-F09 revokedCount<br>M08-F10 无访问权限说明 | M08-A01 组织切换<br>M08-A02 门店筛选<br>M08-A03 今天/近7天/本月/本年/自定义日期<br>M08-A04 应用范围<br>M08-A05 LIVE/TEST切换<br>M08-A06 13主导航<br>M08-A07 移动导航展开/关闭<br>M08-A08 重新验证身份<br>M08-A09 撤销其他会话并确认<br>M08-A10 退出<br>M08-A11 无权限回可访问首页 | 无组织、多组织、只读、门店受限、日期无效、LIVE/TEST、DEMO、权限变化、会话失效。 | 当前顶栏把所有筛选同样铺开，作用域不清晰，手机操作拥挤。 | 224px左栏，64px上下文头；组织切换顶左、账号顶右；56px页面标题行；门店日期作为适用页面的48px范围条；主体24px边距。 详见[M08](#page-m08) |
| M09 重新验证身份 | 在不中断原任务上下文的前提下确认操作者身份。<br>`账号菜单/敏感操作 REAUTH_REQUIRED`<br>来源：public/merchant.js:reauthModal,withReauth<br>可用性：按服务端要求 | M09-F01 当前密码<br>M09-F02 敏感操作原因<br>M09-F03 validUntil<br>M09-F04 错误 | M09-A01 验证身份<br>M09-A02 取消<br>M09-A03 验证后续接原操作 | 当前密码错误、验证中、完成后继续原动作、取消、会话过期；不落盘敏感输入。 | 嵌套弹窗易丢原任务和焦点，需明确续接。 | 440pxDialog，保留原操作对象摘要，密码单字段，提交与取消右对齐。 详见[M09](#page-m09) |
| M10 经营总览 | 先知道当前是否需要处理问题，再看收入与利润变化。<br>`#/dashboard`<br>来源：public/merchant.js:renderDashboardView,loadDashboardCards,loadDashboardTrend,loadDashboardAlerts,loadDashboardRecent<br>可用性：按dashboard.read/costs.read | M10-F01 设备总数/在线数/在线率<br>M10-F02 完成杯数<br>M10-F03 待处理告警数<br>M10-F04 实收receivedMinor<br>M10-F05 退款refundedMinor<br>M10-F06 净收款netCashMinor<br>M10-F07 营业净收入recognizedRevenueMinor<br>M10-F08 估算利润estimatedProfitMinor<br>M10-F09 completeness.status/missing<br>M10-F10 趋势date/receivedMinor/estimatedProfitMinor<br>M10-F11 告警severity/title/description与告警条数<br>M10-F12 最近订单id/orderNo/createdAt/storeNameSnapshot/deviceNameSnapshot/totalMinor/paymentStatus/productionStatus/environment<br>M10-F13 有限发布说明 | M10-A01 范围筛选<br>M10-A02 分区重试<br>M10-A03 打开最近订单详情<br>M10-A04 全部订单<br>M10-A05 权限适配的经营/运维视图 | 各分区独立Loading/Error；今日无订单；成本缺项；无成本权限；趋势部分为空；告警有/无；旧值过时。 | 四卡模板且角色指标可缺失；趋势与指标需说明现金流和确认收入差别。 | 上方全宽状态摘要条；左侧8列为主经营数值+260px趋势，右4列为告警工作队列；第二段最近订单全宽，非四卡模板。利润缺项置于利润数字同层。 详见[M10](#page-m10) |
| M11 我的设备列表 | 快速找到某台属于本组织的设备，识别离线或停用。<br>`#/devices`<br>来源：public/merchant.js:renderDevicesView,loadDeviceList<br>可用性：devices.read | M11-F01 查询q<br>M11-F02 生命周期筛选<br>M11-F03 门店storeId<br>M11-F04 id/deviceId<br>M11-F05 name<br>M11-F06 serialNumber<br>M11-F07 storeName<br>M11-F08 lifecycle<br>M11-F09 online/lastSeenAt<br>M11-F10 version/ownershipVersion | M11-A01 搜索设备名称/ID/SN<br>M11-A02 按生命周期/门店过滤<br>M11-A03 认领设备<br>M11-A04 打开设备详情 | 无设备、筛选无匹配、设备在线/离线/首次未连接、PENDING_ACTIVATION/ACTIVE/SUSPENDED/ARCHIVED生命周期、只读、加载失败。 | 技术版本占表格宽度且手机详情与列表层级不清。 | 工具栏一行，搜索320px+门店/状态；表格主列设备/连接/门店/生命周期/心跳，版本放行展开或详情，行高56px。 详见[M11](#page-m11) |
| M12 认领出厂设备 | 将购买的设备正确绑定自己的组织和经营场所。<br>`设备列表认领弹窗`<br>来源：public/merchant.js:openClaimModal<br>可用性：devices.claim；需有效门店和认领码 | M12-F01 claimCode<br>M12-F02 storeId<br>M12-F03 可选name<br>M12-F04 设备归属校验结果<br>M12-F05 错误/幂等冲突<br>M12-F06 平台归属与历史订单说明 | M12-A01 选择门店<br>M12-A02 输入资产认领码<br>M12-A03 认领<br>M12-A04 取消<br>M12-A05 无门店时引导创建门店 | 认领码错误/过期/已用、门店无效、归属冲突、成功、重新验证、限流。 | 认领与设备激活概念容易混淆，空门店缺少下一步。 | 520pxDialog，认领码和门店纵向，说明置下方；不能把安装激活码当资产认领码。 详见[M12](#page-m12) |
| M13 商户设备详情 | 聚合设备状态、任务、能力和物料，区分设备实时快照与库存账。<br>`设备列表 → Drawer`<br>来源：public/merchant.js:openDeviceDrawer,paintDeviceDrawer,deviceActionsRow<br>可用性：devices.read + allowedActions | M13-F01 设备name/deviceId/serialNumber<br>M13-F02 storeName<br>M13-F03 lifecycle<br>M13-F04 online/lastSeenAt<br>M13-F05 ownershipVersion/version<br>M13-F06 currentJob.id/status/productName（若有）<br>M13-F07 capabilities.id/name/estimatedSeconds及真实recipeId/estimatedDurationSeconds兼容<br>M13-F08 inventory名称/单位/状态/onHandQuantity/reservedQuantity/availableQuantity<br>M13-F09 alerts.severity/title/description<br>M13-F10 allowedActions<br>M13-F11 命令结果区域id/status/resultMessage；PENDING/EXECUTING/SUCCEEDED/FAILED/TIMEOUT；查询超时/失败 | M13-A01 编辑资料<br>M13-A02 生命周期变更<br>M13-A03 申请解绑<br>M13-A04 发起转让<br>M13-A05 允许的设备命令RELOAD_CONFIG/SYNC_CONFIG/CLEAN/RESTART_APP（各自确认）<br>M13-A06 关闭详情<br>M13-A07 失败重试 | 详情加载、设备离线、忙碌/工作中、任务缺失、能力/物料未上报与读取失败、告警、操作禁用。 | 现有物料条用0.12/0.35/1表示状态会被误读为容量；真实快照字段与demo形态并不完全一致。 | 右侧640px Drawer或详情工作区，顶部对象标识与双状态，下面概览/能力物料/技术信息三个局部Tab；主要状态默认可见。 详见[M13](#page-m13) |
| M14 编辑商户设备资料 | 修正设备名称与经营归属，避免覆盖并发修改。<br>`设备详情 → 编辑资料`<br>来源：public/merchant.js:openDeviceEditModal<br>可用性：devices.manage + RENAME/REASSIGN | M14-F01 deviceId<br>M14-F02 name<br>M14-F03 storeId<br>M14-F04 version<br>M14-F05 归属说明<br>M14-F06 字段错误/409 | M14-A01 修改名称<br>M14-A02 重新分配门店<br>M14-A03 保存<br>M14-A04 取消<br>M14-A05 冲突重新加载 | 未修改、保存中、必填错误、版本409、门店无权、已保存、未保存退出。 | 版本冲突解释与用户草稿恢复需要更清楚。 | 520pxDialog，名称单行、门店选择，版本移入技术说明。 详见[M14](#page-m14) |
| M15 商户设备生命周期 | 安全暂停、恢复或归档设备，同时保留历史经营记录。<br>`设备详情 → 生命周期变更`<br>来源：public/merchant.js:openLifecycleModal<br>可用性：devices.manage + allowedActions | M15-F01 设备对象<br>M15-F02 目标action=SUSPEND/RESUME/ARCHIVE（按允许项）<br>M15-F03 reason<br>M15-F04 version<br>M15-F05 归档影响<br>M15-F06 确认文字 | M15-A01 选择动作<br>M15-A02 填写原因<br>M15-A03 确认提交<br>M15-A04 归档二次输入“归档”<br>M15-A05 需要时重新验证<br>M15-A06 取消/冲突重载 | PENDING_ACTIVATION/ACTIVE/SUSPENDED/ARCHIVED、操作SUSPEND/RESUME/ARCHIVE不允许、原因空、重新验证、请求中、完成、冲突。 | 技术枚举与普通保存同级，危险操作需要明确后果。 | 520px确认表单，目标与后果并排说明，归档用独立危险区域。 详见[M15](#page-m15) |
| M16 申请设备解绑 | 记录解绑请求，而不是直接解除设备归属。<br>`设备详情 → 申请解绑`<br>来源：public/merchant.js:openUnbindModal<br>可用性：有限发布关闭：devices.transfer | M16-F01 设备标识/名称<br>M16-F02 reason<br>M16-F03 ownershipVersion<br>M16-F04 请求status<br>M16-F05 阻断原因 | M16-A01 填写原因<br>M16-A02 提交解绑申请<br>M16-A03 取消 | 能力关闭、解绑原因空、当前有任务/归属冲突、重新验证、已受理/拒绝、结果未知。 | 申请与最终资产转移容易混淆；当前入口按权限关闭。 | 480pxDialog，对象摘要+审核运营说明+原因96px。 详见[M16](#page-m16) |
| M17 发起设备转让 | 把设备转让到指定组织并让双方理解阻断条件。<br>`设备详情 → 发起转让`<br>来源：public/merchant.js:openTransferRequestModal<br>可用性：有限发布关闭：devices.transfer | M17-F01 设备标识/名称<br>M17-F02 targetTenantReference<br>M17-F03 reason<br>M17-F04 ownershipVersion<br>M17-F05 result.status<br>M17-F06 blockingReasons | M17-A01 填目标组织标识<br>M17-A02 填原因<br>M17-A03 提交转让<br>M17-A04 取消 | 能力关闭、目标组织不匹配、当前有任务、重新验证、转让待接收/冲突。 | 当前目标是技术标识，需显著确认对象，防错转。 | 560pxDialog，上方来源→目标关系示意（文字节点），下方目标/原因，阻断列表不折叠。 详见[M17](#page-m17) |
| M18 设备转让记录 | 跟踪转出转入申请的阶段及需要谁处理。<br>`#/transfers`<br>来源：public/merchant.js:renderTransfersView,loadTransfers,transferAction<br>可用性：有限发布关闭：devices.transfer | M18-F01 设备deviceName/deviceId<br>M18-F02 createdAt<br>M18-F03 reason<br>M18-F04 direction(IN/OUT)<br>M18-F05 counterpartName<br>M18-F06 status<br>M18-F07 blockingReasons<br>M18-F08 version | M18-A01 刷新<br>M18-A02 确认接收（转入待接收）<br>M18-A03 取消（允许状态）<br>M18-A04 确认弹窗 | 无转让、待接受、完成、取消/拒绝/过期等服务端状态、accept/cancel权限不足、版本冲突。 | 复杂阶段目前仅徽标展示，责任方和阻断原因不易扫描。 | 列表按状态与方向展示，设备/对方/当前阶段/下一步四列；原因和阻断在行展开。 详见[M18](#page-m18) |
| M19 门店列表与门店编辑 | 管理设备的经营地点，保持历史门店归属。<br>`#/stores`<br>来源：public/merchant.js:renderStoresView,loadStores,openStoreModal<br>可用性：stores.read；写入需stores.manage | M19-F01 store.id/name/address/status/deviceCount/version<br>M19-F02 编辑名称/地址<br>M19-F03 ACTIVE/ARCHIVED<br>M19-F04 归档不可直接恢复说明 | M19-A01 新增门店<br>M19-A02 编辑<br>M19-A03 归档并确认<br>M19-A04 保存<br>M19-A05 取消<br>M19-A06 冲突重载 | 无门店、只读、必填错误、地址未填、保存中、归档与设备关联约束、版本冲突。 | 门店归档藏在状态Select里，容易被当普通字段保存。 | 列表占主区，名称地址合并第一列，设备数右对齐；编辑520pxDrawer，地址textarea96px。 详见[M19](#page-m19) |
| M20 商品当前价与计划价 | 明确哪一范围的新订单使用哪一个价格。<br>`#/prices`<br>来源：public/merchant.js:renderPricesView,loadPrices,openPriceModal<br>可用性：prices.read/manage | M20-F01 门店筛选storeId<br>M20-F02 设备筛选deviceId<br>M20-F03 name/sku<br>M20-F04 scope(组织/门店/设备)<br>M20-F05 priceMinor<br>M20-F06 effectiveAt<br>M20-F07 version<br>M20-F08 当前价/计划生效状态<br>M20-F09 新增SKU/name/storeId/deviceId/priceMinor/effectiveAt | M20-A01 筛选门店/设备<br>M20-A02 新增价格<br>M20-A03 立即或计划生效<br>M20-A04 保存<br>M20-A05 取消 | 无可定价产品、当前价缺失、计划待生效/已生效、金额非整数分、时间无效、版本冲突。 | 当前/计划价格的作用对象不突出，日期选择易误解时区。 | 标题行下为范围工具栏；表格商品/范围/当前或计划/金额/生效时间；新增560pxDialog，范围单选引导后映射原字段。 详见[M20](#page-m20) |
| M21 商户订单列表 | 按订单识别支付、制作和退款进度。<br>`#/orders`<br>来源：public/merchant.js:renderOrdersView,loadOrdersPage,reloadOrderListOnly<br>可用性：orders.read | M21-F01 状态筛选全部/PAID/PENDING/REFUNDING/REFUNDED/PARTIALLY_REFUNDED/QUEUED/MAKING/HOLD/DELIVERED/FAILED/CANCELLED<br>M21-F02 deviceId筛选<br>M21-F03 全局日期/门店/LIVE或TEST<br>M21-F04 id/orderNo/createdAt<br>M21-F05 storeNameSnapshot/deviceNameSnapshot/deviceId<br>M21-F06 items.name/quantity<br>M21-F07 totalMinor<br>M21-F08 paymentStatus<br>M21-F09 productionStatus<br>M21-F10 environment<br>M21-F11 nextCursor | M21-A01 查询<br>M21-A02 更改筛选<br>M21-A03 加载更多<br>M21-A04 打开详情<br>M21-A05 从总览直达订单 | 无订单、无匹配、LIVE/TEST、筛选中、返回范围受限、部分字段受权限屏蔽、查询失败。 | 并列状态多且技术枚举影响扫读；分页与详情返回需要保存上下文。 | 一行筛选条+已选chips；表格订单时间、地点设备、商品、金额、支付、制作、环境；首列sticky，行高56–64px；不新增未经API支持的全库搜索。 详见[M21](#page-m21) |
| M22 商户订单详情 | 把一笔订单的商品、钱款与制作事实连接起来。<br>`订单列表/总览 → 订单详情`<br>来源：public/merchant.js:openOrderDrawer,paintOrderDrawer<br>可用性：orders.read；退款另需权限 | M22-F01 orderNo/id<br>M22-F02 门店/设备快照<br>M22-F03 paymentStatus/productionStatus/environment<br>M22-F04 createdAt/paidAt/deliveredAt<br>M22-F05 totalMinor/receivedMinor/refundedMinor<br>M22-F06 items.name/quantity/unitPriceMinor<br>M22-F07 payments.provider/accountLabel/environment/status/amountMinor<br>M22-F08 refunds.status/reason/amountMinor<br>M22-F09 costSummary.materialCostMinor/status<br>M22-F10 timeline.createdAt或at/description或label/status<br>M22-F11 allowedActions | M22-A01 查看商品/支付退款/成本/时间线<br>M22-A02 发起退款（REFUND允许时）<br>M22-A03 关闭<br>M22-A04 失败重试 | 详情失败、支付与制作分离、HOLD/退款中/部分退款、成本缺项、退款不可用、旧快照。 | 资金流、制作状态和成本目前堆叠，重点与历史细节缺少层级。 | 640pxDrawer，顶部订单+双状态；下方金额三列；商品、支付退款、时间线纵向；技术ID可展开；底部退款为次级危险按钮。 详见[M22](#page-m22) |
| M23 部分或全额退款 | 在确认支付事实和可退上限后发起可追溯退款。<br>`订单详情 → 发起退款`<br>来源：public/merchant.js:openRefundModal,withReauth<br>可用性：refunds.manage + allowedActions含REFUND | M23-F01 订单号<br>M23-F02 订单总额<br>M23-F03 实收<br>M23-F04 已退<br>M23-F05 可退上限<br>M23-F06 amountMinor元输入<br>M23-F07 reason<br>M23-F08 请求状态<br>M23-F09 字段错误<br>M23-F10 REAUTH_REQUIRED | M23-A01 填写退款金额/原因<br>M23-A02 取消<br>M23-A03 确认退款<br>M23-A04 重新验证<br>M23-A05 提交后查看退款记录 | 金额超限/为零、原因空、重新验证、已受理/PROCESSING、成功/失败/未知、重复请求、可退余额变化。 | 错误金额与未知上限可能误导，主操作文案需反映异步处理。 | 520pxDialog，顶部三项金额摘要，退款金额大号输入，原因其次，底部提交标注为申请。 详见[M23](#page-m23) |
| M24 物料档案与新增物料 | 建立采购和库存使用的一致单位档案。<br>`#/materials → materials tab`<br>来源：public/merchant.js:renderMaterialsView,renderMaterialsTab,openMaterialModal<br>可用性：读取inventory.read；新增costs.manage；成本列costs.read | M24-F01 物料id/name<br>M24-F02 unit<br>M24-F03 unitPrecision<br>M24-F04 averageUnitCostMinor<br>M24-F05 status<br>M24-F06 新增名称/单位/数量小数位 | M24-A01 物料/采购/库存/出入库四Tab切换<br>M24-A02 新增物料<br>M24-A03 保存<br>M24-A04 取消 | 无物料、单位未填、数量精度错误、非启用状态只读、新建失败、成功。 | 物料状态是只读事实，不能把标签误设计成可切换按钮。 | 四Tab置于成本工作区顶部，档案表物料/单位/精度/成本/状态；新增440pxDialog。 详见[M24](#page-m24) |
| M25 采购列表、草稿编辑与入账 | 先核对采购明细，再把成本与库存记入账。<br>`#/materials → purchases tab`<br>来源：public/merchant.js:renderPurchasesTab,loadPurchases,openPurchaseModal,postPurchaseFlow<br>可用性：读取costs.read；写入/入账costs.manage | M25-F01 采购id/supplier/purchasedOn/storeId/note/status/version<br>M25-F02 lines.materialId/materialName/quantity/unit/totalCostMinor<br>M25-F03 已知合计/缺项标志<br>M25-F04 门店与日期筛选 | M25-A01 新增采购<br>M25-A02 编辑DRAFT<br>M25-A03 添加/删除草稿明细行<br>M25-A04 保存草稿<br>M25-A05 POSTED只读<br>M25-A06 入账并确认<br>M25-A07 取消 | DRAFT/POSTED/其他、零明细、数量/行总成本错误、重复入账、重新验证/冲突、部分供应信息缺失。 | 多行编辑和不可逆入账混在列表动作，缺项小计容易被读作总额。 | 列表供应商日期/门店/明细摘要/总额/状态/操作；草稿编辑用800px宽Dialog或专页，表头信息两列+行项目表；合计sticky但不遮挡。 详见[M25](#page-m25) |
| M26 账面库存 | 了解已记账的库存与占用，避免把账面数当传感器余量。<br>`#/materials → inventory tab`<br>来源：public/merchant.js:renderInventoryTab,loadInventory<br>可用性：inventory.read | M26-F01 门店筛选<br>M26-F02 物料name/unit<br>M26-F03 deviceName/deviceId<br>M26-F04 onHandQuantity<br>M26-F05 reservedQuantity<br>M26-F06 availableQuantity<br>M26-F07 costStatus | M26-A01 筛选门店<br>M26-A02 加载/重试库存<br>M26-A03 切换物料相关Tab | 无账面记录、零库存、负数或异常库存、成本未知、成本缺项、无查看权限。 | 与设备详情的实时物料快照名称相近，需要源头和单位区分。 | 表格主列物料、设备、在存、占用、可用、成本状态；标题旁常显“账面库存”。 详见[M26](#page-m26) |
| M27 出入库流水与登记 | 可追溯地记录补货、损耗、盘点差额及调拨。<br>`#/materials → movements tab`<br>来源：public/merchant.js:renderMovementsTab,loadMovements,openMovementModal<br>可用性：inventory.read/manage | M27-F01 类型RESTOCK/WASTE/ADJUSTMENT/TRANSFER<br>M27-F02 createdAt<br>M27-F03 materialId/materialName<br>M27-F04 eventId<br>M27-F05 quantity/unit<br>M27-F06 sourceStore/Device<br>M27-F07 targetStore/Device<br>M27-F08 reason<br>M27-F09 新增类型/物料/数量/原因/来源门店设备/目标门店设备 | M27-A01 类型过滤<br>M27-A02 新增出入库<br>M27-A03 按类型切换来源目标字段<br>M27-A04 确认语义<br>M27-A05 提交<br>M27-A06 取消 | 无流水、入出库类型不同、数量/来源目标不合法、提交中、服务端约束、完成、权限不足。 | 数量符号、调拨方向容易误读，动态字段和确认摘要必须联动。 | 流水表时间/类型/物料/有符号数量/来源→目标/原因；录入640pxDialog，动态字段在数量下。 详见[M27](#page-m27) |
| M28 运营费用、入账与冲正 | 让成本按正确账期计入经营结果，同时保持更正痕迹。<br>`#/expenses`<br>来源：public/merchant.js:renderExpensesView,loadExpenses,openExpenseModal,postExpenseFlow,reverseExpenseFlow<br>可用性：costs.read/manage | M28-F01 id/category(RENT/LABOR/UTILITIES/MAINTENANCE/OTHER)<br>M28-F02 amountMinor<br>M28-F03 storeId/deviceId<br>M28-F04 occurredOn<br>M28-F05 allocationMethod(DAILY_EQUAL/一次性)<br>M28-F06 allocationStart/allocationEnd<br>M28-F07 分摊天数/近似每日金额<br>M28-F08 note<br>M28-F09 status(DRAFT/POSTED/REVERSED)<br>M28-F10 version<br>M28-F11 冲正reason<br>M28-F12 门店/日期过滤 | M28-A01 新增费用<br>M28-A02 选择归属<br>M28-A03 选择分摊方式/日期<br>M28-A04 保存草稿<br>M28-A05 入账确认<br>M28-A06 已入账冲正及填原因<br>M28-A07 取消 | DRAFT/POSTED/REVERSED/其他、金额/归属日期错误、未知成本分摊、已冲正、只读、请求失败。 | 缺少直观账期预览且冲正易被误认为删除。 | 主表类别/金额/归属/日期/分摊/状态；新增640px表单分金额归属和分摊两区，底部预览；冲正独立480pxDialog。 详见[M28](#page-m28) |
| M29 日/月/年经营报表 | 回答某账期收了多少钱、挣了多少钱、缺哪些成本。<br>`#/reports`<br>来源：public/merchant.js:renderReportsView,fetchReport,exportReportCsv; app/merchant/reports.py:operating,csv<br>可用性：reports.read/export | M29-F01 period.from/to/timezone<br>M29-F02 grain(DAY/MONTH/YEAR)<br>M29-F03 storeId<br>M29-F04 environment<br>M29-F05 图表metric(netCashMinor/recognizedRevenueMinor/materialCostMinor/estimatedProfitMinor)<br>M29-F06 每期period<br>M29-F07 receivedMinor<br>M29-F08 refundedMinor<br>M29-F09 netCashMinor<br>M29-F10 recognizedRevenueMinor<br>M29-F11 materialCostMinor<br>M29-F12 wasteCostMinor<br>M29-F13 paymentFeeMinor<br>M29-F14 operatingExpenseMinor<br>M29-F15 estimatedProfitMinor<br>M29-F16 deliveredCupCount<br>M29-F17 completeness.status/missing<br>M29-F18 totals同名字段<br>M29-F19 CSV独有paidOrderCount/grossProfitMinor<br>M29-F20 notes<br>M29-F21 导出filename | M29-A01 切日/月/年<br>M29-A02 切图表指标<br>M29-A03 门店日期环境筛选<br>M29-A04 展开口径说明<br>M29-A05 查看全部明细和合计<br>M29-A06 导出CSV | 空期间、无成本权限、部分期间缺项、totals未知、CSV导出中/失败、零值/负利润、日期错误。 | 当前汇总把number直接String，存在分/元显示不一致风险；多次取报表可能时点不一致；缺项不能画0。 | 全宽标题+范围条；第一带为现金流文字指标，第二带成本利润分解；图表280px；明细横向可滚表，sticky期间/合计；口径侧边说明可展开。 详见[M29](#page-m29) |
| M30 成员权限与编辑 | 让每位运营人员只接触其职责和门店。<br>`#/members → 成员`<br>来源：public/merchant.js:renderMembersView,loadMembers,openMemberModal,storeScopeEditor<br>可用性：members.read/manage | M30-F01 member.id/displayName/username/email<br>M30-F02 role(OWNER/OPERATOR/FINANCE)<br>M30-F03 storeScope.mode/storeIds<br>M30-F04 status(ACTIVE/SUSPENDED)<br>M30-F05 version<br>M30-F06 末位OWNER保护说明 | M30-A01 编辑角色<br>M30-A02 启停成员<br>M30-A03 ALL/SELECTED门店范围与多选<br>M30-A04 保存<br>M30-A05 取消<br>M30-A06 409冲突重载 | 成员空、只读、OWNER/OPERATOR/FINANCE、门店范围受限、最后OWNER保护、版本冲突、权限变更成功。 | 门店范围目前只显示数量，审核时应能展开具体名称。 | 表格姓名账号/角色/门店范围/状态；编辑560pxDialog分角色能力与门店范围，OWNER后果说明常显。 详见[M30](#page-m30) |
| M31 邀请列表、创建与撤销 | 知道谁被邀请、有没有送达、什么时候失效。<br>`#/members → 邀请`<br>来源：public/merchant.js:loadInvitations,openInviteModal,revokeInvitationFlow,storeScopeEditor<br>可用性：邮件发送当前关闭；既有列表按权限 | M31-F01 invitation.id/email/role/storeScope.mode/storeIds/status<br>M31-F02 deliveryStatus(QUEUED/UNAVAILABLE等)<br>M31-F03 expiresAt<br>M31-F04 创建邮箱/角色/门店范围 | M31-A01 查看邀请<br>M31-A02 创建邀请（开放时）<br>M31-A03 撤销PENDING并确认<br>M31-A04 取消 | 邮件关闭、pending/accepted/revoked/expired服务端对应枚举、发送失败、接受链接缺失、撤销冲突。 | 邀请状态与邮件送达常被混淆，范围需可检查。 | 成员页局部Tab，表格账号/权限范围/邀请状态/投递状态/过期；新邀请520pxDialog。 详见[M31](#page-m31) |
| M32 收款账户与配置校验 | 明确新支付使用哪个账户，历史退款沿哪个账户处理。<br>`#/accounts`<br>来源：public/merchant.js:renderAccountsView,loadAccounts,openAccountModal,validateAccountFlow,setDefaultAccountFlow,disableAccountFlow<br>可用性：payments.read开放；payments.manage有限发布关闭 | M32-F01 account.id/label/provider<br>M32-F02 appIdMasked/merchantIdMasked<br>M32-F03 environment(LIVE/SANDBOX/MOCK)<br>M32-F04 status/isDefault/configuredAt/version<br>M32-F05 新增label/provider/environment/appId/merchantId/appPrivateKey/providerPublicKey<br>M32-F06 校验status/checks.name/status/message | M32-A01 查看脱敏账户<br>M32-A02 新增账户（开放时）<br>M32-A03 校验及查看结果<br>M32-A04 设为默认并确认<br>M32-A05 非默认账户停用并确认<br>M32-A06 取消 | 受限发布禁止写入、LIVE/SANDBOX/MOCK、凭据未配置/校验中/有效/无效、默认账户约束、密钥只写。 | 当前只读发布阶段不能用漂亮的可点击按钮暗示客户可自行开通收款。 | 账户列表突出环境与默认，敏感值仅脱敏；新增720px工作区分基本信息/密钥；校验结果独立检查清单。 详见[M32](#page-m32) |
| M33 组织设置 | 维护组织信息并保护账期一致性。<br>`#/settings`<br>来源：public/merchant.js:renderSettingsView<br>可用性：tenant.manage | M33-F01 tenant.id/name/timezone/version<br>M33-F02 时区选项Asia/Shanghai/Asia/Tokyo/Asia/Singapore/Europe/London/America/New_York/UTC<br>M33-F03 账期变更说明 | M33-A01 修改组织名称<br>M33-A02 选择时区<br>M33-A03 保存<br>M33-A04 409重新加载 | 只读、未修改、时区/名称错误、重新验证、保存中、保存成功、409冲突。 | 技术字段显眼而时区后果不够突出。 | 内容最大800px，左侧标签160px、右侧字段480px；时区影响说明紧贴控件；技术id版本折叠。 详见[M33](#page-m33) |
| M34 商户审计 | 追查本组织的操作结果和责任人。<br>`#/audit`<br>来源：public/merchant.js:renderAuditView,loadAuditPage<br>可用性：audit.read | M34-F01 日期区间<br>M34-F02 action过滤<br>M34-F03 createdAt<br>M34-F04 actorName<br>M34-F05 requestId<br>M34-F06 action<br>M34-F07 resourceType/resourceLabel<br>M34-F08 outcome<br>M34-F09 nextCursor | M34-A01 查询<br>M34-A02 日期/动作筛选<br>M34-A03 加载更多 | 无记录、筛选无结果、字段缺失/长文本、无权限、读取失败。 | 目前requestId占据副标题，对普通用户太重，对排错又缺复制入口。 | 无卡片套卡片的审计表；主列时间/人/动作/资源/结果；requestId进入可展开技术行。 详见[M34](#page-m34) |
| M35 商户演示工具 | 在不接触真实设备、钱款和组织的环境中验收设计状态。<br>`仅 /assets/merchant.html?demo=1`<br>来源：public/merchant.js:initDemoTools,syncDemoTools; public/merchant-demo.js<br>可用性：显式demo专用；与TEST不同 | M35-F01 DEMO横幅<br>M35-F02 当前角色OWNER/OPERATOR/FINANCE<br>M35-F03 empty/forbidden/network/slow故障开关<br>M35-F04 邮件不可用开关<br>M35-F05 claimCode/verifyToken/resetToken/inviteToken固定演示值<br>M35-F06 退款推进数量 | M35-A01 展开/收起工具<br>M35-A02 切角色<br>M35-A03 故障模拟<br>M35-A04 模拟退款成功<br>M35-A05 重置内存数据<br>M35-A06 切邮件故障 | 默认/empty/forbidden/network/slow各开关、角色变更、邮件关闭、内存重置、模拟退款待推进/已成功。 | 工具隐藏在角落且容易把DEMO和TEST混为一谈。 | 顶部明确DEMO条，右下工具入口；工具Drawer宽480px，故障开关纵向。 详见[M35](#page-m35) |
| A01 平台 Token 登录 | 让内部运维明确这是平台入口，不能用商户密码登录。<br>`/admin → /assets/admin.html`<br>来源：public/admin.html + admin.js:handleLogin<br>可用性：独立于商户账号；按平台Token权限 | A01-F01 API Token<br>A01-F02 平台名称<br>A01-F03 会话仅内存说明<br>A01-F04 登录错误<br>A01-F05 运营员身份/角色 | A01-A01 登录<br>A01-A02 密码式Token输入<br>A01-A03 登录失败重试 | 空Token、认证中、无效/撤销/过期Token、网络失败、登录成功。 | 安全说明容易把刷新丢失凭证说成凭证已撤销；与商户入口辨识不足。 | 与M01共享420px表单，左侧显示平台运维标记，蓝青细边区别商户；不出现注册入口。 详见[A01](#page-a01) |
| A02 平台工作区与刷新控制 | 在运维上下文中定位操作并识别数据时效。<br>`admin.html#/dashboard\|devices\|orders\|access\|audit`<br>来源：public/admin.js:buildNav/route/tick<br>可用性：按各平台permission | A02-F01 五个导航与当前标题/说明<br>A02-F02 运营员displayName/actorId/role/tokenLabel<br>A02-F03 刷新时间/倒计时<br>A02-F04 权限不足说明 | A02-A01 切换模块<br>A02-A02 立即刷新<br>A02-A03 自动刷新<br>A02-A04 退出登录<br>A02-A05 无权限返回可用页 | 未认证、无任何页面权限、刷新中、已暂停、数据过时、重新登录。 | 重复刷新可能干扰阅读，需要明确暂停原因而非数字跳动。 | 224px侧栏、64px顶栏，身份与刷新放右上；内容12列，操作不混入商户组织选择。 详见[A02](#page-a02) |
| A03 平台运营总览 | 先发现异常积压，再了解今天运行规模。<br>`admin.html#/dashboard`<br>来源：public/admin.js:renderDashboardView/loadDashboard<br>可用性：dashboard.read；最近订单另需orders.read | A03-F01 设备total/online/restricted<br>A03-F02 订单today/readyToday/successRate/exceptionsToday<br>A03-F03 manualReviews<br>A03-F04 pendingRefunds<br>A03-F05 pendingBusinessEvents<br>A03-F06 pendingCommands<br>A03-F07 最近8笔订单的A08全部概览字段 | A03-A01 刷新<br>A03-A02 展开最近订单<br>A03-A03 前往订单/设备 | 局部订单403、指标缺失、今日零订单时完成率未知、异常积压>0、刷新失败旧值保留。 | 相同强度指标掩盖人工复核；积压事件/命令不能默认绿色安全。 | 顶部状态摘要占8列，右4列更新时间；下方左4列纵向异常待办，右8列最近订单；设备与今日完成率为横排数值而非四卡模板。 详见[A03](#page-a03) |
| A04 平台设备列表 | 定位需要处理的设备。<br>`admin.html#/devices`<br>来源：public/admin.js:renderDevicesView/renderDeviceRows<br>可用性：devices.read；登记需devices.manage | A04-F01 搜索deviceId/SN/门店<br>A04-F02 连接筛选<br>A04-F03 online/hasEverConnected<br>A04-F04 deviceId/serialNumber<br>A04-F05 storeName/storeId<br>A04-F06 profileComplete<br>A04-F07 lifecycleStatus<br>A04-F08 activeOrderCount<br>A04-F09 lastHeartbeatAt<br>A04-F10 softwareVersion | A04-A01 搜索<br>A04-A02 筛选<br>A04-A03 选择设备<br>A04-A04 登记设备<br>A04-A05 刷新 | 未登记、无匹配、在线、离线、从未上线、详情加载失败。 | 表内门店/实例标题与值语义混杂；需要分别列标签。 | 列表主区8列+摘要4列，行56px；前两列粘性连接与ID；完整详情打开640pxDrawer避免并排过窄。 详见[A04](#page-a04) |
| A05 平台设备详情与远程命令 | 诊断连接、能力和物料，并执行有权限的运营操作。<br>`设备列表详情`<br>来源：public/admin.js:renderDeviceDetail/sendDeviceCommand/confirmRestart<br>可用性：devices.read；操作按devices.manage/commands.execute | A05-F01 deviceId/deviceName/serialNumber<br>A05-F02 storeName/storeId/cityCode/timezone<br>A05-F03 profileComplete/profileSource<br>A05-F04 instanceId<br>A05-F05 softwareVersion<br>A05-F06 activeBootId<br>A05-F07 lastSequence<br>A05-F08 heartbeatCount/eventCount/commandCount<br>A05-F09 activeOrderCount<br>A05-F10 capabilities/inventory快照version/receivedAt<br>A05-F11 lastHeartbeatAt<br>A05-F12 lastErrorSummary<br>A05-F13 online/hasEverConnected/lifecycleStatus<br>A05-F14 recipes: name/recipeId/version/estimatedDurationSeconds/priceMinor/currency/available<br>A05-F15 materials: name/materialId/available/capacity/unit/status<br>A05-F16 重启影响与确认文字 | A05-A01 查看基本/能力/物料/操作分区<br>A05-A02 变更生命周期<br>A05-A03 生成激活码<br>A05-A04 RELOAD_CONFIG重载<br>A05-A05 SYNC_CONFIG同步<br>A05-A06 重启应用二次确认<br>A05-A07 关闭详情 | 快照未上报/获取失败/过时、PENDING/ACTIVE/SUSPENDED/MAINTENANCE、命令排队/失败、无命令权限、未知物料状态。 | 旧实现把缺少预计时长默认为60秒、未知能力当可售、未知物料当正常有误导风险；重设计显示未知。 | 640pxDrawer或独立详情全宽：头身份+状态，Tabs概览/能力/物料/操作；键值2列，命令区分低风险配置与危险重启。 详见[A05](#page-a05) |
| A06 登记设备、激活码与生命周期 | 完成出厂登记与安装交接，留存变更原因。<br>`设备操作弹窗`<br>来源：public/admin.js:openRegisterModal/createActivationCode/openLifecycleModal/showSecretModal<br>可用性：devices.manage | A06-F01 deviceId格式coffee-bot-[0-9]{3,6}<br>A06-F02 serialNumber格式CB-[0-9]{4}-[0-9]{3,6}<br>A06-F03 instanceId/storeId可选<br>A06-F04 重复登记说明<br>A06-F05 activationCode/expiresAt<br>A06-F06 目标生命周期<br>A06-F07 必填reason<br>A06-F08 当前设备ID | A06-A01 登记并生成激活码<br>A06-A02 取消<br>A06-A03 重新生成激活码<br>A06-A04 复制一次性激活码<br>A06-A05 关闭秘密展示<br>A06-A06 提交生命周期变更 | 格式错误、重复记录、登记成功发码失败、发码成功、已过期、复制失败、原因空、版本/业务冲突。 | 双步骤失败容易误报整体失败，导致反复登记；秘密显示应避免被Toast遮挡。 | 登记560pxDialog，ID/SN单列48px，选填两列；成功切换480px秘密Dialog；生命周期480pxDialog。 详见[A06](#page-a06) |
| A07 平台订单筛选 | 查找特定设备和状态的订单。<br>`admin.html#/orders`<br>来源：public/admin.js:renderOrdersView/loadOrders<br>可用性：orders.read | A07-F01 订单状态筛选全部/CREATED/AWAITING_PAYMENT/QUEUED/DISPATCHED/ACCEPTED/MAKING/HOLD/READY/FAILED/REFUNDED/CANCELLED/EXPIRED<br>A07-F02 deviceId<br>A07-F03 当前返回范围/条数 | A07-A01 查询<br>A07-A02 Enter查询<br>A07-A03 刷新<br>A07-A04 展开订单 | 初始加载、无订单、无匹配、查询失败、旧结果刷新中。 | 缺乏筛选摘要，窄屏横表难定位异常。 | 全宽56px筛选行，状态200px、设备240px、查询；下方表格余高。 详见[A07](#page-a07) |
| A08 平台订单行与详情 | 把支付、制作、复核证据并列阅读。<br>`平台总览/订单展开`<br>来源：public/admin.js:renderOrderTable/renderOrderDetail<br>可用性：orders.read | A08-F01 orderNo/orderId<br>A08-F02 deviceId<br>A08-F03 storeId或paymentMode=TEST_FREE免支付联调<br>A08-F04 productName<br>A08-F05 totalAmountMinor/currency<br>A08-F06 status<br>A08-F07 paymentStatus<br>A08-F08 progress/currentStepName<br>A08-F09 createdAt<br>A08-F10 productionStatus<br>A08-F11 failureCode/failureMessage<br>A08-F12 updatedAt<br>A08-F13 manualReviewRequired<br>A08-F14 holdReason | A08-A01 展开/收起<br>A08-A02 查看失败与HOLD说明<br>A08-A03 复制完整订单标识（新增纯前端便利） | 所有订单/支付枚举见§11，未知枚举、HOLD、缺失进度、失败信息过长。 | 制作与支付状态容易被混读；进度缺失应未知而非0%。 | 表格行56px；展开2列定义列表或640pxDrawer；状态与支付独立列；失败证据全宽背景浅红，HOLD浅黄。 详见[A08](#page-a08) |
| A09 运营员管理与编辑 | 管理平台内部运维身份，避免与商户成员混淆。<br>`admin.html#/access`<br>来源：public/admin.js:renderAccessView/renderOperators/openCreateOperatorModal/openEditOperatorModal<br>可用性：access.read；写入需access.manage | A09-F01 displayName/operatorId<br>A09-F02 role OWNER/MANAGER/OPERATOR/VIEWER（以availableRoles为准）<br>A09-F03 status ACTIVE/SUSPENDED<br>A09-F04 activeTokenCount<br>A09-F05 lastUsedAt<br>A09-F06 新建名称/角色及availableRoles.permissions权限数量/预览<br>A09-F07 编辑名称/角色/状态；停用后该运营员全部Token失效说明 | A09-A01 新建运营员<br>A09-A02 编辑<br>A09-A03 保存/取消<br>A09-A04 展开Token | 无运营员、只读、保存中、禁用、角色冲突、当前权限失效。 | 内嵌Token表挤压主表，平台角色与租户角色名称相近。 | 全宽运营员表，顶部新建；编辑480pxDialog；展开Token改A10 Drawer。 详见[A09](#page-a09) |
| A10 运营员 Token 与一次性秘密 | 安全发放与撤销访问凭证。<br>`运营员展开详情`<br>来源：public/admin.js:renderOperatorTokens/revokeToken/showSecretModal<br>可用性：access.read/manage | A10-F01 所属运营员<br>A10-F02 token.label/tokenId/status/expiresAt/lastUsedAt/createdAt<br>A10-F03 创建label最长120<br>A10-F04 可选datetime-local到UTC expiresAt<br>A10-F05 新建完整token<br>A10-F06 SHA-256摘要保管说明<br>A10-F07 撤销不可恢复说明 | A10-A01 展开Token<br>A10-A02 创建Token<br>A10-A03 复制完整Token<br>A10-A04 关闭秘密<br>A10-A05 撤销Token并确认<br>A10-A06 刷新列表 | 列表失败、空Token、ACTIVE/REVOKED/其他、已过期、创建成功、复制失败、自身撤销。 | 默认空expiresAt永久有效风险应明确，不能在保存后才告知。 | 640pxDrawer，Token表上方说明，创建表单下方分区；秘密480pxDialog，一次显示可复制。 详见[A10](#page-a10) |
| A11 平台审计列表与详情 | 追溯操作的主体、对象和请求。<br>`admin.html#/audit`<br>来源：public/admin.js:renderAuditView/loadAuditLogs/showAuditDetail<br>可用性：audit.read | A11-F01 筛选action/resourceType<br>A11-F02 createdAt<br>A11-F03 actorName/actorId/actorType<br>A11-F04 action<br>A11-F05 resourceType/resourceId<br>A11-F06 requestId<br>A11-F07 detail完整JSON<br>A11-F08 limit=200返回范围 | A11-A01 查询/Enter<br>A11-A02 打开详情<br>A11-A03 关闭<br>A11-A04 复制非敏感ID（新增纯前端便利） | 无匹配、局部字段缺失、JSON空、读取错误、无权限。 | 全页横滚与长技术字段导致可读性差。 | 表格时间160px、操作者180px、动作/资源自适应、请求ID末列；640px详情Drawer内JSON等宽可横滚。 详见[A11](#page-a11) |
| C01 设备菜单与饮品选择 | 扫码后看清饮品、价格和设备可用性再下单。<br>`/order?device_id={id}`<br>来源：public/order.js:loadMenu/renderMenu/card/selectDrink<br>可用性：匿名设备限定菜单 | C01-F01 deviceId/storeId<br>C01-F02 online/deviceStatus/salesEnabled<br>C01-F03 paymentMode ONLINE/TEST_FREE<br>C01-F04 materialAlertCount<br>C01-F05 可售产品remainingServings求和的旧预计可售杯数<br>C01-F06 recipeId/name/description<br>C01-F07 visual.profile与generic回退<br>C01-F08 priceMinor/currency<br>C01-F09 recipeVersion<br>C01-F10 durationRangeSeconds.min/max/estimatedDurationSeconds<br>C01-F11 available/unavailableReasons[]及当前首项解释<br>C01-F12 remainingServings<br>C01-F13 选中饮品/合计<br>C01-F14 共享物料与付款后派单说明 | C01-A01 选择可售饮品<br>C01-A02 查看不可售原因<br>C01-A03 确认下单<br>C01-A04 刷新菜单/错误重试 | 加载、无device_id、设备不存在、无产品、全部不可售、在线/离线/维护、价格未知、浏览器离线。 | 旧大标题与重复说明挤压菜单；选择态需描边和文字而非只色彩。 当前把共享原料支持的不同配方杯数相加，未必等于设备真实总可售杯数；保留该值在口径说明中并标“各饮品估算之和，非承诺总库存”，不能继续无条件当作总库存。 | 最大1120px，顶部设备信息56px；商品3列，右侧或底部320px选购摘要；商品图片仅用现有SVG，不造未知口味。 详见[C01](#page-c01) |
| C02 创建订单与价格冲突 | 防止重复订单或未经确认的价格变化。<br>`菜单提交状态`<br>来源：public/order.js:submitOrder<br>可用性：可售产品且服务端校验通过 | C02-F01 recipeId/recipeVersion<br>C02-F02 quantity=1/paymentMode<br>C02-F03 支付前合计priceMinor/currency<br>C02-F04 订单idempotencyKey与payment:key<br>C02-F05 服务端错误code/message<br>C02-F06 创建结果orderId/accessToken/paymentId（秘密不展示） | C02-A01 提交<br>C02-A02 失败后重试<br>C02-A03 价格/菜单变化后重新选择确认 | 创建中、校验失败、版本/价格冲突、超时结果未知、成功跳转。 | 失败提示不应只短Toast，不能用假乐观支付成功。 | 在C01摘要区原位显示创建中，锁定主CTA；错误贴近金额而非覆盖全页。 详见[C02](#page-c02) |
| C03 等待支付与稳定二维码 | 确认金额与支付环境，然后完成付款并等待服务端确认。<br>`/order/status#order=…&token=…&payment=…`<br>来源：public/order.js:renderOrder/attachPaymentQr<br>可用性：CREATED/AWAITING_PAYMENT | C03-F01 orderNo<br>C03-F02 product.name<br>C03-F03 totalAmountMinor/currency<br>C03-F04 payment.provider<br>C03-F05 qrCode付款链接<br>C03-F06 二维码/加载说明<br>C03-F07 支付里程碑<br>C03-F08 服务端实时确认说明<br>C03-F09 模拟付款不扣款声明 | C03-A01 打开付款页<br>C03-A02 扫码<br>C03-A03 刷新状态<br>C03-A04 二维码失败重试 | 二维码加载/成功/失败、待付款、回跳待确认、SSE断开、订单失效、未知渠道。 | 旧固定支付宝文案容易误导；同手机扫码需有直接打开链接；付款跳转不能视为支付完成。 | 最大960px两列：左420px商品金额与里程碑，右320px支付面板；二维码224px有白色静区；不占满全屏hero。 详见[C03](#page-c03) |
| C04 排队、制作、完成与退款结果 | 清楚知道等什么、是否能取杯、失败后款项处于何状态。<br>`/order/status同一订单`<br>来源：public/order.js:renderOrder/productionSteps/milestoneMarkup/bannerFor/statusNote<br>可用性：按服务端订单状态 | C04-F01 orderNo/product.name<br>C04-F02 status<br>C04-F03 queuePosition<br>C04-F04 production.overallProgress/progress<br>C04-F05 currentStepId/currentStepName<br>C04-F06 remainingSeconds/plannedDurationSeconds<br>C04-F07 步骤id/name/index/duration<br>C04-F08 支付/排队/制作/完成里程碑<br>C04-F09 failure.message<br>C04-F10 HOLD解释<br>C04-F11 退款原路与时间说明<br>C04-F12 物料预留/扣减与结果确认说明 | C04-A01 刷新状态<br>C04-A02 展开制作步骤/技术说明<br>C04-A03 终态查看结果 | QUEUED/DISPATCHED/ACCEPTED/MAKING/HOLD/READY/FAILED/REFUNDED/CANCELLED/EXPIRED；未知枚举、延迟上报、重连中、步骤数据不全。；兼容旧PAID展示为支付成功正在排队，不作为制作终态。 | 付款成功不等于饮品完成；异常结果与退款最终到账需分开表达。 | 最大960px，左360px状态/96px进度环，右步骤时间线；READY取杯提示置首；技术说明折叠底部。 详见[C04](#page-c04) |
| C05 消费者错误与访问失效 | 让用户区分网络问题和失效链接，知道安全下一步。<br>`菜单/状态错误页`<br>来源：public/order.js:renderError/loadOrder/startOrderStream<br>可用性：匿名请求或订单凭证失效 | C05-F01 错误message/code<br>C05-F02 缺少device_id/order/token<br>C05-F03 重试是否允许<br>C05-F04 连接提示<br>C05-F05 当前设备/订单上下文（非秘密）<br>C05-F06 认证与不存在区分 | C05-A01 重新连接（可恢复错误）<br>C05-A02 回菜单（可恢复设备上下文时的新增纯前端导航） | 断网、超时、接口500、404、凭证缺失/失效、重试中、恢复成功。 | 所有错误统一连接中断易误导，需要按来源给下一步。 | 最大560px错误区域，标题20px，具体原因+主操作，取消无意义状态hero。 详见[C05](#page-c05) |

### 2.2 Feature Inventory：业务链路

| 链路 | 现有场景 | 完成标志/业务边界 |
| --- | --- | --- |
| 注册与登录 | M01–M09 | USERNAME注册→登录→选择组织；邮件路径由配置门控 |
| 客户资产 | M11–M19 | 认领→安装资料→状态管理→有条件解绑/转让；不等于永久删除物理设备 |
| 商品与交易 | M20–M23、C01–C05 | 定价→下单→支付→制作→退款事实；支付与制作分别确认 |
| 成本核算 | M24–M29 | 物料→采购→账面流水→费用→报表/CSV；缺项可追溯 |
| 租户管理 | M30–M34 | 成员/范围、邀请、账户、组织、审计；组织隔离 |
| 平台运维 | A01–A11 | 平台Token→登记/激活→远程命令→运维订单→访问凭证/审计 |
| 安全演示 | M35 | 内存数据与故障模拟；不调用正式写接口 |

### 2.3 Information Inventory：字段口径

| 数据类别 | 显示与排序规则 | 不可混淆的含义 |
| --- | --- | --- |
| 金额 | API `*Minor` 为整数分；CNY显示¥+两位小数，右对齐tabular；CSV遵循现有“分”表头 | 空/无权/非法不是0；收到退款请求不等于退款到账 |
| 数量 | 数量+单位并列；来自响应的0正常显示；不把未知强制转换0 | 杯、采购单位、库存单位、克/毫升不可混加 |
| 时间 | 使用组织timezone展示账期，完整时间在详情；相对时间旁可查绝对时间 | 前端结束日包含当天；API `to` 为下一天起点的右开区间 |
| 标识 | ID/SN/交易号等宽、允许换行/复制，列表可短显但完整值有明确详情入口 | 不将显示名称代替请求ID；复制值不带省略号 |
| 角色/权限 | 中文角色名+必要技术值，权限从服务端获得 | 平台OWNER/MANAGER/OPERATOR/VIEWER与商户OWNER/OPERATOR/FINANCE不同 |
| 状态 | 文字+图标/形状+色，未知显示“未知（原值）” | 生命周期、在线状态、任务状态、支付状态相互独立 |
| 环境 | 顶栏持续标识LIVE/TEST或DEMO；支付账户另标LIVE/SANDBOX/MOCK | TEST调用真实API；DEMO仅内存；ONLINE≠真实扣款 |

### 2.4 Existing Problems 与本轮改进方向

1. 上次视觉更新主要是Token映射与局部样式；认证页和信息架构变化不足。本次验收看布局、层级、导航及跨屏重排，不以颜色变量替换数量验收。
2. merchant 报表汇总存在直接 `String(number)` 路径，分/元可能混用；以 `12345 → ¥123.45` 为固定验收例，表头、图、明细与合计一致。
3. 部分设备能力和库存字段在demo与真实投影间不同；以 `app/merchant/assets.py`、API和formatter核验。无容量只能显示数量或状态，不能用0.12/0.35/1伪造容量百分比。
4. 未知物料/预计时长/进度与成本不能默认为正常、60秒、0或完整；“未上报”“待补全”“无权查看”分别显示。
5. 菜单按产品相加的预计剩余杯数可能重复计算共享物料；保留旧值的可查性，明确估算口径。后台账面库存与设备物料快照分开导航和标题。
6. 大块Hero、同样阴影卡片及长技术说明挤压有效工作区域；改为状态摘要、密集记录、可展开证据和局部工具栏。
7. 关闭邮件/转让/收款写入/商户命令时不能给可执行假入口；开启后要有设计和完整路径。
8. 曾出现静态模块文件权限导致登录加载失败：部署环节必须确认容器非root进程可读所有静态文件；当前已有Dockerfile权限修复，不将它误记为“登录被删”。
9. 创建订单→创建支付、登记设备→生成激活码是两阶段请求。分步失败要准确提示已完成部分，不引导重复创建。
10. 手机表格和弹层需要重组，不应依赖浏览器缩放或全页横向滚动。

证据入口：[merchant.js](../public/merchant.js)、[merchant-api.js](../public/merchant-api.js)、[merchant-format.js](../public/merchant-format.js)、[merchant-demo.js](../public/merchant-demo.js)、[admin.js](../public/admin.js)、[admin-format.js](../public/admin-format.js)、[order.js](../public/order.js)、[merchant router](../app/merchant/router.py)、[security](../app/merchant/security.py)、[assets](../app/merchant/assets.py)、[reports](../app/merchant/reports.py)。

## 3. UX Strategy

### 3.1 用户与首要任务

| 用户 | 首屏问题 | 最短主要路径 |
| --- | --- | --- |
| 商户OWNER | 设备是否营业、赚多少、哪些数据不完整 | 总览→异常设备/报表；资产→认领；组织→成员 |
| 商户OPERATOR | 哪台机器需补料、哪些订单异常 | 设备→详情；库存→流水；订单→详情 |
| 商户FINANCE | 现金与确认收入为何不同、成本缺什么 | 报表→账期/门店→明细→CSV；按实际权限只读 |
| 平台内部运维 | 哪些设备断线、有哪些复核与积压 | 平台总览→设备或订单→证据/有权操作 |
| 消费者 | 能买什么、付多少、何时取杯 | 设备菜单→创建→付款→制作结果 |
| 验收人员 | 每个权限/失败/空态是否正确 | 显式DEMO→工具→场景→恢复，不操作生产 |

服务端permissions与设备allowedActions取交集。OWNER并非在所有发布配置下拥有所有写能力；FINANCE不自动拥有costs.manage。无权模块不展示数据；用户深链进入时给403说明与回可用首页。环境暂关闭的能力向有相关身份者说明“暂未开放”，不冒充角色权限不足。

### 3.2 新信息架构

```text
商户工作区
├ 经营：总览 dashboard｜订单 orders｜经营报表 reports
├ 资产：我的设备 devices｜门店 stores｜设备转让 transfers（门控）
├ 成本与商品：商品价格 prices
│            物料与库存 materials → 物料 / 采购 / 账面库存 / 出入库流水
│            运营费用 expenses
└ 组织：成员 members（含邀请）｜收款账户 accounts（门控）
        组织设置 settings｜审计 audit

平台运维台（独立身份，不复用商户菜单）
├ 运营总览 dashboard
├ 设备 devices → 详情 / 登记 / 激活 / 生命周期 / 远程命令
├ 订单 orders → 支付与制作证据
├ 权限 access → 运营员 → Token
└ 审计 audit

消费者（无后台外壳）
设备菜单 → 创建订单/支付 → 待支付 → 排队/制作 → 完成/异常/退款
```

沿用现有hash标识，调整分组与标题不要求迁移URL。M24–M27保持materials局部Tab；弹层若加深链只放非秘密对象ID，关闭恢复列表筛选/滚动。旧 `/admin`、`/order`、`/order/status` 和静态入口继续可达。

### 3.3 导航与上下文

Desktop侧栏224px，分组标题12px、导航项44px。高频经营/资产展开，组织可折叠；当前项浅蓝底+左2px标记+aria-current。Tablet72px轨点击后展开224px覆盖导航，Mobile顶栏56px加底部64px“总览/设备/订单/更多”；可见项不足时不保留无权空槽。报表、成本与组织等全部从“更多”进入，并显示当前模块名称。

顶栏左侧面包屑，右侧账号菜单；商户范围栏集中组织、门店、日期、环境，切组织先清除旧租户详情与缓存再取数据。Mobile范围栏折叠成“全部门店 · 本月 · LIVE”44px摘要按钮打开筛选Sheet。详情返回不重置查询。

Command Palette是**新增纯前端导航便利**：Ctrl/Cmd+K，仅索引用户可访问模块与导航动作；不搜索后台全部订单、不执行退款/重启，不持久存凭证。搜索建议只来自非敏感本地模块名，最近导航最多5项。没有通知中心API，因此不新增铃铛假数据；使用总览现有告警作为提醒入口。

## 4. Design Principles

- **工具优先**：标题24px、页面主操作与标题同排；数据区在Desktop首屏160px以内开始，不设置后台Hero。
- **用区域而非盒子划分**：默认白色工作面、细分隔、24px段间距；同一任务不套三层Card。背景白/近白占至少75%，高饱和强调总面积不超过15%。
- **一个主任务焦点**：一个工作区域一个主按钮，其余描边/文字；危险动作不使用品牌主CTA抢焦点。
- **数据有来历**：数值旁有口径/环境/时效，未知有原因；不以假进度与动画制造确定性。
- **颜色有分工**：Blue主操作，Green成功，Yellow待确认，Pink错误，Cyan信息；Purple/Orange用于类别，不作为通用业务状态。
- **视觉确有变化**：认证页由厚重居中卡改轻量分栏；总览由等权卡阵改状态与经营重点；明细采用记录工作区；移动端重新排序任务。
- 不用emoji图标、紫蓝大渐变、深色大底、玻璃堆叠、所有组件大胶囊、无意义图标容器或浮动动画。借鉴HIG、Material和现代SaaS的层级与密度，不复制其具体产品。

## 5. Visual Design Language

### 5.1 Color

下表中的default/hover/pressed为实底白字；selected与subtle-bg使用同色板pressed为文字色。禁用统一底 `#E8ECF2`、字 `#596579`。所有配对值以JSON为准，不从色名猜颜色。浅色装饰档不能用作正文或唯一边界。

| Neutral Token | 值 | 用途 |
| --- | --- | --- |
| background | #F7F9FC | 按命名用于基础工作面/文字 |
| surface | #FFFFFF | 按命名用于基础工作面/文字 |
| surface-elevated | #FFFFFF | 按命名用于基础工作面/文字 |
| border | #DDE3EC | 装饰边，不用作唯一输入边界 |
| divider | #E9EDF3 | 按命名用于基础工作面/文字 |
| control-border | #7B8798 | 交互边界≥3:1 |
| text-primary | #17212B | 按命名用于基础工作面/文字 |
| text-secondary | #526174 | 按命名用于基础工作面/文字 |
| text-disabled | #596579 | 不可用说明仍可读 |

| Palette | default | hover | pressed | selected背景 | subtle-bg背景 | 默认白字对比度 |
| --- | --- | --- | --- | --- | --- | --- |
| blue | #2457D6 | #1D49BB | #163A98 | #E9EFFF | #F2F5FF | 6.16:1 |
| purple | #7343C5 | #6034AD | #4E288E | #F0E9FF | #F8F4FF | 6.29:1 |
| green | #087A55 | #066647 | #05523A | #DDF5E9 | #EFFBF5 | 5.35:1 |
| orange | #B74812 | #9E3A0D | #812D08 | #FFEADB | #FFF5ED | 5.32:1 |
| pink | #B92B68 | #9C2057 | #801846 | #FFE5EF | #FFF3F7 | 5.82:1 |
| cyan | #08768B | #056376 | #034F60 | #DCF4FA | #F0FAFD | 5.28:1 |
| yellow | #8A6200 | #745200 | #5D4100 | #FFF0BF | #FFF9E8 | 5.49:1 |

语义映射：primary=#2457D6；success=#087A55；warning=#8A6200；error=#B92B68；info=#08768B。neutral亦有完整六态，见JSON。Accent装饰亮色只用于非文本小面积；选中/禁用态不依赖opacity造成对比度不可控。输入边界与Focus Ring单独定义。

### 5.2 Typography

使用系统无衬线字体；金额与计数使用tabular-nums lining-nums，ID/SN/JSON用系统等宽。标题字重650无对应字体时允许浏览器映射600/700，不下载可变字体。大额 `¥12,345,678.90` 在320px下可换到独立行，不缩成无法阅读字号。日期时间按列对齐；百分号与数值同行；负数带负号不只变红。具体字号/行高/字重见下表与JSON。

| Type | 字号px | 行高px | 字重 |
| --- | --- | --- | --- |
| display | 30 | 38 | 700 |
| h1 | 24 | 32 | 700 |
| h2 | 20 | 28 | 650 |
| h3 | 18 | 26 | 650 |
| h4 | 16 | 24 | 600 |
| body-lg | 16 | 24 | 400 |
| body | 14 | 22 | 400 |
| body-sm | 13 | 20 | 400 |
| caption | 12 | 18 | 400 |
| label | 13 | 20 | 600 |
| numeric | 28 | 36 | 650 |

### 5.3 Spacing / 5.4 Radius / 5.5 Elevation / 5.6 Icon

| 类别 | 数值与用法 |
| --- | --- |
| 网格 | 基础4px；4/8/12/16/20/24/32/40/48/64；页面边24、手机16；段间24；标签到输入8 |
| 圆角 | 4小标签、8输入/按钮、12工作面、16弹层、999仅状态/头像/小进度条 |
| 平面 | level-0 none；静态内容通过背景/边线分区 |
| 微浮层 | level-1：0 1px 2px rgba(23,33,43,.06)，仅粘性表头等 |
| 浮层 | level-2：0 2px 6px rgba(23,33,43,.08), 0 8px 24px rgba(23,33,43,.12) |
| SVG | 24×24 viewBox、stroke1.5、圆端点；图16/20/24/32；外热区≥44；同一风格，不用emoji |
| 模糊 | 默认不使用；遮罩rgba(23,33,43,.36)即可，不以玻璃质感代替层次 |

### 5.7 Data Visualization

每个图明确：标题、时间范围、组织时区、单位、环境、数据时效、图例、空缺说明。经营趋势将现金收款与确认利润分系列；不同单位不共用无标注轴。零值在零线上，未知断开且显示缺失标记；负利润允许穿过0轴。颜色之外用圆点/方点/虚实线区分；图例控制只影响本地显示，不改变合计。下方“查看数据表”提供完整日期和数值，键盘/屏幕阅读器无需操作SVG。无同比/环比字段与可靠同口径数据时不制造“增长12%”。

## 6. Responsive Design

| 断点 | 外壳/边距 | 内容组织 | 详情与操作 |
| --- | --- | --- | --- |
| Desktop ≥1440 | 224侧栏，64顶栏，页边24；内容max1440 | 12列，gap24；允许主8/辅4，表格余宽充分使用 | 640Drawer或宽详情，按钮44/CTA48 |
| Laptop1024–1439 | 侧栏可折224→72，64顶栏；max1120 | 12列gap16；8/4若主区<640则上下排列 | 大表全宽，右Drawer覆盖不挤压到三窄列 |
| Tablet768–1023 | 72轨+224覆盖导航，56顶栏，页边24 | 8列gap16；趋势和列表全宽，摘要2列 | 90vwDrawer，复杂表单全屏，字段44/48 |
| Mobile<768 | 56顶栏、64底导航+safe-area；页边16 | 单列，摘要可2列；消费端max480且无后台底导航 | 全屏详情/短Sheet；48主CTA；键盘避让 |

所有尺寸单位px。320px宽有效内容288px；44px控件不压缩。200%文本缩放下允许上下排列。表格只在自己的容器横滚并提供边缘提示，页面主体不横滚。Sticky Header和Footer不能盖住Focus Ring、错误文本或最后一行。使用100dvh与safe-area，软键盘出现时底部导航可隐藏，操作区随可视区域与内容流重排。

每页Desktop/Tablet/Mobile见§10；Laptop统一采用本节规则，不让OpenDesign自行猜断点。M13等重详情在Tablet可替换正文而非浮层，具体页规则优先。Mobile表格转换后仍显示每条记录的主要标识、关键金额/状态；次级字段在标明标题的完整详情中。

## 7. Component System

这是基于原生DOM/CSS的组件规范，不是假定存在第三方组件库。尺寸指CSS像素；所有交互项的真实布局/点击边界至少44×44，包括桌面。视觉小图标不代表可以用重叠伪元素扩热区。通用D/H/P/F/S分别对应default/hover/pressed/focused/selected；无交互的纯标签不伪造hover/press状态，数据容器使用Loading/Empty/Error等状态。

| Component | Variant / Size | State | Interaction | Responsive Behavior | 复用/扩展 |
| --- | --- | --- | --- | --- | --- |
| Button | primary/secondary/ghost/destructive/link/icon；44px，主CTA48px | default/hover/pressed/focus/disabled/loading | 图标可16/20但热区44；loading保留文案防布局抖动；风险动作无乐观成功 | 手机主操作全宽；并排按钮≥44且不重叠 | 改造三端.btn |
| Input | text/password/number/readonly/error；44px，Mobile48px | 空/有值/focus/error/disabled/readonly | label关联id；blur后校验、提交摘要；金额输入转整数分再提交；密码显隐有可访问名称 | 移动输入字16px避免自动放大；数值inputmode decimal | 改造.field/.input |
| Select | 原生single；44px；组织/门店 | default/selected/disabled/error/loading | 优先原生select；选项仅服务端允许范围；label不省略 | 手机全宽或原生picker | 改造现有select |
| Search | 带搜索/清除/范围说明；44px | 空/输入/结果/无结果/loading/error | Enter查询；本地过滤可150ms防抖；只搜索已加载范围必须标注；不改变现有服务端参数 | 筛选图标44px；键盘search；展开占一行 | Input扩展 |
| Tabs | 下划线；44px命中；2–5项 | default/hover/focus/selected/disabled | tablist/tabpanel；左右/Home/End；按需加载采用Enter激活 | 横滚导航带边缘提示，不横滚页面正文 | 改造现有.tabs |
| SegmentedControl | 中性浅底、活动白底+蓝字；每项44px | default/hover/pressed/selected/disabled | 单选语义；日/月/年、环境、图表指标各独立组 | 空间不足换Select；不裁掉标签 | 改造.m-seg |
| Tag | 中性元数据/类别/可移除筛选；外观24px | default/selected/disabled | 非交互标签无tabindex；删除×独立44px热区 | 多行wrap；交互标签最小高44px | 统一现有badge扩展 |
| Badge | 数量/提示点；视觉20–24px | 0/正数/99+/unknown | 数字需可访问说明；unknown不显示0；独立点击需44px容器 | 附着导航不遮文字 | 现有badge改造 |
| Status | 文字+点/图标；视觉24px | success/info/warning/error/neutral/unknown | 纯状态无hover要求；原枚举详情可查；不靠红绿区分 | 长标签可换行；不省略状态词 | 合并badge/status-dot/live-pill |
| Card | static/interactive/sunken；padding16或24；r8/12 | default/hover/focus/selected/loading | 默认无阴影；交互整卡可键盘激活；不嵌按钮冲突 | 手机任务块间16px，不强套卡片 | 改造.card/.stat |
| List / DefinitionList | 记录列表/键值；只读行36px，交互行≥56px | default/selected/empty/loading/error | 使用ul/dl；金额右对齐；长ID可换行 | 列表主行+详情Sheet；键值一列 | 改造plain-list/kv-grid |
| Table | 普通/财务/可展开；表头44px行56px | loading/empty/error/partial/hover/selected/focus | sticky头/首关键列；金额右对齐；列可见性在本地设置；排序/选择/批量仅有真实能力时出现 | 手机列表+详情；财务矩阵局部横滚，需方向提示 | 改造grid/table-scroll |
| Dialog | 确认480px/表单560px/宽680px；r16 | opening/open/busy/error/closing | focus trap；Esc/外点仅可取消时关闭；未保存提醒；回焦到触发处；确认对象+后果+原因 | 短确认Sheet，复杂表单全屏；不叠三层 | 改造modal-root |
| Drawer | 详情640px/简版520px；max-height100dvh | loading/partial/error/ready/dirty | sticky头脚；内容滚动；关闭恢复位置；请求序列避免旧响应覆盖新对象 | Tablet90vw；Mobile全屏返回，短内容改Sheet | 改造drawer-root |
| Sheet | 筛选/菜单短Sheet，最高80dvh；复杂全屏 | open/dirty/loading/disabled | 关闭按钮44；拖拽只辅助且提供点击等价；不能在选择文字时误关闭 | safe-area；键盘弹出抬升，不遮表单 | Drawer自定义扩展 |
| Popover / Menu | 账号/更多/上下文；宽240–340px | open/hover/focus/disabled | Esc/点击外部关闭；箭头导航menu项；触发器aria-expanded；危险项分隔 | 移动转Sheet；无hover才能打开的必经功能 | 改造pop-panel；新增统一Menu行为 |
| Tooltip | 技术短释义；max280px；12/18px | hover/focus/open | 延迟300ms、Esc关闭、aria-describedby；不承载必须点击的动作；触屏点击信息按钮可读 | 关键帮助直接文字或Popover；不依赖title属性 | 自定义可访问扩展 |
| Toast | info/success/error；Desktop360px | enter/visible/exit | 复制成功1.5秒；普通4秒；错误不自动丢失，页内也有结果；role=status polite | 顶部16px；最多3条，不遮CTA；关闭44px | 改造toast-root |
| Alert / Banner | inline/page/environment；padding12/16 | info/success/warning/error/offline | 有标题+原因+下一步；可恢复才给重试；不可关闭的安全说明不加× | 文案wrap，按钮另行；DEMO始终可见 | 统一callout/notice/alert-item |
| Progress | 线6px/环72或96px；不确定文本 | known/unknown/pending/success/error | 已知使用progressbar及valuenow；unknown无百分比；来自真实值；容量0/未知不除法 | 手机环72px；数值和阶段同时存在 | 改造material-bar/progress-ring |
| Chart | SVG line/bar；高Desktop280、Mobile200 | loading/empty/partial/series-hidden/error | 系列Blue/Green/Cyan/Orange/Purple/Pink/Yellow；配点形/线型/图例；缺失断线；下方可展开数据表 | 减少刻度不减少可查数据；触摸选点不阻止纵向滚动 | 改造现有SVG图 |
| Timeline | 事件/制作/退款；节点12px，间距24px | pending/active/done/error/unknown | 时间、名称、描述分层；不通过排序虚构完成；展开详情44px | 单列，长文本换行；当前步骤先读 | 统一timeline/milestones |
| Avatar | 字母/姓名首字；28/40px | default/image-error | 无头像API时只用首字，不提供虚假上传；装饰头像不单独朗读 | 点击头像需44px外容器 | 新增纯前端 |
| Navigation / Breadcrumb | 224px侧栏/72px轨/64px底栏；项44px | current/hover/focus/collapsed/disabled | aria-current；三级内可回上级；深链权限保护；当前位置不只靠色 | 手机标题+返回；更多Sheet含完整可用模块 | 改造side-nav/nav-item；底栏扩展 |
| Form | 分区/行内/高级设置；段间24px | pristine/dirty/valid/invalid/saving/saved/conflict | label/help/error成组；required文本；Enter不意外触发危险操作；保存不清用户错误输入 | 双列→单列；键盘焦点scrollIntoView，sticky脚不盖输入 | 复用merchant表单工具并统一 |
| Checkbox / Radio / MultiSelect | 外观20px；标签整行44px | unchecked/checked/mixed/disabled/error/focus | 原生input；权限范围多选使用checkbox列表；radio单选；不把多选门店误写全组织 | 选择面板可搜索已知选项、应用/取消 | 原生扩展 |
| Switch | 视觉40×24px，外热区44×44 | off/on/disabled/pending/focus | role=switch或checkbox；DEMO即时切；真实写入失败保留原态并说明 | 标签文字行全宽可点 | 改造DEMO开关 |
| DateRange | 日期/时间/期间；输入44px | empty/valid/invalid/preset/custom | 显式timezone；from≤to；API右开；datetime-local转换UTC；快捷范围不偷偷改环境 | Sheet上下两项与应用48px | 改造现有范围选择 |
| Filter | 工具条/摘要Sheet；高≥44px | inactive/active-count/applying/error | 已用条件Badge、逐项移除与清空；应用后重置真实游标；不自造分页 | 筛选Sheet置顶标题与固定应用；关闭不隐式应用 | 组合既有select/input |
| Pagination | 当前已有加载更多/范围指示；按钮44px | has-next/loading/end/error | 严格采用响应游标；不估算总页数；不为limit列表伪造下一页 | 底部加载更多；错误可重试原游标 | 仅复用现有adapter支持能力 |
| Disclosure / ExpandableSection | 技术详情/口径/原始JSON；标题44px | collapsed/expanded/focus | button aria-expanded或details；数据展开不执行写操作；关联内容可键盘读 | 折叠摘要含关键异常数量 | 现有展开行为统一 |
| Metric / KPI | 主28/36、次20/28、label13；无默认卡壳 | value/zero/unknown/redacted/loading/stale | 单位明确；口径解释可达；图标不硬加；缺项贴着金额显示 | 两列文字栅格，异常优先 | 改造stat与dashboard卡 |
| Product | 饮品选择；Desktop纵向、Mobile横向112–144px | available/selected/unavailable/loading | recipeId与视觉profile分开；可售是单选button；不可售原因可见；不让禁用阻止读原因 | 左96px示意图右名称/金额；剩余量次级 | 改造drink-card |
| QR | 白底、图224px、按二维码内容保留静区 | loading/ready/error/expired | 固定paymentId缓存；不能美化裁切二维码；链接与扫码等价；错误≥20秒重试 | 200–224px；同手机打开链接优先 | 复用attachPaymentQr缓存逻辑 |
| Secret / Copy | 可选文本+复制44px；完整值一次展示 | revealed/copied/copy-error/closed | 只对当前返回秘密展示；copy→check1.5秒；关闭内存清理；不打印日志；普通ID复制共用 | 长串break-all，手动复制兜底 | 复用showSecretModal/copyText |
| Code | 审计JSON/技术ID；13/20pxmono | ready/empty/error | pre文本转义；容器局部横滚；折叠不修改内容；屏蔽上游应脱敏字段 | max-width100%；无全页横滚 | 复用pre样式 |
| Empty | 初次空/筛选无果/权限/错误；max480px | empty/no-match/forbidden/error | 插图可省；一句原因+真实下一步；无权限不显示新建 | 对齐内容而非巨大空白全屏 | 统一emptyState |
| Download | CSV动作44px+格式说明 | ready/loading/success/error | 保留Blob下载/文件名；导出筛选环境时区同当前查询；未知结果不提示已下载 | 菜单项或次按钮，保持可发现 | 复用exportReportCsv |
| Slider / Upload / TagInput | 保留设计扩展规范；当前无这些业务表单；控件热区44px | default/focus/disabled/error/loading | Slider必须有等价数值输入；Upload需后端大小/类型/存储接口；TagInput可删除标签；无接口不落功能入口 | 手机原生选择文件；滑块不与页面滚动争抢 | 非默认实施，需新业务API时单列依赖 |

## 8. Interaction Design

| 场景 | 具体交互与反馈 | 失败/移动端处理 |
| --- | --- | --- |
| 复制 | 点击→Clipboard完成→图标变Check+“已复制”→1.5秒恢复 | 失败显示可手选文本；不把敏感值放Toast |
| 保存 | 校验→Saving禁重复→服务端确认→Saved+刷新对应区 | 错误保留输入；409显示“资料已更新，请重新载入后检查”，不得静默覆盖 |
| 删除/撤销 | 显示对象名、后果、是否可恢复→确认→请求→成功移出列表 | “停用/解绑/冲正”用准确动词，不一律叫删除；金钱/设备/权限不乐观成功 |
| 筛选 | 输入不立刻扰乱列表；点击应用/Enter→Badge显示条件数→读取结果 | 返回详情保留条件；Mobile Sheet取消恢复原条件 |
| 搜索 | 有范围提示；键盘Enter；本地建议只有模块和已知数据 | 不假装后端跨页搜索；最近记录不含订单token |
| 表单 | blur后校验；提交后首错摘要+定位；已修正错误即时消失 | 必填用文字/星号说明；placeholder不作label；保存后不丢对象上下文 |
| 行内编辑 | 双击不是唯一入口，显示编辑按钮；明确保存/取消 | 不在Blur时自动提交价格/权限；Mobile改专用表单 |
| 详情 | 行内更多/整行均可打开；外键ID不被复制按钮连带触发 | 关闭回原触发器；设备已不在列表则回列表标题 |
| 退款 | 展示原金额/已退/可退/本次/原因→重新验证→提交 | 受理≠到账；待确认持续可查，不在网络超时自动重复退款 |
| 设备命令 | 对象ID、命令类型、风险可见；重启二次确认 | “命令已提交”与“设备执行成功”区分；禁止假进度 |
| 刷新 | 旧数据保留+最后成功时间；局部loading不整页闪 | 平台10秒自动刷新遵循暂停规则；消费者重连沿用SSE协议 |
| 未保存退出 | 取消/放弃修改两选项；回到表单焦点 | Esc/遮罩关闭同样触发；避免无限嵌套确认 |
| 通知 | 成功Toast适度；错误页内持久并可重试 | Toast不代替表单错误/秘密结果；读屏只播必要变化 |
| Pull to refresh | 可作为只读列表补充，不作为唯一刷新入口 | 避免浏览器原生下拉冲突；提供44px刷新按钮 |
| Swipe/Drag | 手机滑动只揭示“查看/更多”，拖拽仅Sheet把手辅助 | 不通过滑动直接退款/解绑；无业务排序API不启用拖拽排序 |
| Keyboard | Tab顺序、Enter激活、Esc关闭、菜单箭头导航、Cmd/Ctrl+K模块查找 | 在输入框中不截获普通字符快捷键；公开快捷键说明 |
| Optimistic UI | 仅本地偏好、折叠、图例可即时变 | 金额、库存、设备、账户、权限、注册结果等待服务端事实 |

凭证处理：商户会话cookie继续HttpOnly/Secure/SameSite及CSRF/Origin校验；重设计不得改为localStorage保存密码或会话。消费者accessToken位于fragment并通过既有Header发送，不进入查询参数、埋点、日志、二维码装饰文案。平台Token只在内存。服务端拒绝是权威结果，隐藏按钮不是安全边界。

## 9. Motion Design

| 场景 | 时长/幅度/曲线 | 约束 |
| --- | --- | --- |
| 页面切换 | 180ms opacity，translateY≤4px；enter曲线 | 已缓存列表切换也不能延迟内容可操作 |
| Button | hover颜色120ms；press80ms，可scale.99 | 不改变布局尺寸；reduced时无缩放 |
| Card | interactive仅背景120ms/可level-1 | 静态卡无漂浮，不默认放大 |
| Dialog | 200ms opacity，位移≤8px | 聚焦不等动画结束 |
| Drawer/Sheet | 240ms，位移≤24px，cubic-bezier(.2,0,0,1) | 弹簧感用CSS减速模拟；不默认装spring库 |
| Tooltip/Popover | 180ms淡入；Tooltip300ms触发延迟 | hover可达，Esc立即隐藏 |
| Number | 真实值直接更新；背景高亮160ms | 金额不滚过虚构中间值，不自动动小数 |
| Chart | 初次300ms opacity/线描入 | 只对已到达数据，后续刷新不全图重播 |
| Status | 色/图标opacity160ms | 文案同步更新；不以动画独立表示成功 |
| Success | Check一次160ms淡入 | 退款受理不放完成庆祝；不加彩带依赖 |
| Row removal | 服务端成功后180ms collapse | 焦点移到相邻行/表头；动画不延迟操作 |
| Loading | 先显示按钮/局部状态；超过200ms显示静态骨架 | 骨架尺寸对应真实结构，保留旧值时不用覆盖整页 |

`prefers-reduced-motion: reduce`：动画/位移/缩放/平滑滚动为0，骨架不shimmer，spinner改“加载中…”文字，图表/进度直接到真实值。状态仍通过文本、图标与aria-live更新。进入曲线 `cubic-bezier(.2,0,0,1)`，退出 `cubic-bezier(.4,0,1,1)`。不实现视差、频繁pulse和装饰性转圈。

## 10. Page-by-Page Redesign

阅读规则：Content字段组编号与§2/§15一致；P0为本页必须最先看到的任务/判断，P1为上下文，P2为低频证据与技术值。P2的具体承载位置是每页列明的详情区/展开区/帮助，而非隐藏到无入口。下列操作含读取/提交/关闭/恢复；新增前端便利已标注。通用控件状态由§7落实，页面数据状态由各页及§11落实。


<a id="page-m01"></a>

### Page: M01 商户登录

**现有入口 / 来源**：`/assets/merchant.html#/login`；public/merchant.js:renderAuth(login)。**能力门控**：开放，跟随 auth/config。

#### Purpose

让客户进入自己的组织，不把平台 Token 登录与商户账号混为一谈。

#### User Goal

用户能够围绕“账号密码与登录”完成登录，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：账号密码与登录。
- P1：注册/可用恢复入口。
- P2：会话安全和配置规则。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M01-F01**：registrationMode。
- **M01-F02**：mailEnabled。
- **M01-F03**：passwordMinLength/passwordMaxLength。
- **M01-F04**：usernamePattern。
- **M01-F05**：用户名或已有已验证邮箱。
- **M01-F06**：密码。
- **M01-F07**：品牌/后台名称。
- **M01-F08**：会话安全说明。
- **M01-F09**：登录错误。

#### Layout (Desktop)

居中1120px工作区，左侧280px轻量产品与账号类型说明，右侧420px无悬浮卡片表单，两列间64px；顶部56px品牌栏，表单标题24px，输入48px；不用旧暖棕大阴影登录卡。

#### Layout (Tablet)

两列收为单列，表单最大440px，说明缩为表单上方两行，页边32px。

#### Layout (Mobile)

16px边距、单列表单，品牌栏48px；输入48px，登录48px全宽；注册文字入口44px独立热区；键盘弹出不固定盖住输入。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M01-A01 · Primary**：登录。
- **M01-A02 · Secondary**：创建组织账号。
- **M01-A03 · Secondary**：邮件开启时找回密码/邀请/验证入口。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

配置成功后才确定字段；提交中禁重复；失败保留用户名并聚焦错误摘要；密码成功后清空；401不能触发无限重试。

#### States

初始配置加载、账号密码空/格式错、登录中、401、429、网络断开、成功进入组织。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：两列收为单列，表单最大440px，说明缩为表单上方两行，页边32px。 Mobile：16px边距、单列表单，品牌栏48px；输入48px，登录48px全宽；注册文字入口44px独立热区；键盘弹出不固定盖住输入。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“原界面与旧版几乎相同，技术安全说明抢占核心任务，Label与输入关联不足。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m02"></a>

### Page: M02 创建组织账号

**现有入口 / 来源**：`#/register`；public/merchant.js:renderAuth(register)。**能力门控**：USERNAME开放；EMAIL路径按配置。

#### Purpose

一次建立账号与独立组织，让用户理解注册成功仍不代表已经拥有设备。

#### User Goal

用户能够围绕“用户名密码与组织名称”完成创建账号，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：用户名密码与组织名称。
- P1：姓名与规则/注册结果。
- P2：OWNER说明与邮件模式帮助。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M02-F01**：USERNAME: username。
- **M02-F02**：displayName。
- **M02-F03**：tenantName。
- **M02-F04**：password。
- **M02-F05**：EMAIL: email。
- **M02-F06**：用户名3–32位规则。
- **M02-F07**：密码15–128字符配置。
- **M02-F08**：OWNER身份说明。
- **M02-F09**：REGISTERED/VERIFICATION_PENDING/未知返回状态。

#### Layout (Desktop)

延用M01外壳，表单宽480px，分账号信息/组织信息两个无边框分区；用户名与密码先显示，姓名组织随后；提交区紧邻表单。

#### Layout (Tablet)

最大480px单列，24px分区间距；密码规则紧贴字段，不用侧栏。

#### Layout (Mobile)

所有字段单列48px高；帮助文本常显；错误滚动到首项，保留非敏感值。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M02-A01 · Primary**：创建账号。
- **M02-A02 · Secondary**：字段校验。
- **M02-A03 · Secondary**：返回登录。
- **M02-A04 · Secondary**：注册结果去登录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

USERNAME成功引导去登录且不要求邮箱验证；EMAIL才显示等待验证；不能将未知响应当成功；不引入自动签署营销条款。

#### States

规则未加载、USERNAME/EMAIL两模式、字段错误、用户名占用、REGISTERED、VERIFICATION_PENDING、未知结果、禁用邮件。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大480px单列，24px分区间距；密码规则紧贴字段，不用侧栏。 Mobile：所有字段单列48px高；帮助文本常显；错误滚动到首项，保留非敏感值。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“旧表单信息层级弱；新用户容易把账号创建误认为设备已绑定。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m03"></a>

### Page: M03 找回密码

**现有入口 / 来源**：`#/forgot`；public/merchant.js:renderAuth(forgot),mailDisabledNotice。**能力门控**：邮件关闭时展示不可用说明。

#### Purpose

在不泄露账号存在性的条件下提供恢复路径。

#### User Goal

用户能够围绕“邮箱与发送结果”完成发送找回链接（邮件开放时），并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：邮箱与发送结果。
- P1：回登录。
- P2：受理与隐私说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M03-F01**：注册邮箱。
- **M03-F02**：邮件服务状态。
- **M03-F03**：统一受理结果。
- **M03-F04**：错误。
- **M03-F05**：联系平台管理员说明。

#### Layout (Desktop)

420px表单/说明区，主标题24px，邮箱输入与结果同一区域；不可用状态以说明页替代表单。

#### Layout (Tablet)

单列最大440px，说明在标题下16px。

#### Layout (Mobile)

16px页边，返回登录44px；无邮件时不显示可提交的发送按钮。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M03-A01 · Primary**：发送找回链接（邮件开放时）。
- **M03-A02 · Secondary**：返回登录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

存在/不存在邮箱均相同受理文案；联系管理员仅说明现状，不虚构工单入口或人工重置已实现。

#### States

邮件关闭、提交中、统一受理结果（不泄露账号存在性）、429、网络失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列最大440px，说明在标题下16px。 Mobile：16px页边，返回登录44px；无邮件时不显示可提交的发送按钮。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“关闭功能若只隐藏会让旧链接用户迷失，需要可解释的着陆页。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m04"></a>

### Page: M04 重置密码

**现有入口 / 来源**：`#/reset`；public/merchant.js:renderAuth(reset),readFragmentToken。**能力门控**：邮件关闭时不可用。

#### Purpose

让持有效链接的用户明确完成一次密码重置。

#### User Goal

用户能够围绕“新密码与token有效性”完成设置新密码，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：新密码与token有效性。
- P1：规则与结果。
- P2：凭证来源说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M04-F01**：邮件片段 token。
- **M04-F02**：新密码。
- **M04-F03**：确认密码。
- **M04-F04**：密码长度规则。
- **M04-F05**：密码更新结果。
- **M04-F06**：失效/已使用 token 错误。

#### Layout (Desktop)

480px表单，密码与确认纵向；token置高级展开区但手动粘贴仍可达；结果替换正文。

#### Layout (Tablet)

单列440px，展开区不改变主按钮位置。

#### Layout (Mobile)

输入48px；焦点可视；提交区跟随文档滚动，避免键盘遮挡。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M04-A01 · Primary**：设置新密码。
- **M04-A02 · Secondary**：返回登录。
- **M04-A03 · Secondary**：更新后去登录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

片段token读取后清除地址栏敏感片段并留内存；提交前匹配两次密码；成功清空密码；不自动执行重置。

#### States

token缺失/过期/已用、密码规则失败、提交中、完成、邮件关闭。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列440px，展开区不改变主按钮位置。 Mobile：输入48px；焦点可视；提交区跟随文档滚动，避免键盘遮挡。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“手动token技术字段当前占主流程，且邮件未开启。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m05"></a>

### Page: M05 验证邮箱

**现有入口 / 来源**：`#/verify`；public/merchant.js:renderAuth(verify),readFragmentToken。**能力门控**：邮件关闭时不可用。

#### Purpose

让用户主动确认邮箱验证，避免打开链接即改变状态。

#### User Goal

用户能够围绕“验证结果与下一步”完成主动确认验证邮箱，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：验证结果与下一步。
- P1：邮箱/token状态。
- P2：失效原因。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M05-F01**：验证token。
- **M05-F02**：一次性链接说明。
- **M05-F03**：验证结果。
- **M05-F04**：失败原因。

#### Layout (Desktop)

420px确认页，清晰一句行为说明，token高级区，主确认按钮与取消并列。

#### Layout (Tablet)

单列确认区，说明与按钮相隔24px。

#### Layout (Mobile)

确认按钮全宽48px，返回登录次级44px。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M05-A01 · Primary**：主动确认验证邮箱。
- **M05-A02 · Secondary**：手动粘贴token。
- **M05-A03 · Secondary**：返回登录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

必须点击才消费token；成功/已使用/过期分别显示，不伪造重复成功。

#### States

验证中、无token、过期/已验证、成功、邮件关闭、失败可重试。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列确认区，说明与按钮相隔24px。 Mobile：确认按钮全宽48px，返回登录次级44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“技术token抢占层级，结果状态缺少明确下一步。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m06"></a>

### Page: M06 接受成员邀请

**现有入口 / 来源**：`#/invite`；public/merchant.js:renderAuth(invite)。**能力门控**：邮件关闭时不可用。

#### Purpose

让被邀请者加入正确组织，区分新账号表单与已有账号流程。

#### User Goal

用户能够围绕“邀请token与账号接受条件”完成接受邀请，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：邀请token与账号接受条件。
- P1：姓名密码及登录上下文。
- P2：token来源与密码规则帮助。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M06-F01**：邀请token。
- **M06-F02**：displayName。
- **M06-F03**：password。
- **M06-F04**：密码规则。
- **M06-F05**：已有账号提示。
- **M06-F06**：接受结果。

#### Layout (Desktop)

480px表单，加入组织行为说明在顶部；姓名/密码主区，token高级区；已有账号提示单独一行。

#### Layout (Tablet)

单列480px，不追加无依据的组织预览数据。

#### Layout (Mobile)

48px输入与主按钮，已有账号返回入口44px。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M06-A01 · Primary**：接受邀请。
- **M06-A02 · Secondary**：手动输入token。
- **M06-A03 · Secondary**：返回登录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

当前源码已有账号提示提及组织内确认但未找到该确认UI，标为集成缺口；不虚构自动识别或免密码接受。设计须保留提示并待接口/流程核实。

#### States

邀请缺失/已用/过期/撤销、账号已存在需登录路径、邮件关闭、接受成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列480px，不追加无依据的组织预览数据。 Mobile：48px输入与主按钮，已有账号返回入口44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“已有账号文案与可发现入口存在差距，不能仅凭文案声明闭环。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m07"></a>

### Page: M07 认证配置失败与认证结果

**现有入口 / 来源**：`认证启动及各认证结果页`；public/merchant.js:renderAuthConfigError,authResultPage,mailDisabledNotice。**能力门控**：开放/条件状态。

#### Purpose

避免空白页和假成功，为每次认证请求提供可操作的结果。

#### User Goal

用户能够围绕“失败原因/成功结果与下一步”完成重试配置，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：失败原因/成功结果与下一步。
- P1：当前认证上下文。
- P2：模块/配置诊断。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M07-F01**：错误标题。
- **M07-F02**：详细错误信息。
- **M07-F03**：requestId（若返回）。
- **M07-F04**：配置依赖说明。
- **M07-F05**：结果标题/说明。
- **M07-F06**：注册/验证/重置/邀请状态。
- **M07-F07**：邮件不可用说明。

#### Layout (Desktop)

沿用认证外壳，图标20px+标题24px；结果说明最大60字首段，技术详情可展开。

#### Layout (Tablet)

固定主区宽440px；重试按钮原位反馈。

#### Layout (Mobile)

一屏完成说明与44px以上重试；长错误换行不撑宽。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M07-A01 · Primary**：重试配置。
- **M07-A02 · Secondary**：去登录或返回登录（按结果）。
- **M07-A03 · Secondary**：查看失败说明。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

模块加载失败需HTML可见启动占位和外部脚本错误处理（新增纯前端）；超过10秒提示仍在连接但不冒充API失败；无自动demo降级。

#### States

配置加载失败、JS模块失败时静态恢复说明、未知认证路由、认证成功结果、可恢复/不可恢复错误。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：固定主区宽440px；重试按钮原位反馈。 Mobile：一屏完成说明与44px以上重试；长错误换行不撑宽。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“历史曾有模块权限导致全页空白；当前只有配置请求失败处理，启动资源失败缺兜底。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m08"></a>

### Page: M08 商户工作区与账号菜单

**现有入口 / 来源**：`所有商户认证后路由`；public/merchant.js:buildShell,buildShellControls,buildUserMenu,switchOrg,setEnvironment,route。**能力门控**：按permissions。

#### Purpose

让用户始终知道自己正操作哪个组织、时间范围和数据环境。

#### User Goal

用户能够围绕“当前组织/模块/环境”完成组织切换，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：当前组织/模块/环境。
- P1：门店日期范围和账号。
- P2：高级导航/安全说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M08-F01**：当前组织名称/tenantId/成员关系id。
- **M08-F02**：组织角色。
- **M08-F03**：当前用户姓名/username/email。
- **M08-F04**：门店id/名称。
- **M08-F05**：日期from/to。
- **M08-F06**：组织timezone。
- **M08-F07**：LIVE/TEST。
- **M08-F08**：当前导航/标题/描述。
- **M08-F09**：revokedCount。
- **M08-F10**：无访问权限说明。

#### Layout (Desktop)

224px左栏，64px上下文头；组织切换顶左、账号顶右；56px页面标题行；门店日期作为适用页面的48px范围条；主体24px边距。

#### Layout (Tablet)

左栏收为72px rail，点击标签展开224px浮层；组织与账号留顶栏；筛选第二行。

#### Layout (Mobile)

56px顶栏显示组织+页名，底部64px总览/订单/设备/更多，权限不足动态调整；组织菜单全屏sheet；过滤器sheet展示已选摘要；TEST横幅固定在内容起点。

#### Components

Navigation / Select / DateRange / SegmentedControl / Popover / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M08-A01 · Primary**：组织切换。
- **M08-A02 · Secondary**：门店筛选。
- **M08-A03 · Secondary**：今天/近7天/本月/本年/自定义日期。
- **M08-A04 · Secondary**：应用范围。
- **M08-A05 · Secondary**：LIVE/TEST切换。
- **M08-A06 · Secondary**：13主导航。
- **M08-A07 · Secondary**：移动导航展开/关闭。
- **M08-A08 · Secondary**：重新验证身份。
- **M08-A09 · Secondary**：撤销其他会话并确认。
- **M08-A10 · Secondary**：退出。
- **M08-A11 · Secondary**：无权限回可访问首页。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

切组织先关闭浮层、取消旧请求、清空敏感数据和旧列表，再加载新组织；权限取服务端；财务日期不应伪装为设备列表有效筛选；无全局搜索API，只可新增本地页面命令入口。

#### States

无组织、多组织、只读、门店受限、日期无效、LIVE/TEST、DEMO、权限变化、会话失效。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：左栏收为72px rail，点击标签展开224px浮层；组织与账号留顶栏；筛选第二行。 Mobile：56px顶栏显示组织+页名，底部64px总览/订单/设备/更多，权限不足动态调整；组织菜单全屏sheet；过滤器sheet展示已选摘要；TEST横幅固定在内容起点。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“当前顶栏把所有筛选同样铺开，作用域不清晰，手机操作拥挤。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m09"></a>

### Page: M09 重新验证身份

**现有入口 / 来源**：`账号菜单/敏感操作 REAUTH_REQUIRED`；public/merchant.js:reauthModal,withReauth。**能力门控**：按服务端要求。

#### Purpose

在不中断原任务上下文的前提下确认操作者身份。

#### User Goal

用户能够围绕“密码与原敏感动作”完成验证身份，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：密码与原敏感动作。
- P1：验证结果。
- P2：会话解释。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M09-F01**：当前密码。
- **M09-F02**：敏感操作原因。
- **M09-F03**：validUntil。
- **M09-F04**：错误。

#### Layout (Desktop)

440pxDialog，保留原操作对象摘要，密码单字段，提交与取消右对齐。

#### Layout (Tablet)

440px居中Dialog，遮罩不允许穿透。

#### Layout (Mobile)

全宽Sheet，标题56px，密码48px，键盘出现保持按钮可见。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M09-A01 · Primary**：验证身份。
- **M09-A02 · Secondary**：取消。
- **M09-A03 · Secondary**：验证后续接原操作。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

验证通过显示到期时间并仅重试原操作一次；取消不能执行原操作；密码不记录，关闭清空。

#### States

当前密码错误、验证中、完成后继续原动作、取消、会话过期；不落盘敏感输入。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：440px居中Dialog，遮罩不允许穿透。 Mobile：全宽Sheet，标题56px，密码48px，键盘出现保持按钮可见。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“嵌套弹窗易丢原任务和焦点，需明确续接。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m10"></a>

### Page: M10 经营总览

**现有入口 / 来源**：`#/dashboard`；public/merchant.js:renderDashboardView,loadDashboardCards,loadDashboardTrend,loadDashboardAlerts,loadDashboardRecent。**能力门控**：按dashboard.read/costs.read。

#### Purpose

先知道当前是否需要处理问题，再看收入与利润变化。

#### User Goal

用户能够围绕“异常待办、实收/利润完整性”完成范围筛选，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：异常待办、实收/利润完整性。
- P1：趋势、设备与杯数。
- P2：最近订单与口径。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M10-F01**：设备总数/在线数/在线率。
- **M10-F02**：完成杯数。
- **M10-F03**：待处理告警数。
- **M10-F04**：实收receivedMinor。
- **M10-F05**：退款refundedMinor。
- **M10-F06**：净收款netCashMinor。
- **M10-F07**：营业净收入recognizedRevenueMinor。
- **M10-F08**：估算利润estimatedProfitMinor。
- **M10-F09**：completeness.status/missing。
- **M10-F10**：趋势date/receivedMinor/estimatedProfitMinor。
- **M10-F11**：告警severity/title/description与告警条数。
- **M10-F12**：最近订单id/orderNo/createdAt/storeNameSnapshot/deviceNameSnapshot/totalMinor/paymentStatus/productionStatus/environment。
- **M10-F13**：有限发布说明。

#### Layout (Desktop)

上方全宽状态摘要条；左侧8列为主经营数值+260px趋势，右4列为告警工作队列；第二段最近订单全宽，非四卡模板。利润缺项置于利润数字同层。

#### Layout (Tablet)

上下两个区域：趋势全宽，告警与资产摘要各半；最近订单简化列并可展开。

#### Layout (Mobile)

先告警摘要、再主指标2列文字栅格（无独立厚重卡片）、紧凑趋势、最近订单列表；最多两个一级行动。

#### Components

KPI / Chart / Alert / List / Table / Filter。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M10-A01 · Primary**：范围筛选。
- **M10-A02 · Secondary**：分区重试。
- **M10-A03 · Secondary**：打开最近订单详情。
- **M10-A04 · Secondary**：全部订单。
- **M10-A05 · Secondary**：权限适配的经营/运维视图。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

同筛选采用同一dashboard快照；无costs.read只显示资产与运维允许字段，服务端没有杯数则显示—；告警无处置API不提供关闭/已读承诺。

#### States

各分区独立Loading/Error；今日无订单；成本缺项；无成本权限；趋势部分为空；告警有/无；旧值过时。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

图表首次300ms淡入；后续刷新仅更新数据；金额直接更新+160ms短高亮；缺项不补动画；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：上下两个区域：趋势全宽，告警与资产摘要各半；最近订单简化列并可展开。 Mobile：先告警摘要、再主指标2列文字栅格（无独立厚重卡片）、紧凑趋势、最近订单列表；最多两个一级行动。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“四卡模板且角色指标可缺失；趋势与指标需说明现金流和确认收入差别。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m11"></a>

### Page: M11 我的设备列表

**现有入口 / 来源**：`#/devices`；public/merchant.js:renderDevicesView,loadDeviceList。**能力门控**：devices.read。

#### Purpose

快速找到某台属于本组织的设备，识别离线或停用。

#### User Goal

用户能够围绕“设备身份、连接、生命周期”完成搜索设备名称/ID/SN，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：设备身份、连接、生命周期。
- P1：门店、心跳/任务与告警。
- P2：版本/技术标识。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M11-F01**：查询q。
- **M11-F02**：生命周期筛选。
- **M11-F03**：门店storeId。
- **M11-F04**：id/deviceId。
- **M11-F05**：name。
- **M11-F06**：serialNumber。
- **M11-F07**：storeName。
- **M11-F08**：lifecycle。
- **M11-F09**：online/lastSeenAt。
- **M11-F10**：version/ownershipVersion。

#### Layout (Desktop)

工具栏一行，搜索320px+门店/状态；表格主列设备/连接/门店/生命周期/心跳，版本放行展开或详情，行高56px。

#### Layout (Tablet)

侧栏72px，表格只保留设备/状态/门店/最近联系；其余进入详情。

#### Layout (Mobile)

每行88–112px：名称ID、连接+生命周期、门店/最近联系；整行按钮进入全屏详情，搜索首屏可见。

#### Components

Search / Filter / Table / List / Drawer。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M11-A01 · Primary**：搜索设备名称/ID/SN。
- **M11-A02 · Secondary**：按生命周期/门店过滤。
- **M11-A03 · Secondary**：认领设备。
- **M11-A04 · Secondary**：打开设备详情。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

搜索含SN；空租户显示认领说明，零结果提供清筛选；查询状态与详情返回位置保留；不得从平台设备列表补数据。

#### States

无设备、筛选无匹配、设备在线/离线/首次未连接、PENDING_ACTIVATION/ACTIVE/SUSPENDED/ARCHIVED生命周期、只读、加载失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：侧栏72px，表格只保留设备/状态/门店/最近联系；其余进入详情。 Mobile：每行88–112px：名称ID、连接+生命周期、门店/最近联系；整行按钮进入全屏详情，搜索首屏可见。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“技术版本占表格宽度且手机详情与列表层级不清。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m12"></a>

### Page: M12 认领出厂设备

**现有入口 / 来源**：`设备列表认领弹窗`；public/merchant.js:openClaimModal。**能力门控**：devices.claim；需有效门店和认领码。

#### Purpose

将购买的设备正确绑定自己的组织和经营场所。

#### User Goal

用户能够围绕“认领码、门店与可选设备名”完成选择门店，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：认领码、门店与可选设备名。
- P1：认领结果/归属。
- P2：认领安全说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M12-F01**：claimCode。
- **M12-F02**：storeId。
- **M12-F03**：可选name。
- **M12-F04**：设备归属校验结果。
- **M12-F05**：错误/幂等冲突。
- **M12-F06**：平台归属与历史订单说明。

#### Layout (Desktop)

520pxDialog，认领码和门店纵向，说明置下方；不能把安装激活码当资产认领码。

#### Layout (Tablet)

最大520px居中，门店选择可搜索当前返回列表。

#### Layout (Mobile)

全屏Sheet，扫码输入只是可选新功能且不默认申请相机；默认粘贴码可用。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M12-A01 · Primary**：选择门店。
- **M12-A02 · Secondary**：输入资产认领码。
- **M12-A03 · Secondary**：认领。
- **M12-A04 · Secondary**：取消。
- **M12-A05 · Secondary**：无门店时引导创建门店。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

同次提交复用幂等键；冲突显示归属或码失效的服务端安全信息；成功刷新资产列表；不承诺已具备收款配置。

#### States

认领码错误/过期/已用、门店无效、归属冲突、成功、重新验证、限流。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大520px居中，门店选择可搜索当前返回列表。 Mobile：全屏Sheet，扫码输入只是可选新功能且不默认申请相机；默认粘贴码可用。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“认领与设备激活概念容易混淆，空门店缺少下一步。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m13"></a>

### Page: M13 商户设备详情

**现有入口 / 来源**：`设备列表 → Drawer`；public/merchant.js:openDeviceDrawer,paintDeviceDrawer,deviceActionsRow。**能力门控**：devices.read + allowedActions。

#### Purpose

聚合设备状态、任务、能力和物料，区分设备实时快照与库存账。

#### User Goal

用户能够围绕“设备身份、连接、任务、告警”完成编辑资料，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：设备身份、连接、任务、告警。
- P1：能力与物料状态。
- P2：版本/命令证据/完整ID。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M13-F01**：设备name/deviceId/serialNumber。
- **M13-F02**：storeName。
- **M13-F03**：lifecycle。
- **M13-F04**：online/lastSeenAt。
- **M13-F05**：ownershipVersion/version。
- **M13-F06**：currentJob.id/status/productName（若有）。
- **M13-F07**：capabilities.id/name/estimatedSeconds及真实recipeId/estimatedDurationSeconds兼容。
- **M13-F08**：inventory名称/单位/状态/onHandQuantity/reservedQuantity/availableQuantity。
- **M13-F09**：alerts.severity/title/description。
- **M13-F10**：allowedActions。
- **M13-F11**：命令结果区域id/status/resultMessage；PENDING/EXECUTING/SUCCEEDED/FAILED/TIMEOUT；查询超时/失败。

#### Layout (Desktop)

右侧640px Drawer或详情工作区，顶部对象标识与双状态，下面概览/能力物料/技术信息三个局部Tab；主要状态默认可见。

#### Layout (Tablet)

详情替换主内容，保留面包屑和回列表；两列kv降为单列。

#### Layout (Mobile)

全屏详情，返回保留搜索与滚动；物料逐项列表，技术详情展开；危险操作位于更多菜单。

#### Components

Drawer / Tabs / Status / DefinitionList / List / Menu。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M13-A01 · Primary**：编辑资料。
- **M13-A02 · Secondary**：生命周期变更。
- **M13-A03 · Secondary**：申请解绑。
- **M13-A04 · Secondary**：发起转让。
- **M13-A05 · Secondary**：允许的设备命令RELOAD_CONFIG/SYNC_CONFIG/CLEAN/RESTART_APP（各自确认）。
- **M13-A06 · Secondary**：关闭详情。
- **M13-A07 · Secondary**：失败重试。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

操作由permissions与allowedActions交集决定；库存无容量字段不能画百分比；真实投影与demo字段不同必须适配或标—；关闭停止命令轮询。命令初次查询约1800ms，其后2500ms、最多8次；PENDING/EXECUTING继续，终态停止，查询超时只说明未收到结果，不能判定设备失败。旧UI在请求发出前就写“已受理”，重设计应先显示“提交中”，拿到服务端id才显示“已受理”。

#### States

详情加载、设备离线、忙碌/工作中、任务缺失、能力/物料未上报与读取失败、告警、操作禁用。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：详情替换主内容，保留面包屑和回列表；两列kv降为单列。 Mobile：全屏详情，返回保留搜索与滚动；物料逐项列表，技术详情展开；危险操作位于更多菜单。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“现有物料条用0.12/0.35/1表示状态会被误读为容量；真实快照字段与demo形态并不完全一致。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m14"></a>

### Page: M14 编辑商户设备资料

**现有入口 / 来源**：`设备详情 → 编辑资料`；public/merchant.js:openDeviceEditModal。**能力门控**：devices.manage + RENAME/REASSIGN。

#### Purpose

修正设备名称与经营归属，避免覆盖并发修改。

#### User Goal

用户能够围绕“设备名称与门店”完成修改名称，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：设备名称与门店。
- P1：资料校验/保存结果。
- P2：并发版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M14-F01**：deviceId。
- **M14-F02**：name。
- **M14-F03**：storeId。
- **M14-F04**：version。
- **M14-F05**：归属说明。
- **M14-F06**：字段错误/409。

#### Layout (Desktop)

520pxDialog，名称单行、门店选择，版本移入技术说明。

#### Layout (Tablet)

480pxDialog；表单单列。

#### Layout (Mobile)

Sheet，44px以上保存取消；返回前提示未保存更改（新增本地保护）。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M14-A01 · Primary**：修改名称。
- **M14-A02 · Secondary**：重新分配门店。
- **M14-A03 · Secondary**：保存。
- **M14-A04 · Secondary**：取消。
- **M14-A05 · Secondary**：冲突重新加载。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

PATCH携带version，409保留草稿并提供重新加载对照；不能自动覆盖或默默改租户。

#### States

未修改、保存中、必填错误、版本409、门店无权、已保存、未保存退出。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：480pxDialog；表单单列。 Mobile：Sheet，44px以上保存取消；返回前提示未保存更改（新增本地保护）。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“版本冲突解释与用户草稿恢复需要更清楚。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m15"></a>

### Page: M15 商户设备生命周期

**现有入口 / 来源**：`设备详情 → 生命周期变更`；public/merchant.js:openLifecycleModal。**能力门控**：devices.manage + allowedActions。

#### Purpose

安全暂停、恢复或归档设备，同时保留历史经营记录。

#### User Goal

用户能够围绕“当前/目标状态与原因”完成选择动作，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：当前/目标状态与原因。
- P1：后果与确认。
- P2：版本/权限解释。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M15-F01**：设备对象。
- **M15-F02**：目标action=SUSPEND/RESUME/ARCHIVE（按允许项）。
- **M15-F03**：reason。
- **M15-F04**：version。
- **M15-F05**：归档影响。
- **M15-F06**：确认文字。

#### Layout (Desktop)

520px确认表单，目标与后果并排说明，归档用独立危险区域。

#### Layout (Tablet)

单列Dialog，原因textarea最小96px。

#### Layout (Mobile)

全屏Sheet；后果说明在提交按钮上方，不用手势执行归档。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M15-A01 · Primary**：选择动作。
- **M15-A02 · Secondary**：填写原因。
- **M15-A03 · Secondary**：确认提交。
- **M15-A04 · Secondary**：归档二次输入“归档”。
- **M15-A05 · Secondary**：需要时重新验证。
- **M15-A06 · Secondary**：取消/冲突重载。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

原因必填；只列后端允许动作；归档通常先停用；操作成功以服务端响应为准；409显示阻断条件。

#### States

PENDING_ACTIVATION/ACTIVE/SUSPENDED/ARCHIVED、操作SUSPEND/RESUME/ARCHIVE不允许、原因空、重新验证、请求中、完成、冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列Dialog，原因textarea最小96px。 Mobile：全屏Sheet；后果说明在提交按钮上方，不用手势执行归档。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“技术枚举与普通保存同级，危险操作需要明确后果。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m16"></a>

### Page: M16 申请设备解绑

**现有入口 / 来源**：`设备详情 → 申请解绑`；public/merchant.js:openUnbindModal。**能力门控**：有限发布关闭：devices.transfer。

#### Purpose

记录解绑请求，而不是直接解除设备归属。

#### User Goal

用户能够围绕“对象、原因、解绑条件”完成填写原因，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：对象、原因、解绑条件。
- P1：受理状态/确认。
- P2：归属版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M16-F01**：设备标识/名称。
- **M16-F02**：reason。
- **M16-F03**：ownershipVersion。
- **M16-F04**：请求status。
- **M16-F05**：阻断原因。

#### Layout (Desktop)

480pxDialog，对象摘要+审核运营说明+原因96px。

#### Layout (Tablet)

同Dialog，最大屏宽减48px。

#### Layout (Mobile)

Sheet底部“提交申请”，不用“删除设备”。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M16-A01 · Primary**：填写原因。
- **M16-A02 · Secondary**：提交解绑申请。
- **M16-A03 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

请求状态按后端真实结果展示；已发申请不等于完成解绑；关闭能力仅解释不可用。

#### States

能力关闭、解绑原因空、当前有任务/归属冲突、重新验证、已受理/拒绝、结果未知。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：同Dialog，最大屏宽减48px。 Mobile：Sheet底部“提交申请”，不用“删除设备”。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“申请与最终资产转移容易混淆；当前入口按权限关闭。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m17"></a>

### Page: M17 发起设备转让

**现有入口 / 来源**：`设备详情 → 发起转让`；public/merchant.js:openTransferRequestModal。**能力门控**：有限发布关闭：devices.transfer。

#### Purpose

把设备转让到指定组织并让双方理解阻断条件。

#### User Goal

用户能够围绕“源设备与目标组织”完成填目标组织标识，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：源设备与目标组织。
- P1：原因/转移结果。
- P2：归属版本/审计。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M17-F01**：设备标识/名称。
- **M17-F02**：targetTenantReference。
- **M17-F03**：reason。
- **M17-F04**：ownershipVersion。
- **M17-F05**：result.status。
- **M17-F06**：blockingReasons。

#### Layout (Desktop)

560pxDialog，上方来源→目标关系示意（文字节点），下方目标/原因，阻断列表不折叠。

#### Layout (Tablet)

单列560px，组织长标识折行。

#### Layout (Mobile)

全屏Sheet，目标标识可复制粘贴，确认前显示完整对象。

#### Components

Form / Button / Alert / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M17-A01 · Primary**：填目标组织标识。
- **M17-A02 · Secondary**：填原因。
- **M17-A03 · Secondary**：提交转让。
- **M17-A04 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

幂等键、归属版本与阻断校验保留；不通过前端伪造审批完成；不新增猜测租户搜索API。

#### States

能力关闭、目标组织不匹配、当前有任务、重新验证、转让待接收/冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列560px，组织长标识折行。 Mobile：全屏Sheet，目标标识可复制粘贴，确认前显示完整对象。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“当前目标是技术标识，需显著确认对象，防错转。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m18"></a>

### Page: M18 设备转让记录

**现有入口 / 来源**：`#/transfers`；public/merchant.js:renderTransfersView,loadTransfers,transferAction。**能力门控**：有限发布关闭：devices.transfer。

#### Purpose

跟踪转出转入申请的阶段及需要谁处理。

#### User Goal

用户能够围绕“设备、双方组织、状态”完成刷新，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：设备、双方组织、状态。
- P1：时间与可执行动作。
- P2：转让ID/版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M18-F01**：设备deviceName/deviceId。
- **M18-F02**：createdAt。
- **M18-F03**：reason。
- **M18-F04**：direction(IN/OUT)。
- **M18-F05**：counterpartName。
- **M18-F06**：status。
- **M18-F07**：blockingReasons。
- **M18-F08**：version。

#### Layout (Desktop)

列表按状态与方向展示，设备/对方/当前阶段/下一步四列；原因和阻断在行展开。

#### Layout (Tablet)

六列表转四列；阻断摘要常显。

#### Layout (Mobile)

时间顺序列表，方向用箭头+文字；详情Sheet含完整原因与版本；一个主动作。

#### Components

Table / Status / Timeline / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M18-A01 · Primary**：刷新。
- **M18-A02 · Secondary**：确认接收（转入待接收）。
- **M18-A03 · Secondary**：取消（允许状态）。
- **M18-A04 · Secondary**：确认弹窗。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

状态包含PENDING_RECIPIENT/PENDING_PLATFORM/COMPLETED/BLOCKED/CANCELLED/REJECTED；不为未实现平台审批添加可用按钮。

#### States

无转让、待接受、完成、取消/拒绝/过期等服务端状态、accept/cancel权限不足、版本冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：六列表转四列；阻断摘要常显。 Mobile：时间顺序列表，方向用箭头+文字；详情Sheet含完整原因与版本；一个主动作。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“复杂阶段目前仅徽标展示，责任方和阻断原因不易扫描。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m19"></a>

### Page: M19 门店列表与门店编辑

**现有入口 / 来源**：`#/stores`；public/merchant.js:renderStoresView,loadStores,openStoreModal。**能力门控**：stores.read；写入需stores.manage。

#### Purpose

管理设备的经营地点，保持历史门店归属。

#### User Goal

用户能够围绕“门店名称/地址/状态”完成新增门店，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：门店名称/地址/状态。
- P1：设备数量与归档限制。
- P2：门店ID/版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M19-F01**：store.id/name/address/status/deviceCount/version。
- **M19-F02**：编辑名称/地址。
- **M19-F03**：ACTIVE/ARCHIVED。
- **M19-F04**：归档不可直接恢复说明。

#### Layout (Desktop)

列表占主区，名称地址合并第一列，设备数右对齐；编辑520pxDrawer，地址textarea96px。

#### Layout (Tablet)

三列列表，编辑居中520px表单。

#### Layout (Mobile)

门店紧凑列表+全屏编辑Sheet；归档放危险操作区。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M19-A01 · Primary**：新增门店。
- **M19-A02 · Secondary**：编辑。
- **M19-A03 · Secondary**：归档并确认。
- **M19-A04 · Secondary**：保存。
- **M19-A05 · Secondary**：取消。
- **M19-A06 · Secondary**：冲突重载。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

归档单独确认，设备关联冲突按后端返回显示；不添加无接口的删除/恢复按钮。

#### States

无门店、只读、必填错误、地址未填、保存中、归档与设备关联约束、版本冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：三列列表，编辑居中520px表单。 Mobile：门店紧凑列表+全屏编辑Sheet；归档放危险操作区。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“门店归档藏在状态Select里，容易被当普通字段保存。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m20"></a>

### Page: M20 商品当前价与计划价

**现有入口 / 来源**：`#/prices`；public/merchant.js:renderPricesView,loadPrices,openPriceModal。**能力门控**：prices.read/manage。

#### Purpose

明确哪一范围的新订单使用哪一个价格。

#### User Goal

用户能够围绕“产品、当前价、计划价/生效时间”完成筛选门店/设备，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：产品、当前价、计划价/生效时间。
- P1：状态与保存/取消编辑。
- P2：SKU/作用范围与价格记录版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M20-F01**：门店筛选storeId。
- **M20-F02**：设备筛选deviceId。
- **M20-F03**：name/sku。
- **M20-F04**：scope(组织/门店/设备)。
- **M20-F05**：priceMinor。
- **M20-F06**：effectiveAt。
- **M20-F07**：version。
- **M20-F08**：当前价/计划生效状态。
- **M20-F09**：新增SKU/name/storeId/deviceId/priceMinor/effectiveAt。

#### Layout (Desktop)

标题行下为范围工具栏；表格商品/范围/当前或计划/金额/生效时间；新增560pxDialog，范围单选引导后映射原字段。

#### Layout (Tablet)

保留商品/范围/价格/时间，版本入详情；编辑表单一列。

#### Layout (Mobile)

价格条目首行名称与价格，次行范围和时间；编辑Sheet内设备范围优先级说明常显。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M20-A01 · Primary**：筛选门店/设备。
- **M20-A02 · Secondary**：新增价格。
- **M20-A03 · Secondary**：立即或计划生效。
- **M20-A04 · Secondary**：保存。
- **M20-A05 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

金额元输入精确转分；空生效时间为立即；设备优先门店；历史订单价格固定；datetime-local需标明输入时区与转换结果。

#### States

无可定价产品、当前价缺失、计划待生效/已生效、金额非整数分、时间无效、版本冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：保留商品/范围/价格/时间，版本入详情；编辑表单一列。 Mobile：价格条目首行名称与价格，次行范围和时间；编辑Sheet内设备范围优先级说明常显。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“当前/计划价格的作用对象不突出，日期选择易误解时区。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m21"></a>

### Page: M21 商户订单列表

**现有入口 / 来源**：`#/orders`；public/merchant.js:renderOrdersView,loadOrdersPage,reloadOrderListOnly。**能力门控**：orders.read。

#### Purpose

按订单识别支付、制作和退款进度。

#### User Goal

用户能够围绕“订单标识、金额、支付/制作状态”完成查询，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：订单标识、金额、支付/制作状态。
- P1：设备门店、时间、环境。
- P2：成本/技术标识在详情。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M21-F01**：状态筛选全部/PAID/PENDING/REFUNDING/REFUNDED/PARTIALLY_REFUNDED/QUEUED/MAKING/HOLD/DELIVERED/FAILED/CANCELLED。
- **M21-F02**：deviceId筛选。
- **M21-F03**：全局日期/门店/LIVE或TEST。
- **M21-F04**：id/orderNo/createdAt。
- **M21-F05**：storeNameSnapshot/deviceNameSnapshot/deviceId。
- **M21-F06**：items.name/quantity。
- **M21-F07**：totalMinor。
- **M21-F08**：paymentStatus。
- **M21-F09**：productionStatus。
- **M21-F10**：environment。
- **M21-F11**：nextCursor。

#### Layout (Desktop)

一行筛选条+已选chips；表格订单时间、地点设备、商品、金额、支付、制作、环境；首列sticky，行高56–64px；不新增未经API支持的全库搜索。

#### Layout (Tablet)

隐藏非首要列到展开，仍显订单/金额/双状态；工具栏可折两行。

#### Layout (Mobile)

列表主行订单号+金额，次行商品、双状态与时间；筛选Sheet；详情全屏；加载更多44px。

#### Components

Filter / Table / List / Drawer / Pagination。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M21-A01 · Primary**：查询。
- **M21-A02 · Secondary**：更改筛选。
- **M21-A03 · Secondary**：加载更多。
- **M21-A04 · Secondary**：打开详情。
- **M21-A05 · Secondary**：从总览直达订单。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

状态别名DELIVERED→READY、PENDING→AWAITING_PAYMENT保留；游标分页不用假总页数；双状态独立，加载更多期间不清空已有数据。

#### States

无订单、无匹配、LIVE/TEST、筛选中、返回范围受限、部分字段受权限屏蔽、查询失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：隐藏非首要列到展开，仍显订单/金额/双状态；工具栏可折两行。 Mobile：列表主行订单号+金额，次行商品、双状态与时间；筛选Sheet；详情全屏；加载更多44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“并列状态多且技术枚举影响扫读；分页与详情返回需要保存上下文。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m22"></a>

### Page: M22 商户订单详情

**现有入口 / 来源**：`订单列表/总览 → 订单详情`；public/merchant.js:openOrderDrawer,paintOrderDrawer。**能力门控**：orders.read；退款另需权限。

#### Purpose

把一笔订单的商品、钱款与制作事实连接起来。

#### User Goal

用户能够围绕“金额、支付、制作、退款事实”完成查看商品/支付退款/成本/时间线，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：金额、支付、制作、退款事实。
- P1：商品、时间线、设备/门店。
- P2：成本口径、失败与技术证据。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M22-F01**：orderNo/id。
- **M22-F02**：门店/设备快照。
- **M22-F03**：paymentStatus/productionStatus/environment。
- **M22-F04**：createdAt/paidAt/deliveredAt。
- **M22-F05**：totalMinor/receivedMinor/refundedMinor。
- **M22-F06**：items.name/quantity/unitPriceMinor。
- **M22-F07**：payments.provider/accountLabel/environment/status/amountMinor。
- **M22-F08**：refunds.status/reason/amountMinor。
- **M22-F09**：costSummary.materialCostMinor/status。
- **M22-F10**：timeline.createdAt或at/description或label/status。
- **M22-F11**：allowedActions。

#### Layout (Desktop)

640pxDrawer，顶部订单+双状态；下方金额三列；商品、支付退款、时间线纵向；技术ID可展开；底部退款为次级危险按钮。

#### Layout (Tablet)

内容页模式，主信息2列，时间线全宽。

#### Layout (Mobile)

全屏详情，主状态+商品金额先显示；支付流水/成本详情折叠；时间线可直接进入；返回列表保留位置。

#### Components

Drawer / DefinitionList / Timeline / Status / List。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M22-A01 · Primary**：查看商品/支付退款/成本/时间线。
- **M22-A02 · Secondary**：发起退款（REFUND允许时）。
- **M22-A03 · Secondary**：关闭。
- **M22-A04 · Secondary**：失败重试。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

商品显示单价×数量，不能把单价当行合计；退款申请/处理中与已成功分开；未知成本为待补全而非0；保留所有历史快照。

#### States

详情失败、支付与制作分离、HOLD/退款中/部分退款、成本缺项、退款不可用、旧快照。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：内容页模式，主信息2列，时间线全宽。 Mobile：全屏详情，主状态+商品金额先显示；支付流水/成本详情折叠；时间线可直接进入；返回列表保留位置。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“资金流、制作状态和成本目前堆叠，重点与历史细节缺少层级。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m23"></a>

### Page: M23 部分或全额退款

**现有入口 / 来源**：`订单详情 → 发起退款`；public/merchant.js:openRefundModal,withReauth。**能力门控**：refunds.manage + allowedActions含REFUND。

#### Purpose

在确认支付事实和可退上限后发起可追溯退款。

#### User Goal

用户能够围绕“可退余额、本次金额、原因”完成填写退款金额/原因，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：可退余额、本次金额、原因。
- P1：原单/已退/处理状态。
- P2：幂等与交易证据。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M23-F01**：订单号。
- **M23-F02**：订单总额。
- **M23-F03**：实收。
- **M23-F04**：已退。
- **M23-F05**：可退上限。
- **M23-F06**：amountMinor元输入。
- **M23-F07**：reason。
- **M23-F08**：请求状态。
- **M23-F09**：字段错误。
- **M23-F10**：REAUTH_REQUIRED。

#### Layout (Desktop)

520pxDialog，顶部三项金额摘要，退款金额大号输入，原因其次，底部提交标注为申请。

#### Layout (Tablet)

单列Dialog，金额摘要保持三项但允许换行。

#### Layout (Mobile)

全屏Sheet，确认前显示订单号与金额，禁止滑动直接退款。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M23-A01 · Primary**：填写退款金额/原因。
- **M23-A02 · Secondary**：取消。
- **M23-A03 · Secondary**：确认退款。
- **M23-A04 · Secondary**：重新验证。
- **M23-A05 · Secondary**：提交后查看退款记录。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

金额须正整数分且不超过上限；金额字段不合法/缺失时阻止提交；保留幂等键与后端校验；请求受理不能直接写“退款成功”。

#### States

金额超限/为零、原因空、重新验证、已受理/PROCESSING、成功/失败/未知、重复请求、可退余额变化。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列Dialog，金额摘要保持三项但允许换行。 Mobile：全屏Sheet，确认前显示订单号与金额，禁止滑动直接退款。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“错误金额与未知上限可能误导，主操作文案需反映异步处理。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m24"></a>

### Page: M24 物料档案与新增物料

**现有入口 / 来源**：`#/materials → materials tab`；public/merchant.js:renderMaterialsView,renderMaterialsTab,openMaterialModal。**能力门控**：读取inventory.read；新增costs.manage；成本列costs.read。

#### Purpose

建立采购和库存使用的一致单位档案。

#### User Goal

用户能够围绕“物料名称、单位、精度、状态”完成物料/采购/库存/出入库四Tab切换，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：物料名称、单位、精度、状态。
- P1：新增必填与结果。
- P2：内部ID/时间。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M24-F01**：物料id/name。
- **M24-F02**：unit。
- **M24-F03**：unitPrecision。
- **M24-F04**：averageUnitCostMinor。
- **M24-F05**：status。
- **M24-F06**：新增名称/单位/数量小数位。

#### Layout (Desktop)

四Tab置于成本工作区顶部，档案表物料/单位/精度/成本/状态；新增440pxDialog。

#### Layout (Tablet)

Tab等宽且44px，表格数值右对齐。

#### Layout (Mobile)

Tab可横向滚动但当前项可见；物料列表两行；新增Sheet。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M24-A01 · Primary**：物料/采购/库存/出入库四Tab切换。
- **M24-A02 · Secondary**：新增物料。
- **M24-A03 · Secondary**：保存。
- **M24-A04 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

无costs.read不显示成本值；精度影响数量输入；没有编辑/停用API时不新增可用编辑动作。

#### States

无物料、单位未填、数量精度错误、非启用状态只读、新建失败、成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：Tab等宽且44px，表格数值右对齐。 Mobile：Tab可横向滚动但当前项可见；物料列表两行；新增Sheet。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“物料状态是只读事实，不能把标签误设计成可切换按钮。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m25"></a>

### Page: M25 采购列表、草稿编辑与入账

**现有入口 / 来源**：`#/materials → purchases tab`；public/merchant.js:renderPurchasesTab,loadPurchases,openPurchaseModal,postPurchaseFlow。**能力门控**：读取costs.read；写入/入账costs.manage。

#### Purpose

先核对采购明细，再把成本与库存记入账。

#### User Goal

用户能够围绕“供应/门店、明细数量与行总成本、合计”完成新增采购，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：供应/门店、明细数量与行总成本、合计。
- P1：草稿/入账状态与时间。
- P2：采购ID/版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M25-F01**：采购id/supplier/purchasedOn/storeId/note/status/version。
- **M25-F02**：lines.materialId/materialName/quantity/unit/totalCostMinor。
- **M25-F03**：已知合计/缺项标志。
- **M25-F04**：门店与日期筛选。

#### Layout (Desktop)

列表供应商日期/门店/明细摘要/总额/状态/操作；草稿编辑用800px宽Dialog或专页，表头信息两列+行项目表；合计sticky但不遮挡。

#### Layout (Tablet)

草稿全宽工作页，表头两列转一列，明细每项独立行组。

#### Layout (Mobile)

全屏编辑，物料/数量/金额一组，删行显式44px按钮；底部固定保存并留安全区。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M25-A01 · Primary**：新增采购。
- **M25-A02 · Secondary**：编辑DRAFT。
- **M25-A03 · Secondary**：添加/删除草稿明细行。
- **M25-A04 · Secondary**：保存草稿。
- **M25-A05 · Secondary**：POSTED只读。
- **M25-A06 · Secondary**：入账并确认。
- **M25-A07 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

草稿可编辑，入账确认后只读；至少一条完整明细；缺项合计写“已知小计，待补全”；采购数量遵守物料精度，金额精确转分；版本冲突不覆盖。

#### States

DRAFT/POSTED/其他、零明细、数量/行总成本错误、重复入账、重新验证/冲突、部分供应信息缺失。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：草稿全宽工作页，表头两列转一列，明细每项独立行组。 Mobile：全屏编辑，物料/数量/金额一组，删行显式44px按钮；底部固定保存并留安全区。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“多行编辑和不可逆入账混在列表动作，缺项小计容易被读作总额。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m26"></a>

### Page: M26 账面库存

**现有入口 / 来源**：`#/materials → inventory tab`；public/merchant.js:renderInventoryTab,loadInventory。**能力门控**：inventory.read。

#### Purpose

了解已记账的库存与占用，避免把账面数当传感器余量。

#### User Goal

用户能够围绕“物料、库位、数量/单位”完成筛选门店，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：物料、库位、数量/单位。
- P1：预留/可用与成本状态。
- P2：版本/更新时间。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M26-F01**：门店筛选。
- **M26-F02**：物料name/unit。
- **M26-F03**：deviceName/deviceId。
- **M26-F04**：onHandQuantity。
- **M26-F05**：reservedQuantity。
- **M26-F06**：availableQuantity。
- **M26-F07**：costStatus。

#### Layout (Desktop)

表格主列物料、设备、在存、占用、可用、成本状态；标题旁常显“账面库存”。

#### Layout (Tablet)

单位附在列头和详情，保留三类数量。

#### Layout (Mobile)

每条库存三数并列标注，不只显示可用量；详情展开设备完整ID。

#### Components

Table / List / Select / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M26-A01 · Primary**：筛选门店。
- **M26-A02 · Secondary**：加载/重试库存。
- **M26-A03 · Secondary**：切换物料相关Tab。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

明确非实时传感器数据；未知量显示—；成本缺失不能显示正常；不增容量百分比或自动耗料承诺。

#### States

无账面记录、零库存、负数或异常库存、成本未知、成本缺项、无查看权限。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单位附在列头和详情，保留三类数量。 Mobile：每条库存三数并列标注，不只显示可用量；详情展开设备完整ID。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“与设备详情的实时物料快照名称相近，需要源头和单位区分。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m27"></a>

### Page: M27 出入库流水与登记

**现有入口 / 来源**：`#/materials → movements tab`；public/merchant.js:renderMovementsTab,loadMovements,openMovementModal。**能力门控**：inventory.read/manage。

#### Purpose

可追溯地记录补货、损耗、盘点差额及调拨。

#### User Goal

用户能够围绕“物料、方向/类型、数量、原因”完成类型过滤，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：物料、方向/类型、数量、原因。
- P1：来源目标/设备/时间。
- P2：关联单据与流水ID。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M27-F01**：类型RESTOCK/WASTE/ADJUSTMENT/TRANSFER。
- **M27-F02**：createdAt。
- **M27-F03**：materialId/materialName。
- **M27-F04**：eventId。
- **M27-F05**：quantity/unit。
- **M27-F06**：sourceStore/Device。
- **M27-F07**：targetStore/Device。
- **M27-F08**：reason。
- **M27-F09**：新增类型/物料/数量/原因/来源门店设备/目标门店设备。

#### Layout (Desktop)

流水表时间/类型/物料/有符号数量/来源→目标/原因；录入640pxDialog，动态字段在数量下。

#### Layout (Tablet)

录入改两阶段视觉分区但同一次提交：事件定义、来源目标。

#### Layout (Mobile)

全屏Sheet，动态字段原位展开；确认区完整复述加减方向。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M27-A01 · Primary**：类型过滤。
- **M27-A02 · Secondary**：新增出入库。
- **M27-A03 · Secondary**：按类型切换来源目标字段。
- **M27-A04 · Secondary**：确认语义。
- **M27-A05 · Secondary**：提交。
- **M27-A06 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

RESTOCK仅目标；WASTE/ADJUSTMENT仅来源；TRANSFER两者；盘点允许负差额，其余数量为正；保留eventId/幂等，不能乐观改库存。

#### States

无流水、入出库类型不同、数量/来源目标不合法、提交中、服务端约束、完成、权限不足。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：录入改两阶段视觉分区但同一次提交：事件定义、来源目标。 Mobile：全屏Sheet，动态字段原位展开；确认区完整复述加减方向。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“数量符号、调拨方向容易误读，动态字段和确认摘要必须联动。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m28"></a>

### Page: M28 运营费用、入账与冲正

**现有入口 / 来源**：`#/expenses`；public/merchant.js:renderExpensesView,loadExpenses,openExpenseModal,postExpenseFlow,reverseExpenseFlow。**能力门控**：costs.read/manage。

#### Purpose

让成本按正确账期计入经营结果，同时保持更正痕迹。

#### User Goal

用户能够围绕“费用类别、金额、归属期间/门店”完成新增费用，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：费用类别、金额、归属期间/门店。
- P1：入账/冲正与分摊。
- P2：关联ID/原因/版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M28-F01**：id/category(RENT/LABOR/UTILITIES/MAINTENANCE/OTHER)。
- **M28-F02**：amountMinor。
- **M28-F03**：storeId/deviceId。
- **M28-F04**：occurredOn。
- **M28-F05**：allocationMethod(DAILY_EQUAL/一次性)。
- **M28-F06**：allocationStart/allocationEnd。
- **M28-F07**：分摊天数/近似每日金额。
- **M28-F08**：note。
- **M28-F09**：status(DRAFT/POSTED/REVERSED)。
- **M28-F10**：version。
- **M28-F11**：冲正reason。
- **M28-F12**：门店/日期过滤。

#### Layout (Desktop)

主表类别/金额/归属/日期/分摊/状态；新增640px表单分金额归属和分摊两区，底部预览；冲正独立480pxDialog。

#### Layout (Tablet)

表单一列，分摊日期并排；列表次要分摊细节展开。

#### Layout (Mobile)

费用条目先金额类别，再归属账期；编辑全屏，DAILY_EQUAL才展开日期与预览；冲正必须再次确认。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M28-A01 · Primary**：新增费用。
- **M28-A02 · Secondary**：选择归属。
- **M28-A03 · Secondary**：选择分摊方式/日期。
- **M28-A04 · Secondary**：保存草稿。
- **M28-A05 · Secondary**：入账确认。
- **M28-A06 · Secondary**：已入账冲正及填原因。
- **M28-A07 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

含首尾日期的预览只是估算，最终分摊以服务端舍入规则为准；冲正生成反向事实不删除原记录；草稿与已入账动作不同。

#### States

DRAFT/POSTED/REVERSED/其他、金额/归属日期错误、未知成本分摊、已冲正、只读、请求失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：表单一列，分摊日期并排；列表次要分摊细节展开。 Mobile：费用条目先金额类别，再归属账期；编辑全屏，DAILY_EQUAL才展开日期与预览；冲正必须再次确认。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“缺少直观账期预览且冲正易被误认为删除。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m29"></a>

### Page: M29 日/月/年经营报表

**现有入口 / 来源**：`#/reports`；public/merchant.js:renderReportsView,fetchReport,exportReportCsv; app/merchant/reports.py:operating,csv。**能力门控**：reports.read/export。

#### Purpose

回答某账期收了多少钱、挣了多少钱、缺哪些成本。

#### User Goal

用户能够围绕“期间、净收款、利润及完整性”完成切日/月/年，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：期间、净收款、利润及完整性。
- P1：收入/各成本/合计/趋势。
- P2：完整分项、CSV字段与口径。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M29-F01**：period.from/to/timezone。
- **M29-F02**：grain(DAY/MONTH/YEAR)。
- **M29-F03**：storeId。
- **M29-F04**：environment。
- **M29-F05**：图表metric(netCashMinor/recognizedRevenueMinor/materialCostMinor/estimatedProfitMinor)。
- **M29-F06**：每期period。
- **M29-F07**：receivedMinor。
- **M29-F08**：refundedMinor。
- **M29-F09**：netCashMinor。
- **M29-F10**：recognizedRevenueMinor。
- **M29-F11**：materialCostMinor。
- **M29-F12**：wasteCostMinor。
- **M29-F13**：paymentFeeMinor。
- **M29-F14**：operatingExpenseMinor。
- **M29-F15**：estimatedProfitMinor。
- **M29-F16**：deliveredCupCount。
- **M29-F17**：completeness.status/missing。
- **M29-F18**：totals同名字段。
- **M29-F19**：CSV独有paidOrderCount/grossProfitMinor。
- **M29-F20**：notes。
- **M29-F21**：导出filename。

#### Layout (Desktop)

全宽标题+范围条；第一带为现金流文字指标，第二带成本利润分解；图表280px；明细横向可滚表，sticky期间/合计；口径侧边说明可展开。

#### Layout (Tablet)

图表全宽，财务摘要2列；宽表只在自身区域滚动，保留清晰单位。

#### Layout (Mobile)

现金/收入/成本/利润四组可展开；时期列表主显示净收款、利润及完整性，Sheet展开所有分项；CSV入口44px。

#### Components

DateRange / SegmentedControl / Chart / Table / DefinitionList / Download。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M29-A01 · Primary**：切日/月/年。
- **M29-A02 · Secondary**：切图表指标。
- **M29-A03 · Secondary**：门店日期环境筛选。
- **M29-A04 · Secondary**：展开口径说明。
- **M29-A05 · Secondary**：查看全部明细和合计。
- **M29-A06 · Secondary**：导出CSV。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

UI分→元统一格式，CSV仍按现有表头以分导出且有环境时区；不能把数字直接String导致金额差100倍；grossProfit/paidOrderCount虽CSV已存在，新详情给同名字段；结束日UI含当日/API排除次日；无全库排序接口不能伪装完整排序。

#### States

空期间、无成本权限、部分期间缺项、totals未知、CSV导出中/失败、零值/负利润、日期错误。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

图表首次300ms淡入；后续刷新仅更新数据；金额直接更新+160ms短高亮；缺项不补动画；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：图表全宽，财务摘要2列；宽表只在自身区域滚动，保留清晰单位。 Mobile：现金/收入/成本/利润四组可展开；时期列表主显示净收款、利润及完整性，Sheet展开所有分项；CSV入口44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“当前汇总把number直接String，存在分/元显示不一致风险；多次取报表可能时点不一致；缺项不能画0。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m30"></a>

### Page: M30 成员权限与编辑

**现有入口 / 来源**：`#/members → 成员`；public/merchant.js:renderMembersView,loadMembers,openMemberModal,storeScopeEditor。**能力门控**：members.read/manage。

#### Purpose

让每位运营人员只接触其职责和门店。

#### User Goal

用户能够围绕“成员身份、角色、状态”完成编辑角色，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：成员身份、角色、状态。
- P1：门店范围与编辑。
- P2：ID/版本/OWNER保护说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M30-F01**：member.id/displayName/username/email。
- **M30-F02**：role(OWNER/OPERATOR/FINANCE)。
- **M30-F03**：storeScope.mode/storeIds。
- **M30-F04**：status(ACTIVE/SUSPENDED)。
- **M30-F05**：version。
- **M30-F06**：末位OWNER保护说明。

#### Layout (Desktop)

表格姓名账号/角色/门店范围/状态；编辑560pxDialog分角色能力与门店范围，OWNER后果说明常显。

#### Layout (Tablet)

一列权限编辑，门店选择两列网格。

#### Layout (Mobile)

成员列表两行；权限全屏表单；已选门店数量与名称可展开查看。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M30-A01 · Primary**：编辑角色。
- **M30-A02 · Secondary**：启停成员。
- **M30-A03 · Secondary**：ALL/SELECTED门店范围与多选。
- **M30-A04 · Secondary**：保存。
- **M30-A05 · Secondary**：取消。
- **M30-A06 · Secondary**：409冲突重载。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

不可停用最后OWNER由服务端校验；当前用户权限变更需重新获取会话；门店SELECTED不为空；不使用前端角色推导越权。

#### States

成员空、只读、OWNER/OPERATOR/FINANCE、门店范围受限、最后OWNER保护、版本冲突、权限变更成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：一列权限编辑，门店选择两列网格。 Mobile：成员列表两行；权限全屏表单；已选门店数量与名称可展开查看。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“门店范围目前只显示数量，审核时应能展开具体名称。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m31"></a>

### Page: M31 邀请列表、创建与撤销

**现有入口 / 来源**：`#/members → 邀请`；public/merchant.js:loadInvitations,openInviteModal,revokeInvitationFlow,storeScopeEditor。**能力门控**：邮件发送当前关闭；既有列表按权限。

#### Purpose

知道谁被邀请、有没有送达、什么时候失效。

#### User Goal

用户能够围绕“邀请邮箱、角色/范围、状态”完成查看邀请，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：邀请邮箱、角色/范围、状态。
- P1：有效期与撤销。
- P2：邀请ID/结果证据。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M31-F01**：invitation.id/email/role/storeScope.mode/storeIds/status。
- **M31-F02**：deliveryStatus(QUEUED/UNAVAILABLE等)。
- **M31-F03**：expiresAt。
- **M31-F04**：创建邮箱/角色/门店范围。

#### Layout (Desktop)

成员页局部Tab，表格账号/权限范围/邀请状态/投递状态/过期；新邀请520pxDialog。

#### Layout (Tablet)

保留邀请状态与投递状态两列；完整权限入详情。

#### Layout (Mobile)

每项三行，投递与接受分别文字标识；创建Sheet。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M31-A01 · Primary**：查看邀请。
- **M31-A02 · Secondary**：创建邀请（开放时）。
- **M31-A03 · Secondary**：撤销PENDING并确认。
- **M31-A04 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

QUEUED只代表进入队列，不能写已送达；邮件关闭给说明，仍保留历史邀请与撤销能力；不虚构重发API。

#### States

邮件关闭、pending/accepted/revoked/expired服务端对应枚举、发送失败、接受链接缺失、撤销冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：保留邀请状态与投递状态两列；完整权限入详情。 Mobile：每项三行，投递与接受分别文字标识；创建Sheet。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“邀请状态与邮件送达常被混淆，范围需可检查。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m32"></a>

### Page: M32 收款账户与配置校验

**现有入口 / 来源**：`#/accounts`；public/merchant.js:renderAccountsView,loadAccounts,openAccountModal,validateAccountFlow,setDefaultAccountFlow,disableAccountFlow。**能力门控**：payments.read开放；payments.manage有限发布关闭。

#### Purpose

明确新支付使用哪个账户，历史退款沿哪个账户处理。

#### User Goal

用户能够围绕“账户名称、渠道/环境、状态/默认”完成查看脱敏账户，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：账户名称、渠道/环境、状态/默认。
- P1：配置与校验结果。
- P2：只写凭据/配置说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M32-F01**：account.id/label/provider。
- **M32-F02**：appIdMasked/merchantIdMasked。
- **M32-F03**：environment(LIVE/SANDBOX/MOCK)。
- **M32-F04**：status/isDefault/configuredAt/version。
- **M32-F05**：新增label/provider/environment/appId/merchantId/appPrivateKey/providerPublicKey。
- **M32-F06**：校验status/checks.name/status/message。

#### Layout (Desktop)

账户列表突出环境与默认，敏感值仅脱敏；新增720px工作区分基本信息/密钥；校验结果独立检查清单。

#### Layout (Tablet)

配置表单单列；密钥textarea4行，保留粘贴与清空。

#### Layout (Mobile)

全屏Sheet；环境选择先于密钥；私钥不进入预览/截图，关闭即清空。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M32-A01 · Primary**：查看脱敏账户。
- **M32-A02 · Secondary**：新增账户（开放时）。
- **M32-A03 · Secondary**：校验及查看结果。
- **M32-A04 · Secondary**：设为默认并确认。
- **M32-A05 · Secondary**：非默认账户停用并确认。
- **M32-A06 · Secondary**：取消。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

LIVE/TEST订单环境与LIVE/SANDBOX/MOCK渠道环境分开；不新增任意网关URL；默认切换只影响新支付，历史退款使用原账户；校验不等于真实收款验收。

#### States

受限发布禁止写入、LIVE/SANDBOX/MOCK、凭据未配置/校验中/有效/无效、默认账户约束、密钥只写。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：配置表单单列；密钥textarea4行，保留粘贴与清空。 Mobile：全屏Sheet；环境选择先于密钥；私钥不进入预览/截图，关闭即清空。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“当前只读发布阶段不能用漂亮的可点击按钮暗示客户可自行开通收款。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m33"></a>

### Page: M33 组织设置

**现有入口 / 来源**：`#/settings`；public/merchant.js:renderSettingsView。**能力门控**：tenant.manage。

#### Purpose

维护组织信息并保护账期一致性。

#### User Goal

用户能够围绕“组织名称、时区”完成修改组织名称，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：组织名称、时区。
- P1：保存状态。
- P2：ID/版本与限制。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M33-F01**：tenant.id/name/timezone/version。
- **M33-F02**：时区选项Asia/Shanghai/Asia/Tokyo/Asia/Singapore/Europe/London/America/New_York/UTC。
- **M33-F03**：账期变更说明。

#### Layout (Desktop)

内容最大800px，左侧标签160px、右侧字段480px；时区影响说明紧贴控件；技术id版本折叠。

#### Layout (Tablet)

最大720px，标签上置。

#### Layout (Mobile)

单列表单；保存48px；时区长名称允许换行。

#### Components

Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M33-A01 · Primary**：修改组织名称。
- **M33-A02 · Secondary**：选择时区。
- **M33-A03 · Secondary**：保存。
- **M33-A04 · Secondary**：409重新加载。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

交易后时区修改可能409；不能仅改前端格式代替后端账期；保留服务端未列出的当前时区而非偷偷切默认值。

#### States

只读、未修改、时区/名称错误、重新验证、保存中、保存成功、409冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大720px，标签上置。 Mobile：单列表单；保存48px；时区长名称允许换行。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“技术字段显眼而时区后果不够突出。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m34"></a>

### Page: M34 商户审计

**现有入口 / 来源**：`#/audit`；public/merchant.js:renderAuditView,loadAuditPage。**能力门控**：audit.read。

#### Purpose

追查本组织的操作结果和责任人。

#### User Goal

用户能够围绕“时间、操作者、动作、对象”完成查询，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：时间、操作者、动作、对象。
- P1：筛选/请求ID。
- P2：完整action、resourceLabel、requestId与outcome。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M34-F01**：日期区间。
- **M34-F02**：action过滤。
- **M34-F03**：createdAt。
- **M34-F04**：actorName。
- **M34-F05**：requestId。
- **M34-F06**：action。
- **M34-F07**：resourceType/resourceLabel。
- **M34-F08**：outcome。
- **M34-F09**：nextCursor。

#### Layout (Desktop)

无卡片套卡片的审计表；主列时间/人/动作/资源/结果；requestId进入可展开技术行。

#### Layout (Tablet)

actor与requestId合并，结果独立可见。

#### Layout (Mobile)

时间轴式列表，点击展开完整原始动作与请求ID；提供复制（新增纯前端）。

#### Components

Filter / Table / Timeline / ExpandableSection / Copy。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M34-A01 · Primary**：查询。
- **M34-A02 · Secondary**：日期/动作筛选。
- **M34-A03 · Secondary**：加载更多。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

只读、无删除；游标分页；不要默认提供本API没有的JSON详情字段或全局资源筛选。

#### States

无记录、筛选无结果、字段缺失/长文本、无权限、读取失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：actor与requestId合并，结果独立可见。 Mobile：时间轴式列表，点击展开完整原始动作与请求ID；提供复制（新增纯前端）。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“目前requestId占据副标题，对普通用户太重，对排错又缺复制入口。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-m35"></a>

### Page: M35 商户演示工具

**现有入口 / 来源**：`仅 /assets/merchant.html?demo=1`；public/merchant.js:initDemoTools,syncDemoTools; public/merchant-demo.js。**能力门控**：显式demo专用；与TEST不同。

#### Purpose

在不接触真实设备、钱款和组织的环境中验收设计状态。

#### User Goal

用户能够围绕“DEMO模式、角色、故障开关”完成展开/收起工具，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：DEMO模式、角色、故障开关。
- P1：退款推进/重置。
- P2：固定演示token说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **M35-F01**：DEMO横幅。
- **M35-F02**：当前角色OWNER/OPERATOR/FINANCE。
- **M35-F03**：empty/forbidden/network/slow故障开关。
- **M35-F04**：邮件不可用开关。
- **M35-F05**：claimCode/verifyToken/resetToken/inviteToken固定演示值。
- **M35-F06**：退款推进数量。

#### Layout (Desktop)

顶部明确DEMO条，右下工具入口；工具Drawer宽480px，故障开关纵向。

#### Layout (Tablet)

工具Drawer占60%宽但不覆盖横幅。

#### Layout (Mobile)

全屏工具Sheet，关闭返回原视图；所有开关44px以上。

#### Components

Banner / Switch / Drawer / Button。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **M35-A01 · Primary**：展开/收起工具。
- **M35-A02 · Secondary**：切角色。
- **M35-A03 · Secondary**：故障模拟。
- **M35-A04 · Secondary**：模拟退款成功。
- **M35-A05 · Secondary**：重置内存数据。
- **M35-A06 · Secondary**：切邮件故障。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

demo仅内存，无自动降级；TEST仍是真实API测试数据，不是demo；模拟退款不能作用于正式adapter；重置只清当前演示数据。

#### States

默认/empty/forbidden/network/slow各开关、角色变更、邮件关闭、内存重置、模拟退款待推进/已成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：工具Drawer占60%宽但不覆盖横幅。 Mobile：全屏工具Sheet，关闭返回原视图；所有开关44px以上。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“工具隐藏在角落且容易把DEMO和TEST混为一谈。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a01"></a>

### Page: A01 平台 Token 登录

**现有入口 / 来源**：`/admin → /assets/admin.html`；public/admin.html + admin.js:handleLogin。**能力门控**：独立于商户账号；按平台Token权限。

#### Purpose

让内部运维明确这是平台入口，不能用商户密码登录。

#### User Goal

用户能够围绕“Token输入与登录”完成登录，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：Token输入与登录。
- P1：失败说明/平台身份。
- P2：会话内存说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A01-F01**：API Token。
- **A01-F02**：平台名称。
- **A01-F03**：会话仅内存说明。
- **A01-F04**：登录错误。
- **A01-F05**：运营员身份/角色。

#### Layout (Desktop)

与M01共享420px表单，左侧显示平台运维标记，蓝青细边区别商户；不出现注册入口。

#### Layout (Tablet)

居中440px单列表单，左右24px。

#### Layout (Mobile)

16px边距，48pxToken框和登录按钮，安全说明置底。

#### Components

Form / Button / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A01-A01 · Primary**：登录。
- **A01-A02 · Secondary**：密码式Token输入。
- **A01-A03 · Secondary**：登录失败重试。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

提交后读取身份权限；Token只存内存，不写localStorage；刷新需要重新输入但不会撤销服务端Token。

#### States

空Token、认证中、无效/撤销/过期Token、网络失败、登录成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：居中440px单列表单，左右24px。 Mobile：16px边距，48pxToken框和登录按钮，安全说明置底。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“安全说明容易把刷新丢失凭证说成凭证已撤销；与商户入口辨识不足。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a02"></a>

### Page: A02 平台工作区与刷新控制

**现有入口 / 来源**：`admin.html#/dashboard|devices|orders|access|audit`；public/admin.js:buildNav/route/tick。**能力门控**：按各平台permission。

#### Purpose

在运维上下文中定位操作并识别数据时效。

#### User Goal

用户能够围绕“当前模块、刷新时效”完成切换模块，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：当前模块、刷新时效。
- P1：身份/角色与导航。
- P2：权限说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A02-F01**：五个导航与当前标题/说明。
- **A02-F02**：运营员displayName/actorId/role/tokenLabel。
- **A02-F03**：刷新时间/倒计时。
- **A02-F04**：权限不足说明。

#### Layout (Desktop)

224px侧栏、64px顶栏，身份与刷新放右上；内容12列，操作不混入商户组织选择。

#### Layout (Tablet)

72px图标轨+点击展开224px导航；顶栏56px，刷新保留文字。

#### Layout (Mobile)

顶部56px；底部总览/设备/订单/更多64px；权限和审计在更多Sheet；退出在账号菜单。

#### Components

Navigation / Breadcrumb / Popover / Button / Status。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A02-A01 · Primary**：切换模块。
- **A02-A02 · Secondary**：立即刷新。
- **A02-A03 · Secondary**：自动刷新。
- **A02-A04 · Secondary**：退出登录。
- **A02-A05 · Secondary**：无权限返回可用页。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

10秒刷新在隐藏、输入、弹窗时暂停，恢复时提示更新时间；保留筛选/展开/键盘焦点；401安全退出。

#### States

未认证、无任何页面权限、刷新中、已暂停、数据过时、重新登录。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：72px图标轨+点击展开224px导航；顶栏56px，刷新保留文字。 Mobile：顶部56px；底部总览/设备/订单/更多64px；权限和审计在更多Sheet；退出在账号菜单。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“重复刷新可能干扰阅读，需要明确暂停原因而非数字跳动。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a03"></a>

### Page: A03 平台运营总览

**现有入口 / 来源**：`admin.html#/dashboard`；public/admin.js:renderDashboardView/loadDashboard。**能力门控**：dashboard.read；最近订单另需orders.read。

#### Purpose

先发现异常积压，再了解今天运行规模。

#### User Goal

用户能够围绕“人工复核、退款及积压”完成刷新，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：人工复核、退款及积压。
- P1：今日订单/完成率与设备。
- P2：最近订单详情。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A03-F01**：设备total/online/restricted。
- **A03-F02**：订单today/readyToday/successRate/exceptionsToday。
- **A03-F03**：manualReviews。
- **A03-F04**：pendingRefunds。
- **A03-F05**：pendingBusinessEvents。
- **A03-F06**：pendingCommands。
- **A03-F07**：最近8笔订单的A08全部概览字段。

#### Layout (Desktop)

顶部状态摘要占8列，右4列更新时间；下方左4列纵向异常待办，右8列最近订单；设备与今日完成率为横排数值而非四卡模板。

#### Layout (Tablet)

摘要2列，异常待办横向2×2，订单全宽。

#### Layout (Mobile)

先异常计数和刷新，再今日摘要两列，最近订单变紧凑列表。

#### Components

Metric / List / Table / Status / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A03-A01 · Primary**：刷新。
- **A03-A02 · Secondary**：展开最近订单。
- **A03-A03 · Secondary**：前往订单/设备。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

待办只跳转现有支持的筛选；未有事件处理页的积压项仅解释，不提供虚假处理按钮；订单子区无权不影响总览。

#### States

局部订单403、指标缺失、今日零订单时完成率未知、异常积压>0、刷新失败旧值保留。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：摘要2列，异常待办横向2×2，订单全宽。 Mobile：先异常计数和刷新，再今日摘要两列，最近订单变紧凑列表。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“相同强度指标掩盖人工复核；积压事件/命令不能默认绿色安全。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a04"></a>

### Page: A04 平台设备列表

**现有入口 / 来源**：`admin.html#/devices`；public/admin.js:renderDevicesView/renderDeviceRows。**能力门控**：devices.read；登记需devices.manage。

#### Purpose

定位需要处理的设备。

#### User Goal

用户能够围绕“设备ID、连接、生命周期”完成搜索，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：设备ID、连接、生命周期。
- P1：门店、活跃订单、心跳。
- P2：SN/软件/安装资料。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A04-F01**：搜索deviceId/SN/门店。
- **A04-F02**：连接筛选。
- **A04-F03**：online/hasEverConnected。
- **A04-F04**：deviceId/serialNumber。
- **A04-F05**：storeName/storeId。
- **A04-F06**：profileComplete。
- **A04-F07**：lifecycleStatus。
- **A04-F08**：activeOrderCount。
- **A04-F09**：lastHeartbeatAt。
- **A04-F10**：softwareVersion。

#### Layout (Desktop)

列表主区8列+摘要4列，行56px；前两列粘性连接与ID；完整详情打开640pxDrawer避免并排过窄。

#### Layout (Tablet)

全宽表，隐藏次要列到行展开；详情右侧min(640px,90vw)。

#### Layout (Mobile)

80px记录，ID/门店/连接/生命周期首屏，心跳/软件进详情；搜索全宽，连接Sheet。

#### Components

Table / Search / Select / Drawer / Status。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A04-A01 · Primary**：搜索。
- **A04-A02 · Secondary**：筛选。
- **A04-A03 · Secondary**：选择设备。
- **A04-A04 · Secondary**：登记设备。
- **A04-A05 · Secondary**：刷新。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

搜索遵循当前已拉取设备集合范围，明示结果数量；筛选无结果可清空；未连接过区别于离线。

#### States

未登记、无匹配、在线、离线、从未上线、详情加载失败。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：全宽表，隐藏次要列到行展开；详情右侧min(640px,90vw)。 Mobile：80px记录，ID/门店/连接/生命周期首屏，心跳/软件进详情；搜索全宽，连接Sheet。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“表内门店/实例标题与值语义混杂；需要分别列标签。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a05"></a>

### Page: A05 平台设备详情与远程命令

**现有入口 / 来源**：`设备列表详情`；public/admin.js:renderDeviceDetail/sendDeviceCommand/confirmRestart。**能力门控**：devices.read；操作按devices.manage/commands.execute。

#### Purpose

诊断连接、能力和物料，并执行有权限的运营操作。

#### User Goal

用户能够围绕“连接、生命周期、错误与任务”完成查看基本/能力/物料/操作分区，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：连接、生命周期、错误与任务。
- P1：能力/物料、可用操作。
- P2：启动ID/序列/计数/快照版本。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A05-F01**：deviceId/deviceName/serialNumber。
- **A05-F02**：storeName/storeId/cityCode/timezone。
- **A05-F03**：profileComplete/profileSource。
- **A05-F04**：instanceId。
- **A05-F05**：softwareVersion。
- **A05-F06**：activeBootId。
- **A05-F07**：lastSequence。
- **A05-F08**：heartbeatCount/eventCount/commandCount。
- **A05-F09**：activeOrderCount。
- **A05-F10**：capabilities/inventory快照version/receivedAt。
- **A05-F11**：lastHeartbeatAt。
- **A05-F12**：lastErrorSummary。
- **A05-F13**：online/hasEverConnected/lifecycleStatus。
- **A05-F14**：recipes: name/recipeId/version/estimatedDurationSeconds/priceMinor/currency/available。
- **A05-F15**：materials: name/materialId/available/capacity/unit/status。
- **A05-F16**：重启影响与确认文字。

#### Layout (Desktop)

640pxDrawer或独立详情全宽：头身份+状态，Tabs概览/能力/物料/操作；键值2列，命令区分低风险配置与危险重启。

#### Layout (Tablet)

详情宽90vw，概览2列，能力/物料单列。

#### Layout (Mobile)

全屏详情，顶部返回，Tabs横滚；物料文字数量与条同时显示；命令每行44px以上。

#### Components

Drawer / Tabs / List / Progress / Status / Dialog。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A05-A01 · Primary**：查看基本/能力/物料/操作分区。
- **A05-A02 · Secondary**：变更生命周期。
- **A05-A03 · Secondary**：生成激活码。
- **A05-A04 · Secondary**：RELOAD_CONFIG重载。
- **A05-A05 · Secondary**：SYNC_CONFIG同步。
- **A05-A06 · Secondary**：重启应用二次确认。
- **A05-A07 · Secondary**：关闭详情。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

命令发送成功显示已提交而非设备执行成功；重启提示制作可能中断并确认；快照请求可部分失败；PENDING不能手动转生命周期绕过激活。

#### States

快照未上报/获取失败/过时、PENDING/ACTIVE/SUSPENDED/MAINTENANCE、命令排队/失败、无命令权限、未知物料状态。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：详情宽90vw，概览2列，能力/物料单列。 Mobile：全屏详情，顶部返回，Tabs横滚；物料文字数量与条同时显示；命令每行44px以上。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“旧实现把缺少预计时长默认为60秒、未知能力当可售、未知物料当正常有误导风险；重设计显示未知。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a06"></a>

### Page: A06 登记设备、激活码与生命周期

**现有入口 / 来源**：`设备操作弹窗`；public/admin.js:openRegisterModal/createActivationCode/openLifecycleModal/showSecretModal。**能力门控**：devices.manage。

#### Purpose

完成出厂登记与安装交接，留存变更原因。

#### User Goal

用户能够围绕“登记字段或目标生命周期”完成登记并生成激活码，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：登记字段或目标生命周期。
- P1：激活结果/原因/有效期。
- P2：重复登记与分步结果。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A06-F01**：deviceId格式coffee-bot-[0-9]{3,6}。
- **A06-F02**：serialNumber格式CB-[0-9]{4}-[0-9]{3,6}。
- **A06-F03**：instanceId/storeId可选。
- **A06-F04**：重复登记说明。
- **A06-F05**：activationCode/expiresAt。
- **A06-F06**：目标生命周期。
- **A06-F07**：必填reason。
- **A06-F08**：当前设备ID。

#### Layout (Desktop)

登记560pxDialog，ID/SN单列48px，选填两列；成功切换480px秘密Dialog；生命周期480pxDialog。

#### Layout (Tablet)

最大560px，两边24px，秘密可换行选择复制。

#### Layout (Mobile)

登记全屏表单；生命周期短Sheet；激活码弹层内容不超屏，复制44px。

#### Components

Dialog / Form / Secret / Button / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A06-A01 · Primary**：登记并生成激活码。
- **A06-A02 · Secondary**：取消。
- **A06-A03 · Secondary**：重新生成激活码。
- **A06-A04 · Secondary**：复制一次性激活码。
- **A06-A05 · Secondary**：关闭秘密展示。
- **A06-A06 · Secondary**：提交生命周期变更。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

登记和生成码为两个请求，登记成功但发码失败要显示分步结果，只重试发码；关闭秘密不等于码被撤销；生命周期原因必填。

#### States

格式错误、重复记录、登记成功发码失败、发码成功、已过期、复制失败、原因空、版本/业务冲突。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大560px，两边24px，秘密可换行选择复制。 Mobile：登记全屏表单；生命周期短Sheet；激活码弹层内容不超屏，复制44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“双步骤失败容易误报整体失败，导致反复登记；秘密显示应避免被Toast遮挡。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a07"></a>

### Page: A07 平台订单筛选

**现有入口 / 来源**：`admin.html#/orders`；public/admin.js:renderOrdersView/loadOrders。**能力门控**：orders.read。

#### Purpose

查找特定设备和状态的订单。

#### User Goal

用户能够围绕“状态/设备条件与结果”完成查询，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：状态/设备条件与结果。
- P1：刷新/返回范围。
- P2：技术筛选值说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A07-F01**：订单状态筛选全部/CREATED/AWAITING_PAYMENT/QUEUED/DISPATCHED/ACCEPTED/MAKING/HOLD/READY/FAILED/REFUNDED/CANCELLED/EXPIRED。
- **A07-F02**：deviceId。
- **A07-F03**：当前返回范围/条数。

#### Layout (Desktop)

全宽56px筛选行，状态200px、设备240px、查询；下方表格余高。

#### Layout (Tablet)

筛选分两行，表格自适应列。

#### Layout (Mobile)

搜索设备+筛选Sheet，显示已用筛选数量；结果卡进入A08。

#### Components

Filter / Select / Input / Table。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A07-A01 · Primary**：查询。
- **A07-A02 · Secondary**：Enter查询。
- **A07-A03 · Secondary**：刷新。
- **A07-A04 · Secondary**：展开订单。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

沿用API实际limit与筛选，不伪造全库搜索/分页/批量退款；刷新不清空条件。

#### States

初始加载、无订单、无匹配、查询失败、旧结果刷新中。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：筛选分两行，表格自适应列。 Mobile：搜索设备+筛选Sheet，显示已用筛选数量；结果卡进入A08。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“缺乏筛选摘要，窄屏横表难定位异常。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a08"></a>

### Page: A08 平台订单行与详情

**现有入口 / 来源**：`平台总览/订单展开`；public/admin.js:renderOrderTable/renderOrderDetail。**能力门控**：orders.read。

#### Purpose

把支付、制作、复核证据并列阅读。

#### User Goal

用户能够围绕“订单金额、支付/制作状态”完成展开/收起，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：订单金额、支付/制作状态。
- P1：进度/设备/时间。
- P2：失败代码/复核证据。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A08-F01**：orderNo/orderId。
- **A08-F02**：deviceId。
- **A08-F03**：storeId或paymentMode=TEST_FREE免支付联调。
- **A08-F04**：productName。
- **A08-F05**：totalAmountMinor/currency。
- **A08-F06**：status。
- **A08-F07**：paymentStatus。
- **A08-F08**：progress/currentStepName。
- **A08-F09**：createdAt。
- **A08-F10**：productionStatus。
- **A08-F11**：failureCode/failureMessage。
- **A08-F12**：updatedAt。
- **A08-F13**：manualReviewRequired。
- **A08-F14**：holdReason。

#### Layout (Desktop)

表格行56px；展开2列定义列表或640pxDrawer；状态与支付独立列；失败证据全宽背景浅红，HOLD浅黄。

#### Layout (Tablet)

详情抽屉，列表减少创建时间显示到二行。

#### Layout (Mobile)

80px列表项，金额右对齐，状态行两枚标签；全屏详情中完整技术字段可折叠。

#### Components

Table / Drawer / List / Alert / Status。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A08-A01 · Primary**：展开/收起。
- **A08-A02 · Secondary**：查看失败与HOLD说明。
- **A08-A03 · Secondary**：复制完整订单标识（新增纯前端便利）。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

自动刷新保留展开记录与焦点；HOLD只说明待人工对账，当前UI没有裁决/退款操作，不虚构已经存在。

#### States

所有订单/支付枚举见§11，未知枚举、HOLD、缺失进度、失败信息过长。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：详情抽屉，列表减少创建时间显示到二行。 Mobile：80px列表项，金额右对齐，状态行两枚标签；全屏详情中完整技术字段可折叠。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“制作与支付状态容易被混读；进度缺失应未知而非0%。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a09"></a>

### Page: A09 运营员管理与编辑

**现有入口 / 来源**：`admin.html#/access`；public/admin.js:renderAccessView/renderOperators/openCreateOperatorModal/openEditOperatorModal。**能力门控**：access.read；写入需access.manage。

#### Purpose

管理平台内部运维身份，避免与商户成员混淆。

#### User Goal

用户能够围绕“运营员名称、角色、状态”完成新建运营员，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：运营员名称、角色、状态。
- P1：Token数量/最近使用。
- P2：operatorId。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A09-F01**：displayName/operatorId。
- **A09-F02**：role OWNER/MANAGER/OPERATOR/VIEWER（以availableRoles为准）。
- **A09-F03**：status ACTIVE/SUSPENDED。
- **A09-F04**：activeTokenCount。
- **A09-F05**：lastUsedAt。
- **A09-F06**：新建名称/角色及availableRoles.permissions权限数量/预览。
- **A09-F07**：编辑名称/角色/状态；停用后该运营员全部Token失效说明。

#### Layout (Desktop)

全宽运营员表，顶部新建；编辑480pxDialog；展开Token改A10 Drawer。

#### Layout (Tablet)

表格关键列名称/角色/状态/Token；编辑单列。

#### Layout (Mobile)

成员列表每项80px，名称角色状态与更多；编辑全屏。

#### Components

Table / Form / Dialog / Status。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A09-A01 · Primary**：新建运营员。
- **A09-A02 · Secondary**：编辑。
- **A09-A03 · Secondary**：保存/取消。
- **A09-A04 · Secondary**：展开Token。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

服务端保护最后OWNER等限制必须显示原错误，不能靠隐藏按钮代替授权；改权限后刷新当前身份。

#### States

无运营员、只读、保存中、禁用、角色冲突、当前权限失效。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：表格关键列名称/角色/状态/Token；编辑单列。 Mobile：成员列表每项80px，名称角色状态与更多；编辑全屏。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“内嵌Token表挤压主表，平台角色与租户角色名称相近。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a10"></a>

### Page: A10 运营员 Token 与一次性秘密

**现有入口 / 来源**：`运营员展开详情`；public/admin.js:renderOperatorTokens/revokeToken/showSecretModal。**能力门控**：access.read/manage。

#### Purpose

安全发放与撤销访问凭证。

#### User Goal

用户能够围绕“Token标签、状态、创建/撤销”完成展开Token，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：Token标签、状态、创建/撤销。
- P1：有效期/最近使用/一次性复制。
- P2：tokenId/创建时间与摘要说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A10-F01**：所属运营员。
- **A10-F02**：token.label/tokenId/status/expiresAt/lastUsedAt/createdAt。
- **A10-F03**：创建label最长120。
- **A10-F04**：可选datetime-local到UTC expiresAt。
- **A10-F05**：新建完整token。
- **A10-F06**：SHA-256摘要保管说明。
- **A10-F07**：撤销不可恢复说明。

#### Layout (Desktop)

640pxDrawer，Token表上方说明，创建表单下方分区；秘密480pxDialog，一次显示可复制。

#### Layout (Tablet)

Drawer90vw，创建字段单列。

#### Layout (Mobile)

全屏列表，创建子页；秘密独立弹层不叠加多层Sheet。

#### Components

Secret / Table / Form / Dialog / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A10-A01 · Primary**：展开Token。
- **A10-A02 · Secondary**：创建Token。
- **A10-A03 · Secondary**：复制完整Token。
- **A10-A04 · Secondary**：关闭秘密。
- **A10-A05 · Secondary**：撤销Token并确认。
- **A10-A06 · Secondary**：刷新列表。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

撤销自身Token会导致会话失效；删除返回后再更新；完整token不入日志/截图/存储；复制失败允许手动选中。

#### States

列表失败、空Token、ACTIVE/REVOKED/其他、已过期、创建成功、复制失败、自身撤销。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：Drawer90vw，创建字段单列。 Mobile：全屏列表，创建子页；秘密独立弹层不叠加多层Sheet。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“默认空expiresAt永久有效风险应明确，不能在保存后才告知。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-a11"></a>

### Page: A11 平台审计列表与详情

**现有入口 / 来源**：`admin.html#/audit`；public/admin.js:renderAuditView/loadAuditLogs/showAuditDetail。**能力门控**：audit.read。

#### Purpose

追溯操作的主体、对象和请求。

#### User Goal

用户能够围绕“时间、动作、操作者/对象”完成查询/Enter，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：时间、动作、操作者/对象。
- P1：筛选/请求ID。
- P2：完整脱敏JSON。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **A11-F01**：筛选action/resourceType。
- **A11-F02**：createdAt。
- **A11-F03**：actorName/actorId/actorType。
- **A11-F04**：action。
- **A11-F05**：resourceType/resourceId。
- **A11-F06**：requestId。
- **A11-F07**：detail完整JSON。
- **A11-F08**：limit=200返回范围。

#### Layout (Desktop)

表格时间160px、操作者180px、动作/资源自适应、请求ID末列；640px详情Drawer内JSON等宽可横滚。

#### Layout (Tablet)

筛选两列，详情90vw，长ID可换行。

#### Layout (Mobile)

事件列表按时间逐条，不虚构服务端分组统计；详情全屏，JSON局部横滚并提供可选择文本。

#### Components

Table / Search / Drawer / Code / List。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **A11-A01 · Primary**：查询/Enter。
- **A11-A02 · Secondary**：打开详情。
- **A11-A03 · Secondary**：关闭。
- **A11-A04 · Secondary**：复制非敏感ID（新增纯前端便利）。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

API返回空对象不是丢失记录；原始JSON转义为文本，不执行HTML；限制200条明确显示。

#### States

无匹配、局部字段缺失、JSON空、读取错误、无权限。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

采用Dialog200ms/Drawer240ms，正文不整块重播；错误原位出现；成功根据真实响应160ms；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：筛选两列，详情90vw，长ID可换行。 Mobile：事件列表按时间逐条，不虚构服务端分组统计；详情全屏，JSON局部横滚并提供可选择文本。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“全页横滚与长技术字段导致可读性差。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-c01"></a>

### Page: C01 设备菜单与饮品选择

**现有入口 / 来源**：`/order?device_id={id}`；public/order.js:loadMenu/renderMenu/card/selectDrink。**能力门控**：匿名设备限定菜单。

#### Purpose

扫码后看清饮品、价格和设备可用性再下单。

#### User Goal

用户能够围绕“可选饮品/价格/设备可售性”完成选择可售饮品，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：可选饮品/价格/设备可售性。
- P1：时长/余量/结算。
- P2：口径/共享物料说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **C01-F01**：deviceId/storeId。
- **C01-F02**：online/deviceStatus/salesEnabled。
- **C01-F03**：paymentMode ONLINE/TEST_FREE。
- **C01-F04**：materialAlertCount。
- **C01-F05**：可售产品remainingServings求和的旧预计可售杯数。
- **C01-F06**：recipeId/name/description。
- **C01-F07**：visual.profile与generic回退。
- **C01-F08**：priceMinor/currency。
- **C01-F09**：recipeVersion。
- **C01-F10**：durationRangeSeconds.min/max/estimatedDurationSeconds。
- **C01-F11**：available/unavailableReasons[]及当前首项解释。
- **C01-F12**：remainingServings。
- **C01-F13**：选中饮品/合计。
- **C01-F14**：共享物料与付款后派单说明。

#### Layout (Desktop)

最大1120px，顶部设备信息56px；商品3列，右侧或底部320px选购摘要；商品图片仅用现有SVG，不造未知口味。

#### Layout (Tablet)

商品2列，底部结算条72px。

#### Layout (Mobile)

480px最大单列，图文横排商品高112–144px；名称价格首行；底部72px+safe-area结算；CTA48px。

#### Components

List / Product / Button / Status / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **C01-A01 · Primary**：选择可售饮品。
- **C01-A02 · Secondary**：查看不可售原因。
- **C01-A03 · Secondary**：确认下单。
- **C01-A04 · Secondary**：刷新菜单/错误重试。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

只选一种、数量1，提交真实recipeVersion/price确认；商品售罄不可选择；设备断线与浏览器离线不同；不新增购物车/甜度/杯型。

#### States

加载、无device_id、设备不存在、无产品、全部不可售、在线/离线/维护、价格未知、浏览器离线。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：商品2列，底部结算条72px。 Mobile：480px最大单列，图文横排商品高112–144px；名称价格首行；底部72px+safe-area结算；CTA48px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“旧大标题与重复说明挤压菜单；选择态需描边和文字而非只色彩。 当前把共享原料支持的不同配方杯数相加，未必等于设备真实总可售杯数；保留该值在口径说明中并标“各饮品估算之和，非承诺总库存”，不能继续无条件当作总库存。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-c02"></a>

### Page: C02 创建订单与价格冲突

**现有入口 / 来源**：`菜单提交状态`；public/order.js:submitOrder。**能力门控**：可售产品且服务端校验通过。

#### Purpose

防止重复订单或未经确认的价格变化。

#### User Goal

用户能够围绕“金额与创建状态”完成提交，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：金额与创建状态。
- P1：分步失败与安全重试。
- P2：版本/幂等数据仅程序处理。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **C02-F01**：recipeId/recipeVersion。
- **C02-F02**：quantity=1/paymentMode。
- **C02-F03**：支付前合计priceMinor/currency。
- **C02-F04**：订单idempotencyKey与payment:key。
- **C02-F05**：服务端错误code/message。
- **C02-F06**：创建结果orderId/accessToken/paymentId（秘密不展示）。

#### Layout (Desktop)

在C01摘要区原位显示创建中，锁定主CTA；错误贴近金额而非覆盖全页。

#### Layout (Tablet)

结算条原位状态，不推走已选产品。

#### Layout (Mobile)

底部CTA显示正在创建，错误Alert上推内容但不遮挡商品；重试44px。

#### Components

Button / Alert / Product。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **C02-A01 · Primary**：提交。
- **C02-A02 · Secondary**：失败后重试。
- **C02-A03 · Secondary**：价格/菜单变化后重新选择确认。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

sessionStorage幂等键延续现有逻辑；网络超时不立即新建另一单；价格/配方版本冲突先刷新菜单并让用户确认；成功进入带fragment凭证状态页。 订单创建和payments创建是两阶段，支付创建失败应复用已有订单与同一支付幂等键；沿用现有接口，不假设请求包含客户端价格字段。

#### States

创建中、校验失败、版本/价格冲突、超时结果未知、成功跳转。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：结算条原位状态，不推走已选产品。 Mobile：底部CTA显示正在创建，错误Alert上推内容但不遮挡商品；重试44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“失败提示不应只短Toast，不能用假乐观支付成功。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-c03"></a>

### Page: C03 等待支付与稳定二维码

**现有入口 / 来源**：`/order/status#order=…&token=…&payment=…`；public/order.js:renderOrder/attachPaymentQr。**能力门控**：CREATED/AWAITING_PAYMENT。

#### Purpose

确认金额与支付环境，然后完成付款并等待服务端确认。

#### User Goal

用户能够围绕“金额、付款环境、打开付款”完成打开付款页，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：金额、付款环境、打开付款。
- P1：二维码/订单号/等待确认。
- P2：渠道与稳定二维码说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **C03-F01**：orderNo。
- **C03-F02**：product.name。
- **C03-F03**：totalAmountMinor/currency。
- **C03-F04**：payment.provider。
- **C03-F05**：qrCode付款链接。
- **C03-F06**：二维码/加载说明。
- **C03-F07**：支付里程碑。
- **C03-F08**：服务端实时确认说明。
- **C03-F09**：模拟付款不扣款声明。

#### Layout (Desktop)

最大960px两列：左420px商品金额与里程碑，右320px支付面板；二维码224px有白色静区；不占满全屏hero。

#### Layout (Tablet)

最大720px，支付面板居中，金额在二维码上。

#### Layout (Mobile)

单列16px边距，同手机主CTA打开付款页优先，二维码200–224px次位用于跨设备；底部刷新44px。

#### Components

QR / Button / Status / Timeline / Alert。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **C03-A01 · Primary**：打开付款页。
- **C03-A02 · Secondary**：扫码。
- **C03-A03 · Secondary**：刷新状态。
- **C03-A04 · Secondary**：二维码失败重试。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

provider=alipay_mock才称模拟；未知provider用中性付款；ONLINE不代表真实扣款；相同支付二维码复用DOM/blob不闪烁，失败冷却≥20秒；返回页面重新获取真实状态。

#### States

二维码加载/成功/失败、待付款、回跳待确认、SSE断开、订单失效、未知渠道。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

二维码本身不做重入场/缩放；状态标签160ms；已缓存图像保持稳定，reduced-motion关闭全部过渡。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大720px，支付面板居中，金额在二维码上。 Mobile：单列16px边距，同手机主CTA打开付款页优先，二维码200–224px次位用于跨设备；底部刷新44px。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“旧固定支付宝文案容易误导；同手机扫码需有直接打开链接；付款跳转不能视为支付完成。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-c04"></a>

### Page: C04 排队、制作、完成与退款结果

**现有入口 / 来源**：`/order/status同一订单`；public/order.js:renderOrder/productionSteps/milestoneMarkup/bannerFor/statusNote。**能力门控**：按服务端订单状态。

#### Purpose

清楚知道等什么、是否能取杯、失败后款项处于何状态。

#### User Goal

用户能够围绕“当前状态、是否取杯/退款未决”完成刷新状态，并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：当前状态、是否取杯/退款未决。
- P1：当前步骤、时间/进度。
- P2：全部步骤与分层确认说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **C04-F01**：orderNo/product.name。
- **C04-F02**：status。
- **C04-F03**：queuePosition。
- **C04-F04**：production.overallProgress/progress。
- **C04-F05**：currentStepId/currentStepName。
- **C04-F06**：remainingSeconds/plannedDurationSeconds。
- **C04-F07**：步骤id/name/index/duration。
- **C04-F08**：支付/排队/制作/完成里程碑。
- **C04-F09**：failure.message。
- **C04-F10**：HOLD解释。
- **C04-F11**：退款原路与时间说明。
- **C04-F12**：物料预留/扣减与结果确认说明。

#### Layout (Desktop)

最大960px，左360px状态/96px进度环，右步骤时间线；READY取杯提示置首；技术说明折叠底部。

#### Layout (Tablet)

单列最大640px，进度摘要横排，时间线下方。

#### Layout (Mobile)

状态标题24px，当前步骤+预计时间首屏；里程碑横排可换行；进度环72px，步骤折叠但可打开。

#### Components

Progress / Timeline / Status / Alert / Disclosure。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **C04-A01 · Primary**：刷新状态。
- **C04-A02 · Secondary**：展开制作步骤/技术说明。
- **C04-A03 · Secondary**：终态查看结果。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

SSE请求带Header凭证，3秒重连；隐藏后恢复刷新；READY/FAILED/CANCELLED/EXPIRED/REFUNDED停止流；HOLD不许自动显示退款；未知进度显示待上报而非0%；无时长不造倒计时。

#### States

QUEUED/DISPATCHED/ACCEPTED/MAKING/HOLD/READY/FAILED/REFUNDED/CANCELLED/EXPIRED；未知枚举、延迟上报、重连中、步骤数据不全。；兼容旧PAID展示为支付成功正在排队，不作为制作终态。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

进度只对真实新值160ms过渡，时间线当前步骤同步切换；READY一次Check淡入，无连续旋转；reduced-motion直接呈现。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：单列最大640px，进度摘要横排，时间线下方。 Mobile：状态标题24px，当前步骤+预计时间首屏；里程碑横排可换行；进度环72px，步骤折叠但可打开。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“付款成功不等于饮品完成；异常结果与退款最终到账需分开表达。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

<a id="page-c05"></a>

### Page: C05 消费者错误与访问失效

**现有入口 / 来源**：`菜单/状态错误页`；public/order.js:renderError/loadOrder/startOrderStream。**能力门控**：匿名请求或订单凭证失效。

#### Purpose

让用户区分网络问题和失效链接，知道安全下一步。

#### User Goal

用户能够围绕“失败原因与安全下一步”完成重新连接（可恢复错误），并在结果未确认或不可执行时看到明确原因与下一步。

#### Information Priority

- P0：失败原因与安全下一步。
- P1：设备/订单非秘密上下文。
- P2：错误code说明。放在本页详情/技术说明展开区，具有44px入口和可读标题。

#### Content

- **C05-F01**：错误message/code。
- **C05-F02**：缺少device_id/order/token。
- **C05-F03**：重试是否允许。
- **C05-F04**：连接提示。
- **C05-F05**：当前设备/订单上下文（非秘密）。
- **C05-F06**：认证与不存在区分。

#### Layout (Desktop)

最大560px错误区域，标题20px，具体原因+主操作，取消无意义状态hero。

#### Layout (Tablet)

最大520px，24px边距。

#### Layout (Mobile)

16px边距，上半屏错误说明，44px重试；无有效设备时提示重新扫码而不猜设备。

#### Components

Alert / Button / Empty。名称别名与复用/扩展关系见§7；表单内部控件依字段类型采用Input/Select/Checkbox/DateRange。

#### Primary Action / Secondary Action

- **C05-A01 · Primary**：重新连接（可恢复错误）。
- **C05-A02 · Secondary**：回菜单（可恢复设备上下文时的新增纯前端导航）。

主动作不可用时说明业务/权限原因，不临时把危险操作提升为主操作；只读页面Primary表示首要导航或查询，不要求强行实心CTA。

#### Interaction

401/403/404不无限重试；网络可重试且保留既有订单标识；不把秘密token放入页面说明/客服链接。

#### States

断网、超时、接口500、404、凭证缺失/失效、重试中、恢复成功。 数据区同时采用§11的Loading、Empty、Error、Offline、Partial Data；交互控件采用§7的Default/Hover/Pressed/Focused/Selected/Disabled。纯结果页不伪造无意义hover状态。

#### Motion

控件hover120ms/press80ms，页切换180ms；局部刷新不移动已读内容；reduced-motion为0。

#### Responsive Behavior

Laptop按§6收窄侧栏与gap，双区主区不足640px时改上下排。Tablet：最大520px，24px边距。 Mobile：16px边距，上半屏错误说明，44px重试；无有效设备时提示重新扫码而不猜设备。 局部复杂二维表允许容器横滚；表单/键值/导航不整页横滚，返回保留原上下文。

#### Improvements

针对现状“所有错误统一连接中断易误导，需要按来源给下一步。”，通过上述主次信息分区、可查完整详情与跨屏重组降低操作成本；业务状态按响应展示，不用样式掩盖缺失数据。

## 11. State Design

### 11.1 通用矩阵

| 状态 | 页面/数据组件 | 控件/辅助交互 | 文案与行动 |
| --- | --- | --- | --- |
| Default | 显示当前真实值+时效 | 中性或语义default | 描述当前任务 |
| Hover / Pressed | 只作用可点击记录 | hover加深、press明确，无布局跳动 | 不依赖hover暴露唯一入口 |
| Focused | focus-visible 2px蓝环+2px白隔离 | Tab顺序可见，不被sticky裁切 | 必要时滚入可视区域 |
| Selected | 行/Tab/产品有描边或标记 | aria-selected/pressed与视觉一致 | 命名选中对象 |
| Disabled | 数据只读/服务端关闭/权限限制区分 | 控件不可提交；旁置可读原因 | 无权不回传私有数据 |
| Loading / Skeleton | 初次骨架，刷新保留旧数据 | 按钮busy禁重复；aria-busy | 超时给重试，不无限spinner |
| Empty | 初次无数据 vs 条件无果 | 新建或清筛选只在实际可用时 | “暂无采购记录”/“无匹配订单” |
| Error | 页内原因、请求上下文、可安全展示的requestId | 重试同一次操作须遵守幂等 | 不显示堆栈/密钥 |
| Offline | 浏览器网络断开提示；旧值标时间 | 暂停写操作或给明确失败；保留草稿 | “网络断开，显示上次数据” |
| Partial Data | 成功分区可用，失败分区局部恢复 | 只重试失败分区 | “成本待补全：…”不是¥0.00 |
| Success | 服务端最终事实 | 完成图标+必要Toast | “退款已受理”不同于“退款完成” |
| Warning | 业务未决、物料低、数据过时 | 允许且有依据的处理入口 | “设备结果待确认，暂不能判定交付” |

### 11.2 设备、支付与制作状态

设备连接Online/Offline/Disconnected（断开过程或连接断开证据）、从未上线分别呈现。设备生命周期PENDING/ACTIVE/SUSPENDED/MAINTENANCE另列；Busy/Idle/Working/Error来自实际deviceStatus/任务/告警，不能仅因online=true推断Idle。维护显示工具图标+“维护中”，在线但维护仍不能说可下单。

订单CREATED、AWAITING_PAYMENT为支付前；QUEUED、DISPATCHED、ACCEPTED、MAKING依次表示排队、派发、接受、制作；HOLD是结果未决；READY为制作完成；FAILED/CANCELLED/EXPIRED/REFUNDED按实际状态显示。兼容已有PAID标签只说明付款确认，不能当READY。EXPIRED文案根据已有接口含义写“派单超时”，不要把它随意当支付二维码过期。

支付NOT_STARTED/NOT_REQUIRED/PENDING/PAID/REFUNDING/REFUNDED/PARTIALLY_REFUNDED/CLOSED/FAILED独立显示。退款记录的处理中/失败/成功遵守返回枚举。部分退款不把整个订单改成全额退；制作FAILED不声称款项已退。HOLD没有确定物理结果时不能通过前端自动退款。

物料OK/LOW/CRITICAL用数量+单位+标签。未上报、接口失败、容量未知分别说明。设备实时available与账面onHand/reserved不要拼接成一个无来源百分比。

### 11.3 会计与权限状态

- 实收 `receivedMinor`，退款 `refundedMinor`；净收款 `netCashMinor=实收−退款`。
- 营业净收入 `recognizedRevenueMinor`按交付与冲回事实；毛利 `grossProfitMinor=确认收入−物料成本`；估算利润扣除损耗、渠道手续费与分摊运营费用。表述与 `reports.py` 返回口径保持一致。
- 采购入账、流水记录、费用冲正显示原单引用/状态；不在UI删除历史账务。会计账日期使用组织时区。
- `completeness.status/missing`与相关金额同层，成本缺项时利润为未知；不能填0以画完整图。
- 当前有限发布关闭邮件能力及部分高风险商户操作。保留设计场景但受真实config/permission控制，不能修改后端开关来拍成功截图。
- 成员、邀请、采购、费用、转让、价格计划等枚举逐项来自API；未识别的枚举显示中性标签+原值，不静默降级成功。
- 401重新登录；403解释无权；409冲突先重新读取；422字段关联错误；429显示服务端Retry-After（若有），无值不编倒计时；5xx/断网提示可恢复性。

### 11.4 源码枚举对照与补足

| 位置 | 当前UI识别值 | 新表现/边界 |
| --- | --- | --- |
| 商户生命周期 | ACTIVE / SUSPENDED / PENDING_ACTIVATION / ARCHIVED | 归档是退役；操作SUSPEND/RESUME/ARCHIVE与平台MAINTENANCE不混用 |
| 平台生命周期 | PENDING / ACTIVE / SUSPENDED / MAINTENANCE | PENDING须激活；不添加商户归档状态替代 |
| 商户支付/退款 | SUCCESS与SUCCEEDED别名；支付另有NOT_REQUIRED/PENDING/PAID/REFUNDING/REFUNDED/PARTIALLY_REFUNDED/FAILED；退款另有PENDING/PROCESSING/FAILED | 显示同义中文但保存原状态；处理中不转成功 |
| 商户制作 | DELIVERED与READY均有已交付标签；其余见§11.2 | 可用中文归组，不改请求状态值 |
| 转让 | PENDING_RECIPIENT / PENDING_PLATFORM / COMPLETED / BLOCKED / CANCELLED / REJECTED | 接受只进待平台审核；阻断原因常显；不是直接转让完成 |
| 成本完整性 | COMPLETE / ESTIMATED / INCOMPLETE | 完整/部分估算/未完整录入；missing列表可展开；不能用绿色代表估算 |
| 平台运营员 | ACTIVE / SUSPENDED；角色从availableRoles读取，当前含OWNER/MANAGER/OPERATOR/VIEWER | 创建时权限数量与逐项预览；停用影响全部Token |
| 邀请 | 状态与deliveryStatus分开；QUEUED / UNAVAILABLE等 | 已入邮件发送队列不等于送达，邮件关闭保持说明 |
| 命令 | PENDING / EXECUTING / SUCCEEDED / FAILED / TIMEOUT | 提交中还不是PENDING；查询超时不是执行失败 |
| 库存成本 | MISSING_COST及服务端其他值 | 未识别状态中性，不一律正常 |
| 不可售原因 | DEVICE_OFFLINE / DEVICE_NOT_ACTIVE / MATERIAL_INSUFFICIENT / DISABLED / LOW_STOCK | 中文原因+完整可查解释；禁用饮品按钮不阻止读原因 |
| 认证注册 | USERNAME / EMAIL；REGISTERED / VERIFICATION_PENDING | 模式和结果均来自配置/响应；未知结果不伪装成功 |

模块权限需要细分：物料档案读取inventory.read、创建costs.manage、成本列costs.read；采购读取costs.read、写入和入账costs.manage；账面库存/流水读取inventory.read、登记流水inventory.manage；费用读取costs.read、写入costs.manage。物料工作区可见不表示所有四个Tab都有权限，OPERATOR进入采购时应显示无权说明或禁用Tab，不能因一个403让库存页整体失败。

## 12. Accessibility

| 项目 | 执行标准 | 验收方法 |
| --- | --- | --- |
| 文本对比 | 正文≥4.5:1；大字≥3:1（至少24px常规或18.66px粗体） | Token实际配对计算+截图中真实背景抽检 |
| 图标/控件 | 有意义图标、边界、焦点对相邻背景≥3:1 | 浅border仅装饰；输入用control-border；多状态验证 |
| 命中范围 | Desktop与Mobile所有交互≥44×44px，区域不重叠 | DevTools测DOM矩形；尤其复制、×、Tab、表格菜单 |
| 焦点 | 自定义2px蓝环+2px白间隔；Tab全部可达、焦点不被遮 | 仅键盘完成登录、筛选、详情、表单、取消、退出 |
| 弹层 | role=dialog、aria-modal、名称关联、背景inert、focus trap/return | Esc与关闭按钮等价；敏感busy时可解释不可关闭原因 |
| 语义 | button做动作、a做导航；label/for；表头scope；状态适度aria-live | VoiceOver读表头、错误、状态；图标按钮有名称 |
| 色彩冗余 | 图标/文字/形状同时表示状态 | 灰度与色觉模拟仍能辨识HOLD/失败/成功 |
| 图表 | 图例与等价数据表；缺项说明；不靠鼠标hover读值 | 键盘打开数据表并读所有期间 |
| 缩放 | 200%文本，320px重排，无主体横滚 | 日期/金额/ID/密码帮助不截断；横滚只用于必要二维表 |
| Motion | 系统reduced-motion全量降级 | 骨架静态、取消位移、不依赖动画表达结果 |
| 错误恢复 | 摘要关联字段、不只红框；保留非敏感输入 | 提交多错误时焦点到摘要/首错，修复后可继续 |
| 时间与安全 | Toast不独占关键结果；一次性凭证不能自动消失 | 可读可复制；关闭才清理；不在自动测试截图中泄密 |

44×44是本项目采用的更严格命中标准，不能错误称为WCAG2.2 AA最小命中尺寸要求（AA Target Size Minimum为24px且有例外；44px对应Enhanced要求）。正文/重要说明仍遵循AA，即便禁用控件在规范中有豁免也不刻意降低可读性。

参考：[WCAG 2.2](https://www.w3.org/TR/WCAG22/)、[Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)、[Target Size Enhanced](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html)。HIG/Material/现代SaaS是风格参考，本规范断点与尺寸属于项目约定，不宣称是这些体系的官方固定值。

## 13. Design Tokens

机器文件：[design-tokens.json](design-tokens.json)。这是项目自定义Token结构，值可直接解析；不是声称符合某第三方Token转换器格式。实施时将值映射为CSS自定义属性；语义状态引用同一色板值，不散落硬编码。下方JSON为同文件完整副本。


```json
{
  "meta": {
    "name": "Coffee Cloud · Light Fresh",
    "version": "1.0.0",
    "status": "design-specification-not-applied",
    "sourceCommit": "e66dd053c6d63a3725e25489cf4c526114d96278",
    "units": "px unless explicitly stated",
    "description": "Machine-readable project design tokens; values are literal, not DTCG-format wrappers."
  },
  "color": {
    "neutral": {
      "background": "#F7F9FC",
      "surface": "#FFFFFF",
      "surface-elevated": "#FFFFFF",
      "border": "#DDE3EC",
      "divider": "#E9EDF3",
      "control-border": "#7B8798",
      "text-primary": "#17212B",
      "text-secondary": "#526174",
      "text-disabled": "#596579"
    },
    "semantic": {
      "primary": "#2457D6",
      "success": "#087A55",
      "warning": "#8A6200",
      "error": "#B92B68",
      "info": "#08768B"
    },
    "accent": {
      "blue": "#2457D6",
      "purple": "#7343C5",
      "green": "#087A55",
      "orange": "#B74812",
      "pink": "#B92B68",
      "cyan": "#08768B",
      "yellow": "#8A6200"
    },
    "state": {
      "blue": {
        "default": {
          "background": "#2457D6",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#1D49BB",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#163A98",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#E9EFFF",
          "foreground": "#163A98",
          "border": "#2457D6"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F2F5FF",
          "foreground": "#163A98"
        }
      },
      "purple": {
        "default": {
          "background": "#7343C5",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#6034AD",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#4E288E",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#F0E9FF",
          "foreground": "#4E288E",
          "border": "#7343C5"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F8F4FF",
          "foreground": "#4E288E"
        }
      },
      "green": {
        "default": {
          "background": "#087A55",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#066647",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#05523A",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#DDF5E9",
          "foreground": "#05523A",
          "border": "#087A55"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#EFFBF5",
          "foreground": "#05523A"
        }
      },
      "orange": {
        "default": {
          "background": "#B74812",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#9E3A0D",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#812D08",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#FFEADB",
          "foreground": "#812D08",
          "border": "#B74812"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#FFF5ED",
          "foreground": "#812D08"
        }
      },
      "pink": {
        "default": {
          "background": "#B92B68",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#9C2057",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#801846",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#FFE5EF",
          "foreground": "#801846",
          "border": "#B92B68"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#FFF3F7",
          "foreground": "#801846"
        }
      },
      "cyan": {
        "default": {
          "background": "#08768B",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#056376",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#034F60",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#DCF4FA",
          "foreground": "#034F60",
          "border": "#08768B"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F0FAFD",
          "foreground": "#034F60"
        }
      },
      "yellow": {
        "default": {
          "background": "#8A6200",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#745200",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#5D4100",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#FFF0BF",
          "foreground": "#5D4100",
          "border": "#8A6200"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#FFF9E8",
          "foreground": "#5D4100"
        }
      },
      "neutral": {
        "default": {
          "background": "#FFFFFF",
          "foreground": "#17212B"
        },
        "hover": {
          "background": "#F3F5F8",
          "foreground": "#17212B"
        },
        "pressed": {
          "background": "#E8ECF2",
          "foreground": "#17212B"
        },
        "selected": {
          "background": "#E9EFFF",
          "foreground": "#163A98",
          "border": "#2457D6"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F7F9FC",
          "foreground": "#526174"
        }
      },
      "primary": {
        "default": {
          "background": "#2457D6",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#1D49BB",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#163A98",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#E9EFFF",
          "foreground": "#163A98",
          "border": "#2457D6"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F2F5FF",
          "foreground": "#163A98"
        }
      },
      "success": {
        "default": {
          "background": "#087A55",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#066647",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#05523A",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#DDF5E9",
          "foreground": "#05523A",
          "border": "#087A55"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#EFFBF5",
          "foreground": "#05523A"
        }
      },
      "warning": {
        "default": {
          "background": "#8A6200",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#745200",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#5D4100",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#FFF0BF",
          "foreground": "#5D4100",
          "border": "#8A6200"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#FFF9E8",
          "foreground": "#5D4100"
        }
      },
      "error": {
        "default": {
          "background": "#B92B68",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#9C2057",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#801846",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#FFE5EF",
          "foreground": "#801846",
          "border": "#B92B68"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#FFF3F7",
          "foreground": "#801846"
        }
      },
      "info": {
        "default": {
          "background": "#08768B",
          "foreground": "#FFFFFF"
        },
        "hover": {
          "background": "#056376",
          "foreground": "#FFFFFF"
        },
        "pressed": {
          "background": "#034F60",
          "foreground": "#FFFFFF"
        },
        "selected": {
          "background": "#DCF4FA",
          "foreground": "#034F60",
          "border": "#08768B"
        },
        "disabled": {
          "background": "#E8ECF2",
          "foreground": "#596579"
        },
        "subtle-bg": {
          "background": "#F0FAFD",
          "foreground": "#034F60"
        }
      }
    },
    "focus": {
      "ring": "#2457D6",
      "gap": "#FFFFFF",
      "width": 2,
      "offset": 2
    },
    "decoration": {
      "blue": "#4D83FF",
      "purple": "#B692FF",
      "green": "#76E7B1",
      "orange": "#FFA56F",
      "pink": "#FF8CBB",
      "cyan": "#69D7EE",
      "yellow": "#FFDC62",
      "usage": "non-text decoration only; no semantic reliance; saturated area <=15%"
    }
  },
  "typography": {
    "font-family": {
      "sans": "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
      "mono": "ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace",
      "numeric": "inherit"
    },
    "scale": {
      "display": {
        "fontSize": 30,
        "lineHeight": 38,
        "fontWeight": 700
      },
      "h1": {
        "fontSize": 24,
        "lineHeight": 32,
        "fontWeight": 700
      },
      "h2": {
        "fontSize": 20,
        "lineHeight": 28,
        "fontWeight": 650
      },
      "h3": {
        "fontSize": 18,
        "lineHeight": 26,
        "fontWeight": 650
      },
      "h4": {
        "fontSize": 16,
        "lineHeight": 24,
        "fontWeight": 600
      },
      "body-lg": {
        "fontSize": 16,
        "lineHeight": 24,
        "fontWeight": 400
      },
      "body": {
        "fontSize": 14,
        "lineHeight": 22,
        "fontWeight": 400
      },
      "body-sm": {
        "fontSize": 13,
        "lineHeight": 20,
        "fontWeight": 400
      },
      "caption": {
        "fontSize": 12,
        "lineHeight": 18,
        "fontWeight": 400
      },
      "label": {
        "fontSize": 13,
        "lineHeight": 20,
        "fontWeight": 600
      },
      "numeric": {
        "fontSize": 28,
        "lineHeight": 36,
        "fontWeight": 650
      }
    },
    "numeric-settings": {
      "font-variant-numeric": "tabular-nums lining-nums",
      "text-align": "right",
      "currency-decimal-places": 2
    }
  },
  "spacing": {
    "base-grid": 4,
    "scale": [
      4,
      8,
      12,
      16,
      20,
      24,
      32,
      40,
      48,
      64
    ]
  },
  "radius": {
    "small": 4,
    "medium": 8,
    "large": 12,
    "xl": 16,
    "pill": 999
  },
  "elevation": {
    "level-0": "none",
    "level-1": "0 1px 2px rgba(23,33,43,0.06)",
    "level-2": "0 2px 6px rgba(23,33,43,0.08), 0 8px 24px rgba(23,33,43,0.12)"
  },
  "icon": {
    "library": "project-inline-svg (no external dependency)",
    "stroke-width": 1.5,
    "viewBox": "0 0 24 24",
    "sizes": [
      16,
      20,
      24,
      32
    ]
  },
  "layout": {
    "breakpoints": {
      "mobile": {
        "max": 767
      },
      "tablet": {
        "min": 768,
        "max": 1023
      },
      "laptop": {
        "min": 1024,
        "max": 1439
      },
      "desktop": {
        "min": 1440
      }
    },
    "sidebar": 224,
    "rail": 72,
    "header": 64,
    "compact-header": 56,
    "mobile-nav": 64,
    "content-max": 1440,
    "laptop-content-max": 1120,
    "consumer-content-max": 1120,
    "consumer-mobile-max": 480,
    "mobile-gutter": 16,
    "tablet-gutter": 24,
    "desktop-gutter": 24,
    "section-gap": 24,
    "table-row": 56,
    "table-header": 44,
    "minimum-hit-target": 44,
    "input-height": 44,
    "mobile-input-height": 48,
    "drawer": 640,
    "dialog": 480,
    "wide-dialog": 680
  },
  "motion": {
    "duration": {
      "hover": 120,
      "press": 80,
      "page": 180,
      "popover": 180,
      "dialog": 200,
      "drawer": 240,
      "status": 160,
      "chart": 300,
      "toast": 200,
      "copy-reset": 1500
    },
    "easing": {
      "enter": "cubic-bezier(0.2,0,0,1)",
      "exit": "cubic-bezier(0.4,0,1,1)"
    },
    "max-translation": 24,
    "reduced-motion": {
      "duration": 0,
      "translation": 0,
      "shimmer": false,
      "spinner": false,
      "loading-text": true
    }
  }
}
```

## 14. OpenDesign Implementation Instructions

### 14.1 执行起点与边界

工作副本以当前项目基线为起点，使用 **code to code**。先记录git HEAD与未提交文件清单，创建隔离分支/工作副本；不要用旧OpenDesign备份覆盖当前后端。当前文档任务已完成需求产出；本节是后续实施计划，不代表功能已实现或线上验收通过。

主要实现范围：

| 路径 | 职责 |
| --- | --- |
| `public/shared/coffee-ui.css` | 新Token映射与通用规则 |
| `public/merchant.html/.css/.js` | 商户结构/样式/导航/交互 |
| `public/admin.html/.css/.js` | 平台结构/样式/导航/交互 |
| `public/order.html/.css/.js` | 消费者菜单、支付、制作状态 |
| `public/merchant-format.js`、`admin-format.js` | 格式统一与异常值处理 |
| `public/merchant-demo.js` | 演示场景必要补足，保持内存隔离 |
| `public/merchant-api.js` | 仅在显示适配确有需要时修改，维持协议 |
| `public/shared/*`新增模块（可选） | 共享SVG/组件辅助；需正确处理order普通脚本加载方式 |

不得默认为了视觉改动修改数据库、权限策略、邮件开关、付款渠道、.env、Tunnel或VPS配置。当前运行使用的mock付款不是本次重新部署对象。后端契约缺能力时记录依赖，不能在页面接假成功接口。

### 14.2 能力分类

| 类别 | 本轮处理 | 示例 |
| --- | --- | --- |
| 现有UI能力重设计 | 本轮范围 | Inventory全部现有字段/操作及当前鉴权 |
| 纯前端新增交互 | 本轮可做，标明新增 | Sheet、面包屑、模块命令面板、完整ID复制、字段说明、列显隐 |
| 已有API但目前无UI | 不计作旧UI已覆盖功能，单列后续功能 | 平台订单adjudication；消费者cancel endpoint |
| 服务端能力待建设 | 不实现假入口 | 全站搜索、批量退款、跨页选中导出、通知中心、新头像上传 |
| 当前门控关闭能力 | 设计完整、默认保持关闭 | 邮件找回/邀请/验证、转让、商户收款写入、商户命令 |
| 跨项目UI | 本仓库不实施 | 独立mock付款确认页、咖啡机原生终端屏幕 |

邀请已存在账号的接受流程应与真实API核对，不能假设当前注册式表单已完整支持。报表CSV的paidOrderCount/grossProfitMinor为已有导出信息；若JSON响应没有可直接展示字段，保留CSV可达性并标明需要投影支持，不自行从不同口径数据猜算。

### 14.3 分批执行与交付关口

| 批次 | 范围 | 每批交付与通过条件 |
| --- | --- | --- |
| D0 审计冻结 | Inventory、Token、技术边界 | 对照基线核对字段，记录后续分支差异；确认JSON可解析、配对对比度 |
| D1 外壳与基准屏 | M01/M08/M10、A02、C01 + 基础组件 | 先交1440/390线框与视觉稿；认证/总览/菜单能明显区分新旧且风格一致 |
| D2 认证与组织 | M02–M09、M30–M35 | USERNAME路径可用；邮件门控；角色与范围；敏感凭证处理正确 |
| D3 资产 | M11–M19 + M20 | 列表/详情/表单全部状态；设备实时数据适配；转让保持门控 |
| D4 交易与财务 | M21–M29 | 金额口径样例；退款不乐观；成本缺项、CSV筛选/单位一致 |
| D5 平台运维 | A01–A11 | 独立Token登录、权限、登记激活、命令确认、审计；自动刷新不丢焦点 |
| D6 消费者 | C01–C05 | 下单支付幂等、provider文案、二维码稳定、SSE恢复、制作/退款状态 |
| D7 全量验收 | 三端与矩阵全部行 | 可访问性、视口、失败注入、测试、diff审查；形成可回滚版本 |

每批输出改动文件、截图、对应编号、测试结果、剩余依赖；一批未过不向后批复制错误组件。D1视觉方向需能人工评审；这是后续实施质量关口，不要求本次文档交付等待逐批回复。51场景按业务域分批制作，避免一次生成整站而后半部分粗糙。

### 14.4 数据与安全验收夹具

只在DEMO、本地隔离测试或获准测试环境中操作，不在生产创建随机商户/退款/重启设备来验证视觉。

- 金额：0、12345、负利润、大金额、null、缺字段、非法字符串；UI显示¥0.00/¥123.45/真实负值/—，不得把unknown显示0。CSV分值12345仍是12345，表头说明“分”。
- 权限：OWNER/OPERATOR/FINANCE；平台OWNER/MANAGER/OPERATOR/VIEWER；无组织/多组织/门店受限；会话失效与权限变更。
- 环境：LIVE/TEST/DEMO及账户LIVE/SANDBOX/MOCK；模拟付款必须明确“不产生真实扣款”；菜单未知provider不硬写支付宝。
- 设备：从未上线、在线空闲、在线维护、离线、任务中、快照未上报/请求失败/部分返回；真实inventory/capabilities与demo各跑一次。
- 订单：所有§11状态，支付失败但订单存在、二维码首次失败20秒重试、SSE断开/恢复、后台隐藏恢复、HOLD/部分退款。
- 财务：无记录/缺成本/仅有费用/跨月年/时区边界/最后一天；UI和API右开期间对齐，CSV带相同筛选。
- 表单：名称超长、ID长串、中文/引号/HTML样文本、空必填、重复点击、409、422、429、500、网络超时。
- 密钥：使用虚构测试值验证一次展示/复制；截图、报告和git diff不得包含真实凭证。

### 14.5 工程与视觉验收

1. 逐页在320/390/768/1024/1440验证；核心页至少保存Desktop与Mobile截图，Tablet布局不能仅文字声称通过。所有51场景至少有正常态及一个最重要失败/门控态证据。
2. 检查44px真实命中矩形、焦点、200%文字缩放、键盘弹出、安全区、Drawer关闭回焦、Tab与筛选不丢状态。
3. 图表与表格在金额/时间/环境上相同；未知不补零；会计历史不因视觉“删除”入口而删除。
4. 保留现有路由/鉴权/Header/幂等键/状态机；模块加载失败有可读恢复信息，不能一直空白。
5. 运行项目现有相关测试；无需为颜色变量逐项写镜像单元测试。UI交互、权限/金额回归、模块语法和静态资源响应才是关键证据。仓库没有npm构建时不虚构“npm build通过”。
6. 检查Docker非root用户可读所有HTML/CSS/JS、MIME正确、ES Module imports全部200；保持已有静态权限修复与缓存版本策略。各HTML资源与内部import版本同时一致，避免入口新JS依赖旧模块。
7. `git diff --check`，审查无密钥/运行数据/后端无关改动；代码评审后提交可回滚版本。部署只有在后续用户要求时进行，并核对线上资源校验值与实际显示；不能以本地截图声称VPS已同步。

### 14.6 可直接交给 OpenDesign 的启动提示词

> 请在当前coffee-cloud-mvp工作副本上使用code to code完成全量重设计。先完整读取docs/UI_UX_REDESIGN_SPEC.md和docs/design-tokens.json，以第2节Inventory与第15节矩阵为范围依据。采用Light + Fresh + Dopamine Accent，执行第14.3节分批计划：本次先完成D0核对和D1外壳/基准屏视觉稿，再按批次推进。技术栈保持原生HTML/CSS/JS，不默认新增依赖。必须实现布局与导航的实质变化，不能只换颜色或复用旧卡片排列。每批交付对应页面编号、Desktop/Tablet/Mobile效果、全部字段操作映射、状态证据、修改文件和检查结果。数据、权限、财务、支付与设备命令遵守第11和14节边界；暂关闭功能不可为展示而开启。不要部署、修改生产配置或生成真实付款/退款/设备命令。发现API能力缺口先明确记录，不用演示数据冒充真实结果。

## 15. UI Migration Coverage Matrix

下列Y表示**需求设计已找到承载位置**，不是代码已实现、运行测试已通过或已上线。每个F编号是一组源码同类字段（完整名称见表与Content），每个A编号是一项操作。三端共用的Toast/确认/Loading等组件状态映射随后列出；新增建议仍带新增标识，不伪装现有能力。

| Existing Feature | Existing Page | New Page | New Component / Interaction | Covered (Y/N) |
| --- | --- | --- | --- | --- |
| M01 页面/流程入口 | /assets/merchant.html#/login | M01 商户登录 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M01-F01 registrationMode | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F02 mailEnabled | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F03 passwordMinLength/passwordMaxLength | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F04 usernamePattern | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F05 用户名或已有已验证邮箱 | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F06 密码 | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F07 品牌/后台名称 | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F08 会话安全说明 | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-F09 登录错误 | 商户登录 | M01 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M01-A01 登录 | 商户登录 | M01 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M01-A02 创建组织账号 | 商户登录 | M01 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M01-A03 邮件开启时找回密码/邀请/验证入口 | 商户登录 | M01 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M01 状态与恢复 | 商户登录 | M01 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M02 页面/流程入口 | #/register | M02 创建组织账号 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M02-F01 USERNAME: username | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F02 displayName | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F03 tenantName | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F04 password | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F05 EMAIL: email | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F06 用户名3–32位规则 | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F07 密码15–128字符配置 | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F08 OWNER身份说明 | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-F09 REGISTERED/VERIFICATION_PENDING/未知返回状态 | 创建组织账号 | M02 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M02-A01 创建账号 | 创建组织账号 | M02 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M02-A02 字段校验 | 创建组织账号 | M02 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M02-A03 返回登录 | 创建组织账号 | M02 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M02-A04 注册结果去登录 | 创建组织账号 | M02 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M02 状态与恢复 | 创建组织账号 | M02 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M03 页面/流程入口 | #/forgot | M03 找回密码 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M03-F01 注册邮箱 | 找回密码 | M03 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M03-F02 邮件服务状态 | 找回密码 | M03 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M03-F03 统一受理结果 | 找回密码 | M03 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M03-F04 错误 | 找回密码 | M03 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M03-F05 联系平台管理员说明 | 找回密码 | M03 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M03-A01 发送找回链接（邮件开放时） | 找回密码 | M03 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M03-A02 返回登录 | 找回密码 | M03 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M03 状态与恢复 | 找回密码 | M03 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M04 页面/流程入口 | #/reset | M04 重置密码 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M04-F01 邮件片段 token | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-F02 新密码 | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-F03 确认密码 | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-F04 密码长度规则 | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-F05 密码更新结果 | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-F06 失效/已使用 token 错误 | 重置密码 | M04 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M04-A01 设置新密码 | 重置密码 | M04 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M04-A02 返回登录 | 重置密码 | M04 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M04-A03 更新后去登录 | 重置密码 | M04 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M04 状态与恢复 | 重置密码 | M04 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M05 页面/流程入口 | #/verify | M05 验证邮箱 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M05-F01 验证token | 验证邮箱 | M05 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M05-F02 一次性链接说明 | 验证邮箱 | M05 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M05-F03 验证结果 | 验证邮箱 | M05 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M05-F04 失败原因 | 验证邮箱 | M05 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M05-A01 主动确认验证邮箱 | 验证邮箱 | M05 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M05-A02 手动粘贴token | 验证邮箱 | M05 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M05-A03 返回登录 | 验证邮箱 | M05 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M05 状态与恢复 | 验证邮箱 | M05 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M06 页面/流程入口 | #/invite | M06 接受成员邀请 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M06-F01 邀请token | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-F02 displayName | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-F03 password | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-F04 密码规则 | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-F05 已有账号提示 | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-F06 接受结果 | 接受成员邀请 | M06 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M06-A01 接受邀请 | 接受成员邀请 | M06 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M06-A02 手动输入token | 接受成员邀请 | M06 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M06-A03 返回登录 | 接受成员邀请 | M06 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M06 状态与恢复 | 接受成员邀请 | M06 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M07 页面/流程入口 | 认证启动及各认证结果页 | M07 认证配置失败与认证结果 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M07-F01 错误标题 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F02 详细错误信息 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F03 requestId（若返回） | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F04 配置依赖说明 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F05 结果标题/说明 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F06 注册/验证/重置/邀请状态 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-F07 邮件不可用说明 | 认证配置失败与认证结果 | M07 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M07-A01 重试配置 | 认证配置失败与认证结果 | M07 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M07-A02 去登录或返回登录（按结果） | 认证配置失败与认证结果 | M07 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M07-A03 查看失败说明 | 认证配置失败与认证结果 | M07 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M07 状态与恢复 | 认证配置失败与认证结果 | M07 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M08 页面/流程入口 | 所有商户认证后路由 | M08 商户工作区与账号菜单 | 三端布局 + Navigation / Select / DateRange / SegmentedControl / Popover / Alert | Y |
| M08-F01 当前组织名称/tenantId/成员关系id | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F02 组织角色 | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F03 当前用户姓名/username/email | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F04 门店id/名称 | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F05 日期from/to | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F06 组织timezone | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F07 LIVE/TEST | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F08 当前导航/标题/描述 | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F09 revokedCount | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-F10 无访问权限说明 | 商户工作区与账号菜单 | M08 Content / Information Priority | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M08-A01 组织切换 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A02 门店筛选 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A03 今天/近7天/本月/本年/自定义日期 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A04 应用范围 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A05 LIVE/TEST切换 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A06 13主导航 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A07 移动导航展开/关闭 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A08 重新验证身份 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A09 撤销其他会话并确认 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A10 退出 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08-A11 无权限回可访问首页 | 商户工作区与账号菜单 | M08 Primary / Secondary Action | Navigation / Select / DateRange / SegmentedControl / Popover / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M08 状态与恢复 | 商户工作区与账号菜单 | M08 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M09 页面/流程入口 | 账号菜单/敏感操作 REAUTH_REQUIRED | M09 重新验证身份 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M09-F01 当前密码 | 重新验证身份 | M09 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M09-F02 敏感操作原因 | 重新验证身份 | M09 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M09-F03 validUntil | 重新验证身份 | M09 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M09-F04 错误 | 重新验证身份 | M09 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M09-A01 验证身份 | 重新验证身份 | M09 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M09-A02 取消 | 重新验证身份 | M09 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M09-A03 验证后续接原操作 | 重新验证身份 | M09 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M09 状态与恢复 | 重新验证身份 | M09 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M10 页面/流程入口 | #/dashboard | M10 经营总览 | 三端布局 + KPI / Chart / Alert / List / Table / Filter | Y |
| M10-F01 设备总数/在线数/在线率 | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F02 完成杯数 | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F03 待处理告警数 | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F04 实收receivedMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F05 退款refundedMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F06 净收款netCashMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F07 营业净收入recognizedRevenueMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F08 估算利润estimatedProfitMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F09 completeness.status/missing | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F10 趋势date/receivedMinor/estimatedProfitMinor | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F11 告警severity/title/description与告警条数 | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F12 最近订单id/orderNo/createdAt/storeNameSnapshot/deviceNameSnapshot/totalMinor/paymentStatus/productionStatus/environment | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-F13 有限发布说明 | 经营总览 | M10 Content / Information Priority | KPI / Chart / Alert / List / Table / Filter；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M10-A01 范围筛选 | 经营总览 | M10 Primary / Secondary Action | KPI / Chart / Alert / List / Table / Filter；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M10-A02 分区重试 | 经营总览 | M10 Primary / Secondary Action | KPI / Chart / Alert / List / Table / Filter；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M10-A03 打开最近订单详情 | 经营总览 | M10 Primary / Secondary Action | KPI / Chart / Alert / List / Table / Filter；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M10-A04 全部订单 | 经营总览 | M10 Primary / Secondary Action | KPI / Chart / Alert / List / Table / Filter；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M10-A05 权限适配的经营/运维视图 | 经营总览 | M10 Primary / Secondary Action | KPI / Chart / Alert / List / Table / Filter；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M10 状态与恢复 | 经营总览 | M10 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M11 页面/流程入口 | #/devices | M11 我的设备列表 | 三端布局 + Search / Filter / Table / List / Drawer | Y |
| M11-F01 查询q | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F02 生命周期筛选 | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F03 门店storeId | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F04 id/deviceId | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F05 name | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F06 serialNumber | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F07 storeName | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F08 lifecycle | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F09 online/lastSeenAt | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-F10 version/ownershipVersion | 我的设备列表 | M11 Content / Information Priority | Search / Filter / Table / List / Drawer；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M11-A01 搜索设备名称/ID/SN | 我的设备列表 | M11 Primary / Secondary Action | Search / Filter / Table / List / Drawer；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M11-A02 按生命周期/门店过滤 | 我的设备列表 | M11 Primary / Secondary Action | Search / Filter / Table / List / Drawer；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M11-A03 认领设备 | 我的设备列表 | M11 Primary / Secondary Action | Search / Filter / Table / List / Drawer；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M11-A04 打开设备详情 | 我的设备列表 | M11 Primary / Secondary Action | Search / Filter / Table / List / Drawer；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M11 状态与恢复 | 我的设备列表 | M11 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M12 页面/流程入口 | 设备列表认领弹窗 | M12 认领出厂设备 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M12-F01 claimCode | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-F02 storeId | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-F03 可选name | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-F04 设备归属校验结果 | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-F05 错误/幂等冲突 | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-F06 平台归属与历史订单说明 | 认领出厂设备 | M12 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M12-A01 选择门店 | 认领出厂设备 | M12 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M12-A02 输入资产认领码 | 认领出厂设备 | M12 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M12-A03 认领 | 认领出厂设备 | M12 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M12-A04 取消 | 认领出厂设备 | M12 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M12-A05 无门店时引导创建门店 | 认领出厂设备 | M12 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M12 状态与恢复 | 认领出厂设备 | M12 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M13 页面/流程入口 | 设备列表 → Drawer | M13 商户设备详情 | 三端布局 + Drawer / Tabs / Status / DefinitionList / List / Menu | Y |
| M13-F01 设备name/deviceId/serialNumber | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F02 storeName | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F03 lifecycle | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F04 online/lastSeenAt | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F05 ownershipVersion/version | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F06 currentJob.id/status/productName（若有） | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F07 capabilities.id/name/estimatedSeconds及真实recipeId/estimatedDurationSeconds兼容 | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F08 inventory名称/单位/状态/onHandQuantity/reservedQuantity/availableQuantity | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F09 alerts.severity/title/description | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F10 allowedActions | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-F11 命令结果区域id/status/resultMessage；PENDING/EXECUTING/SUCCEEDED/FAILED/TIMEOUT；查询超时/失败 | 商户设备详情 | M13 Content / Information Priority | Drawer / Tabs / Status / DefinitionList / List / Menu；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M13-A01 编辑资料 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A02 生命周期变更 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A03 申请解绑 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A04 发起转让 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A05 允许的设备命令RELOAD_CONFIG/SYNC_CONFIG/CLEAN/RESTART_APP（各自确认） | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A06 关闭详情 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13-A07 失败重试 | 商户设备详情 | M13 Primary / Secondary Action | Drawer / Tabs / Status / DefinitionList / List / Menu；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M13 状态与恢复 | 商户设备详情 | M13 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M14 页面/流程入口 | 设备详情 → 编辑资料 | M14 编辑商户设备资料 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M14-F01 deviceId | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-F02 name | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-F03 storeId | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-F04 version | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-F05 归属说明 | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-F06 字段错误/409 | 编辑商户设备资料 | M14 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M14-A01 修改名称 | 编辑商户设备资料 | M14 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M14-A02 重新分配门店 | 编辑商户设备资料 | M14 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M14-A03 保存 | 编辑商户设备资料 | M14 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M14-A04 取消 | 编辑商户设备资料 | M14 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M14-A05 冲突重新加载 | 编辑商户设备资料 | M14 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M14 状态与恢复 | 编辑商户设备资料 | M14 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M15 页面/流程入口 | 设备详情 → 生命周期变更 | M15 商户设备生命周期 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M15-F01 设备对象 | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-F02 目标action=SUSPEND/RESUME/ARCHIVE（按允许项） | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-F03 reason | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-F04 version | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-F05 归档影响 | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-F06 确认文字 | 商户设备生命周期 | M15 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M15-A01 选择动作 | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15-A02 填写原因 | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15-A03 确认提交 | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15-A04 归档二次输入“归档” | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15-A05 需要时重新验证 | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15-A06 取消/冲突重载 | 商户设备生命周期 | M15 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M15 状态与恢复 | 商户设备生命周期 | M15 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M16 页面/流程入口 | 设备详情 → 申请解绑 | M16 申请设备解绑 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M16-F01 设备标识/名称 | 申请设备解绑 | M16 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M16-F02 reason | 申请设备解绑 | M16 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M16-F03 ownershipVersion | 申请设备解绑 | M16 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M16-F04 请求status | 申请设备解绑 | M16 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M16-F05 阻断原因 | 申请设备解绑 | M16 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M16-A01 填写原因 | 申请设备解绑 | M16 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M16-A02 提交解绑申请 | 申请设备解绑 | M16 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M16-A03 取消 | 申请设备解绑 | M16 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M16 状态与恢复 | 申请设备解绑 | M16 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M17 页面/流程入口 | 设备详情 → 发起转让 | M17 发起设备转让 | 三端布局 + Form / Button / Alert / Dialog | Y |
| M17-F01 设备标识/名称 | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-F02 targetTenantReference | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-F03 reason | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-F04 ownershipVersion | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-F05 result.status | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-F06 blockingReasons | 发起设备转让 | M17 Content / Information Priority | Form / Button / Alert / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M17-A01 填目标组织标识 | 发起设备转让 | M17 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M17-A02 填原因 | 发起设备转让 | M17 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M17-A03 提交转让 | 发起设备转让 | M17 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M17-A04 取消 | 发起设备转让 | M17 Primary / Secondary Action | Form / Button / Alert / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M17 状态与恢复 | 发起设备转让 | M17 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M18 页面/流程入口 | #/transfers | M18 设备转让记录 | 三端布局 + Table / Status / Timeline / Dialog | Y |
| M18-F01 设备deviceName/deviceId | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F02 createdAt | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F03 reason | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F04 direction(IN/OUT) | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F05 counterpartName | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F06 status | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F07 blockingReasons | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-F08 version | 设备转让记录 | M18 Content / Information Priority | Table / Status / Timeline / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M18-A01 刷新 | 设备转让记录 | M18 Primary / Secondary Action | Table / Status / Timeline / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M18-A02 确认接收（转入待接收） | 设备转让记录 | M18 Primary / Secondary Action | Table / Status / Timeline / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M18-A03 取消（允许状态） | 设备转让记录 | M18 Primary / Secondary Action | Table / Status / Timeline / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M18-A04 确认弹窗 | 设备转让记录 | M18 Primary / Secondary Action | Table / Status / Timeline / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M18 状态与恢复 | 设备转让记录 | M18 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M19 页面/流程入口 | #/stores | M19 门店列表与门店编辑 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M19-F01 store.id/name/address/status/deviceCount/version | 门店列表与门店编辑 | M19 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M19-F02 编辑名称/地址 | 门店列表与门店编辑 | M19 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M19-F03 ACTIVE/ARCHIVED | 门店列表与门店编辑 | M19 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M19-F04 归档不可直接恢复说明 | 门店列表与门店编辑 | M19 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M19-A01 新增门店 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19-A02 编辑 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19-A03 归档并确认 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19-A04 保存 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19-A05 取消 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19-A06 冲突重载 | 门店列表与门店编辑 | M19 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M19 状态与恢复 | 门店列表与门店编辑 | M19 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M20 页面/流程入口 | #/prices | M20 商品当前价与计划价 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M20-F01 门店筛选storeId | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F02 设备筛选deviceId | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F03 name/sku | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F04 scope(组织/门店/设备) | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F05 priceMinor | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F06 effectiveAt | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F07 version | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F08 当前价/计划生效状态 | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-F09 新增SKU/name/storeId/deviceId/priceMinor/effectiveAt | 商品当前价与计划价 | M20 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M20-A01 筛选门店/设备 | 商品当前价与计划价 | M20 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M20-A02 新增价格 | 商品当前价与计划价 | M20 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M20-A03 立即或计划生效 | 商品当前价与计划价 | M20 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M20-A04 保存 | 商品当前价与计划价 | M20 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M20-A05 取消 | 商品当前价与计划价 | M20 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M20 状态与恢复 | 商品当前价与计划价 | M20 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M21 页面/流程入口 | #/orders | M21 商户订单列表 | 三端布局 + Filter / Table / List / Drawer / Pagination | Y |
| M21-F01 状态筛选全部/PAID/PENDING/REFUNDING/REFUNDED/PARTIALLY_REFUNDED/QUEUED/MAKING/HOLD/DELIVERED/FAILED/CANCELLED | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F02 deviceId筛选 | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F03 全局日期/门店/LIVE或TEST | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F04 id/orderNo/createdAt | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F05 storeNameSnapshot/deviceNameSnapshot/deviceId | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F06 items.name/quantity | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F07 totalMinor | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F08 paymentStatus | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F09 productionStatus | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F10 environment | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-F11 nextCursor | 商户订单列表 | M21 Content / Information Priority | Filter / Table / List / Drawer / Pagination；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M21-A01 查询 | 商户订单列表 | M21 Primary / Secondary Action | Filter / Table / List / Drawer / Pagination；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M21-A02 更改筛选 | 商户订单列表 | M21 Primary / Secondary Action | Filter / Table / List / Drawer / Pagination；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M21-A03 加载更多 | 商户订单列表 | M21 Primary / Secondary Action | Filter / Table / List / Drawer / Pagination；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M21-A04 打开详情 | 商户订单列表 | M21 Primary / Secondary Action | Filter / Table / List / Drawer / Pagination；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M21-A05 从总览直达订单 | 商户订单列表 | M21 Primary / Secondary Action | Filter / Table / List / Drawer / Pagination；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M21 状态与恢复 | 商户订单列表 | M21 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M22 页面/流程入口 | 订单列表/总览 → 订单详情 | M22 商户订单详情 | 三端布局 + Drawer / DefinitionList / Timeline / Status / List | Y |
| M22-F01 orderNo/id | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F02 门店/设备快照 | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F03 paymentStatus/productionStatus/environment | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F04 createdAt/paidAt/deliveredAt | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F05 totalMinor/receivedMinor/refundedMinor | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F06 items.name/quantity/unitPriceMinor | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F07 payments.provider/accountLabel/environment/status/amountMinor | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F08 refunds.status/reason/amountMinor | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F09 costSummary.materialCostMinor/status | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F10 timeline.createdAt或at/description或label/status | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-F11 allowedActions | 商户订单详情 | M22 Content / Information Priority | Drawer / DefinitionList / Timeline / Status / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M22-A01 查看商品/支付退款/成本/时间线 | 商户订单详情 | M22 Primary / Secondary Action | Drawer / DefinitionList / Timeline / Status / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M22-A02 发起退款（REFUND允许时） | 商户订单详情 | M22 Primary / Secondary Action | Drawer / DefinitionList / Timeline / Status / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M22-A03 关闭 | 商户订单详情 | M22 Primary / Secondary Action | Drawer / DefinitionList / Timeline / Status / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M22-A04 失败重试 | 商户订单详情 | M22 Primary / Secondary Action | Drawer / DefinitionList / Timeline / Status / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M22 状态与恢复 | 商户订单详情 | M22 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M23 页面/流程入口 | 订单详情 → 发起退款 | M23 部分或全额退款 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M23-F01 订单号 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F02 订单总额 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F03 实收 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F04 已退 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F05 可退上限 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F06 amountMinor元输入 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F07 reason | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F08 请求状态 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F09 字段错误 | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-F10 REAUTH_REQUIRED | 部分或全额退款 | M23 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M23-A01 填写退款金额/原因 | 部分或全额退款 | M23 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M23-A02 取消 | 部分或全额退款 | M23 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M23-A03 确认退款 | 部分或全额退款 | M23 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M23-A04 重新验证 | 部分或全额退款 | M23 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M23-A05 提交后查看退款记录 | 部分或全额退款 | M23 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M23 状态与恢复 | 部分或全额退款 | M23 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M24 页面/流程入口 | #/materials → materials tab | M24 物料档案与新增物料 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M24-F01 物料id/name | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-F02 unit | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-F03 unitPrecision | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-F04 averageUnitCostMinor | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-F05 status | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-F06 新增名称/单位/数量小数位 | 物料档案与新增物料 | M24 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M24-A01 物料/采购/库存/出入库四Tab切换 | 物料档案与新增物料 | M24 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M24-A02 新增物料 | 物料档案与新增物料 | M24 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M24-A03 保存 | 物料档案与新增物料 | M24 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M24-A04 取消 | 物料档案与新增物料 | M24 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M24 状态与恢复 | 物料档案与新增物料 | M24 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M25 页面/流程入口 | #/materials → purchases tab | M25 采购列表、草稿编辑与入账 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M25-F01 采购id/supplier/purchasedOn/storeId/note/status/version | 采购列表、草稿编辑与入账 | M25 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M25-F02 lines.materialId/materialName/quantity/unit/totalCostMinor | 采购列表、草稿编辑与入账 | M25 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M25-F03 已知合计/缺项标志 | 采购列表、草稿编辑与入账 | M25 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M25-F04 门店与日期筛选 | 采购列表、草稿编辑与入账 | M25 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M25-A01 新增采购 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A02 编辑DRAFT | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A03 添加/删除草稿明细行 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A04 保存草稿 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A05 POSTED只读 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A06 入账并确认 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25-A07 取消 | 采购列表、草稿编辑与入账 | M25 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M25 状态与恢复 | 采购列表、草稿编辑与入账 | M25 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M26 页面/流程入口 | #/materials → inventory tab | M26 账面库存 | 三端布局 + Table / List / Select / Alert | Y |
| M26-F01 门店筛选 | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F02 物料name/unit | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F03 deviceName/deviceId | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F04 onHandQuantity | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F05 reservedQuantity | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F06 availableQuantity | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-F07 costStatus | 账面库存 | M26 Content / Information Priority | Table / List / Select / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M26-A01 筛选门店 | 账面库存 | M26 Primary / Secondary Action | Table / List / Select / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M26-A02 加载/重试库存 | 账面库存 | M26 Primary / Secondary Action | Table / List / Select / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M26-A03 切换物料相关Tab | 账面库存 | M26 Primary / Secondary Action | Table / List / Select / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M26 状态与恢复 | 账面库存 | M26 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M27 页面/流程入口 | #/materials → movements tab | M27 出入库流水与登记 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M27-F01 类型RESTOCK/WASTE/ADJUSTMENT/TRANSFER | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F02 createdAt | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F03 materialId/materialName | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F04 eventId | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F05 quantity/unit | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F06 sourceStore/Device | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F07 targetStore/Device | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F08 reason | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-F09 新增类型/物料/数量/原因/来源门店设备/目标门店设备 | 出入库流水与登记 | M27 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M27-A01 类型过滤 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27-A02 新增出入库 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27-A03 按类型切换来源目标字段 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27-A04 确认语义 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27-A05 提交 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27-A06 取消 | 出入库流水与登记 | M27 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M27 状态与恢复 | 出入库流水与登记 | M27 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M28 页面/流程入口 | #/expenses | M28 运营费用、入账与冲正 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M28-F01 id/category(RENT/LABOR/UTILITIES/MAINTENANCE/OTHER) | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F02 amountMinor | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F03 storeId/deviceId | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F04 occurredOn | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F05 allocationMethod(DAILY_EQUAL/一次性) | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F06 allocationStart/allocationEnd | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F07 分摊天数/近似每日金额 | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F08 note | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F09 status(DRAFT/POSTED/REVERSED) | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F10 version | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F11 冲正reason | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-F12 门店/日期过滤 | 运营费用、入账与冲正 | M28 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M28-A01 新增费用 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A02 选择归属 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A03 选择分摊方式/日期 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A04 保存草稿 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A05 入账确认 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A06 已入账冲正及填原因 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28-A07 取消 | 运营费用、入账与冲正 | M28 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M28 状态与恢复 | 运营费用、入账与冲正 | M28 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M29 页面/流程入口 | #/reports | M29 日/月/年经营报表 | 三端布局 + DateRange / SegmentedControl / Chart / Table / DefinitionList / Download | Y |
| M29-F01 period.from/to/timezone | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F02 grain(DAY/MONTH/YEAR) | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F03 storeId | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F04 environment | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F05 图表metric(netCashMinor/recognizedRevenueMinor/materialCostMinor/estimatedProfitMinor) | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F06 每期period | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F07 receivedMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F08 refundedMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F09 netCashMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F10 recognizedRevenueMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F11 materialCostMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F12 wasteCostMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F13 paymentFeeMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F14 operatingExpenseMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F15 estimatedProfitMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F16 deliveredCupCount | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F17 completeness.status/missing | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F18 totals同名字段 | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F19 CSV独有paidOrderCount/grossProfitMinor | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F20 notes | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-F21 导出filename | 日/月/年经营报表 | M29 Content / Information Priority | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M29-A01 切日/月/年 | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29-A02 切图表指标 | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29-A03 门店日期环境筛选 | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29-A04 展开口径说明 | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29-A05 查看全部明细和合计 | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29-A06 导出CSV | 日/月/年经营报表 | M29 Primary / Secondary Action | DateRange / SegmentedControl / Chart / Table / DefinitionList / Download；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M29 状态与恢复 | 日/月/年经营报表 | M29 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M30 页面/流程入口 | #/members → 成员 | M30 成员权限与编辑 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M30-F01 member.id/displayName/username/email | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-F02 role(OWNER/OPERATOR/FINANCE) | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-F03 storeScope.mode/storeIds | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-F04 status(ACTIVE/SUSPENDED) | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-F05 version | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-F06 末位OWNER保护说明 | 成员权限与编辑 | M30 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M30-A01 编辑角色 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30-A02 启停成员 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30-A03 ALL/SELECTED门店范围与多选 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30-A04 保存 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30-A05 取消 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30-A06 409冲突重载 | 成员权限与编辑 | M30 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M30 状态与恢复 | 成员权限与编辑 | M30 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M31 页面/流程入口 | #/members → 邀请 | M31 邀请列表、创建与撤销 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M31-F01 invitation.id/email/role/storeScope.mode/storeIds/status | 邀请列表、创建与撤销 | M31 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M31-F02 deliveryStatus(QUEUED/UNAVAILABLE等) | 邀请列表、创建与撤销 | M31 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M31-F03 expiresAt | 邀请列表、创建与撤销 | M31 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M31-F04 创建邮箱/角色/门店范围 | 邀请列表、创建与撤销 | M31 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M31-A01 查看邀请 | 邀请列表、创建与撤销 | M31 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M31-A02 创建邀请（开放时） | 邀请列表、创建与撤销 | M31 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M31-A03 撤销PENDING并确认 | 邀请列表、创建与撤销 | M31 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M31-A04 取消 | 邀请列表、创建与撤销 | M31 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M31 状态与恢复 | 邀请列表、创建与撤销 | M31 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M32 页面/流程入口 | #/accounts | M32 收款账户与配置校验 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M32-F01 account.id/label/provider | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-F02 appIdMasked/merchantIdMasked | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-F03 environment(LIVE/SANDBOX/MOCK) | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-F04 status/isDefault/configuredAt/version | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-F05 新增label/provider/environment/appId/merchantId/appPrivateKey/providerPublicKey | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-F06 校验status/checks.name/status/message | 收款账户与配置校验 | M32 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M32-A01 查看脱敏账户 | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32-A02 新增账户（开放时） | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32-A03 校验及查看结果 | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32-A04 设为默认并确认 | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32-A05 非默认账户停用并确认 | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32-A06 取消 | 收款账户与配置校验 | M32 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M32 状态与恢复 | 收款账户与配置校验 | M32 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M33 页面/流程入口 | #/settings | M33 组织设置 | 三端布局 + Table / Form / Dialog / Alert | Y |
| M33-F01 tenant.id/name/timezone/version | 组织设置 | M33 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M33-F02 时区选项Asia/Shanghai/Asia/Tokyo/Asia/Singapore/Europe/London/America/New_York/UTC | 组织设置 | M33 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M33-F03 账期变更说明 | 组织设置 | M33 Content / Information Priority | Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M33-A01 修改组织名称 | 组织设置 | M33 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M33-A02 选择时区 | 组织设置 | M33 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M33-A03 保存 | 组织设置 | M33 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M33-A04 409重新加载 | 组织设置 | M33 Primary / Secondary Action | Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M33 状态与恢复 | 组织设置 | M33 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M34 页面/流程入口 | #/audit | M34 商户审计 | 三端布局 + Filter / Table / Timeline / ExpandableSection / Copy | Y |
| M34-F01 日期区间 | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F02 action过滤 | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F03 createdAt | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F04 actorName | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F05 requestId | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F06 action | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F07 resourceType/resourceLabel | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F08 outcome | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-F09 nextCursor | 商户审计 | M34 Content / Information Priority | Filter / Table / Timeline / ExpandableSection / Copy；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M34-A01 查询 | 商户审计 | M34 Primary / Secondary Action | Filter / Table / Timeline / ExpandableSection / Copy；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M34-A02 日期/动作筛选 | 商户审计 | M34 Primary / Secondary Action | Filter / Table / Timeline / ExpandableSection / Copy；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M34-A03 加载更多 | 商户审计 | M34 Primary / Secondary Action | Filter / Table / Timeline / ExpandableSection / Copy；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M34 状态与恢复 | 商户审计 | M34 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| M35 页面/流程入口 | 仅 /assets/merchant.html?demo=1 | M35 商户演示工具 | 三端布局 + Banner / Switch / Drawer / Button | Y |
| M35-F01 DEMO横幅 | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-F02 当前角色OWNER/OPERATOR/FINANCE | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-F03 empty/forbidden/network/slow故障开关 | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-F04 邮件不可用开关 | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-F05 claimCode/verifyToken/resetToken/inviteToken固定演示值 | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-F06 退款推进数量 | 商户演示工具 | M35 Content / Information Priority | Banner / Switch / Drawer / Button；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| M35-A01 展开/收起工具 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35-A02 切角色 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35-A03 故障模拟 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35-A04 模拟退款成功 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35-A05 重置内存数据 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35-A06 切邮件故障 | 商户演示工具 | M35 Primary / Secondary Action | Banner / Switch / Drawer / Button；依本页Interaction、权限门控及Mobile承载方式 | Y |
| M35 状态与恢复 | 商户演示工具 | M35 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A01 页面/流程入口 | /admin → /assets/admin.html | A01 平台 Token 登录 | 三端布局 + Form / Button / Alert | Y |
| A01-F01 API Token | 平台 Token 登录 | A01 Content / Information Priority | Form / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A01-F02 平台名称 | 平台 Token 登录 | A01 Content / Information Priority | Form / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A01-F03 会话仅内存说明 | 平台 Token 登录 | A01 Content / Information Priority | Form / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A01-F04 登录错误 | 平台 Token 登录 | A01 Content / Information Priority | Form / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A01-F05 运营员身份/角色 | 平台 Token 登录 | A01 Content / Information Priority | Form / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A01-A01 登录 | 平台 Token 登录 | A01 Primary / Secondary Action | Form / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A01-A02 密码式Token输入 | 平台 Token 登录 | A01 Primary / Secondary Action | Form / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A01-A03 登录失败重试 | 平台 Token 登录 | A01 Primary / Secondary Action | Form / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A01 状态与恢复 | 平台 Token 登录 | A01 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A02 页面/流程入口 | admin.html#/dashboard\|devices\|orders\|access\|audit | A02 平台工作区与刷新控制 | 三端布局 + Navigation / Breadcrumb / Popover / Button / Status | Y |
| A02-F01 五个导航与当前标题/说明 | 平台工作区与刷新控制 | A02 Content / Information Priority | Navigation / Breadcrumb / Popover / Button / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A02-F02 运营员displayName/actorId/role/tokenLabel | 平台工作区与刷新控制 | A02 Content / Information Priority | Navigation / Breadcrumb / Popover / Button / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A02-F03 刷新时间/倒计时 | 平台工作区与刷新控制 | A02 Content / Information Priority | Navigation / Breadcrumb / Popover / Button / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A02-F04 权限不足说明 | 平台工作区与刷新控制 | A02 Content / Information Priority | Navigation / Breadcrumb / Popover / Button / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A02-A01 切换模块 | 平台工作区与刷新控制 | A02 Primary / Secondary Action | Navigation / Breadcrumb / Popover / Button / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A02-A02 立即刷新 | 平台工作区与刷新控制 | A02 Primary / Secondary Action | Navigation / Breadcrumb / Popover / Button / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A02-A03 自动刷新 | 平台工作区与刷新控制 | A02 Primary / Secondary Action | Navigation / Breadcrumb / Popover / Button / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A02-A04 退出登录 | 平台工作区与刷新控制 | A02 Primary / Secondary Action | Navigation / Breadcrumb / Popover / Button / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A02-A05 无权限返回可用页 | 平台工作区与刷新控制 | A02 Primary / Secondary Action | Navigation / Breadcrumb / Popover / Button / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A02 状态与恢复 | 平台工作区与刷新控制 | A02 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A03 页面/流程入口 | admin.html#/dashboard | A03 平台运营总览 | 三端布局 + Metric / List / Table / Status / Alert | Y |
| A03-F01 设备total/online/restricted | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F02 订单today/readyToday/successRate/exceptionsToday | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F03 manualReviews | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F04 pendingRefunds | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F05 pendingBusinessEvents | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F06 pendingCommands | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-F07 最近8笔订单的A08全部概览字段 | 平台运营总览 | A03 Content / Information Priority | Metric / List / Table / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A03-A01 刷新 | 平台运营总览 | A03 Primary / Secondary Action | Metric / List / Table / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A03-A02 展开最近订单 | 平台运营总览 | A03 Primary / Secondary Action | Metric / List / Table / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A03-A03 前往订单/设备 | 平台运营总览 | A03 Primary / Secondary Action | Metric / List / Table / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A03 状态与恢复 | 平台运营总览 | A03 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A04 页面/流程入口 | admin.html#/devices | A04 平台设备列表 | 三端布局 + Table / Search / Select / Drawer / Status | Y |
| A04-F01 搜索deviceId/SN/门店 | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F02 连接筛选 | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F03 online/hasEverConnected | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F04 deviceId/serialNumber | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F05 storeName/storeId | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F06 profileComplete | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F07 lifecycleStatus | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F08 activeOrderCount | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F09 lastHeartbeatAt | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-F10 softwareVersion | 平台设备列表 | A04 Content / Information Priority | Table / Search / Select / Drawer / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A04-A01 搜索 | 平台设备列表 | A04 Primary / Secondary Action | Table / Search / Select / Drawer / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A04-A02 筛选 | 平台设备列表 | A04 Primary / Secondary Action | Table / Search / Select / Drawer / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A04-A03 选择设备 | 平台设备列表 | A04 Primary / Secondary Action | Table / Search / Select / Drawer / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A04-A04 登记设备 | 平台设备列表 | A04 Primary / Secondary Action | Table / Search / Select / Drawer / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A04-A05 刷新 | 平台设备列表 | A04 Primary / Secondary Action | Table / Search / Select / Drawer / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A04 状态与恢复 | 平台设备列表 | A04 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A05 页面/流程入口 | 设备列表详情 | A05 平台设备详情与远程命令 | 三端布局 + Drawer / Tabs / List / Progress / Status / Dialog | Y |
| A05-F01 deviceId/deviceName/serialNumber | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F02 storeName/storeId/cityCode/timezone | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F03 profileComplete/profileSource | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F04 instanceId | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F05 softwareVersion | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F06 activeBootId | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F07 lastSequence | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F08 heartbeatCount/eventCount/commandCount | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F09 activeOrderCount | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F10 capabilities/inventory快照version/receivedAt | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F11 lastHeartbeatAt | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F12 lastErrorSummary | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F13 online/hasEverConnected/lifecycleStatus | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F14 recipes: name/recipeId/version/estimatedDurationSeconds/priceMinor/currency/available | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F15 materials: name/materialId/available/capacity/unit/status | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-F16 重启影响与确认文字 | 平台设备详情与远程命令 | A05 Content / Information Priority | Drawer / Tabs / List / Progress / Status / Dialog；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A05-A01 查看基本/能力/物料/操作分区 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A02 变更生命周期 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A03 生成激活码 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A04 RELOAD_CONFIG重载 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A05 SYNC_CONFIG同步 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A06 重启应用二次确认 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05-A07 关闭详情 | 平台设备详情与远程命令 | A05 Primary / Secondary Action | Drawer / Tabs / List / Progress / Status / Dialog；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A05 状态与恢复 | 平台设备详情与远程命令 | A05 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A06 页面/流程入口 | 设备操作弹窗 | A06 登记设备、激活码与生命周期 | 三端布局 + Dialog / Form / Secret / Button / Alert | Y |
| A06-F01 deviceId格式coffee-bot-[0-9]{3,6} | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F02 serialNumber格式CB-[0-9]{4}-[0-9]{3,6} | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F03 instanceId/storeId可选 | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F04 重复登记说明 | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F05 activationCode/expiresAt | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F06 目标生命周期 | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F07 必填reason | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-F08 当前设备ID | 登记设备、激活码与生命周期 | A06 Content / Information Priority | Dialog / Form / Secret / Button / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A06-A01 登记并生成激活码 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06-A02 取消 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06-A03 重新生成激活码 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06-A04 复制一次性激活码 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06-A05 关闭秘密展示 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06-A06 提交生命周期变更 | 登记设备、激活码与生命周期 | A06 Primary / Secondary Action | Dialog / Form / Secret / Button / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A06 状态与恢复 | 登记设备、激活码与生命周期 | A06 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A07 页面/流程入口 | admin.html#/orders | A07 平台订单筛选 | 三端布局 + Filter / Select / Input / Table | Y |
| A07-F01 订单状态筛选全部/CREATED/AWAITING_PAYMENT/QUEUED/DISPATCHED/ACCEPTED/MAKING/HOLD/READY/FAILED/REFUNDED/CANCELLED/EXPIRED | 平台订单筛选 | A07 Content / Information Priority | Filter / Select / Input / Table；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A07-F02 deviceId | 平台订单筛选 | A07 Content / Information Priority | Filter / Select / Input / Table；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A07-F03 当前返回范围/条数 | 平台订单筛选 | A07 Content / Information Priority | Filter / Select / Input / Table；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A07-A01 查询 | 平台订单筛选 | A07 Primary / Secondary Action | Filter / Select / Input / Table；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A07-A02 Enter查询 | 平台订单筛选 | A07 Primary / Secondary Action | Filter / Select / Input / Table；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A07-A03 刷新 | 平台订单筛选 | A07 Primary / Secondary Action | Filter / Select / Input / Table；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A07-A04 展开订单 | 平台订单筛选 | A07 Primary / Secondary Action | Filter / Select / Input / Table；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A07 状态与恢复 | 平台订单筛选 | A07 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A08 页面/流程入口 | 平台总览/订单展开 | A08 平台订单行与详情 | 三端布局 + Table / Drawer / List / Alert / Status | Y |
| A08-F01 orderNo/orderId | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F02 deviceId | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F03 storeId或paymentMode=TEST_FREE免支付联调 | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F04 productName | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F05 totalAmountMinor/currency | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F06 status | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F07 paymentStatus | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F08 progress/currentStepName | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F09 createdAt | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F10 productionStatus | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F11 failureCode/failureMessage | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F12 updatedAt | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F13 manualReviewRequired | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-F14 holdReason | 平台订单行与详情 | A08 Content / Information Priority | Table / Drawer / List / Alert / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A08-A01 展开/收起 | 平台订单行与详情 | A08 Primary / Secondary Action | Table / Drawer / List / Alert / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A08-A02 查看失败与HOLD说明 | 平台订单行与详情 | A08 Primary / Secondary Action | Table / Drawer / List / Alert / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A08-A03 复制完整订单标识（新增纯前端便利） | 平台订单行与详情 | A08 Primary / Secondary Action | Table / Drawer / List / Alert / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A08 状态与恢复 | 平台订单行与详情 | A08 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A09 页面/流程入口 | admin.html#/access | A09 运营员管理与编辑 | 三端布局 + Table / Form / Dialog / Status | Y |
| A09-F01 displayName/operatorId | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F02 role OWNER/MANAGER/OPERATOR/VIEWER（以availableRoles为准） | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F03 status ACTIVE/SUSPENDED | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F04 activeTokenCount | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F05 lastUsedAt | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F06 新建名称/角色及availableRoles.permissions权限数量/预览 | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-F07 编辑名称/角色/状态；停用后该运营员全部Token失效说明 | 运营员管理与编辑 | A09 Content / Information Priority | Table / Form / Dialog / Status；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A09-A01 新建运营员 | 运营员管理与编辑 | A09 Primary / Secondary Action | Table / Form / Dialog / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A09-A02 编辑 | 运营员管理与编辑 | A09 Primary / Secondary Action | Table / Form / Dialog / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A09-A03 保存/取消 | 运营员管理与编辑 | A09 Primary / Secondary Action | Table / Form / Dialog / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A09-A04 展开Token | 运营员管理与编辑 | A09 Primary / Secondary Action | Table / Form / Dialog / Status；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A09 状态与恢复 | 运营员管理与编辑 | A09 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A10 页面/流程入口 | 运营员展开详情 | A10 运营员 Token 与一次性秘密 | 三端布局 + Secret / Table / Form / Dialog / Alert | Y |
| A10-F01 所属运营员 | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F02 token.label/tokenId/status/expiresAt/lastUsedAt/createdAt | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F03 创建label最长120 | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F04 可选datetime-local到UTC expiresAt | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F05 新建完整token | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F06 SHA-256摘要保管说明 | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-F07 撤销不可恢复说明 | 运营员 Token 与一次性秘密 | A10 Content / Information Priority | Secret / Table / Form / Dialog / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A10-A01 展开Token | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10-A02 创建Token | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10-A03 复制完整Token | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10-A04 关闭秘密 | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10-A05 撤销Token并确认 | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10-A06 刷新列表 | 运营员 Token 与一次性秘密 | A10 Primary / Secondary Action | Secret / Table / Form / Dialog / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A10 状态与恢复 | 运营员 Token 与一次性秘密 | A10 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| A11 页面/流程入口 | admin.html#/audit | A11 平台审计列表与详情 | 三端布局 + Table / Search / Drawer / Code / List | Y |
| A11-F01 筛选action/resourceType | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F02 createdAt | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F03 actorName/actorId/actorType | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F04 action | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F05 resourceType/resourceId | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F06 requestId | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F07 detail完整JSON | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-F08 limit=200返回范围 | 平台审计列表与详情 | A11 Content / Information Priority | Table / Search / Drawer / Code / List；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| A11-A01 查询/Enter | 平台审计列表与详情 | A11 Primary / Secondary Action | Table / Search / Drawer / Code / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A11-A02 打开详情 | 平台审计列表与详情 | A11 Primary / Secondary Action | Table / Search / Drawer / Code / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A11-A03 关闭 | 平台审计列表与详情 | A11 Primary / Secondary Action | Table / Search / Drawer / Code / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A11-A04 复制非敏感ID（新增纯前端便利） | 平台审计列表与详情 | A11 Primary / Secondary Action | Table / Search / Drawer / Code / List；依本页Interaction、权限门控及Mobile承载方式 | Y |
| A11 状态与恢复 | 平台审计列表与详情 | A11 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| C01 页面/流程入口 | /order?device_id={id} | C01 设备菜单与饮品选择 | 三端布局 + List / Product / Button / Status / Alert | Y |
| C01-F01 deviceId/storeId | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F02 online/deviceStatus/salesEnabled | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F03 paymentMode ONLINE/TEST_FREE | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F04 materialAlertCount | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F05 可售产品remainingServings求和的旧预计可售杯数 | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F06 recipeId/name/description | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F07 visual.profile与generic回退 | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F08 priceMinor/currency | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F09 recipeVersion | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F10 durationRangeSeconds.min/max/estimatedDurationSeconds | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F11 available/unavailableReasons[]及当前首项解释 | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F12 remainingServings | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F13 选中饮品/合计 | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-F14 共享物料与付款后派单说明 | 设备菜单与饮品选择 | C01 Content / Information Priority | List / Product / Button / Status / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C01-A01 选择可售饮品 | 设备菜单与饮品选择 | C01 Primary / Secondary Action | List / Product / Button / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C01-A02 查看不可售原因 | 设备菜单与饮品选择 | C01 Primary / Secondary Action | List / Product / Button / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C01-A03 确认下单 | 设备菜单与饮品选择 | C01 Primary / Secondary Action | List / Product / Button / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C01-A04 刷新菜单/错误重试 | 设备菜单与饮品选择 | C01 Primary / Secondary Action | List / Product / Button / Status / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C01 状态与恢复 | 设备菜单与饮品选择 | C01 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| C02 页面/流程入口 | 菜单提交状态 | C02 创建订单与价格冲突 | 三端布局 + Button / Alert / Product | Y |
| C02-F01 recipeId/recipeVersion | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-F02 quantity=1/paymentMode | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-F03 支付前合计priceMinor/currency | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-F04 订单idempotencyKey与payment:key | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-F05 服务端错误code/message | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-F06 创建结果orderId/accessToken/paymentId（秘密不展示） | 创建订单与价格冲突 | C02 Content / Information Priority | Button / Alert / Product；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C02-A01 提交 | 创建订单与价格冲突 | C02 Primary / Secondary Action | Button / Alert / Product；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C02-A02 失败后重试 | 创建订单与价格冲突 | C02 Primary / Secondary Action | Button / Alert / Product；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C02-A03 价格/菜单变化后重新选择确认 | 创建订单与价格冲突 | C02 Primary / Secondary Action | Button / Alert / Product；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C02 状态与恢复 | 创建订单与价格冲突 | C02 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| C03 页面/流程入口 | /order/status#order=…&token=…&payment=… | C03 等待支付与稳定二维码 | 三端布局 + QR / Button / Status / Timeline / Alert | Y |
| C03-F01 orderNo | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F02 product.name | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F03 totalAmountMinor/currency | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F04 payment.provider | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F05 qrCode付款链接 | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F06 二维码/加载说明 | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F07 支付里程碑 | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F08 服务端实时确认说明 | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-F09 模拟付款不扣款声明 | 等待支付与稳定二维码 | C03 Content / Information Priority | QR / Button / Status / Timeline / Alert；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C03-A01 打开付款页 | 等待支付与稳定二维码 | C03 Primary / Secondary Action | QR / Button / Status / Timeline / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C03-A02 扫码 | 等待支付与稳定二维码 | C03 Primary / Secondary Action | QR / Button / Status / Timeline / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C03-A03 刷新状态 | 等待支付与稳定二维码 | C03 Primary / Secondary Action | QR / Button / Status / Timeline / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C03-A04 二维码失败重试 | 等待支付与稳定二维码 | C03 Primary / Secondary Action | QR / Button / Status / Timeline / Alert；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C03 状态与恢复 | 等待支付与稳定二维码 | C03 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| C04 页面/流程入口 | /order/status同一订单 | C04 排队、制作、完成与退款结果 | 三端布局 + Progress / Timeline / Status / Alert / Disclosure | Y |
| C04-F01 orderNo/product.name | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F02 status | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F03 queuePosition | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F04 production.overallProgress/progress | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F05 currentStepId/currentStepName | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F06 remainingSeconds/plannedDurationSeconds | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F07 步骤id/name/index/duration | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F08 支付/排队/制作/完成里程碑 | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F09 failure.message | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F10 HOLD解释 | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F11 退款原路与时间说明 | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-F12 物料预留/扣减与结果确认说明 | 排队、制作、完成与退款结果 | C04 Content / Information Priority | Progress / Timeline / Status / Alert / Disclosure；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C04-A01 刷新状态 | 排队、制作、完成与退款结果 | C04 Primary / Secondary Action | Progress / Timeline / Status / Alert / Disclosure；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C04-A02 展开制作步骤/技术说明 | 排队、制作、完成与退款结果 | C04 Primary / Secondary Action | Progress / Timeline / Status / Alert / Disclosure；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C04-A03 终态查看结果 | 排队、制作、完成与退款结果 | C04 Primary / Secondary Action | Progress / Timeline / Status / Alert / Disclosure；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C04 状态与恢复 | 排队、制作、完成与退款结果 | C04 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| C05 页面/流程入口 | 菜单/状态错误页 | C05 消费者错误与访问失效 | 三端布局 + Alert / Button / Empty | Y |
| C05-F01 错误message/code | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-F02 缺少device_id/order/token | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-F03 重试是否允许 | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-F04 连接提示 | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-F05 当前设备/订单上下文（非秘密） | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-F06 认证与不存在区分 | 消费者错误与访问失效 | C05 Content / Information Priority | Alert / Button / Empty；P0/P1在主区，P2在有标题的详情/展开区；秘密按一次显示/只写规则 | Y |
| C05-A01 重新连接（可恢复错误） | 消费者错误与访问失效 | C05 Primary / Secondary Action | Alert / Button / Empty；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C05-A02 回菜单（可恢复设备上下文时的新增纯前端导航） | 消费者错误与访问失效 | C05 Primary / Secondary Action | Alert / Button / Empty；依本页Interaction、权限门控及Mobile承载方式 | Y |
| C05 状态与恢复 | 消费者错误与访问失效 | C05 States + §11 | 本页错误/空态/业务分支；§7控件状态；§9降级动效 | Y |
| 跨页：Toast与页内Alert | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：确认弹层与未保存退出 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：Skeleton/Empty/Offline/Partial Data | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：Focus/Keyboard/44px命中 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：复制、一次性秘密、下载 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：表格展开与详情返回 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：权限/环境/暂关闭分支 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |
| 跨页：图表替代表格与缺失值 | 三端现有共用行为及设计补足 | §7–§12 | 统一组件规范与状态矩阵 | Y |

### 15.1 文档覆盖校验结果

- 场景：51（商户35、平台11、消费者5）；每项含完整Content、Desktop/Tablet/Mobile、操作、状态、动效与改进。
- 字段组：405；操作组：231；矩阵总行数746，每项有目标位置。
- 组件规范：39行（部分为同族别名），包括本项目尚无业务需求的Slider/Upload/TagInput规范，后者不计作现有功能。
- Token配对：86组文本/控件边界计算通过；具体界面仍需在实施后检查实际背景、组合和透明度。
- 文档覆盖不替代工程回归。上线、所有页面浏览器验证、真实角色/服务端门控验证均属于后续实施验收，本次未执行。

### 15.2 OpenDesign交付时回填

对矩阵增加“实现commit / Desktop截图 / Tablet截图 / Mobile截图 / 状态证据 / 运行验证”六列；不通过项标N并列原因。新需求或后端接口变化先更新Inventory与Content，再补映射。当前Y仅表示本规格已有设计承载，不能原样当作上线报告。
