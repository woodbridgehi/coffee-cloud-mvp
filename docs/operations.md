# 开发、部署与排障

核对日期：2026-09-17。以下为当前操作方式；2026-09-17 已完成的线上部署及验证见[发布记录](releases/2026-09-17-business-reliability.md)，不包含真实支付或现场硬件验收。

## 本地开发

使用专用本地 PostgreSQL。将下列模板写入本机不提交的 `.env`，替换占位值；生产秘密不要复制到测试环境。

```dotenv
DATABASE_URL=postgresql://<local-user>:<local-password>@127.0.0.1:5432/<local-database>
ADMIN_TOKEN=<至少24字符的随机值>
ORDER_ACCESS_SECRET=<至少32字符的独立随机值>
INTERNAL_GATEWAY_TOKEN=<至少24字符的独立随机值>
PUBLIC_BASE_URL=http://127.0.0.1:8788
PUBLIC_PAYMENT_MODE=TEST_FREE
ALLOW_MOCK_PAYMENT=false
MERCHANT_ENABLED=false
SIMULATOR_BOOTSTRAP_ENABLED=false
```

```bash
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
.venv/bin/python -m app.migrate
RUN_DATABASE_MIGRATIONS=false .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8788
```

此单 API 进程默认同时运行后台工作。若单独运行 `.venv/bin/python -m app.domain_worker`，API 必须再设置 `RUN_BACKGROUND_WORKERS=false`。本地不用 MQTT 时可让隔离终端选择 remote+http；接单和凭证仍需合法配置，不可因是 localhost 绕过设备认证。

## 关键配置与实际默认值

| 配置 | Settings 默认值 | 说明 |
| --- | --- | --- |
| RUN_DATABASE_MIGRATIONS / RUN_BACKGROUND_WORKERS | true / true | 单进程开发方便；Compose API 显式设为 false |
| RUN_ORDER_SSE_LISTENER | true | 每个 API worker 监听 PG/Redis |
| DB_POOL_MIN_SIZE / MAX_SIZE | 2 / 10 | 每进程预算，不是全服务总预算 |
| PUBLIC_PAYMENT_MODE / PAYMENT_DEFAULT_PROVIDER | TEST_FREE / mock | 渠道还受账户、开关与密钥约束 |
| ALLOW_MOCK_PAYMENT | false | 不因 provider 默认 mock 就允许模拟收款 |
| TELEMETRY_REDIS_URL | 未设置 | Compose Redis 为回环6380，需配置 URL 才启用 |
| TELEMETRY_HISTORY_MODE | latest | 可选 audit，瞬时 task.progress 仍按独立路径处理 |
| PUBLIC_ORDER_QUEUE_LIMIT | 20 | 准入上限，不是终端并发制作杯数 |
| PUBLIC_READ_RATE_LIMIT / WRITE_RATE_LIMIT | 240 / 30 | 60秒窗口，进程内基础限流 |
| PUBLIC_SSE_LIMIT | 1000 | 每 API 进程，另有每IP12、每订单3连接限制 |
| OFFLINE_THRESHOLD_SECONDS | 90 | 离线判定；不是自动判定制作失败 |
| TELEMETRY_ONLINE_TTL_SECONDS | 120 | Redis 在线租约 |
| COMMAND_ACK_TIMEOUT_SECONDS / START_TIMEOUT_SECONDS | 30 / 60 | 超时按业务证据处理 |
| PRODUCTION_WAIT_TIMEOUT_SECONDS | 900 | 暂停/重试等待超时进入 HOLD |
| MERCHANT_ENABLED / LIMITED_RELEASE | false / false | 是否开启与是否限量开放是独立开关 |
| MERCHANT_REGISTRATION_MODE | EMAIL | 可设 USERNAME；邮件能力取决于 SMTP |
| MERCHANT_COOKIE_SECURE | true | 本地 HTTP 开发需明确设 false；生产 HTTPS 保持 true |
| SIMULATOR_BOOTSTRAP_ENABLED | false | 开发用软件身份配对开关 |

完整字段以 `app/settings.py` 为准；Gateway 还从 `app/mqtt_gateway.py` 直接读取 MQTT_* 环境变量。不要从历史发布记录复制旧 Token、主机名或资源容量。

