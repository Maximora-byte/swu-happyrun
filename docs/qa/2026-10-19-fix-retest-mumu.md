# 2026-10-19 修复复测与 MuMu 现场验收

本地 Codex 执行独立审核、测试与现场操作；产品修复交给 Dot。原始 XML、日志、数据库留在被 Git 忽略的本机目录。本轮未使用 Matrix，也未修改 Root、框架、系统位置、TLS 或生产配置。

## 决定与准确版本

| 对象 | 测试版本 / 决定 |
| --- | --- |
| #39 | `5d52d78acf6d0f7e7064e1209810746dd05b93d7`：接受；合入原候选基线 `dot/android-remote-agent`，merge `0bb9344ddefe8054177101583282c57f27f5b38a`，#37 已关闭 |
| #40 初版 | `28f811664bdf0c50d21c37da5564d23b9a260f61`：正常恢复通过，pre-bind agent mismatch 负例失败，暂不合并 |
| #40 补测试版 | `69182c7128941feb0d6d9e0b512c988b024c1b03`：仅新增四项测试，生产逻辑未改；同一负例仍失败，#36 保持开放 |
| 本地组合 | `e62c1afc96819648cd7e5a889bfaeef360131700` = 初版 #40 + #39；后续 `9b9b8a4a3e2ea81b622ad2a62b979ba46e22b097` 再含 #40 的四项新测试。仅作 QA，没有推到 Dot 分支或 main |
| MuMu 普通 APK | #25 `77494e21756e514f53e51b3a2c72f22555f0aae6` 对应普通 debug APK；本轮保留已有安装与数据，没有覆盖为 #35 或其他签名包 |

main 仍只有已接受的 C0/C1/L0 与文档；#39 合入候选不等于整个产品已经发布。

本次 QA 文档/脚本基于 main `24958d8074be36e9170beb2ff8b2eca6622838be`，Windows Python3.13 全套 `python -m pytest -q`：exit 0、163 passed；两个复现脚本 Ruff lint/format、`git diff --check` 通过。下表产品检查另用候选环境，不借 main 的测试结果替代。

## 主机独立验证

Windows / PowerShell，uv 0.12.19；Python 3.11.16 和 3.13.15。表中解释器来自明确的隔离环境。

| HEAD / 环境 | 实际命令 | 结果 |
| --- | --- | --- |
| #39 / Python 3.11 | `python -m pytest tests/contracts tests/server tests/integration/test_http_protocol.py -q` | exit 0，269 passed，1 条继承 Starlette warning |
| #40 初版 / Python 3.13 | `python -m pytest tests/contracts tests/agent/test_driver.py tests/agent/test_runner.py tests/integration/test_http_runner.py -q -k 'not test_broken_state_symlink_is_not_fresh_state'` | exit 0，211 passed、1 deselected；该权限夹具另列，不声称全套通过 |
| e62c1af / Python 3.11 | `python -m pytest -q --deselect=tests/agent/test_driver.py::test_broken_state_symlink_is_not_fresh_state --deselect=tests/agent/test_profiles.py::test_profile_resolution_fail_closed[symlink]` | exit 0，709 passed、7 skipped、2 deselected，98.47 秒，1 条继承 warning |
| e62c1af / Python 3.11 | Schema 检查、Ruff lint/format（159 文件）、`uv build`、分发隐私检查 | 全部 exit 0 |
| 9b9b8a4 / Python 3.11 | `python -m pytest tests/agent/test_recovery_identity.py tests/integration/test_recovery_release.py -q` | exit 0，4 passed；不是对新组合又跑了一遍全套 |
| 9b9b8a4 / Python 3.11 | `python -I docs/qa/reproductions/repro_probe_batch.py --expect-fixed`（使用该候选的已安装环境） | exit 0：冲突首收与重传 409，无部分探测写入；合法 A/B→probe 精确绑定与重传 200 |
| 9b9b8a4 / Python 3.11 | `python -B docs/qa/reproductions/repro_finished_recovery.py --source-root <该候选> --expect-recovery-completed` | exit 0：verifying→completed；start/tick/stop 各 1，无上传意图 |
| 9b9b8a4 / Python 3.11 | 同上，改用 `--expect-persisted-agent-rejected` | **exit 1**：归属不符的持久快照仍被判为 completed，阻塞 #40 |

7 项 skip 是 3 项 POSIX 信号及 4 项 Bash harness；两项 deselect 是本机无创建 symlink 权限的既有 WinError1314 夹具。未更改系统权限，也未计为这些断言通过。相应可移植性工作仍由计划任务 3 跟踪。

#39 的独立检查另覆盖服务重建后重放、重放不刷新接收时间、第二设备写入时异常的整批回滚。发现现有测试 `test_probe_batch_atomicity.py` 的 `row[2]` 实际为 fence，不能证明 current_probe 非空；已在 [#37 回执](https://github.com/Maximora-byte/swu-happyrun/issues/37#issuecomment-6260094075) 请求 Dot 改为精确映射。本轮接受依据包含独立精确映射检查。

