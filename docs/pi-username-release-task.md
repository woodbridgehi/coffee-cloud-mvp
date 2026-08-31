# 用户名模式上线前端任务

项目根目录 /Users/alex/Downloads/armaster/coffee-cloud-mvp。现状：原生 JS ES modules + 自定义 CSS，public/merchant.html/css/js/api.js/demo.js/format.js 已有 B 端完整页面，真实 API 默认同源 /api/v1/merchant，?demo=1 才用内存演示。请只修改这些 merchant 前端文件、对应 tests/merchant-ui-*.test.mjs 和本任务交付记录 docs/pi-username-release-delivery.md，不修改 app/、其他旧后台文件，不部署、不创建 commit。你的工作与后端并行进行。

用户已明确授权：现在上线，邮件服务未准备好，暂时允许用户名密码注册登录。请保留已有咖啡棕视觉和响应式，不重做整体页面。详细方案如下，直接实施：

1. 后端新增 GET /api/v1/merchant/auth/config，无需登录，返回 {data:{registrationMode:'USERNAME'|'EMAIL',passwordMinLength:15,passwordMaxLength:128,usernamePattern:'^[a-z][a-z0-9_.-]{2,31}$',mailEnabled:false,limitedRelease:true}}。真实适配器添加 authConfig()。初始化先取配置，不可失败后默认演示/默默假定认证可用。demo 适配器提供同方法，维持 EMAIL 演示兼容现有测试。刷新和失效会话均保留该非敏感配置，不保存密码。
2. USERNAME 模式：登录栏 text 输入“用户名”，autocomplete=username（可提示已注册邮箱账号仍可用邮箱登录），提交 {username,password}。注册必填 username/displayName/tenantName/password，username 输入3–32位，以字母开头，后续仅英文数字点下划线连字符，不区分大小写，提交前 trim lowercase。密码15–128个字符。POST /auth/register 返回 {data:{status:'REGISTERED'}} 后显示“注册成功，可直接登录”，不再提示验证邮箱，不自动伪造 session。EMAIL 模式维持旧 email 流程和 VERIFICATION_PENDING，所有新密码表单将8位旧规则统一到15–128。
3. 没有 mailEnabled 时：隐藏/禁用找回邮箱、邀请成员按钮及发送邮箱入口；直接访问 #/forgot/#/verify/#/invite/#/reset 显示说明“邮件服务未配置，此功能暂未开放；忘记密码请联系平台管理员”，保留返回登录。成员列表仍可用；不得伪造邀请发送成功。已有 session.user 将含 username:null|string、email:null|string、displayName；账号展示优先 username 再 email，不能展示 null 或假邮箱。
4. 有 session 且 limitedRelease 时，在现有页面合适位置放紧凑上线说明：当前已开放账号、组织、门店与基础运营管理；设备转让、商户收款配置暂未开放；设备消耗自动计成本尚未接入，报表缺项会显示“待补全”；库存是账面库存，不代表设备实时可用量。不要每个页面重复堆满说明。后端会从 session.permissions 删除 devices.transfer、payments.manage、commands.execute，并从设备 allowedActions 删除对应操作，UI 要尊重权限、不暴露绕过入口，已有读界面可保留。
5. 不改变后台 API 对权属/权限的责任，不触碰 ADMIN_TOKEN，不从浏览器存储密码。新增针对 USERNAME 模式注册成功/密码长度、mailDisabled 下入口提示、配置失败诚实错误的测试。原有 EMAIL demo 和 API/CSV 测试要继续通过，不为通过测试删除断言。
6. 核对实际界面必要 API 字段并在交付文档列出不匹配项；不要自行修改后台或展开新功能。运行 node --check 与 node --test tests/merchant-ui-*.test.mjs，报告真实结果和未覆盖事项。

完成后写交付文档并退出，无需等待回复。主代理负责真实浏览器联调和 VPS 发布。
