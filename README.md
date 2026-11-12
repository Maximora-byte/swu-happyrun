# SWU HappyRun

西南大学步道乐跑适配项目，规划 Windows/MuMu 执行代理、服务器调度和 vivo 无 Root 兼容性验证。

最新分工（2026-10-18）：**Dot 主导全部主要开发，本地 Codex 负责实测与集成验收。** 当前实施入口为[今晚至次日的冲刺任务](docs/handoffs/2026-10-18-dot-lead-sprint.md)；下列原始计划的旧负责人列由该分工覆盖。

**当前分支继承 C0 共享协议库与 L0 只读诊断，并修复恢复结构边，待评审合并。服务器及执行代理尚未实现；未验证任何步道乐跑版本的完整兼容性。**

## 本地开发与探测

```powershell
uv sync --all-extras --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

诊断退出码 2 表示需要处理环境条件，例如实例未启动或设备未连接。该命令只读取信息，详细行为与本机证据见[兼容性记录](docs/compatibility.md)。统一 CLI 在 L2 交付。

## 开发入口

- [文档导航 / Documentation index](docs/README.md)：按使用、设计、验收和历史记录查找。
- [分支与 PR 地图 / Branch and PR map](docs/repository-map.md)：区分 main、候选和堆叠变更。

**分支区别 / Branch distinction：** 本页的主分支限制不代表所有候选都未实测。`dot/trusted-runtime-context` 已收录 [RC3 桌面与 MuMu 实测回执](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/qa/2026-10-23-rc3-delivery.md)和[使用说明](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/desktop.md)；报告对应固定产品源码，较新分支 HEAD 的修改不能直接沿用旧实测结论。学校小程序轨迹、上传与有效记录仍未验收。Local desktop/MuMu evidence exists on a separate candidate; it is version-specific and does not establish school-record acceptance.

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
