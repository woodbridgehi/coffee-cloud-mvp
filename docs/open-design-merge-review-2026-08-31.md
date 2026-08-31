# Open Design 改版合并评审

## 结论和范围

接受 Open Design 分支的视觉统一方案，在修复评审发现的交互、展示和真实接口适配问题后合并至原项目 main。此次只合并本地代码，不部署 VPS，不修改后端、数据库迁移、支付渠道或生产配置。

本次改版主要是三个前端入口的共享颜色/圆角/字体/焦点令牌、金额列对齐、平台后台移动表格和键盘交互改善，并不是所有子页面的信息架构重做。不要将本次合并表述为“所有页面、所有设备均已全面验收”。

- 原项目：`/Users/alex/Downloads/armaster/coffee-cloud-mvp`
- 来源：Open Design 副本的 `open-design-revamp`，提交 `282dad4`、`2d8c6dd`、`6dfbfd7`。
- 合并前基线：`2d1e13c`。
- 回退标签：`before-open-design-merge-20260831-211244`。
- 双仓库 Git bundle 与原有未提交文件备份：`/Users/alex/Downloads/armaster/.implementation-backups/open-design-review-20260831-211244`。
- Open Design 副本不回写；副本的 `*.artifact.json` 编辑器元数据不导入。
- 原项目原有 `.gitignore` 修改及 `docs/system-architecture/` 未提交目录保持原样，不纳入提交。

## 评审修正

| 问题 | 修正 |
| --- | --- |
| 新增的行键盘事件会处理内部编辑按钮冒泡的 Enter/Space，可能重建行并吞掉按钮操作 | 仅处理直接来自行本身的事件，忽略按键重复；保留按钮原生行为 |
| 新增金额格式化仍会把空白、布尔值、数组等隐式转换为零，非整数分会静默舍入 | 平台与消费者金额拒绝这些输入；保留真实零元及整数数字字符串；百分比拒绝伪数值 |
| 采购明细全部缺失仍显示零元，非法值没有计入缺失标记 | 没有任何已知金额时显示待补全；部分已知继续显示带提示的部分合计；非法分值计入未知 |
| 退款上限缺失值保护不覆盖非法类型、负数与已退超过实收 | 对不可信上限禁用金额和提交，不猜测可退金额；服务端校验保持不变 |
| 新共享样式使用绝对 `/assets/` 路径破坏商户静态预览 | 商户 HTML 改为相对共享样式路径，兼容后端 /assets 和 public 静态目录 |
| 既存订单抽屉/浮层把原生 append 的 null 参数变成可见文字 | 可选节点通过空数组省略；测试 DOM shim 修正为浏览器真实的 null 转文字行为 |
| 既存支付和退款行将 badge DOM 节点放进模板字符串 | 以真实节点插入；补充真实接口的 SUCCEEDED、NOT_REQUIRED、READY 等状态，成功退款不再显示失败 |
| 既存时间线只识别演示字段 at/label | 优先读取真实接口 createdAt/description/status，兼容演示字段 |
| 既存“已交付”筛选 DELIVERED 与持久化状态 READY 不一致 | 真实适配器映射 DELIVERED→READY、PENDING→AWAITING_PAYMENT，其余筛选字段原样保留 |
| 视图自动聚焦时标题或整个内容区域出现焦点边框 | 仅隐藏非交互容器的焦点边框，按钮/输入/可点击行保留焦点提示 |

订单抽屉、状态文字、时间线和筛选适配问题存在于改版前基线，属于本次真实接口验收顺带修复，并非 Open Design 新引入。

## 验证

- Node：`node --test tests/*test.mjs tests/test_order_view.mjs`，61 passed / 0 failed。
- Python：使用本机隔离 PostgreSQL 17 测试库执行完整 pytest，208 passed / 11 skipped。跳过项目保持原有环境条件，不计为通过。
- 新增/扩展回归覆盖：键盘冒泡、金额伪零、采购部分合计、退款异常上限、真实订单字段和状态节点、筛选状态转换、总览四区域共用一个请求及失败后重试。
- 静态检查：所有 public JavaScript 语法检查、git diff --check。
- 真实浏览器 + 临时隔离数据库：平台 Token 登录、总览、键盘立即展开订单、创建运营员、鼠标打开编辑弹窗、Tab 首尾循环、Escape 关闭及焦点归还。
- 商户真实 Cookie 会话：用户名密码登录、组织导航、正式/测试环境筛选、测试订单列表与详情抽屉、缺失成本提示；浏览器复核 null 文字已消失、真实状态中文已显示。
- 消费者真实菜单：隔离设备能力快照的拿铁商品，在线/离线状态与不可下单禁用展示；未触发生产支付或设备命令。
- 静态预览：直接以 public 为静态目录打开 `merchant.html?demo=1`，演示认证页面正常加载。
- 窄屏：通过 320px iframe 截图检查平台登录、消费者菜单、独立静态演示商户登录。未把 iframe 结果当作真机验收。

## 未覆盖与安全边界

- 未完成全部登录后子页面在 390/768/1440 等宽度的完整交互矩阵，也未完成 iOS/Android 真机测试。
- 商户真实页面的 CSP frame-ancestors 与 X-Frame-Options 正常阻止嵌入预览；没有为测试移除或放宽安全策略。320px 商户检查使用无真实数据的独立静态演示入口。
- 浏览器工具的按钮 Enter 未触发原生点击，因此按钮冒泡修复通过实际绑定函数的事件回归验证，点击打开编辑弹窗另以真实浏览器验证；不声称完成原生键盘全链路验收。
- 不触发真实付款、退款、设备指令、邮件；本次不覆盖 VPS/Cloudflare 缓存与部署验收。
- 临时验收页面和测试数据库不随合并发布。新增前端 JS 模块和 shared CSS 均须随 public 完整部署，后续上线不能只拷贝 HTML。

## 后续查看与回退

合并使用独立 merge commit 保留三个来源提交和评审修正。可运行 `git diff before-open-design-merge-20260831-211244..main -- public tests docs` 查看完整结果。若上线后需要撤回，优先 revert 本次 merge commit（`-m 1`），不要使用 hard reset 丢弃用户工作区内容。
