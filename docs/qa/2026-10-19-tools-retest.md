# 2026-10-19：#62 / #65 独立复测及 #63 诊断回执

本地Codex，Windows普通账户（Administrator=false），未提权。产品修复由ChatGPT Dot负责；本轮仅执行独立主机/设备检查、按范围合并和提交QA文档，没有Matrix消息。

## 判定

| PR | 准确修订 | 结果 |
| --- | --- | --- |
| [#62](https://github.com/Maximora-byte/swu-happyrun/pull/62) | `7aeddd4cd21df8adeb78154e2c50d74404e4afba` | **不接受/未合并**：原普通账户真实JVM仍失败，[#59](https://github.com/Maximora-byte/swu-happyrun/issues/59)开放 |
| [#65](https://github.com/Maximora-byte/swu-happyrun/pull/65) | `c7e260b7eafe58d06277afc106f167db5dd3a2ba` | 按自身应用采证工具范围接受，merge `6dda2a4e74e40b92387bcbede2ec4db28abb7662` 合入原候选；[#58](https://github.com/Maximora-byte/swu-happyrun/issues/58)关闭 |
| [#63](https://github.com/Maximora-byte/swu-happyrun/pull/63) | `fdd71853f7fe25bbc33d707fe22c0065aebf1f3a` | 已由Dot合入候选merge `ba990eaf626737c8ef77afe037fe7ad1b8954ed6`；独立核对诊断范围，未重复合并，未认定[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57)修复 |

完整产品仍未接受进入main。#65接受不覆盖#62或API35 HTTPS失败。

## #62：成功保留失败证据，真实导航仍未通过

环境为Windows / Python3.11.16 / Oracle JDK25.0.4.1，使用隔离候选工作树并显式绑定父子进程 `PYTHONPATH=<candidate>/src`，未修改locale、codepage、JVM或编译flags、预算和断言。

```text
python -m pytest tests/delivery/test_android_native_navigation.py tests/delivery/test_navigation_output_capture.py -q -W error::pytest.PytestUnhandledThreadExceptionWarning
31 passed / 1 failed，15.48s，exit1
```

失败为 `test_native_navigation_shared_budget_and_actual_adapter` 的实际javac阶段：

```json
{"stage":"javac","reason":"invalid_utf8","stream":"stderr","encoding":"utf-8","stdout_bytes":0,"stderr_bytes":214}
```

新捕获不再把解码异常丢在后台读线程，31项合成拒绝回归通过；它安全暴露了本机真实失败，不能因此将原账户验收标为通过。用新私有目录再次运行 `check_native_navigation.py --private-output-dir PRIVATE_NEW_DIR`，同样exit1、失败字节保存成功。原始字节只在用户本地私有目录，未上传GitHub。

只读查询实际JVM属性：native.encoding=GBK、stderr.encoding=GBK、file.encoding=UTF-8、user.language=zh、user.country=CN。这是JVM实测声明，不从单字节猜编码，不通过ignore/replace、改全局编码或跳过真实JVM使检查变绿。未在已知聚焦失败后重复完整套件。[失败回执](https://github.com/Maximora-byte/swu-happyrun/pull/62#issuecomment-6264082747)已交Dot继续修订；托管Windows通过不覆盖原机器失败。

## #65：准确源码与主机组合检查

Windows普通账户 / Python3.11.16：

| 检查 | 结果 | 退出 |
| --- | --- | --- |
| 准确C7：`pytest tests/delivery/test_mumu_evidence_entry.py tests/delivery/test_display_observation.py -q` | 39 passed /1 skipped（POSIX FIFO） | 0 |
| 准确C7：完整pytest | 1177 passed /16 skipped /2 warnings，188.81s | 0 |
| C7与当时候选ba990ea的组合：完整pytest | 1193 passed /16 skipped /2 warnings，159.72s | 0 |
| 聚焦Ruff、Schema漂移、git diff whitespace | 通过 | 0 |

组合commit `9bb9452b903bda124954be87d0bf2702131e5625`，tree `f968094ec7c60e27c91a06098a75fefb1de06f25`；四个PR拥有路径与C7逐字一致。GitHub最终merge `6dda2a4e74e40b92387bcbede2ec4db28abb7662` 的tree与组合完全相同。

16项跳过为3项POSIX信号、6项普通账户符号链接权限、6项POSIX shell和1项FIFO。两项warning为继承的Starlette deprecation及未合入#62时的JVM读线程解码问题。**这些完整套件的exit0不构成原机器真实JVM导航接受**；#59仍以#62的准确拒绝证据阻塞。#65只接受其自身采证改动，未隐藏该warning。

独立只读代码审核未确认新增P1/P2，原native accepted判定未改；另在独立快照复跑#65新合成用例35 passed /1 FIFO skip、#62合成回归31 passed、#63诊断14 passed。修复PR的push/PR主机、浏览器、容器和Android build/static检查通过；Android runtime未授权/未执行，未计作设备证据。

## #65：新MuMu实例与配套产物

主机安装信息核对为MuMu6.8.4.0。本轮另建无个人数据Android15 QA实例，未克隆、启动或改动原用户实例及之前的e490 QA实例。每次ADB动作前核对实例index/name/创建时间/当前实际映射，原两实例均保持停止。没有猜端口或选择第一台设备。

实际使用准确C7 / tree `b87706b37f5f92b5f1dea45abd083651248ceb96` 的[push run39229373174](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39229373174)，API35 selfProbe artifact `12176217473`；ZIP SHA256 `4651a9bc62cb28b6b723a4b37ffdd02d6f79804bb38fe9d134f7835c0151d648`。同一归档提供debug与selfProbe各自app/test。

| 产物 | SHA256 |
| --- | --- |
| debug app | `38157cfd4303ca4b3bb606b8e1d154a5f949760c1edacf7cf0a3a62770cdb5d9` |
| debug test | `c1ac914acc00a2c185670c38e4159c042f630b4440492459041f163c3b9dd612` |
| selfProbe app | `17bd6dccccabd7c875d203d5f9da0ffa05992a2171a80c20e7ca4669926a6482` |
| selfProbe test | `3b252ca8f7b24d6eb94e9210a68d072de8e00e94e53f5f330823953f92bf0bdd` |

官方apksigner验证配套签名，四包证书SHA256均 `169ae0e4c30a64b20396deed0fa1f44fa9c36090fe10a61fec8d0fe6bb61416a`。证书与旧e490不同，因此使用新实例，未覆盖旧安装。装包无`-g`，同证书debug→optional仅`install -r`，实际安装路径读回的APK哈希与对应文件一致。JDK25 native-access warning保留，未改保护配置。

## #65：14项实际入口检查

主机采证CLI使用Python3.13.15；测试脚本来源准确C7。普通与optional分别执行：

- 一个native正例：通过显式官方 `--adb` 路径，独立取唯一自身task与实际焦点display，验证包/配套证书/可见控件；checker exit0、observed。
- 三个实际身份反例：错签名、不存在display、错误task，均checker exit1，分别为signature_mismatch、display_missing、task_id_mismatch。
- 一次新UUID文件采样：采样前确认文件不存在，前后核对相同自身task/display/focus；实际vendor dump均exit139。分类器为vendor_dump_nonzero、dump_succeeded=false、driver_input_permitted=false、record_verified=false、exit1；manual_review_candidate=true仅是操作者陈述的一致性分类，不是独立设备证明。
- 两个派生陈述反例：对该本地捕获分别声明未建立新鲜性、焦点改变，均拒绝、exit1；这不是实际制造了两次物理焦点变化。

共2个正例、6个实际native拒绝、2次实际dump非零保留、4个派生陈述拒绝。所有14项符合预期；没有将预期exit1计为dump或真实执行成功。135路径由合成回归覆盖，本轮两次实际dump都是139，不冒称实测135。

native `writes=0`只指测试发出的模拟/控制/输入动作；instrumentation可重启自身进程、恢复自身task并触发生命周期持久化。本轮没有运行完整普通/optional各30项，也没有借用历史e490结果。首次主机helper因窗口使用完整Activity类名而在观测前停止，核对实际dumpsys后修正为同一Activity的明确等价表示，并增加全局焦点检查；这次QA前置失败未计为产品缺陷或通过项，未改产品门禁。

结束后只force-stop自身测试包并停止新QA实例，保留安装和数据；三个实例最终均停止。未卸载、清库、改Root/框架、位置/传感器或TLS。原始XML、窗口、ADB身份、UUID和数据库未提交。[接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/65#issuecomment-6264238687)。#58按自身native采证及XML分类关闭，vendor139/135本身未修复。

## #63集成后：API35实际仍失败

独立核对[run39230003649](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39230003649)，source ba990ea、API35 job117985398817，runtime authorized=true / failed。artifact12176614055 ZIP SHA256 `86eca83d4bca41709fbfd08fa725fc5766821f004592ab057f9bfef7641a21f8`匹配。

本轮15项协议场景均passed，lost_event本次通过；不能据此说历史lost_event根因已修复。前台首项two_jobs主体passed，有TWO_DONE、STOPPED starts=2和PASS标记，但整体FixtureLifecycleError：host_phase=validate_stopped，fixture_phase=shutdown，fixture_shutdown_code=shutdown_failed。服务线程仍活、connections=1/tasks=0；连接transport_closing=true、ssl_state=SHUTDOWN，线程仍在event-loop select，项目tick_loop仍存在。

因此two_jobs整体失败；后续13项前台场景not_run/fixture_contaminated，durable recovery/live-fence报告未生成，仍未运行。#63保留了准确阶段和原预算，并未修掉实际退出问题。最新[证据回写#57](https://github.com/Maximora-byte/swu-happyrun/issues/57#issuecomment-6264192114)交Dot继续定位TLS/fixture关闭，不吞cleanup、不扩大预算或用主体PASS替代终态。

下一步：Dot修#62的原机器可用路径和#57 fixture退出；Codex继续准确HEAD复测。地图#64、MuMu真实通道、实际乐跑与学校记录仍按各自输入和现场证据推进，不由本工具接受结果开放能力。
