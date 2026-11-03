# 2026-10-23 本地产品 RC2 验收

## 结果与准确版本

本机交付 `HappyRun-Local-0.2.0rc2`：中文工作台、离线启动器、独立合成模拟、MuMu 实际定位与轨迹工具、匹配自身观察 APK、私有路线和使用说明。已从交付包安装后的 Python 模块，通过真实 Chromium 页面跑完整条 421.476 米路线，实际 GPS 读回、暂停继续和终点停止确认通过。未登录、操作或上传步道乐跑记录。

产品代码提交：`a7138c19adf398f4beb37b9ac236988c03a1e423`；`src` tree 为 `9f5f45c5b2f96146149ca7b976c876de8c146a2e`，`android` tree 为 `20a697a8db122af0e761f57bef9a71e5afb98ea5`。后续交付说明提交不改变这两棵源码树。GitHub PR 以 `dot/trusted-runtime-context` 为基线，不据此合并尚未完整接受的历史产品到 main。

环境：Windows x64、Python 3.13.15、MuMu 6.8.4.0、Android 15 / API35 x86_64；专用新建 QA 实例 #5，无学校账号。没有修改 Root、Xposed、系统安全保护或第三方应用数据。运行时只给自身应用普通位置权限。

## 实际安装包与设备验收

| 检查 | 结果 |
| --- | --- |
| 实际 `Start-HappyRun.cmd` | SHA256 完整包校验、19 个本地 wheel 离线安装、回环监听与默认浏览器打开通过 |
| 安装内容 | 98 个项目包文件与交付 wheel 逐字节一致；运行模块路径位于交付包 `.runtime`，版本 0.2.0rc2 |
| 双 APK 安装器 | 交付包安装器在 QA #5 的两次 `install -r` 均成功，之后自身粗略/精确位置权限读回通过；未卸载或清数据 |
| 真实浏览器全路线 | 2 m/s，421.47618991545374 m，210.73809495772687 秒有效推进；116 次写入，包含两个校准点 |
| 实际 GPS 关联 | 每次写入均等待同观察窗口的新鲜样本；最大位置误差 1.0869972706370674 m；版本映射与两点校准通过 |
| 暂停和继续 | 暂停确认后额外等待 3 秒，写入数保持 7；继续后沿同一路线完成 |
| 完成与停止 | progress=1.0，stop_confirmed=true，自身观察窗口结束；最后 GPS 定位保留 |
| 进程强制中断 | 安装包子进程在已发送 5 次后 `os._exit(37)`；新进程连接恢复为 needs_attention，等待后仍为 5 次，无自动重放 |
| 显式恢复停止 | 核对原实例创建身份后关闭匹配 QA 实例，确认 Android/进程均停止；不会替换实例或重跑 |
| 浏览器表现 | 1440×1100 和 390×844 无脚本错误，窄屏无水平溢出；原生测试未拦截 MuMu API |

完整路线通过真实 UI 执行连接、私有文件导入、校准、启动、暂停和继续，共六个 POST，各一次；终点自动收尾。源代码现场另外已通过显式正常停止，共 14 次写入、最大误差 0.946 m。安装包再次强制中断测试最大误差 0.707 m。

停止确认仅指本工具发送线程、在途命令和自身观察窗口结束。暂停可能没有新 GPS 回调，因此稳定窗口分别记录存活心跳、最后确认路点和 Android 系统保留位置，不把缓存位置计为新鲜样本，不承诺厂商队列为空或清除虚拟定位。

配对应用 SHA256：`533de820b58f0a2790c21d4b53e8dd1dbc1fa3935263dbb49ff01cd15dde48d4`；测试 APK：`88ce1299c77843aa6d5b630200a9c3c5da2cec12090311ad14fe39cfa86174f8`。两者均通过 apksigner 验证，证书 SHA256 同为 `3ca7a8001517ea2822dd47c23f96d125e959ee0f9ddba324abea0e278f4015a2`，属于临时开发签名 SELF_PROBE 构建。

## 软件检查

以下退出码均为 0，平台 Windows / Python 3.13.15；测试内容和产品代码已固化到上述提交。服务器检查在提交前相同源码树运行，原生实测和最终桌面检查覆盖最终变更。

