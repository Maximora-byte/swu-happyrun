# SWU HappyRun

西南大学步道乐跑适配项目，规划 Windows/MuMu 执行代理、服务器调度和 vivo 无 Root 兼容性验证。

**当前开发与验收入口：[协作状态](docs/status.md)。** 该页按日期和准确提交记录已合入内容、产品候选、独立验收与剩余阻塞；采用候选前仍须核对实际 HEAD 和对应回执。

当前分工：**Dot 主导全部主要开发，本地 Codex 负责实测与集成验收。** [2026-10-18 冲刺交接](docs/handoffs/2026-10-18-dot-lead-sprint.md)保留为历史背景；原始计划中的旧负责人列由上述分工覆盖。

- **main 已有实现：** C0/C1 共享契约与核心模型、状态逻辑，以及 L0 MuMu/ADB 只读诊断和对应测试；C0/L0 与 C1 已合入 main。
- **产品候选待集成：** 服务器、执行代理、统一 CLI、网页与 Android 产品实现已有候选及分项验收记录，尚未合入 main。软件测试和候选构建通过不等于完整产品已交付。
- **设备与学校验收未完成：** 已有的安装、只读观察和合成流程证据各有范围，不能据此认定真实 MuMu 执行、vivo 无 Root 兼容或学校最终有效记录已通过；尚未验证任何步道乐跑版本的完整兼容性。

## 本地开发与探测

```powershell
uv sync --all-extras --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

诊断退出码 2 表示需要处理环境条件，例如实例未启动或设备未连接。该命令只读取信息，详细行为与本机证据见[兼容性记录](docs/compatibility.md)。main 尚无统一 CLI 入口；L2 候选的进度与验收范围见[协作状态](docs/status.md)。

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
| 服务 API、数据库、租约、调度、容器配置 | Dot 开发，本地 Codex 独立验收 | `src/swu_happyrun/server/`、`tests/server/`、`deploy/` |

以上是组件责任边界，不表示所有目录都已进入 main。main 已包含 `contracts/`、`core/`、`drivers/` 及对应测试；`agent/`、`server/`、`tests/server/` 和 `deploy/` 属于尚待集成的产品候选范围。双方使用独立分支和 PR，GitHub Issue/PR 与[协作状态](docs/status.md)记录进度。消息发送、代码提交、软件测试、设备验收和学校记录验收分别记录，不以早期交接包或通知状态判断开发是否启动。

## 兼容性与数据

已知用户环境为无 Root 的 vivo X200 Pro，以及 Windows 上的 MuMu 6.8.4.0 / Android 15 实例。状态页已记录部分地图输入、步道乐跑 4.3.1(231) 的安装与登录前观察；正式学校规则、本人业务页面/记录及真实适配验收仍有缺口，详见[协作状态](docs/status.md)。

服务器方案由在线设备代理执行任务，相关产品实现仍在候选中；无设备的纯接口执行单独研究。模拟器轨迹完成、上传提示和最终有效记录使用不同的验收证据。仓库不提供虚构的学校 ID、打卡点或“100% 成功”承诺。

账号会话、设备截图、原始轨迹和数据库放在被 Git 忽略的本地目录。参考项目及其复用边界见 [第三方来源](THIRD_PARTY_NOTICES.md)。
