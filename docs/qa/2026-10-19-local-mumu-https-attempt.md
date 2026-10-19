# 本机 MuMu HTTPS 构建与入口复测

日期：2026-10-19（Asia/Shanghai）。Codex按 [#41交接](https://github.com/Maximora-byte/swu-happyrun/issues/41#issuecomment-6267549476) 实际执行。**证书、四APK编译/校验和新隔离实例安装已完成；六项入口在HTTPS前被版本守卫拦截，设备HTTPS尚未验收。** 本回执不修改产品代码或门槛。

## 冻结来源与环境

| 用途 | 准确提交 / 证据 |
| --- | --- |
| 产品 | `9534f51efe3a557e6b4bda5605426e4004a34783` / tree `53d6858c01b982e1143436018d7201e934c4ee58` |
| [#75构建工具](https://github.com/Maximora-byte/swu-happyrun/pull/75) | `3ac878f0e62869705f81007f72ae2bcf0a55083e` / tree `4e7e61e985f250f10d90cee3436709ea31921cf1` |
| [#76 runner/adapter](https://github.com/Maximora-byte/swu-happyrun/pull/76) | `db685c369afbaafdc9dda76a2873a1800ed84d75` / tree `7f432845d3f25ebfbbe4c9b5071a45ea09485cf7` |
| 唯一Java adapter | `android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/RemoteMumuHttpsAcceptanceTest.java`；SHA256 `9a5094a55681c34dfae4bfc6015c16cbbf6d774156e52863ae44ab512cfa9c74` |
| 主机 / 编译 | 普通Windows账户、Python3.11.16冻结server/agent/dev依赖、官方Temurin17.0.20.1+1、Gradle8.9、Android SDK35/build-tools35.0.0 |
| 设备 | MuMu6.8.4.0，全新无个人数据的Android15/API35实例；原有实例保持停止 |

使用三个独立detached checkout；工具/adapter头不当作产品头。Gradle和JDK的官方下载校验和已核对，使用已有SDK及许可，没有自动接受新SDK条款。三份源码在构建清理后均为原准确HEAD且无受控修改或未跟踪源码。**#74/#77没有叠入本次9534**；#77的源码/CI/后续组合独立审查。

## 已完成的准备

1. 实际查询新实例和ADB映射，确认boot完成；对本机实际私有IPv4做MuMu零数据TCP连接并由宿主listener确认接入。地址不靠AVD默认值推断，未改防火墙或系统网络。
2. 本机生成三天有效的独立CA和server key/cert；CA/leaf角色、KU/EKU、严格证书链、实际IP SAN及leaf/key匹配检查通过。私钥仅保存在仓库外私有ACL目录，未装系统CA。公有证书也不随本公开报告上传，因为leaf含本机地址。
3. 调用准确#75工具，先实际 `clean assembleDebug assembleDebugAndroidTest`，再带公有CA/唯一adapter运行 `-PremoteQaInstrumentation assembleRemoteQa assembleRemoteQaAndroidTest`。两次Gradle分别exit0、164.547s及34.375s，stdout均有BUILD SUCCESSFUL；同时发现下述stderr捕获缺陷，不能称工具完全通过。
4. `check_local_https_delivery.py`重新校验包名、版本、runner、签名、manifest/资源与公有信任绑定；ordinary无附加测试信任，remoteQa仅绑定本次CA且禁明文，两test无额外信任/私钥。四APK校验及独立公有预检exit0，预检runtime明确为not_run。
5. 新实例安装本次remoteQa app/test，逐个按实际安装路径读回APK，SHA256与交付manifest一致；启动实际解析的MAIN组件，目视确认自身首页。未混用旧CI签名，未覆盖、卸载或清理原实例应用。

同组APK签名证书SHA256：`3ca7a8001517ea2822dd47c23f96d125e959ee0f9ddba324abea0e278f4015a2`。

| 本地文件 | bytes | SHA256 |
| --- | --- | --- |
| ordinary.apk | 104352 | `7c39d9180994cb6cf45401b0c819425ee015d446b9d96376917d3aff02c2a005` |
| ordinary-test.apk | 38892 | `4e459e2a8812c307815cf811aad3dea0e7ab6f20ef0b0dc98dc3a4da285a8f44` |
| remoteQa.apk | 107958 | `12e1cd381d31f6bfd0a5048a14a01f1ba969de70820e3a10dc77a2adbff54789` |
| remoteQa-test.apk | 67626 | `091e9dbd1078f2e5f8513ceab6d3d7f08aa1617172344a6f431d2861da4c6d04` |

交付目录只有四APK、两个公有证书、delivery.json和SHA256SUMS。完整文件与日志留本机，不重新分发remoteQa测试包；产物完整性与工具诊断可靠性分别验收。

## 实际执行结果：版本守卫阻塞

实际核对唯一自身task、当前display/focus、boot、Manager实例/serial映射、app版本；生成当轮全新UUID/带时区时间，绑定格式检查通过后立即调用原#76入口，三个执行/force-stop/无个人数据开关均显式提供。没有复制旧观测时间，也没有绕过AVD或MuMu guard。

入口exit1、artifact_preflight=passed、runtime_status=failed：首例completed在准备阶段得到RuntimeError，后续two_jobs、disconnect_running、lost_renew、cancel、restart均not_run。私有实际子进程命令审计确认 **instrumentation调用0、fixture启动0、HTTPS场景实际运行0项**。因此不是hello失败、DB超时或TLS握手失败，不能用这次结果证明#57根因或修复。

阻塞已提交 [#78](https://github.com/Maximora-byte/swu-happyrun/issues/78)：同一已运行实例，Manager原始 `android_version="15.0"`，ADB原始release=`"15"`、SDK=`35`。`refresh_binding`把 `instances[0].android_version == binding.engine_version` 字符串比较纳入running谓词；binding使用ADB真实release时该谓词false。改填Manager字符串又会使后续ADB字段比较失败，不能靠伪造binding满足二者。

独立只读复现调用原`validate_current`，准确拒绝原因 `current_instance_or_installed_pair_mismatch`；单实例/index/android started/process started均true，安装两个APK hash一致，唯一失败谓词是版本字符串等同。保留原版本证据，等待Dot定义严格等价规则与错版本拒绝回归，不通过忽略版本或手填running=true继续。

## 另外两项本机失败

- **#75 stderr读取线程异常：** 两次首次实际编译均发生 `UnicodeDecodeError`（UTF-8 offset259 /0xca），但Windows子进程管道线程错误未传给主调用，工具继续报告四APK已验证，stderr丢失。用同一真实Gradle的clean debug编译作二进制独立复现：exit0/25.5s，stdout严格UTF-8通过，stderr严格UTF-8在同offset/byte失败、严格GBK可解码。UP-TO-DATE构建无该诊断，不覆盖首次失败。见 [#75复现](https://github.com/Maximora-byte/swu-happyrun/pull/75#issuecomment-6268225149)。Dot修有界字节捕获/明确解码/错误上浮，不改系统codepage或ignore/replace。
- **#76 namespace权限夹具：** JDK17的`Files.createSymbolicLink`在普通账户抛`FileSystemException: 客户端没有所需的特权`；测试只捕获UnsupportedOperationException，整项exit1。此前非symlink行为已经运行，不能因此计整项通过或全部跳过。见 [#76复现](https://github.com/Maximora-byte/swu-happyrun/pull/76#issuecomment-6268039888)。Dot分开必跑行为和精确权限跳过，有能力的平台保留symlink拒绝断言。

冻结产品Python3.11.16环境明确使用产品src、#75/scripts和#76/scripts；执行新增工具/runner/fixture/JVM/workflow测试及共享契约：**201 passed /1 failed /1 permission skip /6 subtests passed，pytest exit1，18.43s**。失败为namespace；skip为现有symlink能力探测。命令形状为 `python -m pytest <PR75>/tests/delivery/test_local_https_delivery.py <PR76>/tests/delivery/test_mumu_https.py <PR76>/tests/delivery/test_mumu_https_fixture.py <PR76>/tests/delivery/test_mumu_namespace_jvm.py <PR76>/tests/delivery/test_mumu_build_only_workflow.py <9534>/tests/contracts -q --junitxml=<PRIVATE>`。

QA外层第一次打印另有GBK编码异常；以上数量/exit取自打印前的真实pytest子进程及JUnit。保留原始输出，只修QA打印，不改产品测试/断言/系统编码。没有重复完整1298项掩盖聚焦失败；托管绿灯也不覆盖本机结果。#76重复push的optional/API35 Maven429继续保留外部失败，未手动重跑或触发新KVM授权。

## 清理与接续

已再次核对新实例身份后force-stop自身包并关闭新实例；终态Manager确认所有实例停止，原实例身份未改。保留本次安装、交付包、证书与失败证据，没有清库/卸载/删除实例。未操作第三方乐跑、系统定位/传感器、Root、学校接口、生产服务器或DNS；账号、IP/serial、原始截图、私钥、SQLite均未进入Git。

Dot先修#78及两个Windows问题；Codex按新准确HEAD复测。若仅修host runner且adapter/产品/CA未变化，可在核对哈希和证书仍有效后复用此配对；下一轮重新开机并采集真实新boot/task/display和30秒内binding。若adapter或产品变更，按新身份重建成套APK，不手改manifest冒充9534。#74/#77分别审核，不自动混入旧产物。

本轮 **#75/#76暂不接受合并，#57及完整#46继续待验收**。只有六项及fixture/进程清理均实际通过后，才能接受该自身app模拟HTTPS范围；Activity/UI、真实通道、第三方乐跑和学校有效记录继续独立验证。
