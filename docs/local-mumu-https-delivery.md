# 9534 本地 MuMu HTTPS 成套构建交付

## 范围与现有产物

产品源固定 `9534f51efe3a557e6b4bda5605426e4004a34783`，tree
`53d6858c01b982e1143436018d7201e934c4ee58`。本交付工具单独版本化，不改变产品源。
这是本人隔离实例中的模拟 HTTPS 验收准备，尚未声称 MuMu HTTPS 或学校记录通过。
旧首次 hello 等间歇失败仍未归因；4c096 的官方 API35 模拟通过不替代本机验收。

[9534 普通包构建产物](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39246790835/artifacts/12183837270)
含 debug/selfProbe 及各自 test APK，2026-10-26 到期。ZIP SHA256：
`9036a93a32c72c54417c82aebe1743c020afa3cfbef124af6f715b8df606a6d8`。
该 CI 签名 SHA256 为 `e7501ada97f13004bd449c503321af310d1ebff67103cf73a4b5f2162f215683`。
普通包可继续离线验收；它与下述本地新签名组不可混配。
9534 自动 CI 的 remoteQa 只上传报告，没有 APK；临时私钥已清理。
即使取回当时公有 CA，也无法据此签发新的有效服务端证书。

## 本地前置条件

由使用者在自己的受控机器上安装官方 JDK17、Gradle8.9、Android SDK35/build-tools35、
Python3.11+ 与 OpenSSL3。SDK许可由使用者处理，脚本不自动接受条款。
Gradle 使用工程固定依赖；工具不下载未知安装器。Windows 可以使用官方 Gradle 的
`gradle.bat`、`apksigner.bat` 和 `apkanalyzer.bat` 的完整路径。
需要全新隔离构建目录及 Git 精确9534 checkout，不能有受控修改或未跟踪源码。
SDK位置使用本机已有环境配置，不向 checkout 添加 local.properties。

使用者自行生成短期测试 CA 和服务端证书，并私下保管 CA/服务端私钥。
证书应包含 critical BasicConstraints、适当 KeyUsage；CA 为 CA:true/keyCertSign，
leaf 为 CA:false/digitalSignature、serverAuth EKU，SAN 包含 MuMu **实际可达**的服务端 IP。
工具要求明确给出 RFC1918、ULA 或 loopback IP；不猜 10.0.2.2、不支持任意公网/DNS目标。
loopback 指当前设备自身，必须确认实际路由，不能把宿主 loopback 当成 MuMu 宿主地址。
由使用者确认 SAN、证书有效期、服务端私钥匹配与必要防火墙访问。
不安装系统 CA、不改变系统网络设置、不传输或提交任何私钥/令牌。

## 构建四个 APK

从交付工具 checkout 运行；`--source-root` 指向另一份干净9534 checkout。
所有占位符必须替换为本地确认值，命令不是已在本机运行的成功记录。

```text
python scripts/build_local_https_delivery.py --source-root <clean9534> --output <newBundleDir> --ca-cert <publicCA.pem> --server-cert <publicLeaf.pem> --host <actualPrivateIP> --gradle <officialGradleExecutable> --openssl <opensslExecutable> --apksigner <SDKapksigner> --apkanalyzer <SDKapkanalyzer> --aapt2 <SDKaapt2>
```

只读接受公有 CA/leaf。构建会在源码的忽略 build 目录暂放公有 CA、运行 Gradle clean，
并由 Android debug 签名机制使用/生成本机 debug key。私钥不会被复制到交付目录。
构建输出仅普通 debug app/test 与 remoteQa app/test、两个公有证书、delivery.json、SHA256SUMS。
同组四 APK 必须同证书；每对 test 必须指向同一个 app 包及预期 runner。
普通包不能带测试信任；remoteQa 必须明确禁明文且只增加所给 CA 的 debug 信任。
工具验证服务端证书链、IP SAN与有效期，保留平台 TLS/hostname 检查。
任何阶段失败都不形成已验收交付；不要使用失败留下的部分目录。

可选 `--adapter <RemoteMumuHttpsAcceptanceTest.java> --adapter-commit <40hex>`
仅临时添加唯一新的 remoteQaAndroidTest 测试文件，完成后删除该工具创建的文件。
manifest 分别记录9534产品和测试适配文件SHA/声明的来源commit；运行入口必须再对照已审版本。
来源commit是构建输入的可追溯声明，不是工具联网验证的签名证明。
无 adapter 时 runtime_capabilities 为空，不能调用旧 AVD 脚本代替 MuMu 入口。

