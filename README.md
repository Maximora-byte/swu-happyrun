# SWU HappyRun

西南大学步道乐跑适配项目，规划 Windows/MuMu 执行代理、服务器调度和 vivo 无 Root 兼容性验证。

最新分工（2026-10-18）：**Dot 主导全部主要开发，本地 Codex 负责实测与集成验收。** 当前实施入口为[今晚至次日的冲刺任务](docs/handoffs/2026-10-18-dot-lead-sprint.md)；下列原始计划的旧负责人列由该分工覆盖。

**当前状态：设计与协作计划阶段。尚未提供可运行产品，尚未验证任何步道乐跑版本的完整兼容性。**

## 开发入口

- [设计评估与修订结论](docs/design-review.md)
- [双端开发总计划](docs/superpowers/plans/2026-10-18-development.md)
- [服务器实施计划：云端 Dot](docs/superpowers/plans/2026-10-18-server.md)
- [执行端实施计划：本地 Codex](docs/superpowers/plans/2026-10-18-agent.md)
- [两端接口契约 v1](docs/contracts/control-plane-v1.md)
- [完整设计说明](docs/superpowers/specs/2026-10-18-swu-happyrun-design.md)
- [当前协作状态](docs/status.md)
- [Dot 接手说明](docs/handoffs/dot-server.md)
- [GitHub 开发任务](https://github.com/Maximora-byte/swu-happyrun/issues)

## 分工

| 工作 | 负责人 | 主要目录 |
| --- | --- | --- |
| 共享契约、核心逻辑、CLI 与实现测试 | Dot 开发，本地 Codex 独立验收 | `contracts/`、`src/swu_happyrun/core/`、`tests/contracts/` |
| Windows/MuMu、ADB 与执行代理 | Dot 开发，本地 Codex 设备实测 | `src/swu_happyrun/agent/`、`src/swu_happyrun/drivers/`、`tests/agent/` |
| 服务 API、数据库、租约、调度、容器配置 | Matrix 群中的 ChatGPT Dot | `src/swu_happyrun/server/`、`tests/server/`、`deploy/` |

以上源码目录是计划中的责任边界，尚未实现。双方使用独立分支和 PR，GitHub Issue 记录任务状态；Matrix 用于通知与澄清。消息发送成功、Dot 接单、代码提交、测试通过和设备验收分别记录。

已创建 11 个开发/交接任务。本轮按用户选择只准备 Dot 交接包，尚未发送 Matrix 启动消息，云端开发未启动。

## 兼容性与数据

已知用户环境为无 Root 的 vivo X200 Pro，以及 Windows 上的 MuMu 6.8.4.0 / Android 15 实例。校区、学校当前规则、乐跑版本及真实路线需要在首次接入时采集。

服务器首版负责调度在线设备代理；无设备的纯接口执行单独研究。模拟器轨迹完成、上传提示和最终有效记录使用不同的验收证据。仓库不提供虚构的学校 ID、打卡点或“100% 成功”承诺。

账号会话、设备截图、原始轨迹和数据库放在被 Git 忽略的本地目录。参考项目及其复用边界见 [第三方来源](THIRD_PARTY_NOTICES.md)。
