# Forest & Cream 前端主题发布记录

日期：2026-09-01（Asia/Taipei）

本次将 `/Users/alex/Downloads/webpage` 的最新 Open Design “Forest & Cream”
视觉语言整合进三套真实动态前端。发布代码提交为 `496c0a3`；API、权限、认证、
支付、退款、设备命令与数据库均未修改。

## 发布范围

- 商户与消费者端使用 forest 主操作色，平台端使用 espresso 主操作色。
- 奶油纸面背景、暖色边框与浅投影、黄铜键盘焦点、衬线大标题、等宽数据和深色秘密域统一到共享设计系统。
- 三套 HTML 静态资源缓存版本更新为 `20260901-forest1`。
- VPS 只重建 `coffee-cloud-mvp`；domain worker、MQTT gateway、Redis、mock 支付、数据库与 Tunnel 均未重建或修改。

## 备份与回滚

发布前远端私有备份：

`/home/alex/.deployment-backups/forest-cream-20260901T025256Z/`

其中包含八个发布文件的压缩归档、发布前 SHA-256 和发布前 API 镜像 ID。发布前镜像另保留为：

`coffee-cloud-mvp:before-forest-20260901t025256z`

发布前镜像 ID：`sha256:f39b08302a138eab7a0900e8e0de52d472c67d217278bb4e37bdfa2c81369be0`。

## 验收

- 新 API 镜像：`sha256:8475dcb48a482d6247ee4cea3603988d49715f8b2a42517dc80f7345a24950ac`，容器 healthy。
- VPS 回环与公网 `/health` 均返回 `status=ok`、`version=0.4.0`。
- 公网 admin、merchant、order HTML 均返回 `20260901-forest1`，共享 CSS 返回 forest Token `#123D31`。
- 浏览器实测平台主色 `#5A3827`、商户主色 `#123D31`、背景 `#F6F0E5`，页面无控制台错误或横向溢出。
- 61 个前端 Node 断言通过；相关 Python 契约测试 4 通过、4 因环境条件跳过。
- 全量 Python 回归在本地旧 Python 3.9 环境为 95 通过、121 跳过、3 失败；两项失败由 Python 3.9 缺少 `anext` / `hashlib.scrypt` 导致，另一项是未改动的 MQTT 生命周期时序测试。本次未修改这些模块。

本次未使用真实管理员 Token 登录，未执行真实付款、退款、设备命令或生产数据写入。
