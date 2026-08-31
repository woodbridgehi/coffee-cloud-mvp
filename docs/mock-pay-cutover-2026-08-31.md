# 2026-08-31：新订单切换到独立模拟支付

## 当前配置

VPS /home/alex/coffee-cloud-mvp 的 API 和 domain-worker 已切换：

    PAYMENT_DEFAULT_PROVIDER=alipay_mock
    PUBLIC_PAYMENT_MODE=ONLINE
    ALIPAY_MOCK_GATEWAY=http://127.0.0.1:8789/gateway.do
    ALIPAY_MOCK_APP_ID=coffee-cloud-mock
    ALIPAY_MOCK_APP_PRIVATE_KEY_FILE=/run/secrets/alipay/mock-app-private-key.pem
    ALIPAY_MOCK_PUBLIC_KEY_FILE=/run/secrets/alipay/mock-gateway-public-key.pem

同一VPS的后台通过回环地址调用独立HTTP网关，避免经Cloudflare绕行；协议仍为RSA2 OpenAPI。
二维码公开地址为 https://mock-pay.woodbridge.top/pay/随机token。
网关回调白名单为 https://coffee-api.woodbridge.top/api/v1/payments/callback/alipay_mock。
网关仍为独立项目，没有导入咖啡代码；这次仅添加普通商户注册配置。

## 为何保留两个渠道

切换前有14笔CLOSED沙箱支付和1笔PENDING沙箱支付，不能直接覆盖全局沙箱配置，
否则历史订单查询、关单和退款会打到错误网关。

- alipay：保留旧沙箱app_id、公私钥、gateway与原回调路径，仅处理原渠道订单。
- alipay_mock：同一AlipayProvider协议实现，独立app_id和RSA密钥，独立回调路径。
- payment/refund原有provider字段固定渠道；不修改历史账本，不需要数据库schema迁移。
- 新订单的页面提交空provider时使用alipay_mock；明确指定alipay仍可测试沙箱。
- 重试尚处于CREATED的旧支付意图，也沿用该行已记录的provider。
- Callback严格核对app_id；两个渠道的签名密钥不能互换。
- 请求时间戳显式使用Asia/Shanghai，不受VPS的UTC时区影响。

ALLOW_MOCK_PAYMENT仍为false。这里的alipay_mock使用完整RSA2网关，并非进程内MockPaymentProvider，
不会开放原进程内mock测试回调。

## 客户端

模拟器coffee-bot-001/002配置仍连接https://coffee-api.woodbridge.top，无需改地址或升级程序。
模拟器显示后台提供的点单入口，支付链接由后台预下单后返回，不在终端写死。
后台托管public/order.js已区分模拟付款与支付宝文案；视觉/页面修改按项目约定交给pi完成。
用户刷新点单页面并创建新订单即可；已打开的旧沙箱订单/二维码不会自动迁移。

## 验收

- Python3.12及项目锁定依赖：97 passed，93 skipped（未配置TEST_DATABASE_URL的数据库集成项）。
- Node订单页回归：3 passed，语法/差异检查通过。
- 新增测试覆盖渠道密钥隔离、独立回调路由、错误/缺失app_id拒绝和北京时间签名。
- VPS原客户端签名查询未知单：NOT_FOUND，响应验签通过。
- 实际公网验收订单ce42ae83-af89-4a89-ac34-2203612514e6：
  新默认渠道alipay_mock，付款页域名mock-pay.woodbridge.top，100分收款，重复确认，
  后台callback inbox恰好1条，进入PAID/QUEUED后取消，工作进程完成100分退款。
- 隔离终端QA-MOCK-953C81A0864F为SUSPENDED且无设备凭据；terminal_command为0。
  保留订单、退款与测试终端记录作为审计证据，没有向已有设备派发制作任务。
- 可在VPS项目目录重跑，每次创建独立暂停终端和模拟订单：

      docker exec -i coffee-cloud-mvp python - --run < scripts/verify_mock_pay_cutover.py

## 回滚

VPS切换前备份在.deployment-backups/mock-pay-cutover-20260831/：
env.before和source.before.tar.gz；旧镜像保留为coffee-cloud-mvp:before-mock-pay-20260831。
原沙箱密钥未覆盖；新商户私钥只保存在咖啡后台，网关仅登记其公钥。

若只是把新订单切回沙箱，将.env中PAYMENT_DEFAULT_PROVIDER改回alipay，然后执行：

    docker compose up -d --no-deps coffee-cloud-mvp coffee-domain-worker

保留本次双渠道代码、ALIPAY_MOCK_*配置和密钥，以便已产生的mock支付继续查询/退款。
不要直接恢复只识别alipay的旧镜像，也不要删除mock密钥或修改已有payment.provider。
本次没有重启MQTT Gateway、数据库、Redis或Cloudflare Tunnel。
