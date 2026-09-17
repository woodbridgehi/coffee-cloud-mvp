# 制作、取杯与资金一致性

核对日期：2026-09-17。实现依据：`production_state.py`、`services/production.py`、`services/public_orders.py`、`services/adjudications.py`、`services/refund_intents.py`、`repositories/pickup.py`。

## 四套状态分别解释

- 订单：CREATED、AWAITING_PAYMENT、PAID、QUEUED、DISPATCHED、ACCEPTED、MAKING、READY、HOLD、FAILED、CANCELLED、EXPIRED、REFUNDED。不要使用旧 README 的 PENDING_PAYMENT 或 COMPLETED 作为当前订单状态。
- 制作任务：QUEUED、DISPATCHED、ACCEPTED、EXECUTING、PAUSED、RETRY_WAIT、HOLD、UNKNOWN 及制作终态。
- 命令：CREATED、DELIVERING、PUBLISHED、ACKED、EXECUTING、UNKNOWN 及命令终态。Broker PUBACK 仅证明发布确认，不等于任务接受。
- 支付/退款：各自有状态和金额预算；订单取消并不代表退款已到账，READY 也不代表顾客已经取走杯子。

## 设备事件映射

| 事件 | 云端任务 | 订单 | 制作命令 |
| --- | --- | --- | --- |
| task.acknowledged | ACCEPTED | ACCEPTED | ACKED |
| task.started / resumed / retry | EXECUTING | MAKING | EXECUTING |
| task.paused | PAUSED | MAKING | EXECUTING |
| task.retry_wait | RETRY_WAIT | MAKING | EXECUTING |
| task.recovered | HOLD | HOLD | UNKNOWN |
| task.succeeded | SUCCEEDED | READY | SUCCEEDED |
| task.failed / rejected | FAILED / REJECTED | FAILED | FAILED / REJECTED |
| task.cancelled | CANCELLED | CANCELLED | CANCELLED |

此表是目标映射，不允许跳过关联、revision 和合法迁移检查。普通 resumed/retry 不会解除 HOLD；匹配的最终事实或人工裁决可结案。终态不能被更大 revision 复活，旧 revision 与同 revision 冲突被拒绝。制作事件可能早于网关 published 回执到达。

暂停/RETRY_WAIT 仍占用活动任务名额；等待超时进入 HOLD，不按失败直接退款。`task.progress` 仅更新 Redis 进度，不决定 SQL 终态。

## 队列、物料承诺与取杯

顾客取消允许未支付或 QUEUED 状态，精确条件见 `PublicOrderService.cancel()`；已派单不能由顾客页面强制撤销设备制作。默认队列准入上限20，由配置控制。

云端对当前快照扣除未决订单物料承诺，并检查库存版本水位，避免生命周期已推进但库存仍旧时继续售卖。终端接单再次检查库存并预占。商户账面库存不参与替代终端物理确认。

`task.succeeded` 后订单 READY，终端取杯位 OCCUPIED；超过两分钟终端标记 NEEDS_CHECK。确认取走后发送 `pickup.collected`，云端保留订单 READY 并记录 collected_at。派单还检查取杯投影，不靠“已制作完成”立即放行下一杯。新终端通过受保护本地接口或现场按钮确认取杯；顾客没有远程清空杯位接口。

## 退款边界

明确失败/拒绝/取消、顾客派单前取消，以及可证明未送达的命令过期等路径，满足已付款及剩余预算条件时创建幂等退款意图。不是只有“排队超时”才能自动退款。

命令曾被领取发布、有投递证据或物理结果未知时，超时走 HOLD/UNKNOWN，不能推断未制作。REQUESTED、PROCESSING、UNKNOWN 和 SUCCEEDED 退款均占预算；UNKNOWN 不能当失败释放预算。只有渠道确认后的结果才结算支付投影。

`ensure_automatic_refund_intent()` 是预算入口；付款回调、退款意图与退款完成不能混称一个状态。TEST_FREE 没有真实付款可退。

## HOLD 的两个独立处理面

### 云端订单裁决

`POST /api/v1/admin/orders/{order_id}/adjudication`，要求 commands.execute 与 refunds.manage，以及 `Idempotency-Key`。请求包含 taskId、expectedRevision、outcome（SUCCEEDED/FAILED/CANCELLED）和 reason。版本冲突返回409；同键同内容返回原结果。

裁决在同事务保存状态、必要退款意图、审计和幂等结果。它不发送物理停止，也不支持“恢复制作”；响应 `physicalStopConfirmedByServer=false`。设备释放提示并非实时硬件证明，后续派单仍检查设备状态。

### 终端现场核验

当前终端 remote 重启的活动任务设置 recoveryHold；普通 cancel/resume/retry/skip 均不能绕过。现场 `confirm_recovery(task_id, revision, checks)` 要求版本匹配和三个严格 true 的检查项，取消旧任务并保留核验记录，释放未消耗预占，不退回已经消耗的物料。

该入口通过 pywebview 桥接，没有公共 HTTP 核验接口。见[终端核验说明](../../coffee-terminal-simulator/docs/restart-recovery.md)。云端裁决和终端现场核验不能互相替代。

## 迁移与验证

迁移11包含活动任务唯一索引，12为裁决幂等记录，21为队列/库存水位，22为取杯联锁，23为执行 attempt。部署须运行全部未应用迁移，不应只按旧发布记录停在12或18。

相关测试：`test_production_consistency.py`、`test_adjudications.py`、`test_payment_consistency.py`、`test_queue_materials.py`、`test_pickup_slot.py`、`test_pickup_stream.py`；真实数据库测试需要隔离 TEST_DATABASE_URL。测试文件存在不代表本次已执行，也不代表物理硬件安全已验证。
