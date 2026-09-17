# 线上部署完成 — 2026-09-17

- 云端 API、domain worker、MQTT gateway 已统一部署 main `88cfdb4fb8038699980c4dc84ef07bcc15c2367c`，三者镜像 revision 标签一致，健康且 restart count=0。
- 数据库由 migration 23 升至 24；67 笔订单、52 个制作任务保留。上线后 Inbox 5258 条均为 PROCESSED，派单请求无积压。
- VPS 终端源码同步 main `4763be1654d705b7d7bce60bc1a89864b892a753`；保留原有 config、identity 和 secrets。VPS 不运行终端桌面程序，此操作不代表其他实际设备已升级。
- 公网 /health、/ready、/admin、/assets/merchant.html 通过；内部数据库就绪、worker 与 gateway 健康检查通过。没有发起测试付款或设备制作命令。

## 唯一保留的本次部署前备份

VPS：`/home/alex/.deployment-backups/coffee-reliability-20260917T0333Z/`，约 104 MB，目录和备份文件限制其他用户读取。

含停机后的最终数据库 custom dump、旧源码与运行配置/秘密归档、三个服务的旧镜像归档和镜像 ID、SHA256SUMS。首次备份与最终备份都在无网络独立 PostgreSQL 容器恢复成功，最终恢复包含 migration 23 和全部 67 笔订单。SHA-256 校验全部通过。秘密仅保留在 VPS 私有备份中，没有下载到本地报告。

已按用户要求删除 59 个旧咖啡系统备份/历史发布归档条目和 15 个旧咖啡镜像标签。删除清单保存在最新备份的 removed-older-backups.json、removed-old-image-tags.json。保留一套最近回退镜像 coffee-rollback/{coffee-cloud-mvp,coffee-domain-worker,coffee-mqtt-gateway}:latest。其他项目（邮件、网站等）备份未删除。恢复演练容器及其数据库匿名卷已移除。

## 部署过程说明

受限密钥由只读挂载容器归档；同步阶段遇到历史 root 所有的 Python 缓存目录，改为排除缓存后继续，业务文件正常同步。三个服务切换初期 gateway 在 API 启动前出现连接重试，API 就绪后恢复，稳定性复查无新增错误。未改生产环境配置或密钥。

如需回退，优先把三个 coffee-rollback 镜像重新标记为 Compose 使用的镜像并重建三个服务。migration 24 是向后兼容新增列/索引，可保留；不要直接用旧数据库 dump 覆盖上线后产生的新交易。回退会重新暴露旧可靠性缺陷。
