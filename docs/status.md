# 协作状态

更新日期：2026-10-18（Asia/Shanghai）。此文件记录证据，不由收到消息或计划勾选自动推断完成。

| 项目 | 当前状态 | 证据/下一步 |
| --- | --- | --- |
| 初版设计 | 已提交 | `687d0be` |
| 设计评估、v1 契约与双端计划 | 已发布，待 Dot 交叉评审 | [设计基线 015447d](https://github.com/Maximora-byte/swu-happyrun/commit/015447dc97637311874dda061cb5fe48babb21f5) |
| GitHub 仓库 | 已创建并推送 | [Maximora-byte/swu-happyrun](https://github.com/Maximora-byte/swu-happyrun)，私有，默认分支 main |
| Matrix Dot 入口 | 已识别，待可用登录会话 | 群名 `Matrix · ChatGPT Dot`；独立连接器没有主动发新消息的接口 |
| Dot 接单与仓库访问 | 未确认，云端开发未启动 | [交接 Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 与[待发送说明](handoffs/dot-server.md)已准备 |
| 服务器实现 | 未开始 | S0-S2 |
| 本地 C0 / L0 | 已实现，待 PR 评审 | 模型、状态表、时钟、配置哈希、Schema、锁文件、CI、只读探测及测试 |
| 本地 L1-L3 | 未开始 | 等待 C0/L0 评审和设备/应用输入 |
| MuMu Android 15 兼容 | 主机探测通过，设备能力未验证 | [本机只读证据](compatibility.md)；实例停止，ADB 无连接 |
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

本轮实现 C0/L0；Windows Python 3.11/3.13 自动测试、Schema 检查、构建与独立安装检查在 PR 中记录实际 HEAD 和结果。GitHub Actions 未运行或失败时单独记录，不代替本地证据。没有产生定位写入、应用流程或有效记录的验收结论。
