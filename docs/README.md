# 云端文档索引

文档基线：2026-09-17本地代码核对。[中文入口](../README.zh-CN.md) · [English](../README.md) · [终端文档](../../coffee-terminal-simulator/docs/README.md)

## 当前维护的主文档

| 阅读目的 | 文档 |
| --- | --- |
| 了解已经实现什么、哪些受配置限制 | [当前实现与边界](current-state.md) |
| 找代码、理解进程和数据流 | [应用架构](application-architecture.md) |
| 订单/任务/命令、退款、HOLD和取杯 | [制作一致性](production-consistency.md) |
| 本地开发、部署、配置、排障 | [运维指南](operations.md) |
| 设备激活、软件配对、身份边界 | [身份与配对](device-registration-pairing-design.md) |
| 商户实际操作与截图 | [商户图解手册](merchant-user-guide.md)（保留用户正在维护的版本） |
| 本次纠错、证据、未决问题与验证 | [文档核对记录](documentation-audit-2026-09-17.md) |

## 当前专题

- [定制选项与配方摘要](drink-customization.md)
- [同机排队与匿名旁观](queue-and-private-scene.md)
- [三维共享资源](robot-live-view.md)
- [失败原因与旧指令兼容](order-failure-diagnostics.md)
- [双通道SSE](dual-channel-sse.md)
- [容量与故障验收计划](capacity-and-fault-test-plan.md)：计划阈值，不是容量承诺。
- [EMQX部署](../deploy/emqx/README.md)
- [OpenAPI快照](../openapi/openapi.json)：字段由代码导出；被include_in_schema=false排除的内部接口/SSE仍需查路由。

## 历史档案

旧文件保留原位置和链接，统一加历史标记；不再把实施前基线或旧路线图当“当前状态”。

- [v0.4/v0.5实施前基线](v0.4-v0.5-current-state.md)、[实施计划](v0.4-v0.5-implementation-plan.md)、[交接](v0.4-v0.5-handoff.md)
- [旧优化路线图](optimization-roadmap-2026-08-30.md)、[MQTT复盘](mqtt-lifecycle-review-2026-08-30.md)、[分层重构计划](application-layer-refactor-plan.md)
- [旧系统架构图源](system-architecture/README.source.md)：含历史VPS观察，当前架构已合并到主文档。
- [原身份规划](archive/device-registration-pairing-original.md)：混合了原实现与工厂身份设想，当前说明已拆开。
- [B端实施计划](b2b-implementation-plan-2026-08-31.md)、[交接](b2b-handoff-2026-08-31.md)、[用户名发布](b2b-username-release.md)、[模拟支付切换](mock-pay-cutover-2026-08-31.md)
- [UI规格](UI_UX_REDESIGN_SPEC.md)、[设计brief](open-design-code-to-code-brief.md)、[前端改版](open-design-frontend-revamp-2026-09-01.md)、[移植计划](open-design-cc-port-plan-2026-09-02.md)、[合并复盘](open-design-merge-review-2026-08-31.md)
- [前端任务](pi-frontend-redesign-prompt.md)、[B端任务](pi-b2b-frontend-task.md)、[B端交付](pi-b2b-frontend-delivery.md)、[用户名任务](pi-username-release-task.md)、[用户名交付](pi-username-release-delivery.md)、[GPT交接](gpt-handoff-2026-09-02.md)
- [发布记录目录](releases/)：记录当时部署与测试，不证明当前线上配置。

修改功能时先更新负责该事实的主文档或专题，再补日期化发布记录。不要复制整份状态机到新的README，也不要把规划接口写入“已实现”表。

## 2026-09-17 可靠性修复与发布

- [整改与回归证据](business-reliability-2026-09-17.md)
- [线上部署与备份记录](releases/2026-09-17-business-reliability.md)
