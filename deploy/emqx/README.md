# Coffee MQTT Broker

独立 EMQX 单节点部署，公网仅发布 MQTT 5.0 over TLS/TCP `8883`。Dashboard/REST API 映射到 VPS 回环地址 `127.0.0.1:18083`，不经过 Cloudflare Tunnel，也不直接暴露公网。

配置源位于 `base.hocon`，运行时数据、认证用户和 ACL 保存在 Docker named volume。Let's Encrypt 证书从宿主机复制到 `certs/`；续期 deploy hook 使用 `renew-certificate.sh` 更新副本并重启 Broker。

设备主题：

- 上行：`v1/devices/{deviceId}/up`
- 下行：`v1/devices/{deviceId}/down`
- 在线状态：`v1/devices/{deviceId}/presence`
- 设备状态：`v1/devices/{deviceId}/state`

设备账号只能写自己的上行、presence 和 state，只能读自己的 down。云端网关账号使用单独 ACL，不与任何设备共享凭证。
