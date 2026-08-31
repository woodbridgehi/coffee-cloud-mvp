# 用户名模式上线 · 前端交付记录（pi）

> 执行方：pi（本任务代理）。工作目录 `/Users/alex/Downloads/armaster/coffee-cloud-mvp`。
> 边界：只修改 merchant 前端文件与 `tests/merchant-ui-*.test.mjs`、本文档；未修改 `app/`、旧后台文件；未部署、未创建 commit。
> 后端 `/api/v1/merchant/*` 由并行工作实现（已落在工作区 `app/merchant/`，非本人改动），本文档第 4 节的核对基于该代码。

## 1. 修改文件清单

| 文件 | 变更 |
| --- | --- |
| `public/merchant-format.js` | 新增纯逻辑助手：`DEFAULT_USERNAME_PATTERN`（`^[a-z][a-z0-9_.-]{2,31}$`）、`normalizeUsername`（trim + lowercase）、`validateUsername`（先规范化再匹配，非法 pattern 回退默认规则、空值不放行）、`validateNewPassword`（默认 15–128，配置可覆盖）。既有函数未改动。 |
| `public/merchant-api.js` | 真实适配器新增 `authConfig()`：`GET /api/v1/merchant/auth/config`，无需登录，走既有 `json()` 通道（同源 cookie、错误规范化、非 JSON 拒绝）。其余方法未动。 |
| `public/merchant-demo.js` | demo 适配器新增同形 `authConfig()`：固定返回 `{registrationMode:'EMAIL', passwordMinLength:15, passwordMaxLength:128, usernamePattern:'^[a-z][a-z0-9_.-]{2,31}$', mailEnabled:true, limitedRelease:true}`，维持 EMAIL 演示兼容既有测试。其余未动。 |
| `public/merchant.js` | 见第 2 节。 |
| `public/merchant.css` | 新增 `.result-icon.error`、`.release-note`（复用 `.callout` 基类的紧凑说明）、`.invite-disabled-note`。咖啡棕变量与既有布局未重做。 |
| `public/merchant.html` | 未改动（认证界面由 JS 渲染，无需结构变化）。 |
| `tests/merchant-ui-format.test.mjs` | 追加 5 个测试：normalizeUsername、validateUsername（默认规则/边界/非法字符/空值）、validateUsername 非法 pattern 回退、validateNewPassword（15–128/配置覆盖）、demo authConfig 形状。原有断言全部保留。 |
| `tests/merchant-ui-api.test.mjs` | 追加 1 个测试：authConfig 请求路径/方法/凭据模式与响应字段。原有 3 个测试未动。 |
| `tests/merchant-ui-auth.test.mjs` | 新增文件，8 个测试（真实适配器 + DOM stub + mock fetch，每场景独立加载全新模块）。 |
| `docs/pi-username-release-delivery.md` | 本文档。 |

## 2. merchant.js 实现要点（对照任务条目）

1. **配置先行**：`boot()` → `startWithAuthConfig()` 先取 `adapter.authConfig()`，存入 `state.authConfig`（非敏感，不含密码，不写任何浏览器存储）。失败时 `renderAuthConfigError()` 诚实展示错误（含 requestId 等）+ 重试按钮，明确“不回退演示、不在未取得配置前展示登录表单”；`renderAuth()` 对未加载配置做防御分支。刷新页面重新拉取；会话失效（401 → `forceLogout`）不清除该配置。
2. **USERNAME 模式**：登录栏 text 输入、label“用户名”、`autocomplete=username`，附提示“已注册邮箱账号仍可用邮箱登录”，提交 `{username, password}`（提交前 `normalizeUsername`）；注册表单必填 username/displayName/tenantName/password，username 3–32 位校验 + trim + lowercase，密码 15–128（minlength/maxlength 与文案均取自配置），成功后显示“注册成功，可直接登录”（附“无需验证邮箱；忘记密码请联系平台管理员重置”），不自动登录、不伪造 session；若服务器返回非 `REGISTERED` 状态则显示“注册请求已提交”+ 状态值，不谎报成功。409 `USERNAME_TAKEN` 的 `fields.username` 映射为行内错误。EMAIL 模式维持旧流程（`VERIFICATION_PENDING` + 主动验证页），所有新密码表单（注册/重置/邀请，两种模式）统一 15–128。
3. **mailEnabled=false**：登录页隐藏“忘记密码/使用邀请链接/验证邮箱”链接（保留“创建组织账号”）；直接访问 `#/forgot` `#/verify` `#/invite` `#/reset` 显示统一说明“邮件服务未配置，此功能暂未开放；忘记密码请联系平台管理员”并保留“返回登录”，不渲染可提交表单；成员页“邀请新成员”按钮禁用并附说明，`openInviteModal()` 入口双保险拦截，邀请空列表文案同步；成员列表照常可用，不伪造邀请发送成功。
4. **账号展示**：新增 `accountLabel(user)`（username → email → displayName → '—'），侧栏 who、顶栏账号按钮、用户菜单（username/email 行仅在非 null 时渲染）、成员列表账号列均改用；不展示 null 或假邮箱。
5. **limitedRelease 上线说明**：仅在总览（dashboard）顶部出现一条紧凑 `.release-note`，文案覆盖任务要求的四点（已开放范围 / 设备转让与商户收款配置未开放 / 设备消耗自动计成本未接入、缺项显示“待补全” / 库存为账面库存）。不逐页重复。
6. **权限尊重**：导航与操作按钮本就由 `can(perm)` + 服务器 `allowedActions` 双重门控（设备转让视图需 `devices.transfer`、命令按钮需 `commands.execute`、收款账户写操作需 `payments.manage`）。后端从 session.permissions 与 allowedActions 删除对应项后，入口自动消失，无绕过路径；只读界面保留。未触碰 ADMIN_TOKEN，无任何浏览器密码存储，无 console 输出（`grep localStorage|sessionStorage|document.cookie|ADMIN_TOKEN|console.` 为空）。

