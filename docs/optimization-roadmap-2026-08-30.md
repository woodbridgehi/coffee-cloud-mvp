# 后续优化路线与执行手册

日期：2026-08-30。本文是**后续实施计划，不是完成报告**。由 Codex 直接实施、逐批验证，不调用 pi。路径以对应仓库根目录为基准。

实施进展：R0/B1.1 经 pi 提交及复核后，Codex 直接补充本地修复与验证，见 [B1.1 修复记录](mqtt-lifecycle-review-2026-08-30.md)。该记录不代表生产发布；下列 A1/A2 基线和历史验收数字保留，B1.2/D1 仍未实施。

## 1. 当前基线与目标

| 项目 | 已确认的基线 |
| --- | --- |
| 后端代码 | `2bc7a0a`，A1 资金闭环及 A2 订单/任务/命令协调 |
| 模拟器代码 | `b88fede`，RETRY_WAIT、最终失败保护、重启恢复门禁 |
| VPS | 3 vCPU、约 4 GiB 内存、4 GiB swap；同时运行 PostgreSQL、EMQX、Redis、Forgejo、MinIO 等服务 |
| 部署 | 后端代码已运行，数据库迁移 12；API/Gateway/Worker 健康；模拟器仅源码归档，不在 VPS 启动桌面程序 |
| 回归基线 | 后端 160、模拟器 28、Node 13、独立支付探针 7，共 208 项通过；这是上一批代码验收，不是千台压测 |

发布、备份与回滚位置见 [本次发布记录](releases/2026-08-30-a1-a2.md)。已有 A1/A2 不重复重写，后续在此基础上增量修改。

目标分两层：先保证断线、重复消息、进程崩溃和渠道超时时业务正确；再证明 1000 台设备在明确上报频率、制作比例与浏览器连接数下具有可接受延迟。2000 台作为下一档压测目标，不提前承诺容量。

## 2. 不应再改变的设计边界

1. HTTP 保留激活、凭证、配置、下单等请求响应接口；MQTT 承载设备上行与任务下发；SSE 承载浏览器实时更新。
2. MQTT 协议 keepalive 不形成业务历史；应用心跳/设备状态只保留最新态，按既有策略投影设备状态，不借心跳查询订单。
3. `task.progress` 只进入 Redis 最新值与通知，正常和故障时都不回退为高频 SQL。生命周期事件、订单和财务事实仍持久化。
4. 进度是“变化达到 5% **或**最长 5 秒”发送；关键开始/完成/失败事件不得被限频丢弃。
5. 普通最新态可覆盖，但制作指令、支付与最终事件不能因“已放入内存队列”就当成功。传输允许重复，业务副作用必须幂等。
6. 订单 → job → command → payment → refund 的锁顺序保持不变；需要设备串行锁时先取设备锁，并注意外键隐式锁。外部 HTTP/MQTT 调用不占 SQL 事务。
7. 未知物理结果进入 HOLD；人工结案不等于硬件停止，设备仍忙不能派下一杯。
8. 暂不引入 Rust/C++、微服务、Kafka、Kubernetes；先消除 I/O、事务、队列与重试缺陷。自动备份项目仍暂缓，单次发布前备份照常执行。

## 3. 执行顺序与交付边界

每一行都应形成可独立复核的提交；“代码合并完成”和“允许生产发布”分开判断。

