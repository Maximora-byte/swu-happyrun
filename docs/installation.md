# 安装与启动候选版本

先取得经审核的候选 commit SHA，在独立目录检出该提交。不要把 main、PR 最新页面或旧测试结果当作候选版本的证据。Python 3.11+；开发检查使用仓库锁定依赖。Python/uv 从其官方渠道安装；不需要 Root、LSPosed、APK 或系统安全设置修改。

## 从旧候选替换安装

本轮包版本仍为 `0.1.0`，版本号本身不能区分旧候选。优先新建独立虚拟环境，安装对应已审核 HEAD 的确切 wheel；若复用环境，必须显式强制重装该文件，例如 `python -m pip install --force-reinstall './dist/swu_happyrun-0.1.0-py3-none-any.whl[server,agent]'`，并使用该虚拟环境的 Python。按实际组件选择 extras。

安装前核对准确 push HEAD 和该 artifact 的 SHA256SUMS（[校验步骤](delivery-validation.md#ci-候选安装包)）。安装后在源码目录外运行 `python -I -c "import swu_happyrun; print(swu_happyrun.__file__)"`，确认路径属于目标环境的 site-packages，再执行 smoke。`already installed` 或只看到 `0.1.0` 不能证明旧包已被替换；不要混用 PR 临时 merge SHA 的 artifact 与准确 push HEAD。

## 本地控制台入口

只运行控制台/服务器使用 `uv sync --extra server --frozen`；不需要Playwright或Chromium测试包。普通开发/软件自检使用下方显式server/agent/dev组合；仅执行浏览器QA时额外添加 `--extra browser-test`。

按照[服务器配置](server.md)设置本地服务与ADMIN凭据后，访问 `http://127.0.0.1:8080/console/`（使用实际端口）。可在原server命令加 `--open-browser`，例如 `swu-happyrun server --host 127.0.0.1 --port 8080 --database ./local/server.sqlite3 --open-browser`；请先确认目录可写。

此选项是显式选择，默认仍不打开浏览器；只允许loopback地址，且成功监听后才尝试打开。浏览器不可用时手动打开URL即可，服务不因此失败；它不启动agent或设备任务。ADMIN凭据仅输入本地页面，不放URL。操作与隐私边界见[控制台说明](console.md)。真实设备后端仍按现有unsupported/needs_samples限制处理。

## Windows PowerShell

以下操作在仓库根目录运行；不需要修改 PowerShell execution policy 或激活脚本。

```powershell
py -3.11 --version
uv --version
uv sync --extra server --extra agent --extra dev --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
uv run --no-sync python scripts/check_install.py
uv run --no-sync python -m swu_happyrun --help
uv run --no-sync python -m swu_happyrun doctor --json
```

`doctor` 只能给出实际探测结果，实例停止/ADB 无连接不是设备能力通过。指定实例的旧模块入口仍可单独检查：

```powershell
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

索引 0 仅在本地确认其为指定测试实例后使用，不要选择其他人的实例。诊断退出码 2 表示存在待处理条件，保留 JSON 里的原因。

## Windows fake 启动验收

依赖与所有组件集成后，在同一 PowerShell 运行：

```powershell
uv run --no-sync python deploy/smoke_fake.py
```

脚本启动仅回环可见的临时服务，自动创建合成配置与独立测试凭证，启动一次 fake agent，再重启服务验证同一任务。输出 `status=passed` 才表示本次 smoke 通过；其他退出码与结果保留用于排查。实际 Windows 验证状态见交付记录，不能预先视为通过。真实代理的 `--agent-id`、`--device-id`、`--profiles`、`--journal` 必须指向管理员注册的身份及本地私有数据，不复用 smoke 的临时资料。

## Linux

```sh
python3 --version
uv --version
uv sync --extra server --extra agent --extra dev --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
uv run --no-sync python scripts/check_install.py
```

仅服务运行依赖可用 `uv sync --frozen --extra server` 安装；开发测试使用 `--extra server --extra agent --extra dev`。代理需要 `--extra agent`；服务端不需要 MuMu/ADB 或 Windows 依赖。CLI 及模块命令是否已集成、具体执行证据以 [交付验证记录](delivery-validation.md) 为准。

## 运行与私有状态

- 服务启动见 [server.md](server.md)；fake 联调见 [fake-e2e.md](fake-e2e.md)。
- 数据库、代理 journal、配置、账号会话和诊断原始数据应放在仓库之外的私有目录，不能随源码打包。
- 服务器 ADMIN 与代理 AGENT 使用不同 token；代理身份必须与服务映射中的 UUID 完全一致。不要把 token 放在命令行参数、截图、终端共享记录、Git 或问题描述中。
- 真实设备运行需要明确能力、配置和版本样本；当前 fake 命令不提供设备执行授权或有效记录证明。
