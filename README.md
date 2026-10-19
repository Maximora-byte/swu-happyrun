# SWU HappyRun

已交付原生 APK 的首阶段构建来自 [PR #35](https://github.com/Maximora-byte/swu-happyrun/pull/35) 的 `28871b2d599a8ec8335570effb3207d2564639ab`：本地模式无需 PC 服务；远程模式由用户显式连接可信 HTTPS 服务，一次连接最多领取一个合成模拟任务。官方 API31/35 的准确 push 验收已通过，范围与未解决问题见[当前状态](docs/status.md)和[APK 安装边界](docs/android-apk.md)。本轮按 [七任务计划](docs/superpowers/plans/2026-10-19-next-stage.md) 纳入最新 main QA、PR39/40 修复、持续前台多任务与原生持久完成恢复。新增 Android 验收待同 HEAD CI；精确结果与阻塞见[统一候选验收记录](docs/acceptance.md)，MuMu完整闭环/学校记录不在已通过范围。

西南大学步道乐跑适配项目：共享控制协议、Python 调度服务器、可恢复执行代理和可替换设备驱动。

**当前交付是软件候选，不是学校有效记录或真实设备兼容性验收。** MuMu Android 15、vivo 无 Root、具体乐跑版本与纯业务接口仍需本地证据；未知规则、点位、应用页面和能力安全拒绝执行。fake `completed` 不表示真实记录 `succeeded`。

## 本轮实现与版本选择

Dot 负责主要实现、测试、依赖与交付；本地 Codex 负责 Windows、真实设备与集成独立验收。本轮通过 GitHub Issue/PR 交付代码、不可变 HEAD 和验证结果；不把消息通知或计划勾选当作完成证据。

实现分支已提供共享模型/Schema、恢复与证据约束、API/SQLite、租约与设备归属、日程、profile 校验、fake driver、agent journal 和 CLI。各组件进度、已发布 PR/阶段 HEAD 与验证层次见 [当前状态](docs/status.md)。旧设计中的负责人列由 [Dot 主导冲刺说明](docs/handoffs/2026-10-18-dot-lead-sprint.md) 覆盖。

**安装时选择集成候选 PR 正文及对应 Actions `github.sha` 指定的完整提交。** 单独的堆叠 PR 只包含其自身与父分支范围：部署文档 PR 基于服务器分支时，并不独自包含 L1/L2；下述 CLI/fake 命令必须在同时集成服务器、驱动与代理的候选上运行。不要混用多个分支的最新文件代替固定候选。

## 本地管理控制台

服务器内置同源管理页面：启动后打开 `http://127.0.0.1:8080/console/`，或显式使用 `server --open-browser`。此选项仅在loopback绑定且成功监听后尝试打开浏览器，默认不打开，也不会启动执行代理。控制台不改变真实设备和学校记录的验收限制。

见[安装与启动](docs/installation.md)、[控制台操作](docs/console.md)、[API与安全范围](docs/console-api.md)。真实Chromium交互/截图验收以对应提交的独立CI结果为准；页面和API检查不能替代浏览器验收。

## 安装和软件自检

Python 3.11+；以下从完整候选仓库根目录执行，Windows PowerShell 与 Linux 均可使用：

```sh
uv sync --extra server --extra agent --extra dev --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
uv run --no-sync python scripts/check_install.py
uv run --no-sync python -m swu_happyrun --help
uv run --no-sync python deploy/smoke_fake.py
```

smoke 启动临时回环服务器，通过实际 HTTP 注册 fake 设备、创建并重放任务、运行 CLI 代理、查询 `completed`，再重启同一数据库确认持久化；同时检查 `/health` 和 `/ready`。只有本次命令成功才算本次 smoke 通过。完整故障矩阵和未运行范围见 [交付验证记录](docs/delivery-validation.md) 与 [50 项验收设计覆盖](docs/acceptance-coverage.md)。

- [Windows/Linux 安装与运行](docs/installation.md)
- [Linux Docker/Compose、非 root 与持久化](docs/server.md)
- [fake 联调、取消、断线与恢复](docs/fake-e2e.md)
- [本地验收与最小输入清单](docs/local-qa.md)
- [vivo 无 Root 证据与后续路径](docs/research/vivo-noroot.md)
- [纯接口证据与后续路径](docs/research/direct-protocol.md)

核心、服务器、代理依赖分别安装；server extra 不依赖 Windows/MuMu。Python CI 候选 artifact 仅包含 wheel、sdist 和 SHA256SUMS；Android 另交普通 APK、匹配 instrumentation APK、签名及合成测试白名单证据。实际下载是否可用以对应提交的 Actions 结果为准。未创建 Release。

## CLI 与只读诊断

集成候选支持 `doctor`、`profiles check`、`route check`、`server`、`agent`、`devices`、`jobs` 和 `schedules`；使用各命令 `--help` 查看参数。已安装入口为 `swu-happyrun`，等价模块入口为 `python -m swu_happyrun`。

```sh
uv run --no-sync python -m swu_happyrun doctor --json
```

只读探测旧模块入口仍可使用：

```sh
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

必须先确认实例 0 是用户指定的测试实例。诊断退出码 2 表示有待处理条件，例如实例停止或 ADB 无连接，不能当作设备执行通过。当前真实设备 CLI 后端在缺少已验证应用适配器时返回 `adapter_not_verified`。

## 安全与证据边界

- ADMIN 与各 AGENT 使用独立 token；身份由管理员注册，不能靠代理自行声明所有权。
- 先持久化意图，再执行设备动作；租约丢失、上传不明或停止未确认时不自动开始第二次运行。
- 真实学校规则、路线、点位和应用选择器来自实际输入，不猜测、不套用他校协议。
- 账号、token、截图、路线、数据库和 journal 放私有目录，不提交 Git 或群消息。
- 无 Root vivo 路径不自动安装 Root/LSPosed，不关闭 TLS 或系统保护。
- 本交付不修改生产服务器、DNS、账号或安全设置；容器文件存在不等于已完成部署。

## 设计与协议

- [控制协议 v1](docs/contracts/control-plane-v1.md)
- [完整设计](docs/superpowers/specs/2026-10-18-swu-happyrun-design.md)
- [设计评估](docs/design-review.md)
- [开发总计划](docs/superpowers/plans/2026-10-18-development.md)
- [服务器计划](docs/superpowers/plans/2026-10-18-server.md)
- [执行端计划](docs/superpowers/plans/2026-10-18-agent.md)
- [兼容性历史证据](docs/compatibility.md)
- [第三方来源与许可](THIRD_PARTY_NOTICES.md)

计划是实现目标；最终状态及测试证据以当前 PR、状态页与对应不可变提交的检查结果为准。