| 顺序 | 编号 | 主要交付 | 前置条件 | 发布限制 |
| --- | --- | --- | --- | --- |
| 0 | R0 | 固定测试环境、版本清单与失败用例 | 当前基线 | 不改生产业务 |
| 1 | B1.1 | MQTT 稳定会话、连接监督、连接代次保护 | R0 | 先验证旧端兼容 |
| 2 | B1.2 | 设备持久 Inbox 后 ACK；任务/事件原子提交 | B1.1 | 与下一行一起完成崩溃验收后发布设备 |
| 3 | D1 | 库存与任务共用 SQLite 事务、一次性导入 | B1.2 | 本地状态备份、迁移验收必须通过 |
| 4 | B2.1 | Redis dirty/inflight 租约和单调投影 | B1 | 单写入版本切换，不能混跑不兼容领取者 |
| 5 | B2.2 | 状态投影后派单、busy→ready 唤醒 | B2.1、A2 | 不允许恢复心跳查订单 |
| 6 | B2.3 | 网关按设备保序、公平重试与错误分类 | B1、B2.1 | 故障设备不能拖住其他设备 |
| 7 | C1.F | 支付/退款渠道事实核验 | A1 | 通过之前不扩大真实支付范围 |
| 8 | C1.1 | 同步操作离开事件循环、只恢复未决消息 | B1/B2 | 无全历史启动重放 |
| 9 | C1.2 | Outbox/发布/支付租约及有界并发、预算清理 | C1.F、C1.1 | 先防旧执行者覆盖，再增加并发 |
| 10 | C2.1 | 激活失败计数、财务终态 SSE、订单号 | C1 | 双通道 SSE 保持分工 |
| 11 | C2.2 | 分页、增量计数、原子审计、配额与调试开关 | B2/C1 | 多 API Worker 共享限制 |
| 12 | D2 | 集成故障测试、100→500→1000→2000 压测 | 以上完成 | 每档达标后才扩大 |

相较早期分批方案，本文建议两处顺序调整：**将原 D 的库存原子性提前紧接 B1**，避免设备升级后仍跨 SQLite/JSON 两个事实源；**将渠道事实核验提前到支付并发之前**，避免并发放大金额判断错误。D 的最终压测和交接仍留到最后。上述调整尚未实施。

## 4. R0：每批开始前的固定动作

1. 记录两仓库 commit、工作树差异、VPS 运行版本及迁移版本。保留用户未提交文件，不覆盖 `.env`、`.secrets`、运行状态或架构文档。
2. 使用独立本地 PostgreSQL、Redis、Mosquitto；PG 每用例随机 schema，Redis 使用隔离前缀/独立实例。禁止把 `TEST_DATABASE_URL` 指向 VPS。
3. 先补能证明原问题的失败用例，再修改代码；旧审查脚本保留历史意义，不改成“永远通过”。
4. 为新迁移做现有数据只读预检；为新增配置写默认值、上限和故障策略。确定本批不修改的模块。
5. 锁定可复现依赖：当前 requirements 固定了直接依赖，但部分传递依赖仍可变化。补充 uv 锁定/约束文件及镜像版本记录，避免同一源码重建出不同环境。该项单独提交验证，不顺便全面升级依赖。

上一批本地测试实例已停止。重建测试环境后再运行：

```bash
# coffee-cloud-mvp：由测试环境安全注入 TEST_DATABASE_URL / TEST_REDIS_URL
uv run --managed-python --with-requirements requirements-dev.txt pytest -q
node --test tests/test_order_view.mjs

# coffee-terminal-simulator
uv run --managed-python --python 3.12 \
  --with-requirements coffee-terminal/requirements.txt --with pytest pytest -q
node --test tests/*.mjs
```

真实 PG/Redis/Broker 集成项被 skip 时不能判定通过。模拟器 Python 使用 uv，不使用 macOS 系统 Python。

## 5. B1：先保证消息与本地业务可恢复

### B1.1 会话与连接生命周期

主要文件：后端 `app/mqtt_gateway.py`；模拟器 `coffee-terminal/mqtt_transport.py`；相关 MQTT 测试。

执行步骤：

