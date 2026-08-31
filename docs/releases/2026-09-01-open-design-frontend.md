# Open Design 前端改版发布记录

日期：2026-09-01（Asia/Taipei）

本次发布将本地 `main` 的合并提交 `49f514b` 同步到 VPS `/home/alex/coffee-cloud-mvp`，并只重建 `coffee-cloud-mvp` 与 `coffee-domain-worker`。部署前已创建远端私有备份：

`/home/alex/.deployment-backups/open-design-frontend-20260831T133329Z/`

其中包含数据库 custom dump、排除运行时密钥和环境文件的源码归档、发布前镜像 ID，以及 SHA-256 校验记录。VPS `.env`、`.secrets`、数据库卷和 Cloudflare Tunnel 没有被覆盖。独立 `mock-alipay-gateway`、MQTT、Redis、EMQX 容器没有重建。

## 验收

- API 容器镜像：`sha256:0264e548b29e27d8fafded403db0293b9cc4af1791989860dd4f166175ab2224`，healthy。
- Domain worker 镜像：`sha256:87ae59edd98d50770f4fc4b781911887e434480f1c3a69e01b172b8829bd1b8e`，healthy。
- `http://127.0.0.1:8788/health` 返回 `status=ok`、`version=0.4.0`。
- `http://127.0.0.1:8789/health` 返回独立 mock 网关 `mode=simulation`。
- `https://coffee-api.woodbridge.top/api/v1/merchant/auth/config` 返回 `registrationMode=USERNAME`、`mailEnabled=false`、`limitedRelease=true`。
- 公网三套页面已返回新共享样式和版本化脚本：`coffee-ui.css?v=20260902`；商户后台、平台后台和消费者页均可加载。

本次未执行真实付款、退款或设备命令；未修改 mock 支付服务配置。回滚时保留并使用发布前镜像和上述数据库备份，先停止新 API/worker，再按既有发布手册恢复，不使用 `git reset --hard` 覆盖工作区。
