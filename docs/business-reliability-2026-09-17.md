# 业务可靠性整改（2026-09-17）

基线：2198bd14d9ed0807cb77b879b445e2575f8b88fd。实现分支：fix/business-reliability-20260917。

## 实现

- C-02：消息比较契约 v2 只排除外层 `sentAt`，业务 payload、设备、类型、协议版本继续参与比较。同 ID 改业务字段仍返回 409。
- 旧记录兼容：持久化摘要仍保持 v1（原始 envelope 的 SHA-256）。摘要不同的消息，先验证已存 envelope 与已存摘要一致，再比较两份 envelope 的 v2 业务摘要。没有覆盖历史摘要或删除去重记录，不需要批量重写旧记录。
- 增加业务事件/命令结果的 RECEIVED/RETRY Inbox 恢复（不重放过时的 presence/state/heartbeat）：正常入口保留消息，后台从原始已存 envelope 重放，仍经过业务服务幂等保护。首次恢复延迟 30 秒，失败退避上限 300 秒；持久调度字段配合 SKIP LOCKED 防止多 worker 同时领取。慢请求超过恢复租期时仍可能重叠，业务幂等承担最终保护。PROCESSED 不会被迟到失败降级成 RETRY。
- C-03：派单返回结构化原因。心跳过旧、已有活动任务、取杯占位、设备忙或停用时，只要仍有排队订单，就保留持久请求并退避（最多 30 秒）；无订单或已派单才完成请求。保留 revision 并发保护和全部业务联锁。
- C-04：新建调试/原始命令缺省有效期为 5 分钟；调试任务控制绑定创建时已上报的 currentTaskId，无目标返回 409。MQTT 发布计算剩余 TTL，已过期不发布，Broker MessageExpiryInterval 不替代终端有效期检查。
- 派单阻塞日志含 terminal/revision/reason/attempts；Inbox 恢复失败日志含设备、消息 ID、次数及异常类型，不输出载荷或凭据。

## 发布与回滚

1. 先升级云端，按项目既有 migration 机制执行 migration 24。该迁移只新增 `mqtt_inbox.recovery_attempts`、`next_recovery_at` 和待恢复索引，保留所有历史记录。
2. 再升级终端；新版终端会拒绝没有 taskId 的任务控制，所以不建议终端先于云端升级。旧维护命令缺失 expiresAt 的兼容期仍保留，但新云端会提供期限。
3. 回滚应用代码可保留新增列/索引，旧版本会忽略；不删除 Inbox，不删除迁移记录。回滚旧云端会重新暴露重试摘要和派单缺陷，应暂停推广并检查积压；不能把回滚描述为可靠性修复。
4. 检查长期 RETRY/RECEIVED、dispatch 阻塞原因及等待时长。永久无效消息仍会受限退避并记录警告，后续可按运营需求增加单独的隔离/人工处理界面。

## 验证

新增 tests/test_business_reliability.py 覆盖真实 PostgreSQL 旧摘要兼容、业务失败后重试、业务已提交后响应丢失、Inbox 独立恢复与恢复领取隔离；真实 Redis + PostgreSQL 覆盖 presence 先到、心跳延迟、刷库再延迟，最终只派单一次。

MQTT 测试覆盖发布 TTL 与过期拒绝；终端配套仓库覆盖真实 Broker 积压消息过期和持久接收。

运行完整 MQTT 测试时，每个仓库应使用全新的独立 Broker。终端测试会留下 retained presence/state；共用累积了这些主题的 Broker，会先占满网关背压测试故意阻塞的接收窗口，导致故障注入条件不成立。此次发现 21 个残留主题后使用独立端口复验，未放宽背压断言。

本次使用独立临时 PostgreSQL、Redis、Mosquitto，仅监听本机；没有访问生产数据或支付渠道。首轮验证：Python 286 passed，Node 89 passed，没有失败或跳过项。GUI、真实支付和机械设备未验收。取杯、HOLD、退款状态保护未取消。

## 复审补充：升级时找回已丢失的派单请求

复审基线 30ed73d。原来的重试只能保留已有请求，无法发现旧版删除请求后留下的 QUEUED 任务；该升级缺口成立，已用真实 PostgreSQL 验证。

- domain worker 启动后的首轮执行补偿，此后每 30 秒扫描一次。每次最多补建 100 个设备请求，后续轮次继续处理余下设备，不在每次心跳上扫描。
- 只为 production_job 与 sales_order 都为 QUEUED、且没有请求的设备补建 `queued-order-recovery` 请求。同一设备多杯只补一个请求。
- `ON CONFLICT DO NOTHING` 避免多 worker 重复插入，并保留已有请求的 revision、退避状态和租约。补偿只入队，不直接创建制作命令，仍经过原有离线、取杯、活动任务/HOLD 等检查。
- 验收包含旧请求缺失且无任何新外部事件时恢复派单、并发扫描、重复扫描、已有 PROCESSING 租约不变，以及离线/取杯/HOLD 期间不派单。

本轮不新增数据库迁移；仍需此前的 migration 24。回滚本轮代码会停止自动发现缺失请求，但保留已经补建的请求和既有业务状态。

复审修复后的全量验证：Python 291 passed；Node 89 passed，无失败、无跳过。使用临时 PostgreSQL/Redis 及两个仓库各自独立的本机 Broker；未访问生产服务。

## 合并与部署状态

修复已合并 main（88cfdb4）并部署云端 API、worker、gateway；migration 24 已应用。VPS 隔离 Python 全套 290 通过、1 项因解释器路径跳过，补齐依赖后含该项的 8 项用例全部通过；Node 89 通过。部署、备份恢复与保留策略见[发布记录](releases/2026-09-17-business-reliability.md)。
