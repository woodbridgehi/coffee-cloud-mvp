# Coffee Cloud MVP

用于验证 `coffee-terminal-simulator` 的 `coffee-bot-002` 通过 HTTPS 连接 VPS。该服务是模块化单体的最小实现，不包含支付、正式订单、库存账本或 OTA。

当前 `0.2.0` 核心能力：一次性设备激活、终端生成凭证、双凭证轮换宽限、撤销/过期、心跳幂等与乱序保护、能力/库存快照、事件 Inbox、正式命令幂等创建和状态迁移历史、受保护管理 API。

它仍不是销售后台：没有支付、正式订单、库存账本、退款或 OTA。正式命令 API 仅用于验证终端接入与制作任务边界。

## 本地检查

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/export_openapi.py
docker compose config
```

OpenAPI 在线入口为 `/openapi.json` 和 `/docs`，固定导出文件为 `openapi/openapi.json`。契约变化后必须重新导出并运行契约测试。

## VPS 启动

VPS 使用独立 `.env`，不得提交。准备数据库后：

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8788/health
```

公网健康检查：

```bash
curl https://coffee-api.woodbridge.top/health
```

管理查询必须携带 `ADMIN_TOKEN`：

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://coffee-api.woodbridge.top/api/v1/admin/devices/002
```

管理页面位于 `/admin`，页面不会保存管理员 Token。

管理台现在是设备总览页：会列出所有已登记终端，包括当前在线、当前离线和从未上线的历史实例，并显示最近心跳、最后上线时间、生命周期、软件版本以及心跳/事件/命令数量。页面每 10 秒自动刷新，Token 只保留在当前页面内存中。

新增本地模拟器实例时，先在管理台点击“登记新设备”，填写 `deviceId`、序列号、`instanceId` 和 `storeId`，复制一次性激活码；然后在模拟器本地执行：

```bash
.venv/bin/python scripts/activate_instance.py coffee-bot-003 \
  --activation-code-file .secrets/coffee-bot-003.activation-code \
  --secrets-file .secrets/coffee-bot-003.env
```

激活成功后启动：

```bash
./start-instance.command coffee-bot-003 \
  --env-file .secrets/coffee-bot-003.env
```

“已登记”是云端历史记录，“在线”由最近心跳租约判断；进程停止后设备不会从列表消失，而会转为离线。

## 身份与正式命令

- `POST /api/v1/admin/devices/{id}/activation-codes`：管理员创建一次性激活码，明文只返回一次。
- `POST /api/v1/device-activations`：终端提交激活码和自己生成的新 Token；可用相同载荷安全重试。
- `POST /api/v1/devices/{deviceId}/credentials/rotate`：终端轮换凭证，必须携带 `Idempotency-Key`。
- `GET /api/v1/admin/devices/{id}/credentials`：只返回版本和状态，不返回哈希或明文。
- `POST /api/v1/admin/devices/{id}/commands`：正式创建设备命令，必须携带 `Idempotency-Key`。
- `GET /api/v1/admin/devices/{id}/commands/{messageId}`：查询命令及完整迁移历史。

命令主路径为 `CREATED → DELIVERING → ACKED → EXECUTING → SUCCEEDED/FAILED`；拒绝、取消和过期是独立终态。实际设备事件中的关联键位于 `payload.taskId`，服务启动时会使用已入库事件补偿尚未推进的命令投影。

完整部署、测试和回滚说明见 `../plan-gpt/10-vps-online-mvp/`。
