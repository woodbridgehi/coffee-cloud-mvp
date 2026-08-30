# Redis + PostgreSQL 双通道 SSE

```text
设备 MQTT/HTTP task.progress
  → Redis Lua：revision 校验 + 最新值(1h TTL) + Pub/Sub
  → 每个 API worker 的 Redis 监听器
  → 按设备+任务唤醒 SSE → 读 Redis 合并进度 → 浏览器
                                （不查、不写 PostgreSQL）

支付/订单/任务与步骤生命周期
  → PostgreSQL 事务提交 → NOTIFY
  → 每个 API worker 的 PG 监听器
  → 按订单唤醒 SSE → 读订单快照 + Redis 进度 → 浏览器
```

## 数据边界

- `task.progress` 无历史记录、无 SQL 最新进度覆盖。Redis 键由设备 ID 与任务 ID 共同确定，TTL 为 3600 秒，每个新版本刷新 TTL。
- 设备必须上传非负整数 `payload.taskRevision`。Lua 原子拒绝旧版本/重复版本，更新快照后才发布通知；Gateway 批处理中同任务只保留最高版本。
- 步骤开始/完成、任务成功/失败等事实仍可靠持久化，因此 PostgreSQL 进度字段是最近生命周期检查点，而非实时进度。
- 心跳/presence/state 继续使用设备 Redis 热状态和批量 SQL 投影；本次不改变它们的存储策略。
- HTTP 兼容上报与 MQTT 使用同一个 Redis-only 进度策略。Redis 故障时瞬时进度可丢，不能退回高频 SQL；下一次有效上报恢复显示。
- 查询进度的 Redis I/O 在 SQL 事务释放后执行。顾客 GET/SSE 首次快照合并两侧数据；管理端列表通过一个 Redis pipeline 补齐实时进度。

## 一致性与恢复

1. 浏览器先经订单访问令牌鉴权，再建立 SSE；只订阅数据库返回的设备/任务，不信任客户端指定映射。
2. 先订阅订单，查询其任务映射，再订阅进度并补读 Redis，关闭查询/订阅间隙。
3. 进度更新只覆盖同设备、同任务且更高 revision 的执行中订单。暂停、HOLD 和所有终态以 PostgreSQL 为准。
4. 每条 SSE 使用容量 1 的合并通知队列；SQL 更新标记不会被进度洪峰覆盖。每次唤醒最多合并 50ms 通知。
5. Redis Pub/Sub 与 PG NOTIFY 都不是事件日志。监听器连接恢复后唤醒已有订阅补读对应快照；Redis 重订阅只读 Redis，不增加 SQL 轮询。
6. 浏览器重连也重新读取最新快照，不回放瞬时进度历史。Redis 丢失全部数据时保留数据库生命周期检查点，等待下一条上报。
7. 已有制作中的 SSE 在 Redis 短暂故障时保留最后显示进度；新连接仅能看到仍然可用的快照。

Pub/Sub 的 at-most-once 语义见 [Redis 官方文档](https://redis.io/docs/latest/develop/pubsub/#delivery-semantics)。这里传递的是“有新快照”通知，而非不可丢的业务事实。

## 运维与测试

- `/metrics` 的 `coffee_sse_postgres_connected` / `coffee_sse_redis_connected` 表示被请求到的 API worker 的监听状态，并非多进程聚合值。
- 不新增数据库迁移；旧 Redis `progressPayload` 不再刷入任务表，设备后续状态更新会移除旧字段。
- Mac 开发由 `.python-version` 与 `uv.toml` 固定为 uv-managed Python 3.12，避免系统 Python。
- `uv run --managed-python --with-requirements requirements.txt --with-requirements requirements-dev.txt pytest -q`
- `TEST_DATABASE_URL` 使用隔离 schema；双通道集成测试还需 **专用可销毁的** `TEST_REDIS_URL`，因为测试会断开该 Redis 的 Pub/Sub 连接。禁止指向生产 Redis。
- 覆盖：纯进度不刷 SQL、不查询 SQL、双 API 监听扇出、迟到 revision、终态保护、浏览器重连、Redis Pub/Sub 断线恢复。
