# Coffee Cloud MVP

面向自动贩卖咖啡终端的早期运营后台。当前 `0.4.0` 增加 Payment Domain、Transactional Outbox、MQTT Inbox/Command Outbox、多设备 MQTT Gateway、MQTT 凭证生命周期和不确定设备结果 `HOLD` 处置；架构保持为 FastAPI + PostgreSQL 模块化单体与独立 Gateway/Worker。

HTTP 应用代码采用 `Route → Application Service → Repository → PostgreSQL` 分层：路由只处理协议适配，Service 负责业务规则和事务，Repository 集中 SQL。模块职责、事务边界和扩展规则见 [应用分层架构](docs/application-architecture.md)。

公网支付由 `PUBLIC_PAYMENT_MODE` 控制。现网在没有支付宝沙箱密钥前必须保持 `TEST_FREE`；设置为 `ONLINE` 后，服务端会拒绝任何绕过支付的测试订单。支付宝沙箱与正式环境共用 `AlipayProvider`，只通过 gateway、appId 和密钥文件切换。

## 1. 已实现的运营闭环

```text
终端上传 recipes/materials
  → 云端形成设备实时菜单与可售杯数
  → 终端显示该设备专属 HTTPS 二维码
  → 手机扫码选择饮品并创建幂等订单
  → ONLINE: Payment PENDING → 支付平台回调/主动查询 → PAID
  → 支付事务写 Business Outbox，Worker 幂等创建制作任务
  → Command Outbox 经多设备 MQTT Gateway 发布 MAKE_DRINK
  → 终端整杯预占、按步骤扣减共享物料
  → 终端可靠上报生命周期事件，并按变化/时间阈值上报制作进度
  → 手机订单页轮询显示实时状态
  → 运营台查看订单、设备和逐项物料余量
```

关键规则：

- 二维码为真实公网地址：`{PUBLIC_BASE_URL}/order?device_id={deviceId}`，每台设备动态生成，不使用写死的 002 链接。
- 终端离线、生命周期未激活、配方下架或物料不足时禁止下单。
- 创建订单、支付和退款必须携带 `Idempotency-Key`；同键同载荷返回原结果，同键异载荷返回 `409`。
- `ONLINE` 模式下未支付订单没有 `production_job` 或设备命令；支付回调不会直接发布 MQTT。
- 支付回调 Inbox、Business Outbox、MQTT Inbox 和 Command Outbox 均由 PostgreSQL 唯一键保证至少一次处理下的业务幂等。
- 状态页使用独立的不可猜测订单访问令牌，通过请求头传输；令牌不写入 URL 查询参数或服务日志。
- 每台设备同时只派发一个制作任务；其余订单保持 `QUEUED`。
- 设备 ACK 是物料预占成功的事实，设备事件是制作状态和实际扣料的事实。
- 未在时限内送达设备的命令会进入 `EXPIRED`，不会无限停留在 `DISPATCHED`。
- 终端 outbox 至少一次重投；云端事件 Inbox 和状态迁移保证重复事件不重复制作或扣料。

## 2. 页面入口

- 手机下单：`https://coffee-api.woodbridge.top/order?device_id=coffee-bot-002`
- 订单状态：下单成功后自动进入 `/order/status#order=...&token=...`。敏感令牌位于 URL fragment，不会发送给 Web 服务器。
- 设备运营台：`https://coffee-api.woodbridge.top/admin`
- OpenAPI：`https://coffee-api.woodbridge.top/docs`
- 健康检查：`https://coffee-api.woodbridge.top/health`

运营台使用 `ADMIN_TOKEN` 登录，Token 只保存在当前页面内存。页面显示历史/在线设备、进行中订单、最近订单；选择设备后查询实时共享物料的 `available / capacity / unit / status`。

## 3. 核心 API

### 公开下单

```text
GET  /api/v1/public/devices/{deviceId}/menu
POST /api/v1/public/devices/{deviceId}/orders
GET  /api/v1/public/orders/{orderId}
POST /api/v1/public/orders/{orderId}/cancel
```

