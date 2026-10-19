# 交付验证记录

日期：2026-10-18。此文件仅记录本交付包验证，整体候选与远端 CI 状态由集成 PR 正文及 Actions `github.sha` 绑定不可变 HEAD（本文不嵌入自身提交 SHA）。尚未绑定完整集成 HEAD 时不能称为发布验收通过。

## 已执行

- Linux / Python 3.12，交付静态与 synthetic fixture 测试：7 passed。测试先因缺失交付文件/fixture 失败，再通过；不是 Docker 构建证据。
- `ruff check` 与 `ruff format --check` 使用仓库 pyproject 配置检查 `deploy/`、`tests/delivery/`：通过。
- 本环境 `which docker` 无结果：没有可执行的 Docker CLI。

准备阶段测试使用 C1 模型校验 synthetic fixture 与 revision；L1 profile 解析和 L2 CLI 执行属于 I0 smoke。所有结果必须在最终集成提交上重跑，不能替代整个候选测试。

S2 `561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9` 的代码/测试与本交付文件组合：完整 `pytest -q` **259 passed**，一条继承的 Starlette/httpx 弃用 warning；ruff、format（75 files）、Schema 漂移检查均通过。服务源代码/测试与远端 S2 blob 核对一致。此组合不含 L1/L2，不能据此宣称 CLI/HTTP smoke 通过。

## 集成验证可复现命令

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

- 最终远端提交的 Hosted CI 与 artifact 下载核验：由该提交的实际 Actions 结果确认；不能由本地结果推断。
- Docker Compose config/build/up、非 root 卷写入与重启持久化：`not_tested`，Docker 不可用；纯文本检查不能代替。
- Windows 3.11/3.13 安装和 CLI：`not_tested`，交给独立本地验收与对应 CI。
- MuMu Android 15、vivo 无 Root、实际 app 流程、学校最终记录：`not_tested`。
- 当前西大直接业务接口：`unsupported_by_this_candidate`；协议输入尚缺。
- Hosted CI：须单列最终提交对应的实际结果，不从本地检查推断。


## 历史 I0 基线验证（PR #25 原 HEAD 19c15ba7）

最终组合包含 L2 `e935632079c805952e7b143e5438c7d829b34f22`、S2 `561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9`、C1 `a82e4d97a5a7e1de5112eabeecac6e97312089a7` 与交付基线 `cc81d124e4feab978ae60a694ae06391cb6cb728`。公共文件差异逐项核对；唯一产品整合是保留 S2 tzdata extra 与 L2 CLI entrypoint 的 pyproject 加法合并。集成提交自身 SHA 以 PR 正文/Actions github.sha 为准，不在文件内自引用。

- Linux x86_64 / Python 3.12.14：完整 `400 passed`；一条 Starlette TestClient/httpx 弃用提示，无测试失败。
- 冻结依赖安装、Schema漂移、ruff check/format与wheel/sdist构建通过。
- core/server/agent三个独立wheel环境依赖隔离与CLI入口通过；包与core.models路径均核对为site-packages。
- 安装后的wheel在源码外cwd、清空PYTHONPATH、Python -I、独立pytest配置并禁用pytest pythonpath：`31 passed`。实际uvicorn TCP/HTTPX覆盖并发领取、fence/事件重放、取消确认响应丢失、开始响应丢失、os._exit后durable intent、跨进程锁、恢复批准/再次失联、立即attention报告、日程自动tick/重启去重/过期不补跑。
- `deploy/smoke_fake.py` 在同一installed wheel通过：health/readiness、设备注册、创建/幂等、真实CLI fake完成、查询、服务子进程重启持久化与日志凭证扫描。
- 新增真实HTTP回归先在旧wheel失败，再在修复后验证：retry_preflight重新进入running后的异常立即报告正确phase；取消后stop失败立即报告needs_attention/stop_unconfirmed，不能停留旧状态等待expiry。

完整50项原始设计映射见 [acceptance coverage](acceptance-coverage.md)。这些是软件和合成故障证据；无真实设备/登录/上传/学校有效记录结论。Docker不可用，容器构建与卷重启仍未执行。最终wheel/sdist SHA256和完整archive成员检查随集成PR报告和CI artifact提供；不存在凭据、数据库、日志、虚拟环境或原始截图入包。

## 本轮控制台软件验证（2026-10-19）

准确继承 `585e1b0674022c8262109a7ea5e5720c0532eee9`，按冻结清单组合API9文件、UI6文件、浏览器CI4文件及QA脚本1文件。入口异步打开器修复纳入最终组合：只在loopback成功监听后启动daemon线程，阻塞浏览器opener不拖住服务请求或退出；测试使用阻塞fake opener，不打开真实浏览器。

