# SWU HappyRun 双端开发总计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. 用户已选择本地 Codex 与 Matrix 群 ChatGPT Dot 协作，保持这一执行方式。

**Goal:** 交付可独立测试的服务器、Windows 执行代理，并用真实设备证据逐步建立西大步道乐跑兼容性。

**Architecture:** 共享模型定义任务与消息，服务器调度，代理主动领取并控制设备。模拟执行验证协议，真实设备与最终记录另行验收。

**Tech Stack:** Python 3.11+、Pydantic v2、FastAPI/Uvicorn、SQLite、HTTPX、pytest；Windows/MuMu 与 Linux 服务器。

**Spec:** [设计说明](../specs/2026-10-18-swu-happyrun-design.md)、[评估结论](../../design-review.md)、[控制协议 v1](../../contracts/control-plane-v1.md)。

## Global Constraints

- 包名 `swu_happyrun`，CLI `swu-happyrun`，API `/api/v1`，协议主版本 `1`。
- Python 3.11+；HTTP 超时 5 秒，心跳 10 秒，租约 30 秒；UTC 存储，Asia/Shanghai 日程。
- 初版 SQLite 单进程、单调度器；服务器与 Windows 依赖分离。
- `needs_attention` 可恢复；simulation 只能 completed，实际记录核验才可 succeeded。
- 不编造学校、规则、点位、接口与验收结果；本地数据不入 Git。

## Review Focus

1. 代理在开始动作之后崩溃：L2/S1 必须证明恢复不重复开始。
2. 两代理争抢同一设备：S1 必须证明只发出一个有效租约。
3. 网络丢失取消回执：L2/S1 必须保留 stop_unconfirmed，不宣称已停止。
4. Android 15 坐标含义不同于参考项目：L0/L1 必须拒绝未经校准的通道。
5. 模拟服务返回“成功”：C0/I0 必须拒绝将其提升为真实记录验收。

## 分工与并行路径

| 阶段 | 本地 Codex | 云端 Dot | 交接条件 |
| --- | --- | --- | --- |
| 启动评审 | 修订设计、契约、建仓库与 Issues | 核对仓库访问和契约，反馈服务端缺口 | 两端确认相同基线 SHA |
| C0 / L0 | 共享模型与工具链；只读设备探测 | S0 的用例设计、API/存储结构评审 | C0 合并后固定模型与依赖锁 |
| L1 / S0 | 驱动和模拟执行器 | 可运行 API、认证和 SQLite | 双方通过同一 contracts 测试 |
| L2 / S1 / S2 | 代理日志、取消、恢复、CLI | 租约、幂等、调度、部署 | 模拟代理真实 HTTP 联调 |
| L3 / I0 | 步道乐跑版本适配与设备证据 | 故障注入、结果校验、修复服务端问题 | 指定版本完整流程验收 |
| R0 | vivo 无 Root 和纯接口证据采集 | 基于已取得的协议样本评估接口执行器 | 独立报告可行性，不阻塞已完成模块 |

依赖图：`C0 -> {S0 -> S1 -> S2, L1 -> L2}`；`L0 -> L1`；`{S2,L2}->I0`；`{L0,L1,L2,真实学校/应用信息}->L3`。L0 和服务器准备工作可同步推进。

详见 [服务器计划](2026-10-18-server.md) 与 [执行端计划](2026-10-18-agent.md)。每个任务对应一个小范围 PR；不把所有工作累计在一个长期分支。

## Task C0：共享模型与可重复开发环境（本地 Codex）

**Files:** 创建 `pyproject.toml`、`uv.lock`、`src/swu_happyrun/__init__.py`、`src/swu_happyrun/core/{models,states,clock}.py`、`contracts/protocol-v1.schema.json`、`tests/contracts/{test_models,test_states}.py`、`scripts/export_schema.py`、`.github/workflows/checks.yml`。

**Interfaces:** 输出契约中的所有 Pydantic 模型；`transition_allowed(current: JobState, target: JobState, mode: str) -> bool`；`Clock.utcnow() -> datetime`、`Clock.monotonic() -> float`。`JobSpec` 按协议字段定义，不在服务器另建副本。

