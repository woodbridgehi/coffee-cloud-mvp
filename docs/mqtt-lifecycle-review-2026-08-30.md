# B1.1 直接复核修复记录

日期：2026-08-30。执行者：Codex，未调用 pi。修改基线为后端 `6a9619e`、模拟器 `e1c3c2b`。本文记录本地修复与测试，不进入 B1.2，不修改数据库结构、支付、SSE、页面或生产配置。后续已按用户授权提交并部署后端，详见 [发布记录](releases/2026-08-30-b11.md)。

## 1. 修复内容与不变量

| 问题 | 修复 | 验证方式 |
| --- | --- | --- |
| ACK 写错误同步触发断线回调，重复获取普通锁死锁 | 两端使用可重入代次锁，回调只变更状态；禁止锁内 join/阻塞连接 | 真实 Paho ACK + socketpair 注入写错误，线程必须结束 |
| 网络线程异常退出后旧代次仍有效，ACK 穿越 socket 重建 | 默认 Paho 客户端覆盖 `reconnect()`，调用父类前先失效；监督器亦先失效再恢复 | socketpair 检查新 socket 上没有旧 MID 的 PUBACK；分别测试直接及监督器重连 |
| 只依赖 `on_pre_connect` 太晚 | Paho 2.1.0 在该回调前已经清理发送队列，故必须在整个 `reconnect()` 入口设置隔离 | 替换父类重连入口，断言在进入父类前已失效；并发 ACK 与重连顺序测试 |
| 订阅拒绝仍就绪、旧 MID 跨代残留 | 每次连接重置待确认 MID；仅接受本代已登记 MID 的 QoS1 成功结果 | 拒绝、降级、未知 MID、跨代未决 SUBACK 测试 |
| 订阅确认没有进入生产门禁 | 全部必需订阅成功后才设置 connected；网关领取与健康检查、设备上线 presence 均依赖它 | 不就绪不领取；健康检查缺少订阅或监督器必须失败 |
| SUBACK 不来时永久等待 | 网关超时默认 10 秒，可配置 1–60 秒；设备固定 10 秒，超时断开退避恢复 | 超时撤销权限及清理 MID 测试 |
| 设备内部异常被当成坏包确认 | 格式错误与内部执行异常分开；内部异常不 ACK，断开重投 | 注入 MemoryError，断言无 ACK |

锁边界：重连/关闭协调锁可覆盖连接恢复和 loop_stop；代次锁只覆盖 ACK 检查及调用、短状态更新。先失效旧代次，再放开代次锁执行连接 I/O。正常 Paho 网络循环存活时不由监督器并行重连。ACK 已进入 Paho 的旧发送队列会在后续 reconnect 重置时清除；失效后的业务 worker 不能再追加旧 ACK。CONNACK 成功开启新代次，但业务“就绪”还必须等待全部 SUBACK。

已有持久会话可能在重新订阅确认前重投消息，因此 ACK 权限与业务就绪不是同一个标志：允许确认新连接已接收的合法消息，不允许提前领取新下行任务。QoS0 降级不是成功，因为该通道要求 QoS1。

实现沿用并锁定 Paho 2.1.0，并读取其 `_thread` 来检查当前客户端所属网络线程，避免按全局线程名误认其他客户端。未来升级 Paho 必须重跑 socket、回调与真实 Broker 用例。

## 2. 本地验收

两仓库新文件均为 `tests/test_mqtt_lifecycle_fences.py`，不需要 Broker、不跳过。先在旧实现运行新增故障用例，后端 6 项、模拟器 5 项全部失败；修复后通过，并增加边界用例。

完整回归使用 uv 管理的 Python 3.12 与已锁定依赖。使用全新 PostgreSQL 测试目录、独立 Redis/Mosquitto，仅绑定本机。未连接 VPS、未执行真实支付或生产故障注入。

验收命令（环境变量必须指向独立本地测试实例）：

```bash
# 后端：需 TEST_DATABASE_URL、TEST_REDIS_URL、MQTT_TEST_BROKER_HOST/PORT
uv run --managed-python --python 3.12 --with-requirements requirements-dev.lock pytest -q -rs
node --test tests/test_order_view.mjs

# 模拟器：需 MQTT_TEST_BROKER_HOST/PORT
uv run --managed-python --python 3.12 --with-requirements requirements.lock --with pytest==8.4.1 pytest -q -rs
node --test tests/*.mjs
```

验收结果（全部无 skip）：

| 项目 | 结果 |
| --- | --- |
| 后端 Python 完整回归 | 185 passed |
| 模拟器 Python 完整回归 | 44 passed |
| 独立一致性探针 `project-analysis/pi-fixes/a1_independent_checks.py` | 7 passed |
| Node 后端 / 模拟器 | 3 / 10 passed |
| 合计（不重复计数） | 249 passed |
| 真实 Broker 背压恢复 + 模拟器回调崩溃恢复 | 各额外重复 5 轮，全部通过 |
| 两端新增离线故障/边界用例 | 后端 15、模拟器 8，已计入完整回归 |
| Ruff F 与两仓库 `git diff --check` | 通过 |

测试 PostgreSQL 位于 `/tmp/coffee-codex-b11.DU8pwN/postgres`，使用本机 55447 端口；Redis/Mosquitto 使用临时回环端口。全部测试实例已停止，临时 PG 数据目录保留，未删除用户数据。真实 Broker 用例跳过时不得宣称完整通过。

## 3. 未完成与发布边界

- 终端命令仍是入内存队列即 ACK；持久 Inbox、SQLite 业务事务属于 B1.2，未实现。
- Broker 会话恢复不等于端到端恰好一次；Broker 自身状态丢失、过期及设备本地崩溃仍有独立边界。
- 本地验收时未验证生产 EMQX TLS/ACL 或 Docker 构建；后续发布已验证镜像构建及网关 TLS/订阅，设备 ACL 与千台压测仍未验证。
- 后续按用户授权提交后端 `8baf0ae`、模拟器 `84a95d8` 并同步 VPS；没有 Git remote，未 push。用户原有 `.gitignore` 与架构文档保持不动。
- 下次发布必须同时更新网关与它的 `file_healthcheck.py`，因为健康文件新增并强制检查 subscribed/supervisorAlive。按既有发布流程先验证镜像、备份及健康，再放量。
