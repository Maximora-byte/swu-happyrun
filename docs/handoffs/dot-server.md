# Matrix ChatGPT Dot 接手说明

用户要求本地 Codex 与 Matrix 群中的真实 ChatGPT Dot 同步开发本项目，服务器端同步推进。GitHub 仓库是代码与任务事实源，群消息用于通知。

**交接状态：已准备，未发送。** 用户本次选择先准备交接任务，Dot 尚未接单、未确认仓库能力、未启动云端开发。

- 私有仓库：[Maximora-byte/swu-happyrun](https://github.com/Maximora-byte/swu-happyrun)
- 启动任务：[Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1)
- 设计基线：`015447dc97637311874dda061cb5fe48babb21f5`；实施前读取最新 main，代码共同基线以后续 C0 合并 SHA 为准。
- 服务器任务：[S0 #4](https://github.com/Maximora-byte/swu-happyrun/issues/4) → [S1 #5](https://github.com/Maximora-byte/swu-happyrun/issues/5) → [S2 #6](https://github.com/Maximora-byte/swu-happyrun/issues/6)

## 先完成的接入检查

1. 通过你自己的 GitHub 连接读取 `Maximora-byte/swu-happyrun`，核对默认分支与基线 SHA。
2. 阅读 `AGENTS.md`、`docs/design-review.md`、总计划、服务器计划和控制协议 v1。
3. 在服务器启动 Issue 回报：是否能读取私有仓库、创建分支/PR、实际执行 Python 测试；逐项报告，不用平台名称推断权限。
4. 对 v1 契约做一次评审，重点检查 lease/fence、恢复、取消、日程和证据边界；有问题先在 Issue 留意见或提交范围明确的文档 PR。

## 实施责任

你负责 S0、S1、S2；本地 Codex 负责 C0、L0-L3、I0。共享模型 C0 合并前可准备测试用例和服务端结构评审，不自行复制另一套模型。进入各阶段前以 GitHub Issue 中的 ready/blocked 状态为准。

请使用 `dot/server-*` 独立分支，保持每个 PR 可独立测试。实现计划位于 `docs/superpowers/plans/2026-10-18-server.md`。每个 PR 回报基线、HEAD、测试命令和实际结果；没有运行测试就写未运行。不要直接推送 main，不修改生产服务器、DNS 或账号配置。

若无法写 GitHub 或执行测试，请明确返回缺失能力与可提供的产出，不改用 OpenClaw/Hermes 代替自己，不把“任务已发送”写成“开发已完成”。

## 消息回报

接入结果与评审结论 → Issue URL；实现进度 → PR URL / HEAD；需要共享契约调整 → 原字段、建议字段、受影响测试；阻塞 → 可复现错误与具体需要的输入。

## 可直接发送到 Matrix 的启动消息

以下是待发送文本，保存此文件不代表消息已发送或任务已启动。

> Dot，请与本地 Codex 协作开发西南大学步道乐跑适配项目，你负责服务器 S0-S2。本地 Codex 负责共享模型、Windows/MuMu 代理和最终集成。
>
> 私有仓库：https://github.com/Maximora-byte/swu-happyrun
>
> 请先处理交接任务 https://github.com/Maximora-byte/swu-happyrun/issues/1 ，分别确认你能否读取仓库、创建分支/PR、实际运行 Python 测试，再评审 AGENTS.md、设计评估、控制协议 v1 和服务器实施计划。设计基线为 015447dc97637311874dda061cb5fe48babb21f5，实施前以最新 main 和 C0 合并 SHA 为准。
>
> C0 #2 合并前先准备服务端测试用例和结构评审，不创建另一套共享模型。之后按 #4 → #5 → #6 依赖推进，每个阶段使用 dot/server-* 独立分支与 PR，附实际 HEAD、测试命令、结果和未验证范围。共享协议、依赖锁或 CI 的修改先在 Issue 协调。
>
> 初版服务器使用模拟代理验证 API、租约、取消、恢复和日程；MuMu/vivo 兼容性与学校有效记录另行实测。不要直接推送 main 或改动生产服务器。若缺少仓库写入或执行能力，请说明具体缺失项和可以交付的内容，不把收到通知视为实现完成。
>
> 请把接入与协议评审结论记录在 #1，并在群里回复对应 Issue/PR 链接。完整交接说明：https://github.com/Maximora-byte/swu-happyrun/blob/main/docs/handoffs/dot-server.md
