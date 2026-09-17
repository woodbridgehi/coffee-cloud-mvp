# 双项目文档核对记录（2026-09-17）

> **整改前历史快照**：下文保留当日首次文档核对时的事实和测试结果。随后已修复落盘前 ACK、空文案覆盖等问题并完成隔离全量回归；当前状态见[可靠性整改](business-reliability-2026-09-17.md)，不再以下文的缺口和旧计数判断现状。

## 范围与方法

核对本地 `coffee-cloud-mvp` 与相邻 `coffee-terminal-simulator` 的实现，沿入口、路由、服务、事务、迁移、终端执行循环、传输、前端及测试追踪实际行为。重点是订单到制作、库存、退款、取杯、身份、商户权限、共享三维资源与运维配置；不是逐行安全审计，也不表示远端服务器已部署这些代码。

本次修改文档与由源码导出的OpenAPI快照，不修改业务实现。开始时已存在的终端两个实例 `device.json`、云端商户手册修改和 `docs/images/` 均保留。没有启动真实设备、执行生产迁移、支付、发布或部署。

## 结构调整

- README保留项目定位、启动入口和文档导航，详细内容集中到 [当前实现](current-state.md)、[架构](application-architecture.md)、[一致性](production-consistency.md)、[运维](operations.md)。
- 终端以 [DESIGN](../../coffee-terminal-simulator/coffee-terminal/DESIGN.md)、[API](../../coffee-terminal-simulator/coffee-terminal/API.md)、[配置](../../coffee-terminal-simulator/config/README.md)、[激活](../../coffee-terminal-simulator/ACTIVATION.md) 为主，专题补充三维、恢复、展示与菜单。
- 带日期的计划、交接、UI规格及发布记录保留原位置并加历史标记，避免破坏外部链接；其中旧测试数字、线上观察和计划事项不再作为当前事实。没有逐条重写历史正文。
- 原身份规划保存在 [历史副本](archive/device-registration-pairing-original.md)，当前 [身份文档](device-registration-pairing-design.md) 分开描述已实现的软件配对和未实现的工厂身份。
- 两个 [云端索引](README.md) / [终端索引](../../coffee-terminal-simulator/docs/README.md) 明确主文档、专题和历史资料；相邻仓库链接假定两仓库位于同一父目录。

## 主要纠错与源码证据

| 旧描述或容易误解的内容 | 当前事实 | 证据 |
| --- | --- | --- |
| 全部模块已按Repository分层 | 主业务已分层；商户模块仍在scoped事务内直接SQL | [架构测试](../tests/test_architecture_layers.py)、[商户目录](../app/merchant/) |
| API始终启动迁移/后台；Worker自动单例 | 开关有效，Compose拆进程；Domain Worker没有入口选主 | [main](../app/main.py)、[worker](../app/domain_worker.py)、[Compose](../compose.yaml) |
| PENDING_PAYMENT、COMPLETED是订单状态 | 当前采用AWAITING_PAYMENT、READY等；制作任务状态是另一套 | [状态定义](../app/production_state.py) |
| HOLD可以普通重试；不确定就自动退款 | HOLD/UNKNOWN需要事实终态或裁决；退款按失败及未发送等证据触发 | [制作服务](../app/services/production.py)、[退款意图](../app/services/refund_intents.py) |
| 支持微信、默认mock即可收款 | 当前provider为mock/alipay/alipay_mock，受配置与渠道条件限制 | [支付实现](../app/payment_providers.py)、[配置](../app/settings.py) |
| 显示有库存就保证能接单 | 还受订单物料承诺、水位和配方约束；不等于实体库存保证 | [物料承诺](../app/material_commitments.py)、[订单仓库](../app/repositories/orders.py) |
| 商户账面库存等于终端库存 | 设备库存、云快照、队列承诺、经营账是四种不同数据 | [当前实现](current-state.md)及商户成本模块 |
| progress高频持久化；最多每5秒上报一次 | Redis瞬时通道；终端整体进度至少5%或经过5秒即触发 | [进度](../app/live_progress.py)、终端backend |
| heartbeat有独立MQTT topic | heartbeat是 `/up` 上的信封；另有down/state/presence | [终端传输](../../coffee-terminal-simulator/coffee-terminal/mqtt_transport.py) |
| 终端手动ACK已经保证落盘接收 | 目前先内存Queue再PUBACK，SQLite Inbox稍后写入，有崩溃窗口 | 同上及[执行循环](../../coffee-terminal-simulator/coffee-terminal/backend.py) |
| 终端inventory.json是运行权威数据 | 库存、任务、Inbox/Outbox进入SQLite；旧JSON只首次导入 | [本地存储](../../coffee-terminal-simulator/coffee-terminal/state_store.py) |
| 进入步骤立即扣料；完成10秒自动清空 | 正常步骤完成扣料；取杯占位待确认，120秒进入NEEDS_CHECK | 终端backend、云端迁移22 |
| 远程重启可无条件续作 | 进入RECOVERING/recoveryHold，现场核验取消旧任务 | [恢复专题](../../coffee-terminal-simulator/docs/restart-recovery.md) |
| 配方升级必然让旧单失败 | 支持有效历史配方归档及冻结摘要；缺失/禁用等仍拒绝 | [catalog](../../coffee-terminal-simulator/coffee-terminal/catalog.py)、[定制](drink-customization.md) |
| 展示仍依赖旧showcase-content.json | 当前是校验过的本机内容包；无云分发和联合包一键导入 | [展示实现](../../coffee-terminal-simulator/coffee-terminal/showcase_packages.py) |
| Three.js是硬件或物理仿真；手机默认2D | 当前是运动学展示；手机有可用计划时默认3D，终端默认2D | [三维专题](robot-live-view.md)、[终端专题](../../coffee-terminal-simulator/docs/robot-scene.md) |
| 所有页面默认静音 | 终端主页默认尝试开启且100%音量，受自动播放策略约束；顾客页默认静音 | [终端声音入口](../../coffee-terminal-simulator/coffee-terminal/web/terminal-sound.js) |
| 所有已实现路由均在已提交OpenAPI内 | 重新导出后补入GET `/api/v1/public/orders/{order_id}/scene` | [快照](../openapi/openapi.json)、[导出脚本](../scripts/export_openapi.py) |

