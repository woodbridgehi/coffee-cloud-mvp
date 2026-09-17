# 设备身份、激活与商户配对

核对日期：2026-09-17。当前有两条已实现路径：预登记激活，以及显式开启的软件模拟器配对。工厂安全芯片/证书方案仍属规划，见[原设计归档](archive/device-registration-pairing-original.md)。

## 标识不能混用

| 标识 | 用途 |
| --- | --- |
| 本地实例目录名 | 启动脚本查找配置；不必等于协议 deviceId |
| deviceId | HTTP身份、MQTT topic/clientId和云端设备关联 |
| serialNumber | 设备序列号；软件模拟器与预登记设备有不同来源 |
| instanceId | 本地运行实例标识 |
| deviceName | 可变展示名，不是认证凭据 |
| activationCode | 平台预登记路径的一次性激活码 |
| pairingCode / claim code | 商户认领/绑定凭据，不是设备Token |
| deviceToken | 设备HTTP Bearer凭据 |
| MQTT username/password | Broker身份和权限，不是商户登录密码 |

## 路径一：平台预登记与激活

1. 平台经 `POST /api/v1/admin/devices` 登记身份，生成激活码。
2. 终端生成待激活 HTTP Token，保留 pending 文件。
3. `POST /api/v1/device-activations` 提交设备标识、激活码、Token及支持的部署信息。
4. 云端校验并保存凭证摘要；是否签发可用 MQTT 凭据还取决于 EMQX 配置。
5. 终端安全保存秘密并启动；HTTP和MQTT轮换走各自接口。

同码同Token可幂等重试，同码另一Token冲突；不要删除 pending 后用新秘密盲目重试。现场脚本见[终端激活手册](../../coffee-terminal-simulator/ACTIVATION.md)。

## 路径二：软件模拟器配对

实现：云端 `services/simulator_pairing.py`、终端 `simulator_identity.py` / `onboarding.py`、商户 `assets.py`。

```text
终端创建/读取本地软件密钥和序列号
  → 带公钥及签名证明申请配对会话
  → 云端生成设备标识与短期配对码
  → 商户登录，认领到自己的门店并填写展示信息
  → 终端查询会话并提交 provision
  → 获取设备资料及凭据，保存后进入运行界面
```

`SIMULATOR_BOOTSTRAP_ENABLED` 默认 false。会话有有效期，签名消息按 bootstrap/status/provision 用途区分；这是软件密钥持有证明，不能称为经过工厂认证的实体硬件身份。普通已配置Token实例不必重新走配对。

商户认领经 `/api/v1/merchant/devices/claim`，遵循登录、CSRF、权限、幂等及租户/门店范围。认领设备不自动代表具备线上支付账户或所有运营权限。

## 凭据与配置存储

设备Token、MQTT密码和身份私钥不放配方、展示包或Git。终端 `write_config()` 去掉认证秘密；秘密单独保存在 `.secrets/`、`.identity/`。打包Windows入口启用DPAPI保护；源代码运行和其他系统不可一概称为硬件密钥存储。

TLS验证Broker服务端证书；当前MQTT使用用户名密码，不是设备客户端证书双向TLS。配置开关、凭证轮换与撤销需结合云端身份服务及EMQX状态核对。

## 尚未实现的生产身份能力

工厂证书导入、安全芯片私钥、实体设备远程证明、签名硬件指令与完整生产制造流程均不属于当前两个项目已交付能力。原方案中的推荐API、角色和流程不得直接当现有接口调用。
