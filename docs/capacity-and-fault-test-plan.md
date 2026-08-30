# 容量与故障验收计划

## 目标模型

- 设备心跳 30 秒并随机错峰。
- 活跃设备每 5 秒最多一条 `task.progress`。
- 生命周期、命令结果、失败与库存事实事件不合并。
- 顾客进度页面使用 SSE，不进行固定周期订单轮询。

## 分档步骤

依次执行 100、500、1000、2000 台。每档至少持续 15 分钟，前一档全部达标后才能进入下一档。

1. 仅 MQTT 长连接和错峰心跳。
2. 20% 设备并行制作。
3. 100% 设备并行制作。
4. 每个活跃订单建立一个 SSE 顾客连接。
5. 在稳态中分别重启 Gateway、Redis、Domain Worker。
6. 注入 PostgreSQL 200ms 延迟和支付渠道超时，验证隔离效果。

## 验收阈值

- 关键事件端到端 P95 小于 500ms，P99 小于 1s。
- HTTP API P95 小于 300ms，错误率低于 0.1%。
- SSE 更新延迟 P95 小于 500ms，断线后 5 秒内恢复。
- MQTT QoS 1 事实事件零丢失、允许幂等重复。
- PostgreSQL 活跃连接低于上限 60%，CPU 持续低于 70%。
- Redis dirty backlog 稳态低于 500，故障恢复后 30 秒内清空。
- Gateway queue 不超过容量 50%，不能出现永久未 ACK 命令。
- Domain Worker 任一子循环不能阻塞其他循环。
- 宿主机可用内存高于 20%，无持续 swap、OOM 或容器重启。

## HTTP 基线工具

`/health` 是不访问数据库的进程存活基线；数据库链路应单独用 `/ready` 验证，避免把探针本身变成数据库压力源。

```bash
uv run --with-requirements requirements.txt scripts/load_test.py \
  --base-url http://127.0.0.1:8788 --path /health \
  --concurrency 100 --requests 5000
```

该工具只用于 API 基线，不等价于完整设备测试。完整测试必须同时覆盖 MQTT、SSE、数据库和故障注入。
压测器应运行在另一台机器；如果和被测 API 共用小型 VPS，单进程 Python 压测器可能先占满 CPU，产生虚假的高延迟。服务端本机极限基线可另用低开销的 `wrk`/`k6` 复核。
