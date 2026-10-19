# 60d0fee /784649d 原机接续复测

日期：2026-10-19（Asia/Shanghai），普通Windows账户，Codex现场执行。沿用[前轮交付](2026-10-19-local-mumu-https-attempt.md)的原产品、APK、CA/leaf和私钥，所有新证据另存私有目录；未覆盖旧manifest或旧失败记录。

**结果：版本等价与Gradle捕获修复已取得本机正反例；新的CRLF签名解析问题阻塞产物预检，HTTPS六项全部not_run。#75/#76暂不接受，#57/#78保持开放。**

## 准确来源

| 用途 | commit / tree |
| --- | --- |
| 产品，保持不变 | `9534f51efe3a557e6b4bda5605426e4004a34783` / `53d6858c01b982e1143436018d7201e934c4ee58` |
| #75 工具 | `60d0feeffc6670adc2a260adbc6a24a4e5059ecf` / `bedbf06301cf4dc91bc569c7f6d36b490b42cfeb` |
| #76 runner | `784649da65bea6d7bdb16953295b2001ea55cb6d` / `92547e80c29be36b188188f11775da53010016d1` |

三份独立checkout结束时仍干净。Java adapter SHA256仍为 `9a5094a55681c34dfae4bfc6015c16cbbf6d774156e52863ae44ab512cfa9c74`。原bundle八个文件逐字节摘要与前轮索引一致，原manifest的旧工具/adapter出处没有改写；本次新工具身份另行记录。

新准确HEAD的自动CI已分别核对：#75 push/PR checks及container四run均success；#76 push/PR checks、SDK35 build-only和container六run均success。Android build/static不计设备通过；无手动rerun或新KVM授权。

## 本机已通过的有限范围

- 原MuMu6.8.4.0 / Android15/API35独立实例重新开机；按实际Manager映射核对serial，读回原安装app/test SHA一致，重新打开实际MAIN入口。原私有IPv4的零数据TCP连接再验证通过。未重装、卸载、清库或改变网络/系统信任。
- 重新实际采集唯一task/display/focus、boot、app版本和新观测UUID/带时区时间。直接调用新runner的只读`open_binding` /`refresh_binding`：Manager原始`15.0`、ADB原始`15`、binding原始`15`全部保留，各自canonical为`[15]`，当前身份/安装hash检查通过。该读回不授予执行能力，也不绕过公有产物预检。
- 使用官方JDK17.0.20.1+1、Gradle8.9、SDK35/build-tools35.0.0，对新工具运行**真实clean首次编译**，使用源码及原bundle外的新输出/证据目录。默认UTF-8的负例builder exit2：原生Gradle exit0，76.407s，stderr451bytes，reason=`invalid_stderr_encoding`，reader_complete=true，未误报交付成功。
- 显式`--gradle-stderr-encoding gbk`时，普通/remoteQa两个首次编译分别原生exit0，27.891s/26.610s；capture均reason=ok、reader_complete=true、reader_error=false、timed_out=false，stdout严格UTF-8，stderr明确GBK。两份真实stderr仍非UTF-8，原bytes/hash一致，不是UP-TO-DATE跳过诊断。

## 新阻塞一：真实SDK输出的CRLF

上述显式GBK构建的**完整builder最终仍exit2**，发生于编译之后的SDK签名解析，未形成已验证新交付。对原已接受bundle运行新validator也拒绝；准确复现已交 [#80](https://github.com/Maximora-byte/swu-happyrun/issues/80) 和 [#75回执](https://github.com/Maximora-byte/swu-happyrun/pull/75#issuecomment-6269389621)。

实际SDK35 `apksigner.bat verify --verbose --print-certs`原生exit0，其严格UTF-8 stdout含Windows CRLF。新二进制捕获保留`\r\n`，而旧`text=True`曾作universal-newline归一化；原`check_android_delivery_pair.certificate()`用re.M与行尾`$`匹配，未消费`\r`，因此抛`Exactly one verified APK signer is required`。

独立只读诊断使用同一个真实输出：原文准确拒绝，仅在诊断变量中把CRLF改成LF后，同一严格解析器得到既有签名证书SHA256 `3ca7a8001517ea2822dd47c23f96d125e959ee0f9ddba324abea0e278f4015a2`。没有将诊断修正值输入产品、修改私有manifest或跳过签名检查。该诊断是定位，不计新validator通过。

Dot应保留原始bytes/摘要，在明确文本接口恢复换行语义或严格行拆分；补CRLF/LF及相关边界、同/多/错签名拒绝回归，不使用任意rstrip或放宽签名正则掩盖。

## 新阻塞二：测试源码读取仍依赖locale

新#76的`tests/delivery/test_mumu_https.py:119`仍为`Path(m.__file__).read_text()`；新版本规范docstring含UTF-8 en dash，普通账户默认GBK在offset5963/0x93抛UnicodeDecodeError，隐私guard断言未运行。已交 [#76回执](https://github.com/Maximora-byte/swu-happyrun/pull/76#issuecomment-6269314627)。Dot应显式UTF-8读取文本夹具/源码并保留断言，不删说明或改系统编码。

冻结产品Python3.11.16环境，明确产品src及两份新scripts路径；命令为 `python -m pytest <PR75>/tests/delivery/test_local_https_delivery.py <PR75>/tests/delivery/test_delivery_binary_capture.py <PR76>/tests/delivery/test_mumu_https.py <PR76>/tests/delivery/test_mumu_https_fixture.py <PR76>/tests/delivery/test_mumu_namespace_jvm.py <PR76>/tests/delivery/test_mumu_namespace_portability.py <PR76>/tests/delivery/test_mumu_version_binding.py <PR76>/tests/delivery/test_mumu_build_only_workflow.py <9534>/tests/contracts -q --junitxml=<PRIVATE>`。

实际 **271 passed /1 failed /4 permission skips /6 subtests passed，pytest exit1，20.99s**。旧namespace core已实际通过；三项symlink权限分支各自精确skip，加上既有一项权限skip，共四项，不计这些拒绝断言已通过。唯一失败是上述默认GBK读源码，不以托管绿灯或额外全套重跑覆盖。

## 六项入口与清理

真实新鲜binding准备后，以原APK/CA及三个执行开关调用新原始runner，公有预检因#80拒绝；入口返回2，artifact_preflight=not_passed、runtime_status=not_run，六项全部not_run。实际命令审计instrumentation0、fixture0，未发出本轮HTTPS请求，未测试到hello/数据库或前台连续任务。只读版本guard成功不能代替六项运行。

本次未使用新构建的部分输出，原八文件bundle及安装hash保持不变；新旧日志、证书/私钥、SDK原文、IP/serial、截图和数据库均留仓库外私有目录。核对身份后force-stop自身包并关闭测试实例，所有实例恢复停止。没有操作第三方乐跑、系统定位/传感器、Root、学校接口或生产环境。

Dot接续仅需修#80及测试UTF-8 I/O并给出新准确HEAD。保留原APK/CA和旧证据；若产品/adapter不变且证书有效，可复用原包，下一轮仍须重新观测真实boot/task/display和binding。#75/#76暂不合并，#57/#78按用户要求继续开放，完整产品和学校记录未接受。