当前最高数据库迁移为23：21处理队列物料水位，22处理取杯占位，23增加execution_attempt。服务版本字符串仍为0.4.0，不应据版本字符串推断全部功能或线上迁移状态。

## 本次实际验证

| 项目与命令 | 结果 | 限制 |
| --- | --- | --- |
| 云端 `.venv/bin/python -m pytest -q` | 130通过、147跳过 | 未配置专用PostgreSQL/Redis集成环境 |
| 云端 `node --test tests/*.mjs` | 89通过、0失败 | Node测试不等于浏览器真实交互验收 |
| 终端 `.venv/bin/python -m pytest -q` | 92通过、8跳过、6个subtest通过 | 8个MQTT会话测试未连接本地测试broker而跳过 |
| 终端 `npm test` | 68通过、1失败 | 下述已有文案问题 |
| 云端 `scripts/export_openapi.py` | 成功，更新快照 | 不含显式排除于schema的路由 |

终端失败用例：`tests/test_i18n.mjs` 的语义键检查。`web/locales.js` 后续注册将 `onboarding.status.waitingDesc` 覆盖为空字符串，断言先报告英文缺失；中文后续覆盖同样为空。测试与实现需在后续功能修复中一起处理，本次没有为了通过测试改代码或放宽断言。

另执行两仓库Markdown本地文件链接检查（跳过依赖目录、代码块、网络链接；不验证所有标题锚点）和 `git diff --check`。不把历史截图、旧发布测试或跳过项列为本次成功验收。没有进行真实浏览器音频、商户截图重拍、渠道、容量、Broker故障或硬件验收。

## 后续工程事项（不是本次已实现内容）

1. **MQTT持久接收**：在PUBACK前持久化下行命令，并测试落盘/ACK/重连各阶段崩溃；当前内存队列和连接代际只解决部分问题。
2. **终端文案回归**：处理重复注册的空值覆盖，重新跑前端全套测试。
3. **隔离环境验收**：配置独立TEST_DATABASE_URL、TEST_REDIS_URL和MQTT测试broker，完成跳过项及端到端订单/退款/取杯测试。
4. **接实体设备前拆执行接口**：增加异步动作、动作日志、结果查询、真实传感器完成判据与互锁。当前计时器、浏览器IK、现场核验按钮不能承担硬件控制。
5. **部署保证**：跨进程全局限流、Domain Worker多实例策略、完整磁盘容量保护仍需明确；目前进程内配额、单实例部署和部分清理不能替代它们。
6. **业务完整性**：工厂硬件身份、资产转移完整审批、设备消耗与商户成本自动闭环、实际支付渠道验收及内容包云分发不能写成已交付。

## 后续维护规则

修改功能时同时更新负责该事实的主文档/专题和相关测试；更改路由后重新导出OpenAPI。计划文档必须标“未实现”，发布记录必须有日期与实际环境。更新文档不能仅修改顶部核对日期，必须核对对应入口、配置、状态迁移与持久化行为。运维命令以仓库脚本为准，文档中不固化真实密钥或把某次部署参数当默认值。