- [ ] 写失败用例：`test_rejects_naive_time`、`test_rejects_unknown_fields`、`test_simulation_cannot_succeed`；断言 `transition_allowed(JobState.VERIFYING, JobState.SUCCEEDED, 'simulation') is False`。
- [ ] 执行 `python -m pytest tests/contracts -q`，确认因缺少模型失败。
- [ ] 实现模型、状态表与时钟接口，导出 JSON Schema；固定配置 JSON 规范化与 revision 哈希算法，提供一致性测试向量。Pydantic 为核心依赖；定义 `[server]`（FastAPI/Uvicorn）、`[agent]`（HTTPX）、`[dev]`（pytest/ruff/build/HTTPX）可选依赖；提交 uv.lock，用 `uv sync --all-extras --frozen` 重建环境。CI 包含 3.11/3.13 和两个系统的共享模型检查。
- [ ] 执行 `python -m pytest tests/contracts -q`、`python scripts/export_schema.py --check`，预期全部通过且导出文件无漂移；安装包后验证导入。
- [ ] 提交 `feat: establish shared protocol models`，PR 由 Dot 核对接口，记录合并 SHA 后双方从该基线开发。

## Task I0：双端联调与发布候选（本地 Codex 主持，Dot 修复服务器）

**Files:** 创建 `tests/integration/test_control_loop.py`、`tests/integration/test_recovery.py`、`docs/acceptance.md`；更新 `README.md`、`docs/status.md`。

**Interfaces:** 消费 `server.app.create_app`、`agent.runner.AgentRunner`、共享模型、假设备和 fake clock；输出可重复运行的联调命令与逐项验收记录。

- [ ] 写失败用例 `test_full_simulation_finishes_completed`：创建任务到 completed、无 app_record；`test_crash_after_start_never_starts_twice`：设备 start 调用计数仍为 1；`test_cancel_while_offline_not_cancelled`：状态 needs_attention。
- [ ] 执行 `python -m pytest tests/integration -q`，确认实际暴露协议接合问题，不能通过跳过断言获得绿灯。
- [ ] 联接真实本机 HTTP 服务器与 fake 代理，补齐双方契约差异；共享契约变更走独立 PR。对 device 任务使用记录样本测试结构，对实时有效性保留未验证状态。
- [ ] 执行全套 `python -m pytest -q`、schema 检查、构建和 Windows/Linux 安装检查；设备流程另记录版本、证据摘要、时间和结果。
- [ ] 提交 `test: verify server agent recovery loop`。发布说明列出实际通过的矩阵和未通过路径，不使用无范围的“完整兼容”。

## Task R0：vivo 与纯接口可行性（证据驱动的独立工作）

**Files:** 创建 `docs/research/vivo-noroot.md`、`docs/research/direct-protocol.md`；仅在真实证据存在后新增对应驱动与测试。

**Interfaces:** 输入用户设备实际版本、权限和本人会话下的脱敏协议样本；输出明确的 supported / unsupported / not_tested 能力表、来源与复现步骤。

- [ ] 记录设备/应用版本和测试条件；没有样本时把缺失输入列为待采集事实。
- [ ] 验证每个候选路径的最小能力，并记录实际错误；不运行来源未知的二进制。
- [ ] 若可以实现，另写有具体契约和测试的驱动计划；若不可行，保留证据和可用的功能范围。
- [ ] 提交研究报告，独立评审；不将失败路径包装成已支持。

## GitHub 与 Matrix 协作规则

- 分支：`codex/contracts-v1`、`codex/mumu-probe`、`codex/agent-runtime`、`dot/server-api`、`dot/server-leases`、`dot/server-scheduler`。
- 每个 Issue 声明负责人、前置任务、文件边界、输入契约、验收命令和阻塞项。PR 引用 Issue，报告不可变 HEAD。
- Matrix 只发送可读任务摘要、Issue/PR 链接和 SHA；不传登录信息、原始定位数据和设备截图。
- 本地 Codex 审核合并与集成；Dot 交叉检查共享协议和服务端测试。未经验证的工作不合并到已验收清单。
- 云端无法读取私有仓库、创建分支或运行测试时，报告具体缺失能力；不以“接到通知”代替已开发。生产部署需要明确目标主机后另行安排。

## 首版完成定义

服务器能在 Linux 独立运行并与 Windows 代理完成创建、领取、续租、取消、恢复和模拟结果查询；MuMu 能力与真实乐跑记录按独立矩阵验收。CLI、部署文件和故障处理文档齐全。所有未具备条件的路径明确标注，不能用占位实现返回成功。
