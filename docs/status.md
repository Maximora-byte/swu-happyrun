# 协作状态

更新日期：2026-10-18（Asia/Shanghai）。此文件记录证据，不由收到消息或计划勾选自动推断完成。

## 最新分工与证据

- 用户最新要求：Dot 主导主要开发，本地 Codex 负责实测与集成审核；见[冲刺任务](handoffs/2026-10-18-dot-lead-sprint.md)。目标明早候选版、24 小时内一次 v1 验收，不承诺未经实测的完整兼容性。
- 仓库已公开。当前 main 尚未合入业务代码；C0/L0 在 [PR #13](https://github.com/Maximora-byte/swu-happyrun/pull/13)，HEAD `3ff0a33a01c629432a2036f4e105bed52157bd9e`，109 tests 和四组 CI 已通过，但 Dot 报告的 verify_only 恢复路径问题仍是阻塞。
- Dot 已在 [Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 回报真实仓库/Python 能力，并提交 [PR #12](https://github.com/Maximora-byte/swu-happyrun/pull/12) 的 50 条待实现服务器测试设计；这不是 S0 产品实现。
- Dot 现在负责接管 C0 修复与 [C1 #14](https://github.com/Maximora-byte/swu-happyrun/issues/14)，随后实现 S0-S2、L1-L3 和 CLI；本地不再负责主要产品编码。新角色覆盖原 Issue/计划中的旧负责人。
- 本地 MuMu 6.8.4.0 / Android 15.0 实例查询通过，实例停止，ADB 无设备；定位/传感器、应用、vivo 与学校有效记录未验证。
- 本轮冲刺消息的实际送达与接单回执以 Matrix / Issue 为证；不能由这份计划的存在推断 Dot 已开始夜间任务。

## 初次建仓快照（历史记录）

以下是本轮角色调整前的历史快照；状态和负责人以本页上方、最新 AGENTS.md 与冲刺任务为准。

| 项目 | 当前状态 | 证据/下一步 |
| --- | --- | --- |
| 初版设计 | 已提交 | `687d0be` |
| 设计评估、v1 契约与双端计划 | 已发布，待 Dot 交叉评审 | [设计基线 015447d](https://github.com/Maximora-byte/swu-happyrun/commit/015447dc97637311874dda061cb5fe48babb21f5) |
| GitHub 仓库 | 已创建并推送 | [Maximora-byte/swu-happyrun](https://github.com/Maximora-byte/swu-happyrun)，私有，默认分支 main |
| Matrix Dot 入口 | 已识别，未派发 | 群名 `Matrix · ChatGPT Dot`；用户本次选择只准备交接任务 |
| Dot 接单与仓库访问 | 未确认，云端开发未启动 | [交接 Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 与[待发送说明](handoffs/dot-server.md)已准备 |
| 服务器实现 | 未开始 | S0-S2 |
| 本地代理实现 | 未开始 | C0、L0-L3 |
| MuMu Android 15 兼容 | 未验证 | 已确认安装信息，无应用运行证据 |
| vivo 无 Root 兼容 | 未验证 | 缺实际 Android/app 版本和测试连接 |
| 西大学校规则与有效记录 | 未验证 | 需实际校区、规则、版本和本人会话 |

每次交接记录 Issue/PR URL、基线与 HEAD、运行的检查、未验证范围。旧 Workflow 连接器本轮返回内部错误；Matrix Dot 独立连接器能够列出群与连接状态，不把回调 HTTP 接收当作 Dot 接单。

## 任务清单

负责人是计划分工，非 GitHub 用户指派；Dot 尚未实际接单。ready 表示可进入实施，不表示已经开工。

| Issue | 负责人 | 前置条件 |
| --- | --- | --- |
| [#1 Dot 接入与协议评审](https://github.com/Maximora-byte/swu-happyrun/issues/1) | Dot | 待发送交接；实际仓库访问与执行能力确认 |
| [#2 C0 共享模型与工具链](https://github.com/Maximora-byte/swu-happyrun/issues/2) | 本地 Codex | 设计基线已发布 |
| [#3 L0 MuMu/ADB 探测](https://github.com/Maximora-byte/swu-happyrun/issues/3) | 本地 Codex | 只读勘察可先行；模型集成依赖 C0 |
| [#4 S0 服务 API 与存储](https://github.com/Maximora-byte/swu-happyrun/issues/4) | Dot | #1、#2 |
| [#5 S1 租约与恢复](https://github.com/Maximora-byte/swu-happyrun/issues/5) | Dot | #4 |
| [#6 S2 日程与部署包](https://github.com/Maximora-byte/swu-happyrun/issues/6) | Dot | #5 |
| [#7 L1 配置与设备驱动](https://github.com/Maximora-byte/swu-happyrun/issues/7) | 本地 Codex | #2、#3 |
| [#8 L2 代理与 CLI](https://github.com/Maximora-byte/swu-happyrun/issues/8) | 本地 Codex | #7；真实 HTTP 验收依赖 #5 |
| [#9 L3 应用适配与记录核验](https://github.com/Maximora-byte/swu-happyrun/issues/9) | 本地 Codex | #8、实际校区/规则/版本/本人会话 |
| [#10 I0 双端联调](https://github.com/Maximora-byte/swu-happyrun/issues/10) | 本地 Codex，Dot 修复服务器 | #6、#8；设备验收依赖 #9 |
| [#11 R0 vivo/纯接口研究](https://github.com/Maximora-byte/swu-happyrun/issues/11) | 本地 Codex，Dot 评审接口样本 | 实际设备版本、连接和脱敏样本 |

本轮交付仅包含设计、协议草案、实施计划和协作任务。Markdown 相对链接、占位符扫描及 Git 空白检查通过；没有业务代码，因此未运行产品测试，也没有生成设备验收结论。
