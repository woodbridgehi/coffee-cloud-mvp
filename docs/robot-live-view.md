# 订单三维制作视图

核对日期：2026-09-17。顾客订单状态页默认嵌入可用的三维制作视图，可切换二维；没有有效计划或WebGL不可用时提供回退。自己的制作跟随原有SSE，不另建订单流。排队时可主动打开同机匿名旁观，详见 [队列与匿名观看](queue-and-private-scene.md)。终端本机仍默认二维、手动打开三维，两端入口不要混淆。

终端接单事件 `payload.stepPlan[].visual` 使用以下格式，保存在现有 `step_durations` JSON 中，无需数据库迁移：

```json
{"version":1,"actions":["milk"],"materials":[{"materialId":"milk","name":"鲜奶","amount":180,"unit":"ml"}]}
```

公共订单响应在 `production.robotView` 返回白名单投影 `{version:1,steps:[...]}`，保留实际步骤耗时。旧设备或不合法计划返回 null，页面继续二维。机器人动作是设备进度的只读示意，不是设备控制指令；制作成功以持久化业务状态为准。支付流程无变化。

## 构建与更新

共享源码位于相邻仓库 `coffee-terminal-simulator/coffee-terminal/web/robot/`，不要直接修改生成包。在该仓库执行：

```bash
npm ci
npm run sync:cloud-scene
```

脚本构建并复制 `robot-live.bundle.js`、`robot-integration.bundle.js`、`robot-live.css`、`process-audio.bundle.js` 和 Three.js 许可证到本项目 `public/robot/`，同时同步 `public/shared/status-sound.js` / CSS及门店GLB。这些文件随普通云端部署发布，由 `/assets/robot/` 同源提供，无 CDN 或终端 localhost 依赖。更新云端及终端后，新接单任务自动启用；历史订单不回填。

渲染在顾客浏览器执行；没有服务器端渲染或逐帧关节上传。此次本地验证包括真实 Python 临时实例与前端/SSE 测试桥、手机窄屏、暂停恢复、物料一致性，以及现有单元测试。未做 VPS 部署、真实支付、真实手机性能测试或 1000 台设备压测。数据库依赖集成测试需要另行提供 PostgreSQL 环境。

### Blender 门店资产

2026-09-12 起，共享 viewer 从自身 bundle 相对地址 `assets/scene/coffee-shop-v1.glb` 加载静态门店 PBR 资源，即云端 `/assets/robot/assets/scene/coffee-shop-v1.glb`。`sync:cloud-scene` 已包含该文件；部署时必须携带完整 `public/robot`。GLB 内嵌烘焙贴图，不请求外部 CDN。资源失败时保留原程序化门店，订单步骤仍按现有协议同步。
