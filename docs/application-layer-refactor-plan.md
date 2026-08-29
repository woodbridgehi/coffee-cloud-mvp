# 应用分层重构计划

## 目标

在不修改公开 API 和状态机语义的前提下，将业务 HTTP 请求统一为 `Route → Service → Repository → PostgreSQL`，并用自动化测试阻止分层回退。

## 实施阶段

| 阶段 | 范围 | 状态 | 验收 |
| --- | --- | --- | --- |
| 0 | 重构前 Git 基线 | 已完成 | 基线提交 `dff2513` |
| 1 | UnitOfWork、Repository、Service 基础设施 | 已完成 | Service 管理事务，Repository 集中 SQL |
| 2 | 公开订单、支付退款、运营查询 | 已完成 | 路由只调用 Service，原接口契约测试通过 |
| 3 | 设备激活、凭证、心跳、快照、事件 | 已完成 | 激活/轮换/去重语义保持 |
| 4 | MQTT Inbox、Command Outbox、后台及调试命令 | 已完成 | 命令租约、PUBACK、重试和幂等逻辑迁移 |
| 5 | 架构测试、文档、OpenAPI、全量回归 | 已完成 | Route/Service 禁止 SQL；Python 与前端测试通过 |
| 6 | 后台 Worker 分层 | 已完成 | `BackgroundWorkerService` + `WorkerRepository`，全量回归通过 |

## Worker 迁移结果

1. OfflineMonitor 查询与更新已迁入 `WorkerRepository` / `BackgroundWorkerService`。
2. Business Outbox 领取、租约、完成/重试已迁入 `WorkerRepository` / `BackgroundWorkerService`。
3. 支付主动查询和退款执行已迁入 `BackgroundWorkerService`，保留外部调用前后短事务边界。
4. 制作 watchdog 与历史事件重放已迁入 `ProductionService` / `BackgroundWorkerService`。
5. `main.py` 中旧的函数式 SQL 实现已删除；现有 36 项后端测试通过。

后续重点是补充真实 PostgreSQL 下的进程中断、重复执行和短暂不可用恢复测试；本次迁移没有改变公开 API 和状态机规则。
