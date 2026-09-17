# 当前实现与边界

核对日期：2026-09-17。范围为两个本地仓库源码和配置结构，不代表远端部署状态。代码定位采用相对路径，历史版本号不作为当前功能目录。

## 功能与证据

| 领域 | 已实现 | 主要证据 | 边界 |
| --- | --- | --- | --- |
| 顾客订单 | 菜单、报价、幂等下单、查询、取消、SSE | `app/services/public_orders.py`、`app/customization.py` | 不直接访问终端 localhost |
| 支付退款 | mock/Alipay/独立 alipay_mock、回调、对账、退款意图与预算 | `app/services/payments.py`、`app/services/refund_intents.py`、`app/payment_providers.py` | 渠道配置和外部验收另计；无微信实现 |
| 制作 | 设备串行队列、任务/订单/命令关联、revision 与终态保护 | `app/services/production.py`、`app/production_state.py` | 没有多杯并行制造调度 |
| 取杯 | EMPTY/OCCUPIED/NEEDS_CHECK 投影，阻止占位时派下一杯 | `app/repositories/pickup.py`、迁移22 | 当前终端是人工模拟传感器确认 |
| 队列准入 | 订单物料承诺、库存版本水位、默认20单上限 | `app/material_commitments.py`、`app/repositories/orders.py`、迁移21 | 保守估算，可能重复计入终端已预占量；不是物理库存保证 |
| 遥测 | 热状态缓存、租约刷库、独立瞬时进度 | `app/telemetry.py`、`app/telemetry_leases.py`、`app/live_progress.py` | Redis 进度允许缺失，不退回高频 SQL |
| 设备身份 | 预登记激活、轮换、MQTT 凭据；开发用软件身份配对 | `app/services/device_identity.py`、`app/services/simulator_pairing.py` | 软件密钥证明不等同工厂证书/安全芯片 |
| 商户 | 用户/组织/门店、资产认领、订单、采购、账面库存、费用、价格、报表、审计 | `app/merchant/` | 功能由 MERCHANT_* 开关与权限共同约束 |
| 商户资产转移 | 发起、接收、取消，存在 PENDING_PLATFORM 阶段 | `app/merchant/assets.py` | 不能描述为平台审批和交付全流程已完成 |
| 三维与声音 | UR10e 简化双臂、拉花、匿名旁观、合成工序声 | `public/order.js`、共享终端 `web/robot/` | 无物理接触仿真或硬件控制；顾客页声音需启用，终端默认尝试开启但受自动播放策略限制 |
| 展示内容包 | 本机 ZIP 导入、校验、预览、启用、回退、运营联合包导出 | 终端 `showcase_packages.py`、`backend.py` | 没有云端内容包批量分发或联合包一键导入 |

## 四种不能混用的数据

1. **终端库存**：终端 SQLite 中 onHand/reserved/available 与消耗幂等键；模拟执行中的权威库存。
2. **云端设备快照**：最近收到的能力和库存，离线时可能陈旧。
3. **云端订单物料承诺**：用于限制新订单，覆盖未支付、排队和未决订单；不是另一份实际扣料账。
4. **商户账面库存与成本**：采购入库、调拨、损耗、费用等经营数据。不能通过编辑此账声称实体机器已经补料，也不能把设备所有消耗自动记账描述为已交付。

## 配置决定的开放范围

- `PUBLIC_PAYMENT_MODE`、设备 `payment_mode`、`SIMULATOR_PAYMENT_MODE` 影响支付路径；创建订单还要通过服务端校验。
- `ALLOW_MOCK_PAYMENT` 控制模拟渠道；在线模式不等于真实资金渠道已配置。
- `MERCHANT_ENABLED` 默认 false；注册方式默认 EMAIL，可选 USERNAME。
- `MERCHANT_LIMITED_RELEASE=true` 移除 `devices.transfer`、`payments.manage`、`commands.execute` 等受限权限；不要用历史发布配置推断当前运行值。
- `SIMULATOR_BOOTSTRAP_ENABLED` 默认 false，仅显式开启开发用软件身份信任路径。
- API 是否运行迁移/后台线程受 Settings 控制；Compose 显式关闭，单进程开发默认开启。

## 已完成与仍待工作

旧路线图提到的本地库存统一 SQLite、退款预算集中、数据库迁移独立运行、双通道 SSE、遥测租约、历史批量清理、公开接口基础限流等，在当前代码中已存在，不应重复列为完全未实现。

已补齐终端 MQTT 落盘后 ACK、命令事务恢复、配方保存失败回滚、云端 Inbox 恢复及缺失派单请求补偿，见[可靠性整改](business-reliability-2026-09-17.md)。云端上线状态见[发布记录](releases/2026-09-17-business-reliability.md)。

仍需继续：真实硬件动作接口与日志、生产身份根、商户设备消耗成本闭环、跨进程统一限流、真实渠道/容量/故障验收。分项依据见 [核对记录](documentation-audit-2026-09-17.md)。

## 文档维护约定

当前事实由本页、[架构](application-architecture.md)、[一致性](production-consistency.md)、[运维](operations.md) 分工维护；字段模型查代码与运行时 OpenAPI。专题文档补充细节，带日期的计划/交付记录保留当时语境，不能覆盖现状。