创建订单（请求中的 `paymentMode` 必须与菜单返回值一致）：

```bash
curl -X POST https://coffee-api.woodbridge.top/api/v1/public/devices/coffee-bot-002/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"recipeId":"espresso-v1","recipeVersion":"1.0.0","quantity":1,"paymentMode":"ONLINE"}'
```

响应中的 `accessToken` 只在客户状态页使用。查询时放在 `X-Order-Access-Token`，不要写进日志或分享给其他人。

### 设备接口

```text
POST /api/v1/device-activations
POST /api/v1/devices/{deviceId}/heartbeat
PUT  /api/v1/devices/{deviceId}/capabilities
PUT  /api/v1/devices/{deviceId}/inventory
GET  /api/v1/devices/{deviceId}/commands
POST /api/v1/tasks/{taskId}/ack
POST /api/v1/devices/{deviceId}/events
GET  /api/v1/devices/{deviceId}/display-config
POST /api/v1/devices/{deviceId}/mqtt-credentials/rotate
```

### 支付接口

```text
POST /api/v1/orders/{orderId}/payments
GET  /api/v1/payments/{paymentId}
GET  /api/v1/payments/{paymentId}/qr
POST /api/v1/payments/callback/alipay
POST /api/v1/payments/{paymentId}/refund   # 管理员权限
```

支付成功事务只更新 Payment/Order 并写 `business_outbox`。后台 Worker 恢复后才创建唯一制作任务；因此服务在回调后崩溃也不会漏单或重复制作。明确 `task.failed/task.rejected` 会创建幂等退款；已发布命令失联则进入 `UNKNOWN/HOLD`，不会在物理结果不确定时自动退款。

### 运营接口

```text
GET  /api/v1/admin/devices
GET  /api/v1/admin/devices/{deviceId}
GET  /api/v1/admin/devices/{deviceId}/inventory
GET  /api/v1/admin/orders
POST /api/v1/admin/devices
POST /api/v1/admin/devices/{deviceId}/activation-codes
POST /api/v1/admin/devices/{deviceId}/commands
```

所有管理接口使用 `Authorization: Bearer $ADMIN_TOKEN`。完整字段和错误响应以 `/docs` 与 `openapi/openapi.json` 为准。

### 运营权限与审计

`ADMIN_TOKEN` 现在作为应急超级管理员凭证保留。日常运营应在管理台创建独立运营员和可撤销 API Token，不应多人共享 `ADMIN_TOKEN`。

角色权限：

- `VIEWER`：查看总览、设备和订单。
- `OPERATOR`：增加设备登记、生命周期管理和安全远程命令。
- `MANAGER`：增加退款、权限只读和审计查看。
- `OWNER`：增加运营员、角色和 API Token 管理。

关键接口：

```text
GET    /api/v1/admin/session
GET    /api/v1/admin/dashboard
PATCH  /api/v1/admin/devices/{deviceId}/lifecycle
GET    /api/v1/admin/devices/{deviceId}/capabilities
GET    /api/v1/admin/operators
POST   /api/v1/admin/operators
PATCH  /api/v1/admin/operators/{operatorId}
GET    /api/v1/admin/operators/{operatorId}/tokens
POST   /api/v1/admin/operators/{operatorId}/tokens
DELETE /api/v1/admin/operators/{operatorId}/tokens/{tokenId}
GET    /api/v1/admin/audit-logs
```

新运营 Token 仅在创建响应中显示一次，数据库只保存 SHA-256 摘要。设备登记、激活码生成、生命周期变更、远程命令、凭证吊销、退款及权限变更都会写入 `audit_log`，审计记录不保存原始 Token。

## 4. 状态模型

订单：

```text
CREATED → AWAITING_PAYMENT → PAID → QUEUED → DISPATCHED → ACCEPTED → MAKING → READY
   └──────────────→ CANCELLED / EXPIRED / FAILED
                                      FAILED → REFUNDED
```

支付与退款：

```text
CREATED → PENDING → PAID → REFUNDING → PARTIALLY_REFUNDED / REFUNDED
                  └──────────────────→ CLOSED / FAILED
REQUESTED → PROCESSING → SUCCEEDED / FAILED / UNKNOWN → PROCESSING
```

