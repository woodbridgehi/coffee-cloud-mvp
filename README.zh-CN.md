# Coffee Cloud MVP

[English](README.md) · [文档索引](docs/README.md)

Coffee Cloud 是与 `coffee-terminal-simulator` 配套的云端业务系统，提供扫码下单、支付退款、设备串行派单、身份与命令管理，以及多租户商户后台。

**本文以 2026-09-17 本地代码核对为准。** 当前 `app/main.py` 的服务版本是 `0.4.0`，数据库迁移最高为 **23**；这不是对线上已部署版本、真实支付验收或硬件生产就绪的证明。

## 系统职责

| 部分 | 当前职责 | 代码入口 |
| --- | --- | --- |
| HTTP API 与网页 | 顾客、平台、商户接口和静态资源 | `app/main.py`、`public/` |
| MQTT Gateway | 多设备上行、命令发布与回执、连接代际保护 | `app/mqtt_gateway.py` |
| Domain Worker | 派单、watchdog、遥测刷库、支付对账、退款与历史清理 | `app/domain_worker.py`、`app/services/background_worker.py` |
| PostgreSQL | 订单、制作任务、支付退款、Inbox/Outbox、商户账与设备快照 | `app/database.py`、`app/repositories/` |
| Redis | 瞬时进度、设备热状态和通知 | `app/telemetry.py`、`app/live_progress.py` |
| 终端模拟器 | 本地配方编译、模拟制作、SQLite 库存与事件、二维/三维显示 | 相邻模拟器仓库 |

主业务采用 Route → Service → Repository；`app/merchant/` 是独立商户领域模块，当前仍在领域对象内执行 SQL，不能描述为整个项目已经完成统一分层。

## 主要业务流程

```text
设备上传配方能力和库存
  → 顾客选择饮品/选项，必要时获取签名报价
  → 幂等创建订单
  → TEST_FREE 进入排队；ONLINE 经支付确认后进入排队
  → 云端检查设备状态、活动任务、取杯位后派发 MAKE_DRINK
  → 终端校验版本/摘要、预占、按步骤模拟执行
  → 可靠生命周期事件推进订单，Redis 进度更新界面
  → READY 提示取杯；取杯位释放后继续下一单
```

正常在线支付订单使用 `CREATED → AWAITING_PAYMENT → PAID → QUEUED → DISPATCHED → ACCEPTED → MAKING → READY`，各路径可以跳过部分中间状态；详细合法迁移以 [状态与一致性](docs/production-consistency.md) 为准。订单状态、制作任务状态、命令状态和支付状态必须分别理解。

付款、制作失败、取消和退款是不同事实。结果不明进入 HOLD，不因超时直接退款或重做；明确失败/拒绝/取消及可证明未送达的过期命令等路径可以创建退款意图，退款到账仍取决于渠道结果。

## 页面与接口入口

| 入口 | 地址 | 身份 |
| --- | --- | --- |
| 顾客菜单 | `/order?device_id=<设备ID>` | 公开菜单 |
| 顾客订单 | `/order/status` | API/SSE 使用 `X-Order-Access-Token` |
| 平台运营 | `/admin` | Bearer；VIEWER/OPERATOR/MANAGER/OWNER |
| 商户经营 | `/assets/merchant.html` | Cookie；OWNER/OPERATOR/FINANCE，租户与门店范围 |
| API 文档 | `/docs`、`/openapi.json` | 运行时生成的请求模型 |
| 探针 | `/health`、`/ready` | 存活、数据库就绪；不是全链路验收 |

源码没有独立 `/merchant` 页面路由。商户写请求还需同源 Origin、JSON 和相应 CSRF 校验。不同权限体系不能混用。

## 开发启动

在本仓库执行，先按 [运维指南](docs/operations.md) 配置专用本地数据库和 `.env`：

```bash
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
.venv/bin/python -m app.migrate
RUN_DATABASE_MIGRATIONS=false .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8788
```

单进程开发模式默认启动后台循环。生产 Compose 则显式关闭 API 内迁移与后台循环，分别执行迁移任务和独立 Domain Worker；不要混用两种模式导致重复调度。

```bash
.venv/bin/python -m pytest -q
node --test tests/*.mjs
.venv/bin/python scripts/export_openapi.py
```

数据库测试需要专用 `TEST_DATABASE_URL`；双通道测试还需要可销毁的 `TEST_REDIS_URL`。未配置时跳过的集成测试不算通过。API 导出脚本会更新 `openapi/openapi.json`。

## 当前边界

- 支付实现有 `mock`、`alipay`、`alipay_mock`；没有微信 Provider。可用渠道还取决于开关、账户与密钥。
- 云端已有商户采购、账面库存、费用和报表；不等同于自动同步设备消耗的完整成本闭环。
- 设备端有配方历史归档、定制选项、取杯占位、现场恢复核验；没有实体机械臂、RS-485、PLC 或物理仿真后端。
- 手机订单当前默认嵌入可用的三维视图，可切二维；排队顾客可主动观看同机匿名制作场景。
- 模型展示、代码测试和历史发布记录均不能代替实机、支付渠道及容量验收。

当前功能、配置依赖和遗留问题统一见 [当前实现](docs/current-state.md)、[文档核对记录](docs/documentation-audit-2026-09-17.md)。历史计划与发布记录由 [文档索引](docs/README.md) 单独归档导航。
