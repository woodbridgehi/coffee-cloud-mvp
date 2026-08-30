# 制作状态一致性整改（2026-08-30）

范围：A2 批次；2026-08-30 随后端 `2bc7a0a` 部署 VPS，迁移 12 已执行，不代表全部系统整改完成。见 [发布记录](releases/2026-08-30-a1-a2.md) 和 [后续执行手册](optimization-roadmap-2026-08-30.md)。

## 状态与事务

`DeviceMessageService.event/task_ack` 进入 `ProductionService.reconcile_device_event`。首次只读定位，随后按 **订单 → 制作任务 → 精确关联制作命令 → 支付 → 退款** 加锁；先共同验证状态、关联和设备 revision，再一次事务更新。HTTP 拉取使用只读候选、逐命令事务，过期处理不能先拿命令锁再等待订单。

| 设备事件 | 云端任务 | 订单 | 制作命令 | 资金处理 |
| --- | --- | --- | --- | --- |
| task.acknowledged | ACCEPTED | ACCEPTED | ACKED | 无 |
| task.started / resumed / retry | EXECUTING | MAKING | EXECUTING | 无 |
| task.paused | PAUSED | MAKING | EXECUTING | 无 |
| task.retry_wait | RETRY_WAIT | MAKING | EXECUTING | 不退款 |
| task.recovered，state=PAUSED | HOLD | HOLD | UNKNOWN | 等待人工核对 |
| task.succeeded | SUCCEEDED | READY | SUCCEEDED | 不退款 |
| task.failed / rejected | FAILED / REJECTED | FAILED | FAILED / REJECTED | 唯一退款意图 |
| task.cancelled | CANCELLED | CANCELLED | CANCELLED | 唯一退款意图 |

表格不代表任意状态均可迁移。例如制作开始后的拒绝 ACK 不再生效，暂停只能 resumed，等待重试只能 retry。终态不能被更大 revision 复活；相同 revision 冲突不覆盖，重复 eventId 比较摘要后幂等返回。旧协议缺少 revision 仍受状态机约束。已认证且关联正确的事件可先于网关 published 回执到达；不要求命令先变为 PUBLISHED。

暂停/重试仍占用该设备活动任务名额。`PRODUCTION_WAIT_TIMEOUT_SECONDS` 默认 900 秒，超时只进入 HOLD，不按制作失败自动退款。制作进度继续按设备 5%/5 秒策略上报，仅保留 Redis 最新值，不参与 SQL 状态迁移。

## HOLD 人工结案

接口：`POST /api/v1/admin/orders/{order_id}/adjudication`。

- Bearer 管理员认证，必须同时具备 `commands.execute` 和 `refunds.manage`（MANAGER/OWNER）。
- 必填 `Idempotency-Key`，1–160 字符。
- `taskId`、`expectedRevision`（云端制作任务版本）、`outcome`（SUCCEEDED/FAILED/CANCELLED）、`reason`（1–1000 字符）。不支持“恢复制作”。
- 管理员订单列表返回 `taskId` 和 `productionRevision`；提交前读取当前版本，版本冲突返回 409。
- 仅 HOLD 且待人工核对的任务可接受新裁决。同键同内容返回原结果（即使已结案）；同键不同内容 409。
- 命令/任务/订单结案、退款意图、派单请求、审计和幂等结果在同一 SQL 事务提交。审计失败时整体回滚，不会只扣款/退款而丢审计。

请求正文示例：

```json
{"taskId":"task-example","expectedRevision":6,"outcome":"SUCCEEDED","reason":"现场确认已出杯，已核对设备停止"}
```

响应 `productionRevision` 是结案后的云端任务版本；`deviceReleasePending` 是提交时设备投影的提示，重放幂等结果不会变成实时查询。`physicalStopConfirmedByServer=false` 明确服务器没有感知物理停止。

**人工结案不是停止硬件的命令。** 必须先核实现场实际结果、安全停止状态，再选择结案结果。设备仍 RUNNING/PAUSED/RETRY_WAIT/BUSY/RECOVERING 时，调度会独立重新检查并拒绝下一杯。远程重启后的模拟器拒绝普通 resume/retry/skip，需要通过现有受控 CANCEL_TASK 结束旧任务、上报空闲状态。ready 状态变化可靠唤醒派单的完善工作仍属于 B2，不能将本批门禁当成该问题也已解决。

## 迁移与上线边界

- 新迁移 11 扩展活动任务唯一索引，包含 PAUSED/RETRY_WAIT/HOLD/UNKNOWN；迁移 12 创建裁决幂等记录表。此前 A1 的迁移 10 增加主支付关联。
- 上线前先只读检查同设备多活动任务，不能通过删除历史任务强行使索引创建成功：

```sql
SELECT terminal_id, count(*) AS active_jobs
FROM production_job
WHERE status IN ('DISPATCHED','ACCEPTED','EXECUTING','PAUSED','RETRY_WAIT','HOLD','UNKNOWN')
GROUP BY terminal_id HAVING count(*) > 1;
```

- 此查询有结果应停止迁移并逐笔人工核对。新代码不会自动修复历史“已退款但设备仍运行”等物理/财务矛盾，亦不自动对真实历史订单发起退款。
- 后端需先支持 task.retry_wait，再升级设备；混合新旧版本必须避免旧设备继续采用 FAILED→retry。最终部署时仍需对未决任务进行核对。
- MQTT 会话/持久接收、SQLite 跨任务与 Outbox 原子性、库存统一事务、Redis dirty 租约、渠道支付金额契约、有界 Worker 和安全配额仍待后续批次；不据此承诺千台容量。