## #40 新阻塞与 Dot 修复要求

详见 [PR 阻塞回执](https://github.com/Maximora-byte/swu-happyrun/pull/40#issuecomment-6260041615)、[#36](https://github.com/Maximora-byte/swu-happyrun/issues/36#issuecomment-6260042024) 和 [新 HEAD 复测](https://github.com/Maximora-byte/swu-happyrun/pull/40#issuecomment-6260093734)。

合成任务走完路线、停止并持久化之后，只改磁盘 `bound_view.agent_id`，再重建 driver 并运行批准的 verify_only。`bind_session` 未核对旧 agent，先以当前授权替换绑定并保存；随后 completion proof 只能看到替换后的 agent，错误返回 completed。计数未增加；问题是错误接纳归属证据，不能因未重复运动而忽略。

Dot 应在覆盖历史绑定之前验证归属，补重建 driver 后经过完整 runner 的负例，并保留合法 fence 增长与设备保留释放正例。当前新增的直接 proof 测试没有经过这条重绑定路径。独立脚本的两个验收模式互斥；负例必须拒绝 completed 并保留原归属。该输入是合成损坏快照，不声明 JSON 本身防篡改。

## MuMu 现场观测

MuMu **6.8.4.0**，实例 0，**Android 15 / API35**；自身包 `org.happyrun.app`，版本 `0.1.0-candidate`。每次操作重新核对自身前台窗口和 display，输入只针对自身模拟控件及其精确确认框。没有点击可选 Root 检查。

普通 APK SHA256：`e362b935ca058b6c7799b299f8bca458bca30ca7728e54f4971778628bf9f69e`，本轮通过 `pm path` 定位自身安装包，只读计算安装包 SHA256，与产物精确相同；`dumpsys package` 读回 versionCode=1、targetSdk=35、versionName=0.1.0-candidate。本轮发现本机官方 SDK build-tools 35.0.0 可用，独立执行 `apksigner verify --verbose --print-certs <普通APK>`：exit 0、v2 验证通过，debug 证书 SHA256 `1db755f3b392173f2ffc9cc2c0c74ee68a408b7608c7f4a152817e8d609b2923` 与既有 CI 报告一致。JDK25 给出 native-access warning，未修改系统配置。

| 自身模拟场景 | 独立观测 |
| --- | --- |
| 正常开始与完成 | 处理“开始模拟”确认框后创建任务；UI 为模拟完成；强停后只读导出自身数据库，completed / simulation_only / 20.0 米，落盘时长约 8.067 秒 |
| 完成后重启 | 同一任务 UUID、completed、20.0 米保持，不创建新任务 |
| 开始后进程中断 | 确认开始后 0.5 秒 force-stop；停止后的库为 running，约 1.134 米；重启 UI 为同一 UUID / 需要关注，库为 needs_attention / restart_uncertain |
| 不自动重跑 | 重启后额外等 9.5 秒；开始按钮 disabled、停止 enabled；再次强停并只读核对，仍是相同任务、距离精确不变、行数没有增加 |
| 待处理任务显式停止 | 处理“确认停止”弹窗；UI 已停止；库为 cancelled / local_simulation_stopped_after_attention，距离不变；再重启保持同一任务已停止 |
| 运行中直接停止 | **未验收**：独立第三次任务在慢速导出/查找停止控件期间已走完 8 秒，再读到停止 disabled；库确认 completed / 20.0 米。没有将测试时序限制判为应用缺陷，需任务 5 的稳定测试入口继续验证 |

数据库仅在自身进程已 force-stop 时通过 `run-as org.happyrun.app` 导出至私有临时目录读取；未写回、清库、卸载或上传原始数据库。测试后自身应用 force-stop，保留三条合成模拟任务和安装，清理自身 sdcard QA 导出文件。

上一轮主机 helper 漏处理开始/停止确认框，并把含更新时间的整段 task_id 文本当成固定 ID；本轮已纠正，比较提取后的 UUID。因此上一轮点击后的失败不能再归因于应用逻辑。

MuMu 的 `uiautomator dump` 多数退出 139，一次退出 135；每次先删自身固定导出文件，要求新文件可解析且前后仍为自身焦点，再使用节点。非零退出作为工具异常保留，不能记作 dump 命令成功。测试所用的主机 helper 留本地；需要 Dot 按任务 5 提供同签名 app / instrumentation APK，缩短对 8 秒模拟的取证时序并完善多显示器定位。当前未获匹配测试 APK，不自动卸载或绕过签名检查。

以上只接受自身 APK 的部分本地模拟行为。#35 原生单次远程 fake、真实步道乐跑、位置/传感器写入、vivo 无 Root、学校配置及有效跑步记录均未在本轮设备上验收。Android 托管失败保留：原 #39/#40 的 Python/浏览器/容器成功不等于 Android CI 全绿；#40 新 HEAD 也不能沿用旧 CI 结论。
