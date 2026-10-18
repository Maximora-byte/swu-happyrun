# 交付验证记录

日期：2026-10-18。此文件仅记录本交付包验证，整体候选与远端 CI 状态由集成 PR 正文及 Actions `github.sha` 绑定不可变 HEAD（本文不嵌入自身提交 SHA）。尚未绑定完整集成 HEAD 时不能称为发布验收通过。

## 已执行

- Linux / Python 3.12，交付静态与 synthetic fixture 测试：7 passed。测试先因缺失交付文件/fixture 失败，再通过；不是 Docker 构建证据。
- `ruff check` 与 `ruff format --check` 使用仓库 pyproject 配置检查 `deploy/`、`tests/delivery/`：通过。
- 本环境 `which docker` 无结果：没有可执行的 Docker CLI。

准备阶段测试使用 C1 模型校验 synthetic fixture 与 revision；L1 profile 解析和 L2 CLI 执行属于 I0 smoke。所有结果必须在最终集成提交上重跑，不能替代整个候选测试。

S2 `561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9` 的代码/测试与本交付文件组合：完整 `pytest -q` **259 passed**，一条继承的 Starlette/httpx 弃用 warning；ruff、format（75 files）、Schema 漂移检查均通过。服务源代码/测试与远端 S2 blob 核对一致。此组合不含 L1/L2，不能据此宣称 CLI/HTTP smoke 通过。

## 待完整集成后执行

```sh
uv sync --all-extras --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
uv run --no-sync python scripts/check_install.py
uv run --no-sync python deploy/smoke_fake.py
```

`smoke_fake.py` 是自包含交付脚本：临时回环 TCP 服务、health/ready 校验（含重启后）、内存生成测试凭证、synthetic profiles、注册设备归属、任务创建/幂等、fake CLI agent、最终查询、停止服务再启动后查询相同任务。数据放临时目录并在结束清理，输出不包含 token。该脚本成功也不证明完整故障矩阵或设备有效记录。

## 未运行 / 不据此宣称通过

- 最终候选上的实际 HTTP smoke、完整 pytest、冻结安装、build 与独立安装：待集成。
- Docker Compose config/build/up、非 root 卷写入与重启持久化：`not_tested`，Docker 不可用；纯文本检查不能代替。
- Windows 3.11/3.13 安装和 CLI：`not_tested`，交给独立本地验收与对应 CI。
- MuMu Android 15、vivo 无 Root、实际 app 流程、学校最终记录：`not_tested`。
- 当前西大直接业务接口：`unsupported_by_this_candidate`；协议输入尚缺。
- Hosted CI：须单列最终提交对应的实际结果，不从本地检查推断。

## CI 候选安装包

工作流在现有构建与独立安装检查成功后，仅 Ubuntu / Python 3.11 job 生成 `dist/SHA256SUMS` 并上传 `candidate-<完整提交 SHA>` artifact，保留 7 天。仅包含 wheel、sdist 和校验文件；不包含环境、数据库、路线或账号资料。上传步骤固定官方 `actions/upload-artifact` v4 提交 SHA。

这是 CI 配置的预期行为，尚未据此宣称已经产生可下载包。发布/评审时须核查该不可变 HEAD 的实际 Actions run 和 artifact，下载后验证 SHA256；不创建 GitHub Release。

校验文件中的路径以仓库根目录为基准，形如 `dist/<文件名>`。下载 artifact 后将其内容放进独立验收目录的 `dist/`，从该目录运行 `sha256sum -c dist/SHA256SUMS`；Windows 可逐项用 `Get-FileHash -Algorithm SHA256` 对比。不要把路径布局差异当作哈希验证已通过。
