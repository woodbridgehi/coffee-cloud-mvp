# 应用分层架构

当前 HTTP 业务请求统一采用以下依赖方向：

```text
FastAPI Route（协议适配、认证依赖、参数解析）
  ↓
Application Service（业务规则、状态编排、事务边界）
  ↓
Repository（SQL、行锁、持久化映射）
  ↓
PostgreSQL
```

## 各层职责

| 层 | 目录 | 可以做 | 不应做 |
| --- | --- | --- | --- |
| HTTP 路由 | `app/main.py` | 接收参数、调用 Service、选择响应类型 | SQL、订单状态判断、跨表编排 |
| Service | `app/services/` | 校验业务规则、控制事务、调用外部 Provider、组织返回 DTO | 写 SQL、依赖 FastAPI Request/Response |
| Repository | `app/repositories/` | 查询、更新、行锁、唯一键与数据库映射 | HTTP 状态码、业务流程编排、外部网络调用 |
| 事务 | `app/db/unit_of_work.py` | 提供一次业务操作的连接和提交/回滚边界 | 业务判断 |

Service 使用 `UnitOfWork.transaction()` 开启事务，并在事务内创建所需 Repository。同一个订单、支付、退款或命令状态迁移涉及的多表写入必须共享同一事务。

## 当前模块映射

- `PublicOrderService` → `OrderRepository`、`TerminalRepository`
- `PaymentApplicationService` → `PaymentRepository`、`OrderRepository`
- `DeviceIdentityService` → `IdentityRepository`、`TerminalRepository`
- `DeviceMessageService` → `DeviceMessageRepository`
- `CommandService` → `CommandRepository`、`TerminalRepository`
- `MqttGatewayService` → `MqttGatewayRepository`，并将已去重消息交给设备消息 Service
- `AdminOperationsService` → `TerminalRepository`、`OrderRepository`
- `AdminAccessService` → `AdminAccessRepository`，负责运营员、角色权限、可撤销令牌与审计日志
- `ProductionService` → `CommandRepository`、`OrderRepository`、`PaymentRepository`，负责制作任务、设备事件、订单状态和自动退款意图
- `BackgroundWorkerService` → `WorkerRepository`、`ProductionService`、`OrderRepository`、`PaymentRepository`，负责离线扫描、Business Outbox、支付对账、退款重试、历史清理和 watchdog
- `OrderEventBroker` → PostgreSQL `LISTEN/NOTIFY` + Redis Pub/Sub 双监听，分别分发订单事实变更和瞬时进度
- `order_stream` → 事务通知重新查询 SQL；进度通知只读 Redis；首次连接订阅后补读两侧快照
- `live_progress` → 设备/任务匹配、revision 比较与终态优先；Lua 原子更新快照并发布通知

外部支付和 EMQX 管理 API 由 Service 调用。数据库事务不能跨越耗时网络调用：先保存待处理状态并提交，调用外部系统，再在新事务中保存结果。这样可避免长事务和数据库行锁长期占用。

## 可靠性边界

- Route 不持有数据库连接。
- Service 决定事务范围，但不包含 SQL。
- Repository 不自行开启事务，因此一个业务用例可以原子更新多张表。
- MQTT Inbox、Command Outbox、Payment Callback Inbox 和 Business Outbox 的唯一键仍是幂等性的最终保护。
- Service 抛出 `ServiceError`，统一由 HTTP 层转换为响应；Repository 不依赖 FastAPI。
- `ADMIN_TOKEN` 只作为应急 OWNER；日常运营使用数据库中仅保存摘要的独立运营 Token。

## 后台任务边界

`main.py` 只保留应用组装、生命周期和线程调度。API 进程不执行 migration 或后台扫描；migration 由一次性 `app.migrate` 完成。独立 `coffee-domain-worker` 将遥测刷库、领域派单、支付退款拆成三个工作循环，避免支付渠道超时阻塞派单或遥测。后台任务仍采用短事务：领取/标记本地状态后提交，外部支付调用完成后再开启新事务保存结果。

后台任务的依赖关系如下：

```text
OfflineMonitor / Telemetry / Domain / Payment（独立线程调度）
                 ↓
      BackgroundWorkerService
          ├── WorkerRepository
          ├── ProductionService
          ├── OrderRepository / PaymentRepository
          └── 外部支付 Provider

设备事件 / 订单支付
        ↓
  ProductionService
        ├── CommandRepository
        ├── OrderRepository
        └── PaymentRepository
```

这样可以在后续拆分独立 Worker 进程时复用 Service 和 Repository，而不需要重新复制 `main.py` 中的 SQL 和状态机逻辑。

## 性能并发边界

- `Database` 使用 psycopg 连接池，连接池大小由 `DB_POOL_MIN_SIZE`、`DB_POOL_MAX_SIZE` 和 `DB_POOL_TIMEOUT_SECONDS` 配置；事务边界仍由 `UnitOfWork` 管理。
- Business Outbox 由 `BackgroundWorkerService` 一次领取一批事件，并使用 savepoint 隔离单条失败，避免一个坏事件回滚整批事件。
- MQTT Gateway 按 `deviceId` 将上行消息分片到多个 Worker；同一设备保持在同一分片中，以保留消息顺序，不同设备可以并发处理。
- MQTT Gateway 的内部 API 使用共享 Keep-Alive HTTP 客户端，命令发布独立于上行消息处理线程。
- 心跳、presence、state 默认使用 `latest` 模式，Worker 通过集合 SQL 刷新设备快照。`task.progress` 使用独立 Redis 键与 Pub/Sub，不入 dirty 队列、不刷数据库；旧 hash 中的 progressPayload 也不再刷库。
- `step.started/step.completed`、完成、失败等事实事件仍进入持久 Inbox 并更新 PostgreSQL。SSE 通过双通道通知更新，进度通知不查询数据库。管理订单列表通过 Redis pipeline 合并实时进度。
- 扩容前应观察 `/metrics` 中的连接池、Redis dirty backlog、SSE 连接数和 Worker 健康文件，并执行容量与故障验收计划。

## 新功能开发规则

1. 新接口先定义 Service 用例，再增加 Repository 方法，最后添加 Route。
2. 禁止在 Route 和 Service 中新增 `.execute()` 或 SQL 字符串。
3. Repository 方法名表达业务数据动作，例如 `find_refund`、`claim`，不要泄漏 HTTP 概念。
4. 状态迁移必须在锁定当前记录的事务中完成，并保留 revision/transition/event 记录。
5. 跨外部系统操作使用“本地意图 → 提交 → 外部调用 → 本地结果”的短事务模式。
