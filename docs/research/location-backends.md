# 可选定位后端：R5 固定源码接口审查

审查日期：2026-10-19（Asia/Shanghai）。关联 [Issue #11](https://github.com/Maximora-byte/swu-happyrun/issues/11)。仅独立研究，不开启真实能力，不阻塞 R1–R4。

## 结论与执行边界

LocationSpoofer **有外部 START/STOP broadcast 入口**，不能写成“完全没有外部接口”。但已审调用链没有本项目所需的认证 job/session/fence 绑定、消费端停止确认和独立只读回查契约。广播发出、Receiver 完成、配置写入、前台服务停止分别是不同层次，均不能单独成为设备 stop-ack。

固定源码：sun-zihang/LocationSpoofer `dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7`。本次通过 GitHub 只读工具逐文件检查下列链接与递归树；未构建、安装、运行第三方 EXE/APK，未发送广播、连接设备、写位置/传感器、修改 Root/LSPosed/权限/系统保护，未运行第三方测试。真实设备与学校记录均 `not_tested`，当前候选接入为 `unsupported_by_this_candidate`。

[LICENSE](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/LICENSE) 声明 GPL version 3 or any later version，即 GPL-3.0-or-later。这里只写原创分析和接口需求，不复制 GPL 实现到本项目，不分发 APK。若日后考虑复用或组合分发，须先明确来源、修改、分发边界与许可处理，不把“独立进程”自动当作免除许可义务的结论。

## 文件/方法证据

| 能力 | 固定源码与方法 | 可以证明 / 不可证明 |
| --- | --- | --- |
| 外部入口 | [AndroidManifest.xml](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/AndroidManifest.xml)；[SpoofingControlReceiver.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingControlReceiver.kt) `onReceive/handleStart/handleStop` | Receiver exported=true，声明 START/STOP；此 manifest 未给该 receiver 配置 permission，所审方法也未认证调用者。不能据此宣称完整 APK 所有构建变体都已做安全测试。 |
| 启动参数 | [SpoofingControlReceiver.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingControlReceiver.kt) `handleStart` | 仅解析 int `favorite` 索引，读取用户已保存点；非法索引直接返回。以 STILL 模式调用 repository，不接收任意坐标、路线、job/session/fence/idempotency key。不是可直接映射本项目 tick 的定位写接口。 |
| 服务边界 | [AndroidManifest.xml](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/AndroidManifest.xml)；[SpoofingService.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingService.kt) `onBind/onStartCommand` | 服务 exported=false，onBind 返回 null；没有从此服务取得外部 Binder 查询接口。内部 ACTION_START 可带 lat/lng，但不能把内部 Intent 当作公开 RPC。 |
| 本地控制抽象 | [SpoofingServiceController.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/data/repository/SpoofingServiceController.kt)；[SpoofingServiceControllerImpl.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingServiceControllerImpl.kt) `startForeground/stop/isRunning` | Kotlin 注入接口，不是 IPC 定义；isRunning 读取服务进程静态 boolean。stop 吞掉 stopService/startService 异常，无返回的消费端确认。 |
| 启停副作用 | [LocationRepository.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/data/repository/LocationRepository.kt) `startSpoofing/stopSpoofing` | 启动调用 rootManager.grantMockLocation；停止清本地状态、saveConfig(false)、清理 TestProvider、停服务、revokeMockLocation。停止未检查 saveConfig 返回 Boolean，清理多处吞异常；这不是无 Root 后端或纯只读检查。 |
| 配置发布 | [ConfigManager.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/utils/ConfigManager.kt) `writeLocked/publishLocked`；[FrameworkConfigPublisher.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/utils/FrameworkConfigPublisher.kt) `publish` | desired_config 本地持久化；框架断连会返回 false、保留最新配置，并每 3 秒及重连重发。发布成功表示框架存储 commit 接受 snapshot，包含随机 id/published_at；不是当前 job/session/fence，更不是消费端已应用确认。 |
| 消费端 | [FrameworkConfigReceiver.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/xposed/src/main/java/com/vincenthzr/locationspoofer/xposed/utils/FrameworkConfigReceiver.kt) `start/refresh/close` | 注册配置监听并每秒刷新，decode 后 onConfig；异常保留最后有效内存快照。所审类没有把 applied/stopped ack 返回外部控制方的路径。stop 配置未读到时旧 active 状态可能仍在，不能按固定 sleep 推定停止。 |
| 自动恢复 | [BootCompletedReceiver.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/BootCompletedReceiver.kt) `onReceive`；[LocationRepository.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/data/repository/LocationRepository.kt) `recoverAfterBoot` | 重启/包更新恢复可能依 isSpoofingActive 再次 startSpoofing；ConfigManager 重连也会发布 desired_config。与本项目恢复仅回查、禁止隐式第二次开始的约束不能直接混用。 |
| 回查 | [SpoofingControlReceiver.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingControlReceiver.kt)；[SpoofingService.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/service/src/main/java/com/vincenthzr/locationspoofer/service/SpoofingService.kt)；[LocationRepository.kt](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/core-data/src/main/java/com/vincenthzr/locationspoofer/data/repository/LocationRepository.kt) | 已审外部 broadcast 仅 START/STOP；本地布尔量、最后坐标、发布时间不构成认证只读设备状态或学校结果接口。结论限于本次所审入口及调用链，不声称逐行排除了全仓库的一切接口。 |

应用 manifest 另核于 [AndroidManifest.xml](https://github.com/sun-zihang/LocationSpoofer/blob/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7/app/src/main/AndroidManifest.xml)；本次未生成 merged manifest，因此包级实际权限/签名/组件暴露情况仍需对未来获准候选单独验证。

## 停止确认为什么仍缺失

1. `goAsync()` 的 PendingResult.finish 只结束广播处理；Receiver 没有结构化响应或命令关联结果。
2. `stopSpoofing` 可能已把本地状态改成 inactive，但框架断连使 stop 配置尚未发布。
3. 框架 commit 成功与消费端 refresh/onConfig 是分离步骤；读失败保留旧快照。Publisher 自身也明确区分 Binder 回应丢失与写入拒绝。
4. 前台 Service 的 isRunning=false 或通知消失，只表示该服务本地生命周期；没有证明所有消费端已停、队列排空、不会恢复重发。
5. 因此当前广播包装不能发 stop-ack，不能据此释放设备再次运行；必须保留 `stop_unconfirmed` / `needs_attention`，不得为确认停止自动结束或上传学校记录。

## 独立适配设计，仅需求，不实现/启用

不能仅在旧广播前套一层 host-side guard：外部入口和框架重连/重启仍可能绕过它。后续如用户另行选择该方向，先提交独立版本/许可/权限方案，再评审以下接口要求；不是本项目 wire v1 的字段变更：

- 认证边界：仅允许已验证的本地代理，绑定调用方身份与选定设备/应用版本；禁止公网裸 RPC、任意 URL 或未认证广播执行。凭据/持续权限扩展另行授权，不在本次创建。
- 会话边界：本地绑定 job/session/profile/app_version、device-binding digest、单调 fence 与有效期限；每个副作用前重新检查持久意图、当前锁、取消与预算。幂等命令关联必须在设备执行端生效，旧会话不能覆盖新会话。
- START：接受前持久化关联意图；明确 accepted/applied/unknown，超时不再次开始。只能采用已核准输入范围，不把 favorite 索引当稳定点位身份，也不继承该源码坐标换算或步频默认值。
- STOP：与 finish/upload 分开；取消/清空本会话未执行队列、持久化停止状态，阻止旧 active 在重启/重连后重发。设备消费端返回绑定会话、fence、命令序号的 applied-stop 与排空证据；只有这些证据及新鲜回查一致才可确认。
- 只读 query：返回认证来源、boot/process epoch、会话/fence、最后接受/应用序号、待执行队列、停止状态、观测时间和版本；不得调用 recoverAfterBoot、重新启动、写配置或申请 Root。位置读回还需显式 CRS、校准和观测有效期；学校记录另由当前版本的关联证据核验。
- 失败关闭：跨进程读不到、状态过期、消费者不完整、版本不匹配、任何 stop 不确定均保持不可执行。没有设备端支持时不宣称仅靠代理即可补齐。

未来独立验收应覆盖：伪造调用方、旧 fence、同命令重放、双会话、停后积压、断连停止、重启/包更新、publish 成功但消费端读失败、停止回应丢失、verify_only 零副作用。此处是待测要求，没有声称执行或通过。

## R5 证据矩阵与下一步

| 路径 | 当前输入 / 实际范围 | 结果 | 下一最小证据 |
| --- | --- | --- | --- |
| LocationSpoofer | 上述固定 SHA/许可，逐方法静态审查 | 有受限广播，无已证实安全会话及停止回查契约；未接入 | 用户明确方向之后，独立接口/权限/许可方案及可控自身测试环境；不要求先 Root |
| vivo X200 Pro | 只有用户报告型号；旧教程来自其他型号 | 实机 Android/ABI/版本及连接未知，not_tested | [私有只读清单](vivo-noroot.md) |
| 当前学校纯接口 | 尚缺本人当前版本脱敏协议/签名语义 | 不构造/发送正式请求，not_tested | [协议输入门槛](direct-protocol.md) |

研究不是运行授权；R5 不改变现有能力列表、CLI 门禁或真实版本注册表。后续 #11 回报应分别记录静态审查、离线测试、设备接受与最终记录，不合并称“已支持”。