- Linux x86_64/Python3.12.14：最终完整 **556 passed**（90.92秒），一条继承Starlette/httpx弃用提示。此前555项快照未含最终opener修复，仅作历史证据。
- 新构建wheel在源码外、Python-I/清PYTHONPATH/独立pytest配置：**34真实HTTP passed**、**7 daemon passed**；CLI fake smoke包括route_finished、同job查询与服务重启持久化通过。
- 新console安装包真实TCP检查通过：三asset响应逐字节等于wheel安装内容；no-store/CSP/nosniff/frame/referrer安全头、静态白名单、401/403权限、ADMIN两页无重复以及重启后cursor结果稳定。没有用TestClient替代这些TCP检查。
- Node语法与生产JS helper/DOM-fetch harness通过，包括输入/UTC+8真实日期边界、无效成功响应保留同幂等键/请求、明确拒绝后编辑、重试与放弃操作互斥。Node harness不等于真实浏览器。
- frozen全部extra依赖、Schema漂移、ruff check/format、wheel/sdist构建通过。core/server/agent独立wheel环境验证实际site-packages导入、CLI入口和依赖隔离；三者均无Playwright。browser-test单独锁定Playwright，官方Chromium安装仅在独立CI任务中执行。
- README/安装页提供本地console入口和显式--open-browser，默认不变、无agent启动。README包元数据更新后，最终wheel重新安装复验；最终SHA256与archive清单随发布证据提供。

本地没有启动Chromium，也没有绕过IPC隔离。真实交互、桌面/手机布局和截图结果以同一候选HEAD的Actions `console-browser-qa` 和PR记录为准；脚本存在、Node或HTTP通过都不能替代该结果。CI只上传合成截图和results.json，不包含临时数据库或账号凭据。既有设备、容器、真实登录/上传及学校有效记录限制保持不变。

## 本轮 CI 测试同步修正验证（2026-10-19）

基线 `4d73f42ec15e0c2cc14371f8a4441ef2101e6e41`；只更新 `tests/agent/test_daemon_process.py`、`tests/server/test_scheduler.py` 和两份结果文档。42个生产Python模块与构建配置逐字节不变。

- 历史 [run39179740749](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39179740749) 的Windows/Python3.13 active-renewal失败保留。独立诊断让父进程在child完成后才检查，旧active轮询确定性失败；此重现不能证明该次CI的唯一根因。新测试预先布置故障，在请求处理时观察持久化active并同步返回503，退出后验证start/stop计数、needs_attention与无renew重试。定向10次重复通过。
- 中间组合全套 **518 passed / 1 failed** 保留，失败是 readiness 测试直接改状态与后台tick竞争。新测试注入真实scheduler失败并通过队列屏障逐阶段验证成功、503脱敏和恢复；独立20个pytest进程重复通过。
- 最终完整 **519 passed**（84.96秒），一条继承Starlette/httpx warning。冻结依赖、Schema、lint/format通过。
- 同一已安装wheel，源码外本轮重跑 **7 daemon passed**（15.48秒）和 **15 scheduler passed**（2.84秒，含新的readiness回归）。子进程使用-I/清PYTHONPATH，生产模块导入site-packages；外部测试副本仅隔离启动路径，场景断言不变。
- wheel SHA256仍为 `288f97d6460f8693ff343e98bd96c2eb9d8cfb8757590cf0d50dcd135d572329`。前一轮34HTTP、9lifecycle、50边界、CLI smoke和三extras隔离按此相同字节复用，明确不是本轮重跑。sdist因测试/文档改变需使用本轮独立校验值。

最终Hosted CI须绑定新准确HEAD核查，不从本地通过推断；之前CI失败与本地中间红灯均留存。设备、容器和学校有效记录的未验证范围保持不变。

## 本轮信号重入修复验证（2026-10-19）

基于准确候选 `58264f22ba8829ec707f2d1a07617332f42ef48d`，仅产品 lifecycle.py 与对应回归测试变更，另更新两份结果文档。SIGTERM/SIGINT handler 原 Event.set 在 condition 锁内重入会死锁；改为无锁 signum 和单调时钟、最长50ms轮询。旧 wheel 的独立真实子进程回归3秒超时失败，新 wheel 同场景通过。

