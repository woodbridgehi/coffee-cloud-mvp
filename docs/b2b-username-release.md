# B 端用户名注册初版发布

用户已授权先上线，邮箱服务尚未准备，允许用户名密码注册登录。本发布不代表原完整实施计划全部交付。

## 当前开放范围

- 独立入口 `/assets/merchant.html`；旧 `/admin` 仍为平台管理入口。
- 用户名注册后直接登录，事务内创建独立组织及 OWNER 成员，不继承平台历史设备、订单、账户和权限。
- 用户名大小写归一，3–32位；密码15–128字符，scrypt 加盐哈希。Cookie 为 Secure/HttpOnly/SameSite=Lax；修改请求要求同源 Origin 和 CSRF。
- 组织、门店、已有成员权限、已归属设备基础管理、订单查询、采购库存账、费用分摊、年月日报表/CSV、审计。
- 物料消耗自动处理尚未开放；有交付但无材料成本时必须显示缺项，不按零成本计算。设备库存是账面库存，不代表实时可用量。

## 本次明确关闭

`MERCHANT_LIMITED_RELEASE=true` 在服务端移除 `devices.transfer`、`payments.manage`、`commands.execute` 权限，直接请求对应 API 也被拒绝。前端同步隐藏操作，不能只靠前端隐藏。

邮件投递、邮件注册验证、邮件邀请及邮件找回入口不开放。用户名账号 `email` 和 `verified_at` 保持 NULL，不伪造邮箱或验证状态。已有已验证邮箱账号仍能登录。忘记密码须联系平台管理员，后续另行补安全的人工重置流程，不能绕过身份核实。

注册成功不等于拥有设备；领取必须持有平台为对应设备签发的一次性领取码。历史测试资产保持平台归属，不会默认送给第一个注册用户。没有自己的有效收款账户时，新领取设备不能创建线上支付订单。本初版不开放客户自行配置收款账户，绑定运营设备需后续平台配置与验收。

## 发布配置及权限

```dotenv
MERCHANT_ENABLED=true
MERCHANT_REGISTRATION_MODE=USERNAME
MERCHANT_LIMITED_RELEASE=true
MERCHANT_RUNTIME_ROLE=coffee_merchant
MERCHANT_COOKIE_SECURE=true
PUBLIC_BASE_URL=https://coffee-api.woodbridge.top
```

`MERCHANT_ENCRYPTION_KEY` 在 VPS 生成并写入受保护 `.env`，不要放入源码或输出到日志。SMTP 留空。

生产原连接 `coffee_cloud` 非 superuser、无创建角色权限。DB 管理员先创建 `coffee_merchant` 为 NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT，并授予 `coffee_cloud` 角色成员关系；业务连接执行迁移18及 `app.merchant.provision`，仅授予当前 schema 所需表权限。启动会检查迁移及角色权限。运行时不创建角色。

## 发布与回滚

1. 最新源码/配置、数据库 dump、支付密钥和旧 API/worker/mock 镜像备份：`/home/alex/.deployment-backups/b2b-username-20260831T093732Z`。本次不修改 mock 服务、Tunnel 或支付密钥。
2. 独立数据库 `coffee_b2b_username_rehearsal_20260831` 恢复此 dump，使用真实非 superuser 业务账号演练迁移13–18和接口；不能向设备发送命令或真实支付。
3. 构建版本固定的发布镜像；更新前保留旧镜像。迁移生产，再只替换 API/worker，不重建 MQTT/Redis/EMQX/mock 容器。数据库迁移保持旧字段和旧调用兼容。
4. 检查公网注册、登录、新组织资源隔离、写操作 CSRF、无邮件模式和关闭能力；检查旧后台、mock 网关、worker 健康。
5. 如发布验收失败，停用 `MERCHANT_ENABLED` 并恢复备份配置和旧 API/worker 镜像。优先保留向前兼容的新增表，避免用旧 dump 覆盖上线期间的交易；数据库整库恢复只能停服并核对增量后执行。

发布实际镜像、时间、验收和遗留限制见发布完成后的记录。

## 实际发布结果（2026-08-31）

- 17:49 Asia/Taipei 已发布，镜像 `coffee-cloud-mvp:b2b-username-20260831-r1`。
- 公网入口：https://coffee-api.woodbridge.top/assets/merchant.html 。`auth/config` 返回 USERNAME、mailEnabled=false、limitedRelease=true。
- API 与业务 worker 使用新镜像且 healthy；MQTT、Redis、EMQX、独立 mock 网关保持原容器。mock 公网 `/health` 返回 ok。
- 迁移至18，恢复演练原有3设备、26订单保持不变；新租户看不到这些历史资产。
- 本地 Python 全量 208 passed / 11 skipped；最终报表/用户名/架构补验18 passed；Node 46 passed。
- 公网31项接口检查通过，含 Cookie、CSRF、跨租户门店修改/报表拒绝、邮件不可用、关闭功能403、CSV、旧后台和健康检查。
- 真实浏览器已通过公网注册→无需邮箱验证→登录→独立组织后台→退出；本地真实后端还验证了门店创建和成员邀请禁用。未进行390px移动端专门验收，不据此宣称全部视口验收完成。
- 验收账号3个已停用，所属测试组织停用、门店归档、会话撤销，保留审计记录。
- 部署记录 `deployment.json`、公网接口 `public-smoke.json`、清理记录 `qa-cleanup.json` 位于上述 VPS 备份目录。部署前额外生成最新 `coffee-db-pre-cutover.dump`。

完整多商户支付和设备成本闭环仍按原方案继续开发，不在本次“用户名可注册登录初版”完成范围内。
