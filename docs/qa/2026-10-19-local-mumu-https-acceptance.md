# 6d8fa394 MuMu HTTPS 自身模拟验收

日期：2026-10-19（Asia/Shanghai），Codex原普通Windows账户。**新四APK构建、严格SDK验证、公有预检和MuMu六组HTTPS自身应用模拟均通过。** 本轮不覆盖真实定位/传感器、Activity/UI、步道乐跑或学校有效记录；完整产品#46仍按最终组合独立接受。

## 冻结来源与配对

| 用途 | commit / tree |
| --- | --- |
| 实际运行产品 | `9534f51efe3a557e6b4bda5605426e4004a34783` / `53d6858c01b982e1143436018d7201e934c4ee58` |
| 已接受#75工具 | `0cea241776c0233cd222213c475dec25aaf04be9` / `a70301e2113a85223c0c0d395efb5d432809a97d` |
| 本轮#76 runner/adapter | `6d8fa394f7f404a5303cb57d073c0a9d2acf95aa` / `c44312cf23588121e41ec31851537d014491e749` |

Windows / CPython3.11.16 / Temurin17.0.20.1+1 / Gradle8.9 / SDK35与build-tools35.0.0；MuMu6.8.4.0、同一无个人数据Android15/API35独立验收实例。三份源码checkout结束仍干净，原实例与数据均保留。

Java adapter路径为 `android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/RemoteMumuHttpsAcceptanceTest.java`，新SHA256 **`7e172abd370a1380da9a3ebe0e89dff77bb1620218e5c11565cc8f39c2479eaf`**。旧9a5094包未被声明为新实现。

在仓库外新目录，使用受审builder、原CA/leaf及原本机签名环境，完整运行ordinary与remoteQa两组Gradle任务。命令参数：`python <tools>/scripts/build_local_https_delivery.py --source-root <9534> --output <NEW_PRIVATE_BUNDLE> --gradle <GRADLE> --adapter <6d8/ADAPTER> --adapter-commit 6d8fa394f7f404a5303cb57d073c0a9d2acf95aa --private-build-evidence <NEW_PRIVATE_CAPTURE> --gradle-stderr-encoding gbk <证书和已观测host及SDK参数>`。真实build **exit0 /91.922s**；两组严格字节捕获reader完整、reason=ok，未改变系统codepage。

新四APK和新manifest完成真实OpenSSL/apksigner/aapt2/apkanalyzer校验：独立validator **exit0 /5.844s**，公有预检 **exit0 /5.640s**、runtime not_run。manifest独立记录产品9534和adapter6d8来源；没有手改旧manifest。

新remoteQa app SHA256 `12e1cd381d31f6bfd0a5048a14a01f1ba969de70820e3a10dc77a2adbff54789`，与原安装读回完全相同；新test SHA256 `407535a47d826102f0b5d9ba059ab9393771fea95739dfc6008149b2a6411362`。配对证书相同，仅以同签名更新test，随后安装app/test逐hash匹配新manifest。未卸载、清库或生成新证书；原八文件bundle和CA/leaf/key逐hash不变。

## 主机回归与入口

- 工具/runner/fixture/JVM任务身份/namespace/version/UTF8/跨checkout入口/workflow及共享契约：**340 passed /4权限skip /6 subtests passed，exit0，25.53s**。四项skip仅对应普通账户符号链接权限；namespace core和新增34项任务身份回归实际执行。JUnit合计350包含子测试，不能写成346项普通测试。
- 命令沿用[第三轮回执](2026-10-19-local-mumu-https-retest-v3.md)的聚焦集合，新增`<PR76>/tests/delivery/test_mumu_task_identity.py`和`test_mumu_checkout_entry.py`；`python -m pytest <上述集合> <9534>/tests/contracts -q --junitxml=<PRIVATE>`。原始stdout和JUnit留本机。
- 产品cwd、tools-first `PYTHONPATH=<tools>/scripts;<runner>/scripts;<product>/src`、模块入口 `python -m check_mumu_https`。实际加载的validator/packaging helper来自0cea，runner/fixture来自6d8，运行产品来自9534；不调用会遮蔽helper的直接脚本入口。
- 准确6d8 HEAD的push与PR事件checks、container及SDK35 build-only自动run均终态success；不是旧HEAD或手动重跑结果。托管CI与下列MuMu运行分别记录。

## MuMu六组实际结果

