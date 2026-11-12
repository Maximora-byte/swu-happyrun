# MuMu 自身应用 HTTPS 验收入口

## 边界与来源

这是独立于官方 AVD harness 的本机入口。`scripts/check_mumu_https.py` 不调用旧 AVD 的 guard、reset 或 fixture，不放宽 emulator/qemu 限制，不使用 AVD 主机地址假设。产品基线固定为 `9534f51efe3a557e6b4bda5605426e4004a34783` / tree `53d6858c01b982e1143436018d7201e934c4ee58`。

需要另外构建含 `RemoteMumuHttpsAcceptanceTest.java` 的配对 remoteQa app/test APK。普通 APK 和没有 adapter 的 9534 remoteQa APK不能用于此入口。产品源码与新增测试 adapter 分开追溯：交付 manifest 保留产品 commit/tree，另外记录 adapter source commit、唯一文件路径和 SHA256；入口再核对当前受审 adapter 文件内容。不能把 adapter 构建称为未经修改的旧 9534 测试 APK。

交付工具 `build_local_https_delivery.py` / `check_local_https_delivery.py` 是前置依赖，来自独立 [PR #75](https://github.com/Maximora-byte/swu-happyrun/pull/75)，固定为已接受的工具提交 `0cea241776c0233cd222213c475dec25aaf04be9`；此入口不重复构建或签名。请使用同一审核组合中的工具和源码，不从旧 APK拼装配对。

本入口只操作 `org.happyrun.app` / `org.happyrun.app.test`，驱动为产品现有 `RemoteFakeDriver`。不操作第三方乐跑、定位/传感器、学校接口或学校记录。不安装/卸载 APK，不清 app 数据，不点击 UI，不启动模拟器，不修改 Root、防火墙、系统 CA、TLS hostname verifier 或网络设置。

## 已实现用例的验收含义

- `completed`：真实 HTTPS、产品 runner、真实服务器终态 completed，恰好一次模拟开始，停止后距离不再增长。
- `two_jobs`：同一个真实 `RemoteForegroundSession` 完成两个不同任务，累计两次开始；这是 session 测试，不是 Activity/UI/多显示器验收。
- `disconnect_running`：开始持久化后主动断开本次 runner/client；不允许报告 completed，模拟驱动停止。
- `lost_renew`：真实 fixture 第四次续租响应故障，产品进入不确定状态并停止，必须证明故障实际触发。
- `cancel`：服务器先进入 cancelling，必须观察到真实 `/stop-ack` 的 200 才接受 cancelled，不能仅凭取消请求成功。
- `restart`：观察到持久 start 后真实 force-stop 自身包；等租约转 needs_attention，再对同 job/session 请求 verify_only，并验证新 fence 增大、零新增开始、保持 verification_pending。它验证的是不确定开始的恢复，不冒充“已完成记录恢复成功”。

Activity/UI生命周期、显示器 viewport、真实传感器/第三方目标和有效学校记录始终单列未验证。任一用例、fixture退出、控制线程或自身进程清理失败，都停止后续用例；不会继续运行污染后的套件。

## 本机前置条件

1. 用户确认独立 MuMu 实例没有个人数据。用户/本地验收者负责观察实例、ADB serial、MuMu/Android版本以及自身 app 的 task/display。入口不猜地址或实例映射。
2. 已在该实例安装准确 manifest 对应的 remoteQa app/test，并手动打开自身 app，形成唯一自身任务。签名不匹配时停止，不能自动卸载或绕过签名。
3. 用项目既有 `MumuBinding` 的完整字段格式保存当前本地复核结果：instance/serial 与 mapped instance/serial一致，`mapping_source=local_review`，唯一自身 task，app/engine/host版本、boot ID、全新 observation UUID、带时区 observed_at。入口首次接收要求不超过30秒；它验证格式与一致性，不把自填 JSON 当成独立认证。必须由本地验收者先真实核实映射。
4. 明确选择本机已有可达的私有 IPv4 和可用端口；不默认监听所有接口，不自动改网络或防火墙。证书 SAN 必须精确包含实际地址。loopback 只适用于你已验证相应路径可达的情况；不能假定 MuMu 的 loopback 就是主机。
5. 公有 CA 和 leaf certificate 与交付 manifest/APK 内测试 CA一致。服务器私钥仅在本机保留，通过 `--server-key` 本地路径使用；不上传、不贴到聊天、不加入交付包。fixture 在监听前核对 leaf/key配对。用户实际私钥与实现测试临时生成的 localhost 合成密钥完全分离。
6. 本机 Python3.11+，按冻结依赖安装 server/agent/dev；使用明确可信 ADB、MuMuManager、OpenSSL、apksigner、apkanalyzer、aapt2路径。入口仅使用仓库已有的 `MuMuManager info --vmindex` 查询，不猜新的 MuMu 命令。

每次 instrument 前重新读取原实例、boot、Android版本和安装 app/test 的实际 APK SHA256；Android内再校验自身 app/test签名、包名、唯一自身task、原boot和显式模拟许可。一次本机进程内使用单调时钟限制新观测到动作的间隔；不会伪造跨进程单调时间或重写原复核时间。重启恢复仍由同一 host进程持有本轮 run UUID，不能传入任意旧 run目录继续执行。

## 运行

先构建并验证包含受审 adapter 的交付包。以下参数值都由本地观察/交付工具提供，示例不提供猜测的 serial 或 MuMu地址。

使用三个分开的、已核对准确提交的 checkout：`$productCheckout` 是上述 9534 产品，`$toolsCheckout` 是上述 0cea241 工具，`$runnerCheckout` 是本次待验收准确 HEAD 的 MuMu 入口及受审 adapter。先将这些变量设为对应的本机路径，再在同一个 PowerShell 会话中执行：

```powershell
$product = (Resolve-Path -LiteralPath $productCheckout).Path
$tools = (Resolve-Path -LiteralPath $toolsCheckout).Path
$runner = (Resolve-Path -LiteralPath $runnerCheckout).Path
Set-Location -LiteralPath $product
$env:PYTHONPATH = "$tools/scripts;$runner/scripts;$product/src"
```

预检和实际执行均保持产品 checkout 为工作目录，使用下面的模块入口。Windows 的 `PYTHONPATH` 用分号，顺序必须是工具 scripts、入口 scripts、产品 src，并替换而非追加未知的旧 `PYTHONPATH`。`check_local_https_delivery` / `check_remote_qa_packaging` 应来自工具 checkout，`check_mumu_https` / `mumu_https_fixture` 来自入口 checkout，`swu_happyrun` 来自产品 src。其他平台按本机路径分隔符设置相同顺序。

[Issue #82](https://github.com/Maximora-byte/swu-happyrun/issues/82) / [PR #83](https://github.com/Maximora-byte/swu-happyrun/pull/83) 的入口差异由合成三 checkout 子进程回归保留：直接按脚本路径启动会把入口 scripts 插到搜索路径首位，遮蔽工具 checkout 中较新的 `check_remote_qa_packaging`，即使原 `PYTHONPATH` 已把工具排在最前也无效。因此不能把下面的 `python -m check_mumu_https` 改成脚本路径调用，也不能在入口 scripts 目录运行。该回归只验证导入来源，不是 APK、公有预检或 MuMu HTTPS 通过证据。

纯公有材料/产物预检（不会调用 ADB、不会读取私钥）：

```powershell
python -m check_mumu_https --bundle "$bundle" --ca-cert "$ca" --server-cert "$leaf" --host "$observedHost" --openssl "$openssl" --apksigner "$apksigner" --apkanalyzer "$apkanalyzer" --aapt2 "$aapt2" --output "$newPreflightReport"
```

无 adapter / 哈希不匹配 / 信任不匹配时 exit2、全部 not_run。正确预检 exit0 只表示预检通过，`runtime_status` 仍为 `not_run`。

实际本机执行必须显式确认以下三个开关；尤其 force-stop 会停止该隔离实例中的自身包进程（包括重启用例与失败清理），但不会清数据：

```powershell
python -m check_mumu_https --bundle "$bundle" --ca-cert "$ca" --server-cert "$leaf" --host "$observedHost" --port $port --openssl "$openssl" --apksigner "$apksigner" --apkanalyzer "$apkanalyzer" --aapt2 "$aapt2" --adb "$adb" --manager "$manager" --serial "$observedSerial" --instance "$observedIndex" --binding "$freshBinding" --server-key "$localPrivateKey" --private-dir "$existingPrivateDirectory" --execute-own-app-simulation --allow-own-package-force-stop --isolated-no-personal-data --output "$newRuntimeReport"
```

`--output` 必须是新文件，位于已有非 symlink父目录、交付包外，不能别名到任何输入。入口以独占方式新建，不能覆盖已有报告或私钥。所有工具输出和 instrumentation 原文只在本机内存中处理；公开报告仅有固定阶段/错误类别、布尔、计数与已核 source摘要，不含 token、路径、serial、账号、原始日志或截图。

每例使用新随机 `files/mumu-https-qa/<runUUID>/journal`；owner以独占新建保存，仅恢复本轮完全一致的owner。拒绝 symlink、旧目录复用或不符owner。正常结束不自动删除这些目录；失败 journal保留给本地复核。主机fixture SQLite也保留在本次私有目录，不能原样上传。用户app其他目录、数据库与 shared preferences不清理。

只有所有六项及其清理均成功才 exit0 / runtime passed。任何失败 exit1；前置条件不足 exit2。若身份已变化导致安全清理被拒绝，报告单列 cleanup失败，后续不运行；本地验收者先核对当前实例及自身进程，不得靠放宽guard继续。

## 实现验证和现场证据

宿主机单测、合成 localhost TLS 和 JVM namespace helper 只能证明实现层边界，不能证明 MuMu已连通或安装过此候选。完整 Android Gradle编译、MuMu实际执行与独立接受各自记录准确 commit、adapter hash、命令和退出码。旧 API35 归档不代替本候选的新构建或本机运行；未运行和中断都不是 passed。

专用 `mumu-adapter-build-only.yml` 只在 `dot/mumu-own-https-runner` 的 push 或同仓库该分支 PR 编译新增 adapter，使用官方 SDK35/build-tools35.0.0、现有固定 Gradle8.9/AGP8.7.3 和预装 JDK17。其一次性 CA 只用于编译资源，私钥与公有资源在 shell 退出时清理，不上传任何产物；该作业不能提供用户本地 HTTPS 服务用的成套交付或设备运行证据。最终以准确 head 的 CI 编译退出结果为准。


## 现场格式差异修订（#78）

2026-10-19 本机验收已完成短期证书、同组四 APK 构建/配对、公有预检和隔离 MuMu 安装，记录见 [PR #79](https://github.com/Maximora-byte/swu-happyrun/pull/79)。旧入口 db685 在 HTTPS 前把 Manager `15.0` 与 ADB release `15` 误判，instrumentation/fixture/HTTPS 均为零；此失败不能称为网络或服务端故障。

host 入口现在只在比较 Android release 时规范化：1–3 个 ASCII 十进制组件，各组件 0–999，主版本必须正，无前导零、空白、后缀或缺失；只删除尾部零组件。因此 `15`、`15.0`、`15.0.0` 等价，`15.1` 与 `15`、`14` 与 `15` 仍拒绝。Manager、ADB、binding 原值及各自规范 tuple 保留于本轮内存 `engine_version_evidence`；不改写原始版本或用户 binding，不将版本差异合成为运行状态。实例数量/index/真实 started flags、boot、安装 APK hash、host 版本与 Android 内 SDK/task/signature guard 保持原规则。

本修订不改变 Java adapter/产品/测试 CA。原配对 APK 仅在重新验证产品、adapter hash、公有 CA、签名和安装 hash 全一致后可复用；必须重新真实观测新鲜 binding，再由本地验收者复测。此代码修复本身不是 MuMu HTTPS 通过证据。

## 停止后的 recent task 身份（#82）

[PR #83 现场回执](https://github.com/Maximora-byte/swu-happyrun/pull/83)记录了旧 adapter 首例的真实失败：host 按已授权流程 force-stop 自身包后，instrumentation 读取到唯一且 task ID 一致的 recent task，但 `baseActivity == null`。Android hello/renew 均为 0，后五例未运行。现场未验证后面的 baseIntent、isRunning、numActivities 或 topActivity，不能推断这些字段已满足新检查。

旧检查把 Activity 仍然存活作为 task 归属的必要条件，与主动停包的测试生命周期不一致。[Android TaskInfo 文档](https://developer.android.com/reference/android/app/TaskInfo)区分 baseIntent 与运行中的 Activity；[Android 15 Task 源码](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-15.0.0_r1/services/core/java/com/android/server/wm/Task.java)和 [TaskInfoHelper](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-15.0.0_r1/services/core/java/com/android/server/wm/ActivityTaskSupervisor.java)也分别保留任务的 baseIntent、计算非 finishing Activity 信息。此依据说明旧生命周期假设错误，不证明某台 OEM 设备的新字段必然合法。

修订仍要求唯一自身 task、原 task ID、boot、双签名、包名、display 存在和显式模拟许可。baseIntent 必须有显式自身 component，PackageManager 必须能找到已注册 Activity，且其包、类名和 application UID 与目标应用一致。只有 `baseActivity == null`、`isRunning == false`、`numActivities == 0`、`topActivity == null` 同时成立，才接受没有 Activity 记录的 recent task。活动态则要求 running、正数 Activity 计数和自身包的 base/top Activity；矛盾或身份缺失一律拒绝。此判断只验证任务归属，不声称当前焦点、viewport 或 Activity/UI 生命周期通过。

本次 Java adapter 内容发生变化，旧 SHA256 `9a5094a55681c34dfae4bfc6015c16cbbf6d774156e52863ae44ab512cfa9c74` 的已安装 test APK不能代表修订。新 adapter SHA256 为 `7e172abd370a1380da9a3ebe0e89dff77bb1620218e5c11565cc8f39c2479eaf`；交付时还须使用最终受审 commit，并等该 commit 的 SDK35 build-only 编译通过。

技术上本次只影响 remoteQa test APK；产品 app、普通 pair、CA/leaf 均没有源码改动。现有受审 builder 没有单 test 重配功能，稳妥路径是保留旧 bundle，复用用户已有 CA/leaf 与本机签名环境，在**新输出目录**运行现有完整构建并生成新的配对 manifest，随后严格验证。无需重做证书，也不能手工改旧 manifest 的 adapter/hash 字段来冒充新构建。若新 manifest 中 remoteQa app SHA256 与已安装 app 读回值完全相同且签名/版本匹配，本地验收者可只更新匹配的新 test APK；若 app hash 不同，必须使用新 manifest 对应的同签名 app/test 配对，不能把旧 app 当成新 manifest 的产物。构建和安装由本地验收者执行，保留数据，不自动清库/卸载；重新真实观测 binding 后再运行。

新增 JVM 测试抽取 adapter 的实际 task 检查语句，以合成 Android 字段/PackageManager 返回做正反例；它验证判定逻辑，不模拟 Android 系统生命周期，也不替代 SDK 编译或原机 HTTPS 接续。#82 的现场失败保留，直到原机独立接受才决定关闭。
