# 0cea241 /288ab69 原完整bundle及设备接续

日期：2026-10-19（Asia/Shanghai），Codex原普通Windows账户。**原完整bundle的新SDK验证/公有预检和301项聚焦回归通过；#75按工具范围合入候选、#80关闭。设备首例在Java guard失败，#76暂不接受，#57/#78继续开放。**

## 来源与产物复用

| 用途 | commit / tree |
| --- | --- |
| 实际受测产品，保持冻结 | `9534f51efe3a557e6b4bda5605426e4004a34783` / `53d6858c01b982e1143436018d7201e934c4ee58` |
| #75 工具 | `0cea241776c0233cd222213c475dec25aaf04be9` / `a70301e2113a85223c0c0d395efb5d432809a97d` |
| #76 runner | `288ab6919dd71344dc4c83132f9ddff867610569` / `a79fc1dda160082f0e8a7506dbcacc377bef90e3` |

三份独立checkout结束仍干净。复用[首轮交付](2026-10-19-local-mumu-https-attempt.md)的原八文件bundle、CA/leaf/key与安装app/test，逐hash一致，未使用[v2失败的部分构建](2026-10-19-local-mumu-https-retest-v2.md)。原manifest的工具/adapter出处不改写；Java adapter仍SHA256 `9a5094a55681c34dfae4bfc6015c16cbbf6d774156e52863ae44ab512cfa9c74`。本轮未生成证书、重签/重构建/重装APK或清库。

## 工具与主机回归

- Windows普通账户 /Python3.11.16 /Temurin17.0.20.1+1 /SDK35/build-tools35.0.0：新版validator对原完整bundle exit0，真实OpenSSL、apksigner、apkanalyzer、aapt2及签名/包/资源/信任绑定均通过。CRLF返回仅归一为LF，原bytes不变，不放宽单签名、孤立CR、错证书等拒绝条件。
- 新版公有预检exit0，artifact_preflight=passed、runtime_status=not_run；旧预检拒绝保留。本轮验证旧完整产物，未声称0cea新四APK完整build重新运行。v2真实首次Gradle默认拒绝/显式GBK捕获的有限通过继续保留。
- 工具/runner相关回归及共享契约 **301 passed /4权限skip /6 subtests passed，exit0，24.34s**。旧默认GBK读UTF-8源码失败已消除，原隐私断言实际运行；namespace core必跑，四个symlink权限skip不算对应拒绝断言通过。
- 命令：`python -m pytest <PR75>/tests/delivery/test_local_https_delivery.py <PR75>/tests/delivery/test_delivery_binary_capture.py <PR75>/tests/delivery/test_delivery_crlf.py <PR76>/tests/delivery/test_mumu_https.py <PR76>/tests/delivery/test_mumu_https_fixture.py <PR76>/tests/delivery/test_mumu_namespace_jvm.py <PR76>/tests/delivery/test_mumu_namespace_portability.py <PR76>/tests/delivery/test_mumu_version_binding.py <PR76>/tests/delivery/test_mumu_text_encoding.py <PR76>/tests/delivery/test_mumu_build_only_workflow.py <9534>/tests/contracts -q --junitxml=<PRIVATE>`。明确PYTHONPATH、冻结产品环境，未改系统codepage。
- #75准确新HEAD的checks/container四个自动run均success、bot neutral；#76准确新HEAD的checks/container/SDK35 build-only六个自动run均success。Android runtime未新授权；托管结果与设备结果分别记录。

## 三checkout的实际入口

直接执行runner目录的脚本时，Python把该目录置于PYTHONPATH之前；其旧`check_remote_qa_packaging`遮蔽新工具同名helper，缺少`check_manifest`，最初CLI预检拒绝。已独立复现该ImportError并保留失败。

验证可用的入口是在产品根目录使用模块方式：`PYTHONPATH=<tools>/scripts;<runner>/scripts;<product>/src`，运行 `python -m check_mumu_https`，参数沿用受审入口。逐一核对实际加载的runner来自288ab69、validator及packaging helper来自0cea241，文件hash与冻结源一致。设备QA调用同一来源的原`main`，只增加私有输出记录，没有替换实现、输入诊断修正值或跳过guard。请Dot更新跨checkout交接命令；这不是APK问题。

## MuMu首例实际失败

MuMu6.8.4.0 / Android15 API35独立实例重新启动；实际安装两APK读回hash不变、原私有地址TCP可达、MAIN入口真实解析。重新采集实例/serial映射、新boot、唯一task/display/focus、版本及30秒内新鲜binding；Manager15.0/ADB15/binding15原值保留、canonical均[15]，只读身份检查通过。

三个执行/force-stop/无个人数据开关明确给出后，真实fixture和instrumentation各启动一次。第一例`completed`的adb原生exit0，但JUnit **Tests run:1 /Failures:1 /Errors:0**；runner正确判失败，未因adb exit0误报成功。

堆栈固定为 `RemoteMumuHttpsAcceptanceTest.guard(RemoteMumuHttpsAcceptanceTest.java:91)`，该行 **`assertNotNull(task.baseActivity);`** 失败。方法此前的签名/boot/display、`tasks.size()==1`及task ID等同均已通过；字段实际为null。后面的baseIntent及component断言未运行，不能冒称已通过。host在instrument前force-stop自身包的真实序列完整保留；需要Dot核对API35停止/启动instrumentation时的任务生命周期，而不是删身份检查。

fixture仅记录host准备设备/任务的两个HTTP201，Android **hello_count=0、renew_count=0**。本轮尚未发起Android hello，不能称设备TLS握手、数据库或前台连续任务通过/失败。首例失败后其余五例not_run；runtime failed/exit1、device_verified=false。fixture正常退出，fixture/host清理错误均为空，未用污染后的套件继续执行。

新设备阻塞已交 [#82](https://github.com/Maximora-byte/swu-happyrun/issues/82) 和 [#76回执](https://github.com/Maximora-byte/swu-happyrun/pull/76#issuecomment-6269951490)。Dot修最小生命周期/身份路径，保留实例/boot/唯一task/签名/包和显式模拟许可正反例；如果改adapter，必须交新hash和配对构建说明，不能将旧APK声明为新adapter。当前原APK和证书均保留。

## 接受与集成范围

[#75接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/75#issuecomment-6269983011)只接受工具/原完整产物验证增量。已合入候选 `dot/android-foreground-agent`，merge **`839faf87cb0180f0732f2ef4278e4944bf1ccf70`**，parents为9534和0cea，最终tree与受审0cea完全相同。未把该新候选树当作本次运行的产品源，未借旧全套数量覆盖新候选。#80按CRLF修复范围关闭，完整#46继续Draft。

#76因#82暂不接受；#57/#78按用户要求继续开放，历史hello根因与#77数据库修复没有被本轮触及。Activity/UI、物理通道、第三方乐跑、vivo和学校记录继续独立验收。

结束后核对身份、force-stop自身包并关闭测试实例，所有实例恢复停止，原安装与数据保留。原始日志、请求/绑定、SQLite、IP/serial、截图、私钥均在仓库外私有目录；不操作第三方应用、Root、系统定位/传感器、学校接口或生产环境。