制作任务：

```text
QUEUED → DISPATCHED → ACCEPTED → EXECUTING → SUCCEEDED
   └──────────────────────────→ REJECTED / FAILED / CANCELLED / EXPIRED
```

- `ACCEPTED`：终端已校验配方版本并成功预占整杯物料。
- `MAKING`：收到 `task.started`；设备以整杯进度变化至少 5% 或最长 5 秒为准上报 `task.progress`，Gateway 立即写 Redis 最新快照、Worker 批量刷新 `production_job`。手机端不自行推导步骤或重新计算随机时长。
- `READY`：只由终端 `task.succeeded` 推进。
- 客户仅能取消尚未派发的 `QUEUED` 订单。派发后不允许用网页强行取消真实动作。

## 5. 配置

`.env` 不得提交。关键字段见 `.env.example`：

- `DATABASE_URL`：PostgreSQL 连接。
- `ADMIN_TOKEN`：运营后台管理凭证。
- `PUBLIC_BASE_URL`：二维码和手机端公网根地址。
- `PUBLIC_ORDER_QUEUE_LIMIT`：单设备进行中/排队订单上限，默认 20。
- `ORDER_ACCESS_SECRET`：独立随机密钥，用于派生订单状态访问令牌；生产必须配置且不应与管理员 Token 共用。
- `OFFLINE_THRESHOLD_SECONDS`：超过该心跳租约后禁止下单。
- `PUBLIC_PAYMENT_MODE`：`TEST_FREE` 或 `ONLINE`；是服务端强制规则，不只是 UI 开关。
- `PAYMENT_DEFAULT_PROVIDER`：`mock`（仅测试）或 `alipay`。
- `ALIPAY_GATEWAY/ALIPAY_APP_ID/ALIPAY_APP_PRIVATE_KEY_FILE/ALIPAY_PUBLIC_KEY_FILE`：支付宝环境与 RSA2 密钥配置；密钥文件不得提交。
- `INTERNAL_GATEWAY_TOKEN`：API 与 MQTT Gateway 之间的独立随机凭证。
- `TELEMETRY_REDIS_URL/TELEMETRY_ONLINE_TTL_SECONDS/TELEMETRY_FLUSH_BATCH_SIZE`：Redis 热状态层连接、在线租约和批量刷库大小；只用于最新遥测，不能替代订单事务。
- `API_WORKERS`：Uvicorn API 进程数；VPS 当前使用 `2`，后台任务以 `SKIP LOCKED` 协调并发领取。
- `EMQX_MANAGEMENT_URL/EMQX_DASHBOARD_USERNAME/EMQX_DASHBOARD_PASSWORD`：用于激活、轮换、吊销时同步每设备 MQTT user/ACL；只能指向 VPS 本机管理口。

现网第一次升级到 `0.3.0` 时应在 VPS `.env` 增加独立密钥：

```bash
openssl rand -hex 32
```

把输出安全写入 `ORDER_ACCESS_SECRET`，不要贴到聊天、日志或 Git。未配置时程序暂时回退到 `ADMIN_TOKEN` 以兼容旧部署，但管理员 Token 轮换会令旧订单状态链接失效。

## 6. 本地检查与部署

```bash
.venv/bin/pytest -q
node --check public/order.js
.venv/bin/python scripts/export_openapi.py
docker compose config
```

VPS 更新前先备份数据库，再同步代码且排除 `.env/.git/.venv`：

```bash
docker exec postgres-web pg_dump -U coffee_cloud -Fc coffee_cloud_mvp > coffee-cloud-before-upgrade.dump
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8788/health
```

数据库迁移由应用启动时按 `schema_migration` 顺序执行。迁移 4 新增 Payment/Refund/Callback Inbox、Business Outbox、MQTT Inbox、Command Outbox、MQTT Credential、Security Event 与 HOLD 字段。升级前必须备份；不要手工把迁移 4 标记为已执行。

## 7. 设备激活和启动