1. 用固定唯一 Client ID、非零会话有效期和 MQTT5 `clean_start=False`；移除随机默认网关 ID，单实例稳定默认与多实例唯一 ID 写入配置说明。
2. 每个传输只保留一个连接监督器，统一处理初次连接失败、意外断开、背压断开、暂停/恢复和关闭。网络回调只发信号，不能 join 自身线程。
3. 在旧网络循环停止后重连；指数退避可被 stop 打断。close 幂等，关闭后禁止重新连接。
4. 接收消息携带连接 generation。旧连接的 MID 不能 ACK 新连接中的另一条消息；关键线程退出使健康失败并触发受控恢复。

验收：真实 Broker 上同 ID 客户端对象重建后收到离线 QoS1 消息；反复 suspend/resume 后只有一个网络循环；初连失败能恢复；旧 generation 不 ACK 新连接；close 后无线程泄漏。Paho 的 clean-start 会清除会话，manual ACK 可由应用在处理完成后调用，不能把默认回调返回当作持久成功。[Paho 官方接口说明](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html#paho.mqtt.client.Client.connect)

### B1.2 持久接收与任务事务

主要文件：模拟器 `coffee-terminal/state_store.py`、`coffee-terminal/backend.py`、`coffee-terminal/mqtt_transport.py`。

执行步骤：

1. 校验 JSON 对象、完整 topic、内外层 deviceId、messageId 和摘要后写 SQLite Inbox；提交成功才发 MQTT ACK。永久坏包隔离，磁盘失败不 ACK 并报告故障。
2. 内存队列只负责唤醒，SQLite RECEIVED 才是待办事实。提供有界读取，在启动/重连/唤醒及低频兜底时处理；唤醒队列满不能丢已持久指令。
3. `LocalStateStore` 增加可嵌套事务，外层 `BEGIN IMMEDIATE`，内层复用或 savepoint。
4. 接单、拒绝、开始、暂停、重试、失败、完成、取消和重启恢复各自采用业务事务，将 job、关联事件、命令结果一并提交，而不是只添加未使用的 transaction helper。
5. 异常回滚后恢复内存 task/revision/events/进度报告状态，或停止执行进入明确故障。禁止 DB 回滚而内存继续动作。此时库存原子性还未完成，进入 D1 后再发布设备版本。

验收：分别在 Inbox 提交前/后、ACK 前/后、job 保存后/事件保存前注入崩溃，重开数据库后只存在“一起提交”或“一起回滚”；重复 taskId/messageId 不再次执行；队列满仍能从 Inbox 恢复。

## 6. D1：库存与任务统一事实源

主要文件：模拟器 `coffee-terminal/inventory.py`、`coffee-terminal/state_store.py`、`coffee-terminal/backend.py`。

1. Runtime 库存使用同一个 SQLite 连接与事务；配方、materials.json 继续作为配置，不迁移为业务数据库。
2. 仅在 SQLite 无库存时导入旧 `state/inventory.json`，校验余额、预占、consumedKeys、版本；原子保存迁移标记。保留旧 JSON，不自动删除或反复导入。
3. 将预占 + job + ACK、步骤消耗 + 幂等操作 ID + 进度 + 事件、取消/完成释放 + 最终事件分别纳入同一事务；回滚同时恢复内存库存。
4. 重启核对预占归属：活动任务匹配则保留；孤儿预占/未知消费进入恢复故障，不能直接清空或初始化成满库存。
5. 保留 `taskId:stepId:attempt` 消费幂等键；不增加每 250ms 的库存落库。SQLite 事务不能回滚物理电机，真机仍需硬件操作 ID、传感器和互锁。

验收：一次导入、重复启动不导入、损坏 JSON 失败关闭；预占/扣料/事件之间每个崩溃点均原子；重复动作不重复扣料；孤儿预占可见。**一旦新版本写了 SQLite 库存，不能直接回滚到继续读取旧 JSON 的设备版本。** 必须停机对账并有显式反向转换方案，否则前向修复。

## 7. B2：最新状态可靠投影，派单不丢唤醒

### B2.1 Redis dirty/inflight 租约

主要文件：`app/telemetry.py`、`app/repositories/telemetry.py`、`app/services/background_worker.py`。

1. 用 Lua 原子完成 hash 更新、revision 增加和 dirty 标记；用 pipeline 合并往返，不存遥测历史。
2. 将 `ZPOPMIN` 后就消失的待刷记录改为 dirty → inflight，附唯一 token 与 lease deadline；批量领取有界。
3. PG 成功提交后才 ACK 领取 token。写库失败仅释放自身领取；过期领取可回收，不能依赖设备下一次上报才恢复。
4. ACK 不能删并发出现的新 dirty；旧 token 不能确认新租约。PG 投影检查时间/接收次序单调性，不能只依赖 Redis 重启后可能归零的 revision。
5. 同 boot 的 sequence/stateRevision 拒绝倒退；跨 boot 需要明确会话/时间规则，不能用随机 UUID 大小判断新旧。

验收：claim 后崩溃仍可回收；两个 Worker 不重复占有同一租约；新上报不被旧 ACK 删除；慢 Worker 不能覆盖较新 PG 状态；progress 仍不写 SQL。指标至少有 dirty/inflight 数量、最老年龄、claim/flush 失败；禁止每轮全库扫描计算精确积压。

### B2.2 状态转换驱动派单

主要文件：`app/repositories/telemetry.py`、`app/repositories/dispatch.py`、`app/services/production.py`、`app/services/background_worker.py`、`app/services/device_messages.py`。

1. 同一 PG 事务批量更新状态并按旧/新快照识别“离线→在线”和“busy/recovering→可接任务”；仅转换时 enqueue 去重派单请求，不查订单。
2. presence 早于心跳时不能提前消费唯一派单机会；新鲜心跳真正落地后仍应触发派单。普通重复 IDLE 心跳不触发。
3. 调度显式区分 dispatched、no-work、busy、waiting-online。暂不可派单不能一律删除意图；通过有界退避/状态事件恢复，旧 complete 不能删并发新 revision 的请求。
4. HTTP 降级路径使用同样的状态转换语义；A2 设备忙碌门禁保留。

验收：presence 先到仍能派旧排队单；人工结案后设备稍晚空闲能继续派单；重复心跳不产生订单查询/派单请求风暴；旧快照不伪造空闲。

### B2.3 网关公平保序与错误分类

主要文件：`app/mqtt_gateway.py`、`app/services/mqtt_gateway.py`、`app/main.py`。

1. 使用有界 per-device FIFO 与 ready/due 调度；失败消息保留该设备队首并设置下次时间，不放回队尾，不让整个 shard sleep。
2. 其他设备继续执行；总容量、每设备容量和最老等待时间均可见。瞬时遥测可合并，持久生命周期不能越过同设备失败的前序消息。
3. 永久协议错误隔离；网络、5xx、429 和网关凭证配置错误保留重试/报警，不能到次数就丢关键事实。
4. 内层 Pydantic 错误映射 422，批量响应按原始 index 区分成功与失败；处理 UTF-8、非对象 JSON、非法 topic，不让异常杀死关键线程。

验收：故障设备 A 不拖慢设备 B；A 的事件不乱序；混合好坏 batch 不误 ACK；满队列触发可恢复背压；旧连接 ACK 保护持续有效。

## 8. C1：渠道事实、异步入口与后台资源预算

### C1.F 先核对实际付款/退款结果

主要文件：`app/payment_providers.py`、`app/payment_service.py`、`app/services/payments.py`、`app/services/public_orders.py`、`app/services/background_worker.py`、`app/repositories/payments.py`。

1. 提取统一渠道结果转换函数，核对商户单号、稳定渠道交易号、应用身份和 Decimal 金额。查询/关单返回 PAID 时，禁止拿本地期望金额冒充渠道实收金额。
2. 复用到创建支付后的查询、后台对账、取消后的渠道关单；金额缺失/冲突维持未决并报警，不派单、不伪造成功。
3. 退款不使用 `bool("0.00")` 或缺失 `fund_change` 默认成功；核对原支付和退款请求号、正数精确金额及适用渠道状态。未知结果继续占用退款预算，重试使用原退款单号。
4. 迟到的 PENDING 元数据不能覆盖已 PAID/REFUNDING/CLOSED 的交易号和状态；保持 A1 幂等、主支付与退款额度规则。

验收：零/缺失/错误金额、错误单号、pending 带金额、重复退款、迟到查询全部覆盖。先 mock 渠道 + 真 PG，再独立安排渠道沙箱；mock 通过不等于真实扫码付款验收。实施前复核项目实际采用的支付宝 V2 接口契约，不把 V3 示例直接套入 V2。

### C1.1 事件循环与未决恢复

主要文件：`app/main.py`、`app/domain_worker.py`、`app/services/background_worker.py`、`app/repositories/mqtt_gateway.py`。

1. 逐个检查 async 路由；同步 SQL/HTTP/验签通过线程池执行，可类型化的端点改为同步 def。SSE 等待仍 async。
2. 删除 API 与 Domain Worker 正常启动时的全历史事件重放。已在一个事务应用的 terminal_event 不需要启动再应用。
3. 只恢复 MQTT Inbox 的 RECEIVED/RETRY：追加领取租约、重试时间、次数与部分索引，使用有界 `LIMIT/SKIP LOCKED`，逐项短事务，通过统一业务入口幂等处理。
4. 历史修复若保留，改为有范围、limit 和人工触发的离线工具，不阻塞就绪。

验收：80ms 同步业务不阻塞 10ms 定时任务；大量已完成历史不增加启动扫描量；未决消息崩溃后恢复；恢复不触发 progress SQL。

### C1.2 租约、有界并发与清理

主要文件：`app/repositories/` 下的 workers/commands/payments 模块及对应 Service、`app/mqtt_gateway.py`、`app/settings.py`。

1. Business Outbox 的 PROCESSING 超时可重新领取；complete/retry 校验 token，旧执行者不得覆盖新领取。
2. 发布者只领取立即可处理的任务，初始每次 1 条，不再领取 100 条后串行等待。published/retry 带 attempt/token，不能仅依赖同一 gatewayId。
3. 支付与退款使用长期复用的独立有界执行池，建议初始各 2 并发；只领取空闲槽数量，不堆无界 future。租约覆盖渠道最坏超时，外部请求期间不占 SQL 连接。
4. 对已最终完成但 Outbox 仍 PUBLISHING/RETRY 的记录做小批结案，使用明确的“无需再投递”状态，不能伪造 Broker PUBACK；UNKNOWN/HOLD 保留证据。
5. 历史清理每批独立事务，建议初始 1000 条、每轮总预算 2 秒，各表公平推进；保护未决事件、任务、支付与退款事实。指标区分可处理积压与待人工核对。

验收：领取后崩溃可恢复，旧 token 被拒；慢渠道不占满连接池；并发数不超过配置；超过 5000 条历史可持续清理而非一次大事务；最终命令不再误发。

## 9. C2：SSE、运营查询与资源入口

### C2.1 激活、财务完成与订单号

主要文件：`app/services/device_identity.py`、`app/order_stream.py`、`app/order_events.py`、订单/支付 Repository、`public/order.js`。

1. 错误激活计数与锁定/过期标记先提交，再返回错误；不能因抛异常回滚计数。达到上限后正确码也不能绕过锁定。
2. 统一 `streamComplete`：制作最终态且没有待处理支付/退款才关闭 SSE。用有索引的 EXISTS 投影财务未决标志，退款状态更新也发 PG 通知。
3. 浏览器初始/重连/更新使用同一完成判断；Redis 进度通知只读 Redis，不能因退款等待而退回定时 SQL 轮询。断线重连补读当前快照，通知不是业务事实存储。
4. 订单号使用完整日期 + 至少 96bit 随机值；仅 order_no 唯一冲突可用 savepoint 有限重试 3 次，不重建访问令牌或改变请求幂等性。

验收：激活多次错误后真实持久 LOCKED；FAILED+REFUNDING 不断流，退款最终通知后关闭；相同幂等请求仍返回原订单；碰撞重试不使外层事务失效。

### C2.2 查询、审计和公共配额

主要文件：`app/services/admin_operations.py`、`app/services/admin_access.py`、各写业务 Service、`app/repositories/terminals.py`、`public/admin.js`、`app/settings.py`。

1. 设备列表默认 50、最大 200，按稳定 id 游标分页；页面提供下一页/加载更多。GET 不执行离线更新扫描。
2. 用独立 `terminal_counters` 表保存累计基线与增量，代替每台设备全历史 count；事件首次成功应用后同事务加计数，计数锁放在业务锁之后。不要用事件触发器先 UPDATE terminal 再锁订单。
3. 管理 DB 写操作与审计同一事务；外部 Broker 操作用意图/结果记录，不虚构跨网络原子事务。审计禁止包含 Token、激活码或密钥。
4. 未支付配额独立于在制队列，建议每设备 20 个；无支付意图的超期订单小批过期，有渠道未决结果的不能假设没付款。
5. 公共写操作按 IP + device/order 分层限制，SSE 按 IP + order + 全局活动连接限制；Redis 原子计数/租约跨 API Worker 共享。429 带 Retry-After，连接结束释放、崩溃后 TTL 回收。
6. 生产限制器 Redis 故障时写入与新 SSE 连接返回明确 503；已认证只读可继续。开发本地限制器必须显式启用，不能伪装多进程共享。
7. IP 来源只信任实际配置的代理链，不直接相信任意 X-Forwarded-For。生产 debug 端点默认关闭，正式管理员受限操作保留。

验收：分页无遗漏重复；GET 零写；事件重复不加计数；审计失败业务回滚；并发建单不超额；双 Worker 限额共享；伪造转发头不绕过；SSE 异常断开可回收额度。

## 10. D2：如何证明 VPS 能承载目标设备数

### 10.1 先定义负载，不只写“1000 台”

| 场景 | 1000 台的估算/要求 |
| --- | --- |
| 30 秒一次错峰应用心跳 | 约 33 次/秒；另计 presence/state，不能重复算作免费 |
| 进度 5% 或 5 秒 | 不是硬性最多 200 次/秒；快速制作可能因 5% 阈值更频繁 |
| 保守进度预算 | 活跃设备数 A、平均制作时长 T 秒，可先按 `A × (20/T + 1/5)` 次/秒预留，再用真实轨迹校准；不含生命周期事件 |
| 示例 | A=1000、T=60，保守预算约 533 次/秒；它是规划上界近似，不是实测吞吐 |
| 浏览器 | 独立注明同时打开的 SSE 数量；1000 台设备不自动等于 1000 个顾客连接 |
| 故障 | 分别测试单设备断网、网关重启、Redis 中断、慢 PG、渠道超时、批量重连 |

VPS 上还有其他服务，不能把 4 GiB 全部划给咖啡系统；swap 只作缓冲，不作为可持续容量。

### 10.2 连接与内存预算

先保留现有 API 2 Worker，不盲目增加进程。记录真实池配置后计算：

`总 PG 连接预算 = API Worker数 × 每池上限 + Domain Worker池 + 每API进程LISTEN连接 + 其他应用/运维预留`

例如仅作初始试验，API 两池各 8、Domain 池 6、LISTEN 2，则本系统约 24 条，另加其他服务和运维；这不是已修改配置。若引入事务池，需要为会话绑定的 LISTEN 单独保留直连/会话通道，不能把全部连接一概放入事务池；该设计依据 LISTEN 的会话语义。[PostgreSQL LISTEN 文档](https://www.postgresql.org/docs/current/sql-listen.html)

每次只改变一个变量：池大小、线程并发、批大小或 API Worker 数。记录变更前后 CPU、可用内存、池等待、队列年龄及延迟，不以空载内存或 `/health` QPS 推断设备容量。

### 10.3 分档与通过标准

在独立测试机产生负载，不在 VPS 同时运行高负荷 Python 压测器。100→500→1000→2000 每档先空闲心跳，再 20% 制作，再 100% 制作与指定 SSE 数；每小档至少 15 分钟。1000 台达标后增加至少 2 小时稳定性观察，之后才能评估 2000 台。生产 VPS 的故障注入/压力测试需要单独安排窗口，不随普通部署自动执行。

建议初始门槛（均为待验证目标，不是承诺）：

- 订单、扣料、退款副作用零重复；可恢复故障中关键事件零丢失；永久坏消息有隔离记录。
- HTTP P95 <300ms，错误率 <0.1%；关键事件 P95 <500ms、P99 <1s；SSE P95 <500ms。先明确计时起终点，区分队列等待与传输。
- 只注入 progress 的场景中，production_job revision/updated_at、事件历史数和订单 SQL 读量不随 progress 增长。
- 宿主机 CPU 持续 <70%、可用内存 >20%，无 OOM、持续 swap 或重启；正常队列占用 <50% 且最老年龄不持续增长。
- dirty/inflight、未决 Inbox/Outbox 在停止故障后有界收敛；先以 30 秒恢复目标测试小故障，再按停机时长与积压量调整恢复预算。

任一正确性门槛失败立即停止扩容；资源/延迟失败时保存火焰图或采样、SQL 等待和队列指标，定位一个瓶颈再修复。只有证明存在显著 CPU 热点且 Python 方案已优化后，才评估将独立解析/计算模块迁入 Rust/C++；不整体重写订单事务。

## 11. 每批验收、发布与回滚清单

- [ ] 新失败用例能复现原问题；修改后通过，旧 A1/A2 回归不退化。
- [ ] 真 PG/Redis/Broker 测试、Node 逻辑、Ruff、diff 检查通过；记录 skipped 与未测场景。
- [ ] 新配置、迁移、协议版本、旧端兼容及指标已写入文档；未用“全部完成”覆盖待办。
- [ ] 本地提交代码与测试，再提交验收记录；部署只使用已提交归档，不拷贝 `.env/.secrets`。
- [ ] 发布前核对活动任务、未决支付、重复活动 job 和版本；不静默修复历史资金/物理结果。
- [ ] 保存旧镜像、源码和数据库备份；先构建并以实际非 root 用户导入应用，再进入维护窗口迁移。
- [ ] 归档解压保留源码读取权限，备份目录维持私有权限；两者不能混用 umask 导致容器不可读。
- [ ] 后端先兼容新协议再升级设备；Redis key/SQLite 数据格式变更必须给出混跑或停写切换方案。
- [ ] 逐步扩大设备批次，核验健康、源码哈希、迁移、关键接口与队列；只返回 200 不算全链路通过。
- [ ] 触发失败则停止派新任务并保持证据。数据库/SQLite 迁移后的回滚不等于恢复旧镜像；先评估新状态是否被旧代码识别，优先前向修复，禁止直接把备份覆盖当前生产库。

每批交付记录统一包含：问题编号、基线/结果 commit、修改文件、迁移/配置、实际测试命令与结果、故障注入证据、部署版本、回滚条件、遗留问题。完成一批再进入下一批，不把“已写方案”标成“已实现”。

## 12. 下一次可直接开始的任务

先执行 **R0 + B1.1**：补稳定会话、连接监督和 generation 的真实 Broker 测试，修改两端传输生命周期，运行两仓库回归并形成一个独立提交。验收后继续 B1.2/D1。不要同时改支付、SSE 或管理页面；不要在本轮只写路线文档时悄悄实施这些后续代码改动。