原独立实例重启后，核对created identity/serial映射、新boot、安装两APK、版本和真实MAIN入口；原私有地址实际TCP可达。真实窗口观察得到唯一task/display/focus，采集30秒内新鲜binding；Manager原值15.0、ADB和binding原值15的等价guard通过，未改写原证据。

显式给出`--execute-own-app-simulation --allow-own-package-force-stop --isolated-no-personal-data`，使用原受审runner `main`、原fixture和`RemoteFakeDriver`。私有QA仅包装日志记录，不更改实现或注入通过值。

| 场景 | 实际结果 | starts | 服务端即时状态 |
| --- | --- | --- | --- |
| `completed` | passed，执行器已停 | 1 | completed |
| `two_jobs` | passed，同一前台会话两任务、不重叠 | 2 | completed /completed |
| `disconnect_running` | passed，中断后执行器已停、无完成误报 | 1 | running |
| `lost_renew` | passed，实际续租503故障被触发、执行器已停 | 1 | running |
| `cancel` | passed，取消控制器与stop-ack闭环 | 1 | cancelled |
| `restart` | passed，持久start后实际停包、只核验恢复 | 恢复阶段0 | needs_attention |

`running`是用例返回时的服务器状态，不冒充最终终态；本地执行器已停止，也未提交completed。重启用例先观察`starts=1 persisted_start=true`标记再实际停包，恢复沿用原session、更高fence、verify_only，恢复start=0，不生成第二次运行。

runner总结果 **runtime_status=passed /exit0**，六场景均passed，body/fixture/cleanup/controller/fixture-cleanup错误全部为空。六个真实fixture分别收到Android hello；合计 **hello8 /renew30**，不是host准备请求冒充Android联网。每个fixture线程均已退出。

新guard实际越过旧[PR83失败](2026-10-19-local-mumu-https-retest-v3.md)并进入HTTPS，不以SDK编译代替原机验证。停止后的recent task允许null baseActivity，但仍检查唯一task、原taskId、boot、双签名、显式自身component及注册Activity/类/UID，并要求停止状态字段一致。运行结果只证明本次身份条件被原实现接受；未额外采集Java全部TaskInfo原字段，不把旧失败时未知字段补写成已观测值。

## 合并审查与后续

复用现有隔离QA工作区，在`codex/pr76-integration-20261019`冻结已接受#75后的候选839faf8加本轮6d8；本地合并预览commit `5bfe459ad8130c674a399c86d83c1284b4f4709c`、tree **`9400abfd34fd45f9297b9c1cf3d1405c25b0f4c5`**。命令`PYTHONPATH=<preview>/src;<preview>/scripts python -m pytest -q --junitxml=<PRIVATE>`，普通Windows/Python3.11.16完整结果 **1515 passed /23 skipped /1既有依赖warning /6 subtests passed，exit0，186.96s**。Ruff check、format check和协议Schema漂移检查均exit0。

23skip逐项为Windows不可捕获SIGTERM3、WinError1314符号链接10、另一符号链接权限1、POSIX shell6/FIFO1、JDK19+标准流条件2；不是23项已通过断言。未修改权限或系统JDK来取得结果。托管Windows/Linux的准确6d8结果单列，不把本机组合全套记成原始6d8产品运行结果。

独立只读源码审查覆盖完整PR76及最后生命周期增量，无阻塞；另核对准确HEAD、实际候选ref、可合并性和契约兼容。按[接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/76#issuecomment-6271057907)将#76合入候选，实际merge **`e681aaa8ae81c61c8386ca697a2451b4bb7c08e7`**；已通过GitHub git commit API核对parents为839faf8与6d8，tree与上述完整受测预览一致。#78/#82按版本/任务身份原机阻塞修复范围关闭；#57保持开放，不由本轮结果宣称旧间歇根因全部解决。

本次`device_verified=true`仅限自身应用HTTPS模拟，`activity_ui_verified=false`、`school_record_verified=false`。#74只读观察器/#77数据库修复未叠入运行产品；#57历史间歇问题、真实通道/第三方乐跑/vivo/最终记录继续分别验收。

结束时仅停自身包并关闭测试实例，所有实例恢复停止，新配对、旧完整bundle、证书和应用数据保留。原始日志、请求/SQLite、绑定、IP/serial、截图和私钥只在本机私有目录；未修改Root、系统CA/TLS、防火墙、全局网络、定位/传感器、学校接口或生产环境。
