# Matrix ChatGPT Dot 接手说明

用户要求本地 Codex 与 Matrix 群中的真实 ChatGPT Dot 同步开发本项目，服务器端同步推进。GitHub 仓库是代码与任务事实源，群消息用于通知。

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