- Linux x86_64 / Python 3.12.14：**519 passed**（82.91秒），一条继承 Starlette/httpx warning。
- 源码外准确 wheel：**34真实HTTP**（43.42秒）、**7原daemon场景**（15.84秒）、**9 lifecycle场景**（0.77秒，含新真实信号重入回归）、**50额外边界检查**（0.63秒）通过。外部测试仅使用测试fixture代码；生产模块来自site-packages，禁用PYTHONPATH/pytest pythonpath并使用-I，子进程同样隔离。外部harness差异与逐次导入证明留在验收日志。
- 同wheel CLI smoke、core/server/agent三extras隔离、frozen依赖、Schema、ruff check/format、构建通过。文档更新后重建，并确认wheel字节仍与已安装测试一致；最终SHA256与archive成员检查随发布证据提供。
- 原513/34/7与更早400/31结果保留为历史快照，不能替代本轮信号修复证据。最终远端CI须按本轮不可变HEAD单独核查。

环境阻塞已核实：云端无Docker/Podman/nerdctl/containerd/ADB或Docker socket，用户桌面离线、无已保存可用环境。本轮没有设备、容器、真实应用/登录/上传或学校有效记录验证；Linux信号测试也不证明Windows信号行为。

## 本轮路线完整性与生命周期集成验证

准确基线为 PR #25 `19c15ba7cfad7fc1039b7b552677a3bd3e82cf6b`；叠加 Android PR #26 `5e841d1fa8e231caa33608cdd689f0b79b1f9d8d`、坐标 PR #27 `9db9c8f31567b3300699e79b3a340f7bbaf3c22c`、代理 PR #28 `9c358125a9724fafd3468a64f069e5ec92acab49`，以及冻结路线与 I0 文件。所有输入逐文件 SHA256/Git blob 核对，最终集成提交由 PR/Actions 精确 push HEAD 绑定。

- Linux x86_64 / Python 3.12.14：完整 **513 passed**（78.61 秒），一条继承 Starlette/httpx 弃用 warning。
- 源码外安装 wheel：**34 passed**（40.56 秒）。保留原故障断言，并增加预算未完成立即 attention、不重复开始，以及 GCJ02/BD09 完整 HTTP/fake 路线流程，检查 WGS84 端点、源文件/revision 不变、无学校记录证据。
- 同一 wheel 的原 7 项 daemon/TCP/subprocess 场景：**7 passed**（14.38 秒）。仅外部测试副本的启动 harness 清除 PYTHONPATH、加 Python -I；每次启动用同一 sys.executable 断言导入 site-packages。场景覆盖 Linux SIGTERM/SIGINT、停止失败、空闲 hello/heartbeat 重连、claim 响应丢失不重试、active renew 失败停止。Windows 的三项信号场景明确跳过，不能称已实测 Windows 信号处理。
- CLI smoke 使用约 1.57 米合成路线、合法 2 m/s、2 秒 budget；除服务重启和同 job 查询，还读取 fake 状态确认 route_finished=true。未到端点必须 needs_attention/simulation_incomplete，而不是“计时结束即完成”。两项新路线约束先在历史代码失败，再在本轮通过。
- core/server/agent 三独立 wheel 环境依赖隔离与 CLI 入口通过；安装测试清空 PYTHONPATH、Python -I、独立 pytest 配置并禁用 pythonpath，实际导入均来自 site-packages。
- frozen sync、Schema 漂移、ruff check/format、wheel/sdist 构建通过。最终归档成员和 SHA256 随发布证据给出；文档更新后重建并验证 wheel 与已安装测试的字节一致。

这些只证明软件和合成输入行为。Android 只读采样测试没有连接真实设备；GCJ/BD 公式不等于实测测绘精度。MuMu/vivo、步道乐跑 UI/登录/真实上传、学校有效记录与 Docker 容器仍未验证。最终候选 Hosted CI 和 artifact 须独立核查，不能沿用原 PR25 CI 替代。

## CI 候选安装包

工作流在现有构建与独立安装检查成功后，仅 Ubuntu / Python 3.11 job 生成 `dist/SHA256SUMS` 并上传 `candidate-<完整提交 SHA>` artifact，保留 7 天。仅包含 wheel、sdist 和校验文件；不包含环境、数据库、路线或账号资料。上传步骤固定官方 `actions/upload-artifact` v4 提交 SHA。

这是 CI 配置的预期行为，尚未据此宣称已经产生可下载包。发布/评审时须核查该不可变 HEAD 的实际 Actions run 和 artifact，下载后验证 SHA256；不创建 GitHub Release。

校验文件中的路径以仓库根目录为基准，形如 `dist/<文件名>`。下载 artifact 后将其内容放进独立验收目录的 `dist/`，从该目录运行 `sha256sum -c dist/SHA256SUMS`；Windows 可逐项用 `Get-FileHash -Algorithm SHA256` 对比。不要把路径布局差异当作哈希验证已通过。