## 3. 验证命令与真实结果

```
node --check public/merchant.js public/merchant-api.js public/merchant-demo.js public/merchant-format.js   # 全部通过
node --check tests/merchant-ui-{api,auth,format,smoke}.test.mjs                                            # 全部通过
node --test tests/merchant-ui-format.test.mjs tests/merchant-ui-api.test.mjs tests/merchant-ui-smoke.test.mjs tests/merchant-ui-auth.test.mjs
# tests 46 / pass 46 / fail 0（Node v24.20.0）
```

分文件：format 27/27、api 4/4、smoke 7/7（含 EMAIL demo 回归，导航 13/6 项等原有断言未删改）、auth 8/8（新增）。

新增 auth 测试覆盖：配置先行与 USERNAME 登录栏形态；注册用户名/密码校验失败不发请求；注册成功文案/`{username:'owner.user'}` 规范化提交/不伪造 session；mailDisabled 四个入口统一说明；配置失败诚实错误 + 重试恢复；登录成功后 username 优先展示与总览唯一上线说明；EMAIL 模式回归；mailDisabled 成员页邀请禁用与账号展示。

## 4. API 字段核对（对照并行后端 `app/merchant/`）

逐项核对结果——**未发现阻塞级不匹配**，关键契约一致：

| 契约点 | 前端用法 | 后端实现 | 结论 |
| --- | --- | --- | --- |
| `GET /auth/config` | `registrationMode/passwordMinLength/passwordMaxLength/usernamePattern/mailEnabled/limitedRelease` | `service.auth_config()` 返回同名字段（15/128、同一正则、`mailEnabled = SMTP 配置且非 limited_release`） | 一致 |
| `POST /auth/register`（USERNAME） | 提交 `{username,displayName,tenantName,password}`，期望 `{data:{status:'REGISTERED'}}` | `register_username()` 同字段，返回 `{status:'REGISTERED'}`；重复用户名 409 `USERNAME_TAKEN` + `fields.username` | 一致 |
| 密码长度 | 提交前 15–128 校验，行内错误 key `password` | `hash_password()` 15–128，422 `INVALID_PASSWORD` + `fields.password` | 一致 |
| `POST /auth/login` | USERNAME 模式提交 `{username:<trim+lowercase>}`（可含邮箱） | `'username' in data` 取值，含 `@` 走 email 分支；`username()`/`email_address()` 同样 strip+lower | 一致 |
| `GET /session` user | `username/email/displayName` 可空，`accountLabel` 优先 username | `_session_payload()` 返回 `{id,email,username,displayName}`（可空） | 一致 |
| `GET /members` 条目 | `accountLabel(member)`（username→email） | 返回 `email/username/displayName` | 一致 |
| limited release 权限 | `can()` 门控导航/按钮 | `permissions()` 删除 `devices.transfer/payments.manage/commands.execute` | 一致 |
| 邮件入口禁用 | 前端隐藏/禁用；后端 `mail_ready()` 直接 503 `MAIL_UNAVAILABLE` | 双侧一致，无伪造发送 | 一致 |

次要备注（不阻塞，联调时留意）：
1. 注册 displayName/tenantName 输入框未加 `maxlength`（后端 `text_field` 上限 160，超限返回 422 行内错误可正常展示）。沿用原实现，未额外限制。
2. USERNAME 登录把整个输入 lowercase 后提交；对邮箱输入无影响（后端同样 lowercase），但如果后端未来对邮箱大小写敏感需回退此行为——当前实现不会。
3. 既有契约疑点（`GET /session` 无 `membershipId`、`PATCH /purchases/{id}` 等）沿用上一轮交付文档第 7 节，未新增。

## 5. 已知取舍与未覆盖事项（如实记录）

- **演示模式权限未随 limitedRelease 收紧**：demo `authConfig` 声明 `limitedRelease:true`（总览会显示上线说明），但 demo 角色权限表保留全量（OWNER 13 个导航含设备转让/收款账户），以维持既有冒烟测试的导航数量断言（任务要求不为通过测试删除断言）。仅影响演示审阅观感，真实模式完全跟随服务器权限。
- **真实浏览器联调未执行**：本机无 headless 浏览器；USERNAME 注册→登录→外壳、邮件禁用提示的视觉/交互以 DOM stub 测试与代码审查为准，待主代理真实浏览器验收（含 390px 视口）。
- **VPS 发布、后端联调、CSRF/限流实测**：属主代理职责，未执行。`tests/test_merchant_username.py` 等后端测试属并行工作，未运行、未改动。
- **`node --check` 对 ES module 的检查以 `--input-type=module` 导入复核过语法**（`location is not defined` 属 Node 无浏览器全局的预期报错，非语法问题）。
- 上线说明仅在总览出现；若产品后续要求组织设置页也提示，需另行委派。

## 6. 结论

任务 1–6 全部完成：配置驱动的双模式认证、mailDisabled 全入口诚实降级、username 优先账号展示、单点上线说明、权限尊重，以及 46/46 通过的前端测试（含 8 个新增 USERNAME/mailDisabled/配置失败场景）。等待主代理进行真实浏览器联调与 VPS 发布。
