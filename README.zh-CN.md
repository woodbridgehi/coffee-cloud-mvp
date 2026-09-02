# Coffee Cloud MVP

> English overview: [README.md](README.md) · [文档索引](docs/README.md)

面向自动贩卖咖啡终端的早期运营后台。当前 `0.4.0` 增加 Payment Domain、Transactional Outbox、MQTT Inbox/Command Outbox、多设备 MQTT Gateway、MQTT 凭证生命周期和不确定设备结果 `HOLD` 处置；架构保持为 FastAPI + PostgreSQL 模块化单体与独立 Gateway/Worker。

HTTP 应用代码采用 `Route → Application Service → Repository → PostgreSQL` 分层：路由只处理协议适配，Service 负责业务规则和事务，Repository 集中 SQL。模块职责、事务边界和扩展规则见 [应用分层架构](docs/application-architecture.md)。

2026-08-30 A1/A2 已提交并部署 VPS，数据库升级到迁移 12：统一订单/制作任务/命令状态校验，增加 `PAUSED/RETRY_WAIT` 非终态及带权限、版本、幂等和同事务审计的 HOLD 人工结案。见 [制作状态一致性](docs/production-consistency.md)、[发布与回滚记录](docs/releases/2026-08-30-a1-a2.md)。MQTT 持久接收、Redis dirty 租约及 Worker 有界并发等尚未实施，下一步按 [后续优化路线与执行手册](docs/optimization-roadmap-2026-08-30.md) 分批推进。

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
  → PostgreSQL 事务通知 + Redis 进度通知双通道驱动 SSE，手机订单页实时显示状态
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
- 只有确定从未投递的超时命令才进入 `EXPIRED` 并创建必要退款；已领取/存在投递证据但结果未知的命令进入 `UNKNOWN`、订单 `HOLD`，不能推断未制作并自动退款。
- 终端 outbox 至少一次重投；云端事件 Inbox 和状态迁移保证重复事件不重复制作或扣料。

## 2. 页面入口

- 手机下单：`https://coffee-api.woodbridge.top/order?device_id=coffee-bot-002`
- 订单状态：下单成功后自动进入 `/order/status#order=...&token=...`。敏感令牌位于 URL fragment，不会发送给 Web 服务器。
- 设备运营台：`https://coffee-api.woodbridge.top/admin`
- OpenAPI：`https://coffee-api.woodbridge.top/docs`
- 存活检查：`https://coffee-api.woodbridge.top/health`（不访问数据库）
- 就绪检查：`https://coffee-api.woodbridge.top/ready`（检查数据库，5 秒防抖缓存）
- Redis 宿主机参数：部署 `deploy/sysctl/99-coffee-redis.conf` 后执行 `sysctl --system`，避免 AOF/RDB fork 因内存提交策略失败。

运营台使用 `ADMIN_TOKEN` 登录，Token 只保存在当前页面内存。页面显示历史/在线设备、进行中订单、最近订单；选择设备后查询实时共享物料的 `available / capacity / unit / status`。

## 3. 核心 API

### 公开下单

