# Coffee Cloud 前端产品化重构任务

项目根目录：`/Users/alex/Downloads/armaster/coffee-cloud-mvp`

你是本项目的前端负责人，请直接读写项目文件，完成产品化 UI 重构。

## 技术边界

- FastAPI + 原生 HTML/CSS/JavaScript，无 React/Vue、无构建工具。
- 不得引入 CDN、远程图片、远程字体或外部前端依赖。
- 不修改 API 协议、后端业务、`.env`、密钥或部署配置。
- 需要重做 `public/order.html`、`public/order.css`、`public/order.js`。
- 将 `app/main.py` 内嵌的 `ADMIN_HTML` 拆为 `public/admin.html`、`public/admin.css`、`public/admin.js`；仅将 `/admin` 路由改为 `FileResponse` 返回 `public/admin.html`，不要改动其他后端代码。

## 视觉要求

- 可商业试点的自动咖啡机器人产品，不像工程 Demo。
- 手机端温暖、克制、现代；管理端高信息密度、专业、清晰。
- 手机端重点适配 360–430px，管理端适配 1440px 桌面和 768px 平板。
- 使用系统字体、CSS 图形或内联 SVG，避免 emoji 堆砌。
- 完整 focus-visible、可读对比度、`prefers-reduced-motion`。
- 所有主要操作具备 loading、disabled、error、empty 状态。

## 手机下单与订单状态页

保留现有 URL、请求字段、鉴权头、幂等键和 SSE 实时更新规则：

- `GET /api/v1/public/devices/{deviceId}/menu`
- `POST /api/v1/public/devices/{deviceId}/orders`
- `POST /api/v1/orders/{orderId}/payments`
- `GET /api/v1/public/orders/{orderId}`
- `GET /api/v1/public/orders/{orderId}/events`（`text/event-stream`，同样使用订单访问请求头）
- `GET /api/v1/payments/{paymentId}/qr`

必须保留：

- 同一 `paymentId` 不因 SSE 重复状态事件而替换二维码 DOM 或 Blob URL。
- 初次二维码加载失败后至少 20 秒再重试。
- 测试依赖的设备权威 `stepName`、`overallProgress` 和 `#payment-qr` DOM 稳定语义。
- 菜单展示设备状态、饮品、价格、剩余杯数、预计时长、不可售原因、底部结算栏。
- 状态页明确表达支付、排队、派单、设备接受、制作、HOLD、完成、失败、退款。
- 不虚构会员、优惠券、配送等不存在功能。

## 管理后台

Token 只保存在页面内存，不写 localStorage/sessionStorage/cookie/URL。登录后先请求：

- `GET /api/v1/admin/session`

按返回的 permissions 控制导航和操作：

- `dashboard.read`
- `devices.read`
- `orders.read`
- `devices.manage`
- `commands.execute`
- `refunds.manage`
- `access.read`
- `access.manage`
- `audit.read`

API：

- `GET /api/v1/admin/dashboard`
- `GET/POST /api/v1/admin/devices`
- `GET /api/v1/admin/devices/{id}`
- `GET /api/v1/admin/devices/{id}/inventory`
- `GET /api/v1/admin/devices/{id}/capabilities`
- `PATCH /api/v1/admin/devices/{id}/lifecycle`，body `{status,reason}`
- `POST /api/v1/admin/devices/{id}/activation-codes`
- `POST /api/v1/admin/devices/{id}/commands`，必须有 `Idempotency-Key`
- `GET /api/v1/admin/orders`
- `GET/POST /api/v1/admin/operators`
- `PATCH /api/v1/admin/operators/{operatorId}`
- `GET/POST /api/v1/admin/operators/{operatorId}/tokens`
- `DELETE /api/v1/admin/operators/{operatorId}/tokens/{tokenId}`
- `GET /api/v1/admin/audit-logs`

使用侧边导航和工作区，至少包括：

1. 总览：设备总数/在线/受限，今日订单/完成率/异常，人工复核、待退款、积压事件和命令。
2. 设备：筛选、列表、详情面板、能力清单、物料余量、生命周期管控。变更生命周期必须确认并填写原因。
3. 订单：状态/设备筛选，支付、制作进度、失败和 HOLD 信息。
4. 权限：运营员、角色和状态编辑，Token 创建/撤销；新 Token 只显示一次且不写 console。
5. 审计：操作者、动作、资源、时间、详情，支持 action/resourceType 筛选。

权限规则：

- `devices.manage` 才能登记、生成激活码、变更生命周期。
- `commands.execute` 才显示远程命令，仅提供 `RELOAD_CONFIG`、`SYNC_CONFIG`、`RESTART_APP`；重启必须二次确认，不提供 MAKE_DRINK 调试入口。
- `access.manage` 才能增改运营员和 Token，`access.read` 只能查看。
- `audit.read` 才显示审计页。
- 403 明确显示权限不足。

安全与交互：

- API 数据优先用 `textContent`；使用 `innerHTML` 必须先可靠转义。
- 不输出管理 Token、设备 Token或其他秘密到 console/错误信息。
- 激活码和新运营 Token 只在一次性结果弹窗显示。
- 自动刷新不得打断输入、弹窗和设备选择；页面隐藏时暂停高频刷新。
- 使用 toast、确认弹窗、空状态、加载骨架，避免以 `alert` 作为主要交互。
- 中文为主。

## 验证

完成后运行：

```bash
node --check public/order.js
node --check public/admin.js
node --test tests/*.mjs
```

最终说明改动文件、设计选择、验证结果和需要后端确认的问题。