## 离线复核与执行边界

```text
python scripts/check_local_https_delivery.py --bundle <newBundleDir> --ca-cert <publicCA.pem> --server-cert <publicLeaf.pem> --host <actualPrivateIP> --openssl <opensslExecutable> --apksigner <SDKapksigner> --apkanalyzer <SDKapkanalyzer> --aapt2 <SDKaapt2>
```

该命令重新检查 APK 内容/签名/公有信任绑定及manifest哈希，不启动设备、ADB或服务端。
另行受审 MuMu runner 负责明确实例绑定和本人模拟测试范围；尚缺该入口/目标host/公有证书/
配对 APK 时应停止并报告缺项。原 AVD 的 emulator/qemu 守卫和清库脚本不可绕过用于 MuMu。
remoteQa 包仅用于隔离 HTTPS 验收，不是日常分发包；同 appId 不能与普通版并存。
**若签名不兼容，不自动卸载、不清数据绕过。使用新隔离实例或原签名重新构建。**
本工具不会运行安装、修改 Root/LSPosed、写学校应用、上传记录或放宽任何网络预算。

当前云端证据仅源码/模拟工具回归；完整 SDK 编译、四APK实际配对与 MuMu HTTPS 均须本地实跑。

## Windows Gradle 输出修订（PR75 本机复测）

Codex 已在产品9534、工具3ac878、adapter db685上实际完成本机CA、同组四APK编译、
资源/签名/配对验证及新隔离实例安装。该成功产物事实保留；原工具的 Windows 文本管道
reader 在首次实际编译的 stderr 解码失败但未通知主线程，故工具本身不能接受为全绿。
现场二进制复核证明 stdout 是 UTF-8，stderr 可严格 GBK 解码；UP-TO-DATE 的无诊断
输出不能代替首次 clean 编译验证。详细记录见 [PR79](https://github.com/Maximora-byte/swu-happyrun/pull/79)
及 [PR75 本机反馈](https://github.com/Maximora-byte/swu-happyrun/pull/75#issuecomment-6268225149)。

修订对所有外部工具用 binary pipes，每路最多8 MiB，主线程检查读取错误、退出码、
原请求超时及线程结束；超限、超时、非法字节、reader错误均拒绝。失败清理最多另等
进程2秒及reader合计2秒，不能据此延长成功预算。它只结束自身启动的直接子进程；
若Gradle另有后代持有pipe，reader无法结束会明确失败，不能当作后台工作已全部停止。

默认两路都严格 UTF-8。**只对已核实的本机 Gradle stderr**，在原build命令额外指定：

```powershell
--gradle-stderr-encoding gbk --private-build-evidence "$newPrivateEvidence"
```

stdout仍严格UTF-8；证书、SDK XML、资源表、签名和Git机器输出始终严格UTF-8，
不受该flag影响。无自动编码猜测、ignore/replace、系统codepage或全局UTF-8模式修改。
这不是要求重建或上传现有用户CA/APK；由本地验收者决定是否做受控工具复测。

证据路径必须是**源码及交付包外的新目录**，父目录已存在且无符号链接；不复用旧目录。
ordinary/remoteQa各保留stdout.bin、stderr.bin及capture.json（仅固定原因、返回码、
预算、编码、捕获字节数及SHA256）。原始字节可能含本机路径或工具诊断中的敏感信息，
只留本人私有目录，不进Git、APK包、CI artifact或聊天。目录以0700、文件以0600创建；
Windows权限仍依本机ACL，由使用者选择已有私有父目录，工具不更改系统安全设置。
未提供该可选路径时仅有有界内存捕获，不持久保存原始日志；故障复测建议显式提供。
超限仅保存有界前缀，reason=output_limit，不能将该SHA当完整流摘要。

任一步失败不会输出 Four APKs verified，也不继续认定已有APK为本次成功。
本次仅修交付捕获，不改变9534产品、CA信任、配对schema或MuMu执行授权。

交付链对APK信任内容的检查复用已binary/strict UTF-8捕获的manifest，调用共享纯
check_manifest函数，不再隐蔽启动第二次apkanalyzer。共享脚本旧独立CLI wrapper的
文本捕获不在本次交付链中；本修订不宣称已处理全仓所有子进程输出。私有路径先词法
消除`.`/`..`，再拒绝路径父链的symlink并检查源码/交付包包含关系，不通过resolve
跟随链接绕过限制。