| 命令 / 范围 | 实际结果 |
| --- | --- |
| `python -m pytest tests/desktop tests/contracts -q` | 239 passed，40.75s；包含安装器、身份固定、观察解码、轨迹状态、恢复和协议 |
| `python -m pytest tests/server tests/integration -q` | 200 passed，161.60s |
| `python scripts/check_mumu_browser.py --output <新私有目录>` | 9 组真实 Chromium UI 检查通过；这里使用拦截的合成 MuMu 回执，与上方实际设备验收分别记录 |
| `python scripts/export_schema.py --check` | 协议 v1 Schema 与共享模型一致 |
| `ruff check .` / `ruff format --check .` | 通过；367 个文件格式一致 |
| `uv lock --check --offline` / `git diff --check` | 通过；依赖版本未改，项目版本更新为 RC2 |
| `uv build --out-dir local/rc2-build` | RC2 wheel 和 sdist 成功生成 |
| `python scripts/check_distribution_privacy.py <准确 RC2 wheel> <准确 RC2 sdist>` | 两个分发件通过；无 APK、签名私钥或 Android 本机构建状态 |
| 干净 core-only venv，离开源码目录、`-I` 导入和 CLI help | 通过；未安装 FastAPI/httpx，组件依赖仍可选 |
| Android 离线 `assembleSelfProbe assembleSelfProbeAndroidTest -PprobeInstrumentation` | 同一源码配对构建通过；连续观察纯 Java 辅助测试 35 项通过 |

独立审查核对了不可变提交中 14 个范围文件：13 个 SHA256 完全相同，JavaScript 只有 Git CRLF→LF 规范化；请求范围内没有未解决的 Critical / Important / Minor 问题。审查不是对全仓库、发布安装器或托管 CI 的替代验收。

## 保留的失败与未验收范围

- 全仓库历史回归没有全绿结论。早期串行运行在 1031 秒后中止，发现的四个 Windows 子进程启动预算夹具问题已针对性修复并通过 16 项检查；随后旧基线 3004 项分成四组，各 751 项无遗漏，每组在 2400.09 秒上限时仍未完成，均记为 `timeout_unfinished`，不计为通过。未通过无限重复掩盖超时。
- Android 完整 unit/lint 曾因未缓存 JUnit 4.13.2 无法离线解析，在线重试在 900 秒超时；没有完整 unit/lint 通过声明。新观察 APK 构建、辅助测试与实际运行结果分别如上。
- 托管 GitHub CI 需在发布 PR 的准确 HEAD 上单独查看，不能把本地结果当作 CI 通过。旧 Python 3.11 AV / `configuration_readback=format_unknown` 问题 #110 没有复跑或关闭。
- 初次定位 ACK 字段、冷启动 GPS provider、Android15 instrumentation 前台约束、输入坐标偏移、暂停无新回调等失败均保留私有原始证据；分别修复和重新验证，没有把错误 ACK、旧样本或数学推断直接改成成功。
- 每个观察窗口最多 30 分钟，包含校准与暂停；工具轨迹有效推进预算最多 1800 秒。长时间暂停或接近上限会安全停止或需要处理，不能保证无限期运行。
- 只验收此 MuMu / Android 组合的本地定位工具。旧 native CLI/enrollment 仍关闭；vivo、其他 MuMu/Android 版本、学校账号、学校规则、乐跑页面、上传与有效记录未验收。
- 私有路线上报、原始读回、实例身份、截图、journal 和数据库未提交 Git；随本机私有交付包提供的路线不是官方打卡点或学校规则。未进行生产部署、DNS 或现有服务器修改。

## 证据与使用

交付文件夹附带 `source.json`、`SHA256SUMS.json`、`验收记录.json`、实际完整路线截图、配对 APK、19 个离线 wheel、中文说明与私有路线。压缩包按清单生成，不包含 `.runtime`、用户数据库、未决 journal 或原始日志。

本机忽略目录中的原始证据：`local/installed-mumu/run-1792746451683494100/`、`local/mumu-crash-qa-rc2/`、`local/mumu-browser/qa-20261023-final/`、`local/mumu-review-3.md`、`local/complete-shards-v3/result.json`。它们仅用于本机复核，不作为 Git 公开附件。

启动与操作见 [本地工作台](../desktop.md) 和 [MuMu 工具](../mumu-desktop.md)。