在 `/admin` 登记设备并生成一次性激活码，然后在模拟器目录执行：

```bash
.venv/bin/python scripts/activate_instance.py coffee-bot-003 \
  --activation-code-file .secrets/coffee-bot-003.activation-code \
  --secrets-file .secrets/coffee-bot-003.env

./start-instance.command coffee-bot-003 \
  --env-file .secrets/coffee-bot-003.env
```

“已登记”是历史记录，“在线”由最近心跳判断；停止进程后设备会转为离线，但不会从运营台消失。

## 8. 当前边界与近期优先级

当前必须保持：支付前不派单、支付/退款幂等、单设备串行派单、设备 ACK/事件裁决、终端共享物料预占与扣减、数据库备份、秘密文件隔离。

近期应做：

1. 配置支付宝沙箱密钥并完成真实扫码、回调、主动查询和退款验收，再把现网 `PUBLIC_PAYMENT_MODE` 切到 `ONLINE`。
2. 增加运营员账号/RBAC、人工 HOLD 处置页和完整审计，替换共享管理员 Token。
3. 增加云端库存交易投影与补料工单，而不只保存设备快照。
4. 增加公网接口速率限制、WAF 规则和订单滥用监控。
5. 完成 100/500/1000 设备连接、重连风暴与 Outbox 延迟压测。

当前不急于引入：微服务、Kafka、Kubernetes、独立时序数据库。现阶段 PostgreSQL 模块化单体更容易保证订单—制作一致性和快速迭代。

完整架构决策和 VPS 手册见 `../plan-gpt/`。

## 9. MQTT 5.0 接入网关

`coffee-mqtt-gateway` 是无单设备配置的独立进程，不承载扫码 Web/API，也不复制订单状态机。一个实例订阅所有设备上行 Topic：心跳、presence、state 及制作进度默认先写入项目专用 Redis 热状态层，并按批量合并刷新 PostgreSQL 的最新快照；网关会将这类可覆盖遥测按最多 100 条或 100ms 聚成一个 HTTP 内部请求。订单、任务/步骤生命周期、命令结果和订单事件绕过微批，立即进入持久 `mqtt_inbox` 与领域状态机。设备端对普通进度采用“5% 或 5 秒”节流；设置 `TELEMETRY_HISTORY_MODE=audit` 可额外保留遥测历史。下行从 `command_outbox` 领取带租约的命令，Broker PUBACK 后再标记 `PUBLISHED`。QoS 1 上行启用 manual ACK，进程崩溃时由持久 MQTT session 重投。

`coffee-cloud-mvp` 的两个 Uvicorn worker 现在只处理 API 请求；`coffee-domain-worker` 是唯一的后台进程，负责离线扫描、Redis 遥测落库、领域 outbox、订单派发、支付对账、退款和看门狗。这样扩展 API 并发时不会重复启动这些轮询任务。

`coffee-telemetry-redis` 只绑定 VPS 回环地址的 6380 端口，保存在线 TTL、设备最新状态和最新制作进度；Redis 不参与订单、支付或命令事实判定，缓存不可用时 MQTT 接入自动回退为 PostgreSQL 更新。

```bash
docker compose build coffee-mqtt-gateway
docker compose up -d coffee-mqtt-gateway
docker logs -f coffee-mqtt-gateway
```

网关 MQTT 凭证保存在未跟踪的 `.secrets/coffee-cloud-gateway.mqtt.env`。网关配置不再读取 `DEVICE_ID/DEVICE_TOKEN`；设备 Topic 与 payload 的 `deviceId` 必须一致，Broker 以每设备 username/password 和 ACL 约束 Topic。Paho 订阅端不能直接取得发布者 principal，因此当前 principal→Topic 绑定依赖 EMQX 认证/ACL；生产 mTLS 版本需把证书主体写入可验证接入上下文。

EMQX 部署源、证书续期 hook 和 ACL 初始化脚本位于 `deploy/emqx/`。公网只允许 `mqtt-api.woodbridge.top:8883`；Dashboard 仅绑定 VPS `127.0.0.1:18083`。
