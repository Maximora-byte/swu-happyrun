# 2026-10-19 MuMu 现场复测与修复接受

执行者：本地 Codex；Windows 普通账户，未提权。Dot 继续负责产品修复；本轮通过 GitHub 回写，没有使用 Matrix。本报告更新现场事实，旧报告保留原候选的失败历史。

## 接受范围与源码

- [#55](https://github.com/Maximora-byte/swu-happyrun/pull/55) HEAD `98057f986bef87138385d5643d91d19a2bc10aac`：Windows 权限夹具修复通过独立复测，merge `5eb00e27f59a7fe927dff389e4cdd6d8d8665a55` 合入原候选，关闭 [#52](https://github.com/Maximora-byte/swu-happyrun/issues/52)。[接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/55#issuecomment-6263093425)。
- [#56](https://github.com/Maximora-byte/swu-happyrun/pull/56) HEAD `090f7eea6479cd5ce094741b4730aec6697543dd`：校准/绑定回调后重新检查实际执行授权，merge `f705f91409df88df9614aa4dd53c136dd00ed8a0` 合入原候选，关闭 [#53](https://github.com/Maximora-byte/swu-happyrun/issues/53)。[接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/56#issuecomment-6263322762)。
- 本地完整组合测试 commit `02c3af437c44431669004cb5541d18e51686e916`；其 tree 与最终 merge `f705f91409df88df9614aa4dd53c136dd00ed8a0` **完全一致**，均为 `e26de49fec98b62521740cad956e3ca056c6b05e`。通过 `git diff --quiet` 和 tree ID 核对。
- Android APK 来自较早的准确源 `e490dce3b8eec56d2db5ccad939ec49fb3fa73ed` / tree `2b38bde278e4301758030983a25f14abd0c0bbc6`。#55/#56 没有改变 Android 源码；本报告没有将 APK 重标为新 merge 的重新构建产物。
- 以上修复合入 `dot/android-foreground-agent`；完整 [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46) 保持 Draft，产品实现尚未接受进入 main。

## 主机复测

| 对象 | Windows / Python3.11.16 结果 | 退出 |
| --- | --- | --- |
| #55 准确 HEAD，全套 pytest | 1093 passed / 15 skipped / 2 warnings，115.18s | 0 |
| #55+#56 组合树，全套 pytest | 1125 passed / 15 skipped / 2 warnings，111.83s | 0 |
| #53 原始独立复现，旧 e490 | 校准/绑定耗时至 t=31，租约30s；仍发生1次 transport write，零写断言失败 | 1 |
| 同一复现，组合修复 | t=0、31 均检查 guard，失租后 transport writes=0 | 0 |
| MuMu 聚焦 Ruff、Schema 漂移检查 | 通过 | 0 |

全套命令为隔离候选环境 `.venv/Scripts/python.exe -m pytest -q --junitxml=<private-output>`；原始复现为本地 QA 脚本 `repro_location_guard.py --source-root <candidate-worktree> --expect-no-write`。日志和 JUnit 留本地 `local/`，不上传原始运行数据。

15项跳过分别为3项 Windows 不可捕获的 POSIX SIGTERM、6项普通账户 WinError1314 符号链接权限、6项 POSIX shell harness。精确跳过不能解释成断言通过，没有修改系统权限。两项 warning 是继承的 Starlette deprecation 和 Windows native-navigation 输出线程 UTF-8 解码异常；后者单独交 [#59](https://github.com/Maximora-byte/swu-happyrun/issues/59)，没有隐藏。

独立审核另复跑了 #56 的104项校准、绑定、取消、停止、预算和组合协议测试。#55/#56 准确 HEAD 的 push/PR 主机、浏览器、容器及 Android build/static 检查通过；这些事件的 Android runtime 未授权/未运行，未计为设备证据。e490 的 API35 HTTPS 失败另列 [#57](https://github.com/Maximora-byte/swu-happyrun/issues/57)，不被修复 PR 的绿灯覆盖。

## 新 MuMu 实例和安装来源

主机 MuMu **6.8.4.0**；本轮新建一个独立的 **Android15 / API35** 实例，未克隆原实例。执行前原实例停止，期间未启动、覆盖、卸载或清理原安装；每次测试通过本地实例 index/name/创建时间与实际 ADB 映射检查，只允许这台新 QA 实例和自身包执行。

普通版与可选模块版使用同一个构建归档中的配套 app/test APK：[run39218995566](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39218995566)，`android-self-probe` / API35 / selfProbe，artifact `12171340709`。归档 SHA256：`650038a7d0fed88ab3432c15362c058d1fdfedd577010a0a984f79043680bcb2`。

| APK | SHA256 |
| --- | --- |
| 普通 app-debug.apk | `57122f22af9581a8a36b70609edd48ce85c643afda9afa39830c088e0c18c05d` |
| 普通 app-debug-androidTest.apk | `ca1606180538ba4be3a7b53222116d0e1ed11244e7ebfb4a4ceedc750d2a1104` |
| 可选 app-selfProbe.apk | `992584da2c27d026a2ab5d5fd5ffbca61d473ea7fafd2b8f87c8fdddd7589b3f` |
| 可选 app-selfProbe-androidTest.apk | `cddd1bf6eb92f4667533f8b61bfe28c88764ef9ef42496a4fadf1b6e18de594c` |

本机官方 Android build-tools35.0.0 的 `apksigner verify --verbose --print-certs` 对四包均 exit0；同一证书 SHA256 `1d8ad5d8e109c759f85c20331c3dba8b9c63b4122c29447596226cb1cb302579`。JDK25 native-access warning 保留，未改系统配置。包 `org.happyrun.app` / test包 `org.happyrun.app.test`，versionCode1、versionName0.1.0-candidate。初次普通包安装没有 `-g`，冷启动363ms。

普通包非 instrumentation 场景建立的两个合成任务，在同证书 `install -r` 升级可选 app/test 后逐字段保持相同；没有卸载或清库来完成升级。可选测试所需的后续场景复位仅作用于新 QA 实例的自身合成数据。最终从实际安装路径只读计算可选 app/test SHA256，与表中产物相符。

## 设备 instrumentation：普通30、可选30，均通过

| 组 | 每种 APK 的实际测试数 | 观测 |
| --- | --- | --- |
| AndroidAcceptanceTest | 4 | 原生界面、真实自身模拟完成、重复 start 复用同一活动任务、运行中确认停止且进度不再变化、真实执行禁用 |
| ProcessRecoveryTest 分阶段 | 4 | 实际引擎完成后进程重启；running 持久意图后主机 force-stop；同 UUID 进入 needs_attention，不自动重跑，明确停止后允许新任务 |
| StorageFailureTest | 3 | 真实 SQLite trigger 故障，写意图/进度失败不伪报已保存、停止或完成 |
| PollingAcceptanceTest | 4 | 空/终态空闲，运行进度、切后台返回及停止，存储故障状态保持 |
| RemoteNamespaceProofTest | 3 | origin / agent / device 变化不能消费其他命名空间的停止证明；此组使用本地合成数据 |
| DisplayObservationTest 六个拒绝夹具 | 6 | ART 上运行合成错 display、陈旧观测、失败 dump、多个 task、无窗口、超时策略；不能写成六次真实窗口故障实验 |
| WizardAcceptanceTest | 4 | 引导流程与诊断呈现；仅打开并取消 Root 提示，未确认 Root、安装框架或改变安全设置 |
| SelfProbeInactiveTest | 1 | 当前 debug / optional 变体标记；未激活 hook |
| testObserveOwnActivity 正例 | 1 | 从实际 dumpsys 独立选定唯一自身 task/display，核对安装签名、实际 Activity、可见窗口和控件，结果 observed |

每种29项分组测试加1项真实窗口正例，共 **60项通过**。本机新实例观测到 display0；每次重新取 task，未将示例 task ID 或旧实例的多显示器情况套用到新实例。正例仅是窗口/签名观测，其 `writes=0` 限于测试发出的模拟/输入/控制动作；instrumentation 可以重启自身进程并触发正常生命周期持久化，不能用于已有个人安装或当作跑步完成。

仅在新 QA 实例，host 按顺序选择测试方法、插入真实 force-stop；逐次校验 ADB 返回、精确 JUnit 数量和 instrumentation failure marker。没有把 `am instrument` 的 shell exit0 单独当作通过。旧 CI AVD 脚本及其限制保持原样，没有伪造 emulator serial 或泛化 CI/KVM 授权。

窗口正例使用：

```text
python scripts/check_mumu_observation.py --serial SERIAL --display OBSERVED_DISPLAY --task OBSERVED_TASK --signature-sha256 VERIFIED_CERT_SHA256 --isolated-no-personal-data --output PRIVATE_OUTPUT
```

另在当前安装的可选版上，实测错误签名、不存在 display、错误 task 各一次，三项均准确拒绝：`signature_mismatch`、`display_missing`、`task_id_mismatch`，checker exit1 是预期拒绝结果。未发出模拟/控制动作；前后两条合成数据库记录完全不变。这三项另计，未加进60项通过数。

## 不调用 instrumentation 的实际界面检查

普通版、可选版分别从自身原生界面执行，确认框匹配精确标题和正向按钮，ADB 输入固定到刚观测的自身焦点 display。运行数据仅为8秒/20米本地合成模拟：

1. 点击开始并确认，实际引擎到终点；force-stop 后只读导出自身 SQLite，状态 completed、distance=total=20m。重启仍为同 UUID。
2. 新任务开始确认约0.5s后 force-stop，磁盘上为 running 且距离小于20m。重启显示同 UUID 的 needs_attention，开始按钮禁用。
3. 再等待9.5s（超过一轮时长），没有新增任务，距离与中断时精确相同。
4. 明确确认停止待处理任务，重启后仍为同 UUID 的 cancelled，距离不变。没有因恢复或停止隐式开始/上传。

两版均通过。普通版中断进度约1.413m，可选版约1.380m；这仅是合成路线进度。界面由主机 QA helper 操作，读数据库前先确认自身进程已停止，数据库只读离线核对，没有写回设备。

`uiautomator dump` 仍有 vendor 工具异常：普通版18次均139，可选版18次中17次139/1次135，写出了可解析 XML。每次先删除自身临时 XML，要求新文件、自身节点与前后焦点一致，非零退出均保留警告。此限定自身应用的 QA 路径不能变成 dump 命令通过或真实驱动输入许可；正式 XML 门禁没有放宽。[#58](https://github.com/Maximora-byte/swu-happyrun/issues/58) 已交 Dot 提供可靠 MuMu 采证入口。实际窗口正例和60项 instrumentation 不依赖此 XML 路径。

本地主机 helper 初次对空界面调用“重启并读 UUID”失败，之后改成先重启再开始；这是 QA 前置条件错误，不算产品缺陷，也没有将该次失败算通过。原始 XML、数据库、设备标识和运行 UUID 留 `local/`，本报告未提交。

## 只读物理通道输入与剩余检查

已实际读取 MuMuManager6.8.4.0 的帮助，确认以下命令形状，**没有执行定位/传感器写入**：

```text
MuMuManager.exe control --vmindex INDEX tool location --longitude LONGITUDE --latitude LATITUDE
MuMuManager.exe control --vmindex INDEX tool gyro --gyro_x X --gyro_y Y --gyro_z Z
```

location帮助声明经度[-180,180]、纬度[-90,90]；gyro帮助称重力感应，没有声明实际步数、CRS、读回或队列清空/停止确认。帮助可见不能授予已验证能力，不能猜 Android12 补偿、学校点位或命令语义。输入回写 [#7](https://github.com/Maximora-byte/swu-happyrun/issues/7)，由 Dot 先设计版本专用读回/停止探针与有界 transport，再交 Codex 测试。

`collect_device_context.py --manager MANAGER --adb ADB --instance INDEX --serial SERIAL --package org.happyrun.app` 读取元数据成功，准确返回 `blocked/binding_evidence_required`、capabilities=[]、writes=0、native exit2；当前采样器不组装别名映射、host/engine版本、boot与display/task的可信绑定。即使这些信息可分别由操作员观察，也不把只读采样结果强行标成绑定通过。

本轮未在 MuMu 运行 remoteQa HTTPS / 远程取消 / stop-ack联网恢复；当前普通包及可选包的离线成功不覆盖该门槛。[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57) 保留 e490 API35 HTTPS失败及两组恢复未运行。未部署生产服务，未修改系统信任、TLS、Root或框架。MuMu物理定位/传感器、实际步道乐跑、vivo无Root、业务纯接口和学校最终记录都没有接受证据。

结束时只停止新 QA 实例，保留当前可选 app/test 安装与两条合成终态记录；原实例仍停止且未改动。未删除实例、卸载应用或清理用户数据。

## Dot 接续

1. 优先修 [#57](https://github.com/Maximora-byte/swu-happyrun/issues/57) 的 API35 HTTPS 运行与清理失败，保留明确的 runtime 授权边界；Codex 在准确修复 HEAD 复测。
2. 处理 [#58](https://github.com/Maximora-byte/swu-happyrun/issues/58) 的 MuMu 采证入口和 [#59](https://github.com/Maximora-byte/swu-happyrun/issues/59) 的 Windows 输出读取诊断。
3. 消费 #7 的本机命令帮助，只实现可证明读回及停止的版本专用 transport；同时按 #9 准备实际版本/校区/页面输入。缺失样本不阻塞离线解析和服务器故障测试。
4. [后续计划](../superpowers/plans/2026-10-19-post-e490-device-delivery.md)任务1目前接受的是 **MuMu自身应用离线模拟与观测**；联网部分仍未完成。继续任务2–4，不能把此报告当成西大有效记录或“100%支持”。