```text
GET  /api/v1/public/devices/{deviceId}/menu
POST /api/v1/public/devices/{deviceId}/orders
GET  /api/v1/public/orders/{orderId}
GET  /api/v1/public/orders/{orderId}/events   # SSE
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
- `MAKING`：收到 `task.started`；设备以整杯进度变化至少 5% 或最长 5 秒为准上报 `task.progress`。Gateway 将进度仅写 Redis，并通过 Pub/Sub 通知 SSE；不会刷入 `production_job`。手机端不自行推导步骤或重新计算随机时长。
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
# 依赖统一从锁文件安装（运行时 requirements.lock；开发/测试用 requirements-dev.lock，
# 均含全量传递依赖，见 R0 依赖锁定），避免传递依赖漂移：
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
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
2. 已有运营员账号/RBAC 与人工 HOLD 裁决 API；继续完善管理操作原子审计和资源配额，处置页如需建设应单独安排。
3. 增加云端库存交易投影与补料工单，而不只保存设备快照。
4. 增加公网接口速率限制、WAF 规则和订单滥用监控。
5. 完成 100/500/1000 设备连接、重连风暴与 Outbox 延迟压测。

当前不急于引入：微服务、Kafka、Kubernetes、独立时序数据库。现阶段 PostgreSQL 模块化单体更容易保证订单—制作一致性和快速迭代。

完整架构决策和 VPS 手册见 `../plan-gpt/`。

## 9. MQTT 5.0 接入网关

`coffee-mqtt-gateway` 是无单设备配置的独立进程，不承载扫码 Web/API，也不复制订单状态机。心跳、presence、state 经 Redis 合并后批量刷新 PostgreSQL 的设备快照；`task.progress` 使用独立 Redis 任务键，只保存最新值并原子发布 Pub/Sub 通知，不标记 dirty、不写 SQL。网关仍按最多 100 条或 100ms 聚合可覆盖遥测请求。订单、任务/步骤生命周期、命令结果绕过微批，立即进入持久 Inbox 与领域状态机。设备端按“5% 或 5 秒”上报进度，必须携带非负整数 `taskRevision`。`TELEMETRY_HISTORY_MODE=audit` 保留心跳/state 等历史，但不改变 `task.progress` 的 Redis-only 策略。下行仍使用命令租约和 Broker PUBACK；QoS 1 上行启用 manual ACK。

### 连接生命周期（2026-08-30 B1.1）

- 网关 Client ID 必须稳定：默认 `coffee-mqtt-gateway-v1`，由 `MQTT_GATEWAY_ID` 覆盖。Client ID 即 Broker 会话身份，随机默认会在每次重启时丢弃会话与排队的 QoS 1 上行。**多实例部署时每个网关进程必须配置各自唯一且稳定的 ID**（如 `coffee-mqtt-gateway-v2`），同 ID 互踢会导致会话抖动。
- MQTT 5 会话为持久会话：`clean_start=False` + 会话有效期 7 天（`MQTT_SESSION_EXPIRY_SECONDS`，默认 604800）。网关重启/重建对象后，离线期间排队的 QoS 1 上行会被重投。CONNACK 返回 `sessionPresent=false` 时会记录警告：Broker 可能已丢弃会话状态（首次连接除外），不能把 MQTT QoS 1 等同于应用层恰好一次。
- 连接监督：Paho 网络循环在主动 `disconnect()`（背压队列满、订阅失败）后自行终止且不会重连；网关唯一的监督线程检测到循环死亡后执行 `loop_stop → reconnect → loop_start`，带指数退避（上限 60s）。初次连接失败与意外断线由 Paho 循环内建重试处理，监督器不与存活循环竞争。网络回调只记录状态，绝不在线程内 join/重连。
- 连接代次（generation）ACK 隔离：主动断开、关闭和进入 Paho `reconnect()` 前均撤销旧代次权限；覆盖监督器和 Paho 自动重连。撤销与 ACK 调用由可重入锁串行化，允许 Paho 写失败同步触发断线回调；不在该锁内执行线程 join 或阻塞连接。过期消息仍可处理但不 ACK，后续依赖持久会话重投与业务幂等。此项不是端到端不丢消息的承诺，设备持久 Inbox 仍待 B1.2。
- 订阅就绪：每次连接清理旧 MID；全部必需订阅收到成功的 QoS1 SUBACK 才设置 `connected/subscribed`，允许下行领取并通过健康检查。拒绝、QoS0 降级或缺失确认均不就绪；`MQTT_SUBSCRIBE_TIMEOUT_SECONDS` 默认 10 秒、限制 1–60 秒，超时断开后退避恢复。已有持久会话在 SUBACK 前重投的上行仍可处理和确认。
- 关键线程退出（上行 worker、命令发布线程、监督线程）会使健康文件置为失败并以非零码退出进程，交给容器 `restart: unless-stopped` 受控恢复，而不是永远假存活。监督器与 shutdown 通过重连锁协调：重连返回后复查关闭状态，关闭完成时不残留新连接或网络线程。`shutdown()` 幂等并保留 Broker 会话。

直接复核修复及测试边界见 [B1.1 修复记录](docs/mqtt-lifecycle-review-2026-08-30.md)。后端代码 `8baf0ae` 已部署 VPS，数据库保持 migration 12，详见 [发布记录](docs/releases/2026-08-30-b11.md)。

`coffee-cloud-mvp` 的每个 Uvicorn worker 各维护一个 PostgreSQL LISTEN 连接和一个 Redis Pub/Sub 连接。订单/支付/生命周期通知刷新 SQL 快照；进度通知只读 Redis，不查询 SQL。浏览器初次连接/重连时先鉴权，再订阅并合并 PostgreSQL 状态与 Redis 进度。`coffee-domain-worker` 只刷设备状态，不再刷制作进度；领域派单、支付退款仍相互隔离。管理端订单列表也以单个 Redis pipeline 叠加最新进度。

`coffee-telemetry-redis` 只绑定 VPS 回环地址 6380。进度按“设备 + 任务”隔离，TTL 为 1 小时，版本递增才接受；订单终态/暂停状态不会被迟到进度覆盖。Redis 不参与订单、支付或命令事实判定。Redis 不可用时瞬时进度丢弃并等待下一次上报，绝不回退高频 SQL；设备状态仍保留 SQL 降级。Redis/PG 监听重连会补读当前快照，详见 [双通道 SSE](docs/dual-channel-sse.md)。

数据库 migration 由一次性 `coffee-db-migrate` 工具执行，API 和 Worker 不在并发启动时修改 schema：

```bash
docker compose --profile tools run --rm coffee-db-migrate
```

默认离线判定为 90 秒、Redis 在线 TTL 为 120 秒。已处理的 heartbeat、MQTT inbox、设备事件和 outbox 按配置分批清理；订单、支付和制作业务事实不由该清理任务删除。容量和故障验收步骤见 `docs/capacity-and-fault-test-plan.md`。

```bash
docker compose build coffee-mqtt-gateway
docker compose up -d coffee-mqtt-gateway
docker logs -f coffee-mqtt-gateway
```

网关 MQTT 凭证保存在未跟踪的 `.secrets/coffee-cloud-gateway.mqtt.env`。网关配置不再读取 `DEVICE_ID/DEVICE_TOKEN`；设备 Topic 与 payload 的 `deviceId` 必须一致，Broker 以每设备 username/password 和 ACL 约束 Topic。Paho 订阅端不能直接取得发布者 principal，因此当前 principal→Topic 绑定依赖 EMQX 认证/ACL；生产 mTLS 版本需把证书主体写入可验证接入上下文。

EMQX 部署源、证书续期 hook 和 ACL 初始化脚本位于 `deploy/emqx/`。公网只允许 `mqtt-api.woodbridge.top:8883`；Dashboard 仅绑定 VPS `127.0.0.1:18083`。
