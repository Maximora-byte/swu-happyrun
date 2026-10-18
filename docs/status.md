# 协作状态

更新日期：2026-10-18（Asia/Shanghai）。当前结论以下方“当前交付候选”为准；末尾保存旧快照用于追溯，不能将旧“未接单/未开始”作为本轮状态。

## 当前交付候选

Dot 已承担主要实现与修复；本地 Codex 负责 Windows、真实设备与集成独立验收。此分工覆盖旧计划中的负责人，详见 [冲刺交接](handoffs/2026-10-18-dot-lead-sprint.md) 与 [Issue #16](https://github.com/Maximora-byte/swu-happyrun/issues/16)。本文不宣称全部 v1 已验收，也不把提交、局部测试、软件联调、设备观测和学校有效记录合并为同一种“完成”。

| 范围 | 代码交付状态 | 软件验证证据 / 剩余门槛 | 设备与记录 |
| --- | --- | --- | --- |
| C0/L0 继承与恢复结构边 | [替代 PR #17](https://github.com/Maximora-byte/swu-happyrun/pull/17)，HEAD `6ed02c29924ccc3ab26c028fbf46d15477d84eb0` | 修复 verify_only 恢复路径；基于旧 PR #13 继承，最终候选须保留修复 | 只读主机诊断不等于设备执行通过 |
| C1 恢复/归属/证据契约 | [PR #19](https://github.com/Maximora-byte/swu-happyrun/pull/19)，阶段 HEAD `a82e4d97a5a7e1de5112eabeecac6e97312089a7` | 摘要别名一致性与 ASCII 日程时间修复；该版本本地 163 tests 通过，最终集成还需重跑 | 无设备/学校有效记录结论 |
| S0 API 与 SQLite | [PR #18](https://github.com/Maximora-byte/swu-happyrun/pull/18)，阶段 HEAD `c474119cdc18fa34fefffd5e8ea64c79f0106159`（继承 C0） | 本地 152 tests；该 HEAD 两个 CI run success 已核对；不代表 S1/S2 | 不依赖真实设备 |
| S1 租约、取消、恢复 | [PR #22](https://github.com/Maximora-byte/swu-happyrun/pull/22)，阶段 HEAD `e3ffab6a0309d2b7e484edfe9498f4e2aab9e1b2` | 本地 223 tests、独立审计 14 项；最终安装包实际 HTTP 故障验收待 I0 | 不依赖真实设备 |
| S2 日程与重启 | [PR #23](https://github.com/Maximora-byte/swu-happyrun/pull/23)，阶段 HEAD `561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9` | 本地 252 tests、独立审计 6 项；ready/tzdata/schema3；最终集成待验证 | 无设备结论 |
| L1 profile / driver / fake | [PR #20](https://github.com/Maximora-byte/swu-happyrun/pull/20)，阶段 HEAD `10b2172bebd8aba302cc8a0345503b32d38589f6`，继承 C1 alias 修复 | 阶段本地 216 tests；新 HEAD CI 单列核对；fake 不产 app_record | 真实设备适配 `needs_samples` |
| L2 agent / journal / CLI | [PR #21](https://github.com/Maximora-byte/swu-happyrun/pull/21)，阶段 HEAD `ce14f968339307d14acce88d3af8cbab13b9c0ac`，已继承新版 L1 | 阶段本地 252 tests，Windows lock 修复已发布；此 HEAD CI 待核对，实际 HTTP 待 I0 | 当前物理后端 `unsupported_by_candidate` |
| 安装/部署/文档 | 候选文件已准备，尚未据此声称容器可运行 | 7 项交付静态/fixture 测试与 lint/format 通过；Docker CLI 不可用，容器检查 `not_tested` | Windows 安装待独立验证 |
| I0 集成 | 等待完整候选绑定不可变 HEAD | 完整 pytest、冻结安装、Schema、构建、HTTP 故障矩阵、CI 与 artifact 下载仍需独立结果 | 不替代本地设备验收 |
| L3 乐跑应用适配 | `needs_samples` / `unsupported_by_candidate` | 需要精确版本、本人会话、学校规则与脱敏页面样本，见 [Issue #9](https://github.com/Maximora-byte/swu-happyrun/issues/9) | `not_tested` |
| vivo 无 Root | 保留研究方向；当前候选 `unsupported_by_candidate` | 见 [证据矩阵](research/vivo-noroot.md)，不推断平台永久不可行 | `not_tested` |
| 纯接口直传 | 保留研究方向；当前候选 `unsupported_by_candidate` | 未取得西大真实业务协议/签名样本，见 [证据矩阵](research/direct-protocol.md) | `not_tested` |

上述阶段 HEAD 用于追溯已报告的检查，不是最终统一候选。最终安装与验收必须使用集成 PR 正文和对应 Actions `github.sha` 指定的不可变 HEAD；I0 manifest 记录组件来源，不能混用分支最新内容。

### 发布门槛与可复现资料

- 候选 HEAD 由集成 PR 正文/Actions `github.sha` 绑定，父基线、各 PR 继承关系和最终集成命令/结果在 I0 发布记录补齐；“推进中”不是验收通过。
- [50 项验收设计覆盖映射](acceptance-coverage.md) 标明实际测试方法与尚未覆盖范围；映射存在不等于通过。
- [交付验证记录](delivery-validation.md) 区分执行过和未执行的检查；[安装](installation.md)、[服务器](server.md)、[fake 与故障](fake-e2e.md)、[本地 QA](local-qa.md) 提供操作步骤。
- CI 只在既有检查和独立安装成功后生成候选 wheel/sdist/checksum artifact。未核对实际 run 和 artifact 前，不称已有可下载安装包；没有创建 Release。
- MuMu 已知历史证据仅为 6.8.4.0 / Android 15 实例可查询且停止、ADB 无设备。新的 device_verified / record_verified 必须来自指定版本的实际观测。
- 本轮不操作用户桌面，不修改生产服务器、DNS、账号、Root 或系统安全设置。原始截图、路线、数据库、账号与 token 留私有环境。

## 历史记录（下列内容已被上方当前状态覆盖）

以下原文保留当时接单与分工背景；“未开始”“旧负责人”“本轮交付仅设计”等表述仅适用于对应历史快照。


更新日期：2026-10-18（Asia/Shanghai）。此文件记录证据，不由收到消息或计划勾选自动推断完成。

### 当时的分工与证据

- 用户最新要求：Dot 主导主要开发，本地 Codex 负责实测与集成审核；见[冲刺任务](handoffs/2026-10-18-dot-lead-sprint.md)。目标明早候选版、24 小时内一次 v1 验收，不承诺未经实测的完整兼容性。
- 仓库已公开。当前 main 尚未合入业务代码；C0/L0 在 [PR #13](https://github.com/Maximora-byte/swu-happyrun/pull/13)，HEAD `3ff0a33a01c629432a2036f4e105bed52157bd9e`，109 tests 和四组 CI 已通过，但 Dot 报告的 verify_only 恢复路径问题仍是阻塞。
- Dot 已在 [Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 回报真实仓库/Python 能力，并提交 [PR #12](https://github.com/Maximora-byte/swu-happyrun/pull/12) 的 50 条待实现服务器测试设计；这不是 S0 产品实现。
- Dot 现在负责接管 C0 修复与 [C1 #14](https://github.com/Maximora-byte/swu-happyrun/issues/14)，随后实现 S0-S2、L1-L3 和 CLI；本地不再负责主要产品编码。新角色覆盖原 Issue/计划中的旧负责人。
- 本地 MuMu 6.8.4.0 / Android 15.0 实例查询通过，实例停止，ADB 无设备；定位/传感器、应用、vivo 与学校有效记录未验证。
- 本轮冲刺消息的实际送达与接单回执以 Matrix / Issue 为证；不能由这份计划的存在推断 Dot 已开始夜间任务。

### 初次建仓快照（历史记录）

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

### 初次任务清单（历史负责人）

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
