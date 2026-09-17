# 饮品个性化（2026-09-11）

当前本地实现包含手机选项、签名报价、冻结订单、全队列物料承诺、MAKE_DRINK 摘要验证及终端执行计划。支付走既有TEST_FREE / ONLINE流程，实际渠道由配置与账户决定；本专题不代表真实支付验收。

## 配方规则

终端 `customization.py` 是唯一剂量编译器。配方通过 `optionSchema` 显式声明允许的 sugar/ice/milk 值、默认值、规则版本和 `priceDeltaMinor`。独立出料步骤必须声明 `customizationRole` 和 `dispenseChannel`，且只含一种原料；禁止根据原料名称推断糖度。

糖度枚举：NONE / LIGHT / LESS / STANDARD / EXTRA，对应 0 / 0.25 / 0.5 / 1 / 1.25。冰和奶：NONE / STANDARD。剂量精度为 0.001 个配方单位。零剂量步骤直接移除；降低剂量保留机械动作时间下限，多糖按比例延长时长。每次接单仍冻结一次随机执行时长，重试、恢复共用已存配方。

早期交付曾升级001、003的部分配方；当前003已扩为十款城市菜单，版本和组合以当前recipes及capabilities为准，见 [城市菜单说明](../../coffee-terminal-simulator/docs/beijing-city-menu-and-sync.md)。卡布奇诺等未开放的组合继续拒绝。温度按配方固定 HOT / AMBIENT / ICED，去冰不加热。填充策略仅支持 NO_TOP_UP，去冰/奶不补液。默认无选项加价；可配置非负整数附加价。牛奶、巧克力等自身含糖，因此文案限定“无添加糖（可调糖浆）”。

## API 与一致性

1. 设备 capabilities 上报 `optionSchema`、`customizationVariants`，每个组合含标准化选项、物料需求、时长范围和 `compiledRecipeDigest`。云端不另写剂量换算公式。
2. `POST /api/v1/public/devices/{identifier}/quotes`，请求字段同下单模型，传 recipeId、recipeVersion、paymentMode、customization，不传 quoteId。返回 quoteId、expiresAt（Unix 秒）、available、product。报价五分钟有效，绑定设备、配方/规则/编译摘要、选项、金额、币种及支付方式，不预占库存。
3. `POST .../orders` 携带原报价 quoteId、同一组 customization 和 Idempotency-Key。服务器在设备行锁下重新核验现价、报价和整个队列物料承诺。缺货仍可能发生；QUOTE_CHANGED 返回 409，必须获取新报价并再次确认。
4. 订单 product_snapshot 冻结选项、规则版本、摘要、价格和需求；幂等摘要包含选项和报价。重复成功请求优先返回原订单，即使报价后来过期。前端保存待提交报价和幂等键用于网络错误重试；支付创建前即保存已创建订单，以便恢复。
5. 派发发送冻结选项和摘要。终端以本机模板重新编译并核对，版本或摘要不符拒绝接单。编译后的步骤同时用于预占、扣料、二维动画和三维 stepPlan；没有出料动作的物料不会被三维恢复。液位按基础配方液体量作参照，去奶不再画成满杯。

旧设备不声明 optionSchema 时，保留原默认下单契约，拒绝未支持选项。已完成/进行中的旧任务保留自己的 SQLite 冻结配方。终端已支持经过校验的recipe-archive历史版本：升级时保留旧订单依赖版本及物料定义；缺少有效归档或当前饮品禁用时仍拒绝。不要沿用“所有旧版本一律拒绝”的早期限制。本专题不表示已经部署。

`dispenseChannel` 为模拟执行通道标识（榛果、香草、巧克力独立命名）；三维仍是通用糖浆区域，没有完成真实泵接线、不同出口坐标或传感器标定，不作为实机出料认证。