启用商户前需配置 `MERCHANT_ENCRYPTION_KEY` 并准备受限 `MERCHANT_RUNTIME_ROLE`。`app.migrate` 在商户开启时调用角色授权工具；执行身份若无建角色/授权权限，应先由数据库管理员按 `app/merchant/provision.py` 准备，不能把高权限长期交给业务运行角色。

## Compose 的边界与部署顺序

主 `compose.yaml` 包含 API、MQTT Gateway、Domain Worker、一次性 migrate 和 Redis；**不包含 PostgreSQL 与 EMQX**。EMQX 使用独立的 [部署说明](../deploy/emqx/README.md)。当前配置采用 host network，部署前核对目标系统网络行为、外部数据库和 Broker 连接。

部署前完成数据库与配置备份、记录旧镜像/提交、核对未决订单，准备 `.env`、Gateway 的秘密环境文件和支付密钥目录。然后：

```bash
docker compose build
docker compose --profile tools run --rm coffee-db-migrate
docker compose up -d
docker compose ps
docker compose logs --tail=100 coffee-domain-worker coffee-mqtt-gateway
```

必须先运行全部未应用迁移再启动新版；当前最高24（MQTT Inbox 恢复调度）。数据库结构升级不等于已有订单数据已核对。回滚优先回到兼容镜像；不得直接用旧 dump 覆盖升级后产生的交易。

API/worker/gateway 由 `supervised_process` 等机制和 Docker restart 策略配合监督。Docker 仅标 unhealthy 不会自动重启仍存活容器；Supervisor 检查连续健康失败后退出。Domain Worker 按单实例部署，不声称有自动 leader election。

## 部署备份保留规则

咖啡系统的部署前备份仅保留最近一次完整备份。先备份数据库、源码、运行配置/秘密及旧镜像，验证校验和并在隔离数据库恢复成功；上线健康检查通过后，再删除较早备份、历史发布归档和旧回退镜像。新备份未验证成功时不得删除上一份有效备份。保留一套与最新备份对应的回退镜像，不清理其他项目的备份。此规则是部署操作要求，目前没有自动定时清理任务。

备份目录和含秘密文件必须限制读取权限；日志与公开文档不得包含秘密内容。维护切换前核对活动制作任务；同步源码时保护 `.env`、`.secrets/`、终端 `config/` 和 `.identity/`，排除 Python 缓存。终端 VPS 源码同步不代表现场设备已升级。

## 健康与故障判断

| 现象 | 优先检查 |
| --- | --- |
| `/health` 正常但订单失败 | `/ready`、worker健康、业务状态及渠道；health不检查数据库 |
| `/ready` 正常但进度停住 | Redis、SSE双监听与设备上报；ready只检查数据库并缓存5秒 |
| 已付款但不派单 | 订单HOLD、设备在线/生命周期、活动任务、取杯占位、派单积压 |
| 库存显示足够仍不可售 | 队列物料承诺、库存版本水位、选项组合和配方版本 |
| 配方升级后旧单拒绝 | 终端 recipe-archive 是否存在且有效、编译摘要是否匹配 |
| 取杯后仍不派下一杯 | pickup.collected 是否上报、设备状态是否恢复、worker是否工作 |
| 商户看不到按钮 | 实际 permissions、租户/门店范围和 LIMITED_RELEASE，不要先改前端绕过 |
| MQTT 连接反复被踢 | deviceId/clientId是否重复、gatewayId、凭证、SUBACK和连接代际日志 |

HOLD 的云端裁决与终端核验见 [一致性](production-consistency.md)；不要重放 MAKE_DRINK 试探是否已出杯。

`/metrics` 是命中 API worker 的局部指标，不是集群聚合。Gateway/Domain 另有健康文件。基础限流也是进程内的，不能据此宣称跨副本全局配额。

## 测试和共享资源发布

```bash
.venv/bin/python -m pytest -q
node --test tests/*.mjs
.venv/bin/python scripts/export_openapi.py
```

数据库测试设置专用 `TEST_DATABASE_URL`；Redis 测试设置专用可销毁 `TEST_REDIS_URL`，其中有断开 Pub/Sub 连接的测试。未配置的 skip 必须单独报告。容量阈值见 [验收计划](capacity-and-fault-test-plan.md)，不是已测结果。

三维/音频源码在相邻终端仓库；在该仓库执行 `npm run sync:cloud-scene`，它会构建并更新本仓库 `public/robot/`、共享声音 JS/CSS 和 GLB。不要手改生成 bundle。正常云端部署须携带这些静态文件；同步脚本本身不会部署服务器。
