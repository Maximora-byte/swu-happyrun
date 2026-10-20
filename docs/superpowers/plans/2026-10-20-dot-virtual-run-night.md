# MuMu虚拟跑步夜间交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dot交付能在MuMu实际回放虚拟轨迹的可安装工具，并推进步道乐跑4.3.1完整操作；Codex独立实测，争取下一日达到明确范围的可用状态。

**Architecture:** 复用已接受#85的参数编码，补原生有界执行器和#74自有探针读回；虚拟轨迹工具复用现有轨迹进度计算及取消边界。学校业务继续走既有DeviceDriver/AgentRunner与控制协议；本地回放与学校有效记录有独立结果，不能把fake后端冒充实际MuMu输入。

**Tech Stack:** Python3.11+、Windows/PowerShell、MuMu6.8.4.0/Android15 API35、Java/Android自有测试APK、SQLite/HTTPS。

**Spec:** [原设计](../specs/2026-10-18-swu-happyrun-design.md)、[控制协议v1](../../contracts/control-plane-v1.md)、[角色交接](../../handoffs/2026-10-18-dot-lead-sprint.md)、[既有任务2–4](2026-10-19-post-e490-device-delivery.md)。本轮最新用户要求及进度写入[执行Issue #86](https://github.com/Maximora-byte/swu-happyrun/issues/86)；旧计划时间表由本轮覆盖。

## Global Constraints

- 用户要虚拟定位、虚拟轨迹和模拟跑步，不要求本人到操场实跑，也不采集本人实时GPS。旧文档的physical/device指实际操作模拟器，与真实世界位置无关。
- Python3.11+，package `swu_happyrun`，CLI `swu-happyrun`，API `/api/v1`，protocol major `1`；不兼容wire更改先独立契约PR。
- Dot负责实现和测试，使用`dot/*`；Codex负责Windows/MuMu独立实测和合并。共享契约/依赖/CI改动先记本Issue，不写其他worker分支。
- 写入前持久化意图并核当前binding/授权/取消；开始或上传不确定、失租后不自动再次开始。停止不隐式调用结束上传。
- `needs_attention`可恢复；设备可能活动时，远程取消必须等明确stop-ack。未知通道、学校规则、选择器和协议不变成支持。
- `simulation`的fake后端约束和device任务能力门槛保持；本地虚拟回放是明确命名的本机工具，不借fake任务或虚构SchoolProfile取得学校成功。
- 不改Root/LSPosed、系统TLS/全局网络或生产服务。坐标、样本、截图、账号、SQLite、密钥只留本机；公开夹具用合成数据。
- 执行任务收到即可开工，无需等到晚间；1/3/6小时交检查点，目标日期为2026-10-21早间，Asia/Shanghai。目标不是预先保证业务验收通过。

## 基线与验收目标

候选为`ec15ea880012b85f7e25778b6b8d149553827040`、tree`2d55bd3cdb16fdaaeb7e4aa2b34cb4d6c2f779dc`。#85已接受，完整Windows1580通过/23条件skip/6subtests；#76六组HTTPS自身模拟已接受，#84报告已合main83757fd6。它们尚不证明虚拟轨迹已写入MuMu。

#74=`1377dc2ae1076580e5181831eb21333ba9cbd0f8`；#77=`45a2b9fde32f011f67eb62bf0c06c575188a18b2`，均待Codex接受。#74旧全套有HTTP超时，#77不是该历史失败的已证根因；#57继续按证据链处理。#61为独立探针设计，不能当作已合代码。

**A：虚拟跑步控制器可用。** 普通账户安装、选择MuMu/本地OSM路线/明确速度时长，实际回放；自有探针读到关联虚拟坐标，能暂停/继续/停止并说明停止确认状态。

**B：步道乐跑全自动可用。** 还须本人登录、正式学期规则、4.3.1操作页面和本次有效记录核验。A不是整个项目完成；缺失B的输入时，继续交付A及不依赖输入的代码，同时登记具体业务阻塞。vivo无Root/纯接口保持独立研究，不阻塞MuMu主线。

## Review Focus

1. 本地回放拿不到正式学校规则：本地速度/时长参数可使用，但不能填造SWU规则或成功记录；N3/N4覆盖。
2. Windows父进程超时而子进程继续发坐标：进程树清理、输出预算、不可重发和停止未确认必须明确；N1覆盖。
3. Android elapsedRealtime与宿主monotonic时钟不同：样本用设备时钟及关联标记，不直接比较两个时钟的数值；N2覆盖。
4. 取消发生在观测/写入间，或者暂停时仍有队列：最终写前再核授权，停止后不接受旧generation写入；N1/N3覆盖。
5. TYPE_GRAVITY、vendor gyro、步数并不等价，旧记录也不等于本次记录：分通道校准及会话绑定，无证据保持unknown；N2/N4覆盖。

## N0：集成前置项，交出第一份可测组合

**Files:** 沿用#74的`android/app/src/androidTest/java/org/happyrun/app/observation/`、`scripts/check_selfprobe_apks.py`；#77的`src/swu_happyrun/server/store.py`及`tests/server/test_sqlite_busy_response.py`。

**Interfaces:** 保留`AndroidObservation.start(ownTarget, channel, durationMillis)`和既有stopObserving语义；SQLite busy仍是503/database_busy/retryable，不放宽5秒HTTP预算。

- [ ] Dot从ec15在自己的集成分支准备#74/#77组合；保留各自准确HEAD，不改原Codex分支。Codex并行独立接受，未接受不宣称已合。
- [ ] `python -m pytest tests/contracts tests/android_contracts/test_owned_observation.py tests/delivery/test_selfprobe_packaging.py tests/server/test_sqlite_busy_response.py -q`；记录平台、exit、skip和历史HTTP失败，不盲重跑。
- [ ] 交自有selfProbe app/test同源同签名构建及本机观察步骤。权限由本人明确选择；普通/remoteQa权限不扩张，未知权限只阻塞对应观测。

## N1：MuMu原生有界调用与停止依据

**Files:** 新增`src/swu_happyrun/drivers/mumu/native_684.py`、`tests/agent/test_mumu_native_684.py`；消费`commands_684.py`、`binding.py`。停止依据记录到`docs/mumu-command-preparation.md`。

**Interfaces:** 新增`MuMuNative684(manager: Path, binding: MumuBinding, *, binding_check: Callable[[], None], authorization_check: Callable[[], None], clock: Clock)`；方法`write_location(point: GeoPoint, *, deadline: float) -> None`、`write_gyro(sample: tuple[float, float, float], *, deadline: float) -> None`、`stop() -> None`。deadline与clock同一宿主时钟域。stop未确认抛`DriverError("stop_unconfirmed")`；写入超时/回执不确定后实例永久拒绝新写，停止仍可尝试。

- [ ] RED：`test_expired_or_wrong_binding_starts_zero_processes`断言子进程数0；`test_timeout_after_side_effect_is_not_retried`断言写次数1；`test_stop_checks_all_channels_and_rejects_late_writes`断言停止遍历全部通道且旧generation新增写0；另测父退出/子存活、stdout/stderr超限和严格编码。
- [ ] 实现仅调用#85已核argv、`shell=False`与真实进程硬预算；不能提供任意shell命令或调用方`verified=True`解锁。选定实例/boot改变时拒绝，观测结束后紧邻写前再核授权。现有`drivers/command.py::run_readonly`仍只读，其替换解码/exit0不能作为写入回执；新增写路径保留严格字节证据与固定错误码，不全局放宽旧helper。
- [ ] 查明当前版本是单次设置还是厂商队列；停止轨迹推进可以保留最后一个虚拟坐标，不要求恢复真实GPS。无stop命令时，只能在证明无厂商排队、无在途进程且本地生产者关闭后确认；单纯join/kill、读回静止或停止监听均不足以独立证明所有条件。没有依据时交`stop_unconfirmed`，不编造reset命令。
- [ ] GREEN：`python -m pytest tests/agent/test_mumu_commands_684.py tests/agent/test_mumu_native_684.py tests/agent/test_mumu_calibration.py tests/contracts -q`；提交小PR，交可执行本机命令。模拟进程测试与厂商/设备证据单列。

## N2：自身探针私有读回与通道关联

**Files:** 修改#74 observation包；新增`src/swu_happyrun/drivers/mumu/own_probe.py`、`scripts/check_mumu_virtual_channel.py`、`tests/agent/test_mumu_own_probe.py`；扩展`tests/android_contracts/test_owned_observation.py`。

**Interfaces:** `OwnProbe.sample(channel: Literal["location", "gravity"], *, duration_ms: int) -> tuple[OwnSample, ...]`；`OwnSample`字段为`values: tuple[float, ...]`、`elapsed_realtime_ns: int`、`channel: Literal["location", "gravity"]`和原始`accuracy: float | int`，不混淆位置米数与sensor accuracy状态。使用每轮私有nonce/绑定摘要和设备侧窗口起点关联，范围沿用1–5000ms/128样本，不拿宿主时间直接减设备时间。

- [ ] RED：`test_old_nonce_or_boot_is_rejected`、`test_host_and_android_clocks_are_not_compared_directly`、`test_old_duplicate_or_late_sample_is_rejected`、`test_gravity_samples_do_not_enable_gyro_or_steps`；`test_private_readback_never_enters_public_report`断言公开JSON无坐标/serial/路径/nonce。
- [ ] 实现自有包内取样及本机私有桥接；保留listener关闭门、逐项注销和失败结果。位置无精确权限、没有回调、清理失败分别报告，缺样本不生成成功。
- [ ] 在隔离实例按已有授权流程提交有界试验；先交停止/队列依据，再由Codex写入。至少用两个不对称受控虚拟目标验证轴/坐标语义，原始点留本机；误差预算随试验声明。gravity单独观察，不把它当作vendor gyro或计步证明。未通过的通道保持关闭。
- [ ] GREEN：运行新增Python/JVM/SDK编译检查，交本机入口、固定包/签名及私有证据说明；Codex记录实际读回/停止结论和每通道缺失项。不得只交未接设备的fake seam。

## N3：可直接使用的本地虚拟轨迹控制器

**Files:** 修改`src/swu_happyrun/core/route.py`、`src/swu_happyrun/cli.py`；新增`src/swu_happyrun/drivers/mumu/virtual_replay.py`、`tests/agent/test_mumu_virtual_replay.py`、`docs/virtual-replay.md`。

**Interfaces:** `RouteExecution.for_local_replay(route: RouteProfile, *, speed_mps: float, maximum_duration_seconds: float, clock: Clock) -> RouteExecution`复用纯轨迹计算，正常构造器SchoolProfile校验保持。`VirtualReplaySession.start()/pause()/resume()/stop()`消费N1/N2和现有持久意图/设备锁/取消检查；它是本地工具，不新增远程JobSpec状态机。CLI为`swu-happyrun mumu replay --instance ... --route <LOCAL> --speed-mps ... --duration-seconds ... --execute-virtual-replay --isolated-no-personal-data`，没有execute开关只做无副作用预检。

- [ ] RED：`test_local_replay_does_not_fabricate_school_profile`、`test_preview_starts_zero_processes`、`test_pause_cancel_or_lease_loss_adds_no_writes`、`test_late_tick_never_bursts_missed_points`、`test_uncertain_stop_is_not_reported_success`；正常业务构造器仍拒绝不合学校规则的路线。
- [ ] 实现路线/版本/CRS和本地速度时长显式校验；复用现有OSM三路线，不重采，不生成官方SWU规则。日志仅进度/固定错误码，不输出连续坐标。写前留持久意图，恢复只核验/停止，不自动重开回放；暂停与停止各自验证生产者及在途动作。
- [ ] GREEN：`python -m pytest tests/agent/test_mumu_virtual_replay.py tests/contracts -q`加现有route suite；交普通PowerShell启动脚本。Codex做先单点后30秒有界轨迹的读回、暂停/继续/停止、中断和重复启动拒绝验收；实际试验由已核语义和原机结果决定，不把30秒当正式跑步指标。

## N4：步道乐跑4.3.1与服务器操作接续

**Files:** 沿用`src/swu_happyrun/drivers/budao/{adapter,selectors,records}.py`、`drivers/adapter_inputs.py`、`drivers/mumu/driver.py`、`agent/{runner,journal}.py`；测试`tests/agent/test_budao_states.py`、`test_record_verification.py`及`tests/integration/test_device_control_plane.py`。新增脱敏夹具必须注明实际版本/状态来源。

**Interfaces:** 保留`BudaoAdapter.inspect_state()/start()/finish()/read_result(...)`和DeviceDriver的prepare/start/tick/stop/verify；本轮native驱动不得复用`for_synthetic_testing`或FakeDriver作为设备执行后端。服务器继续现有协议与控制台，不新增绕过业务验收的mode。

- [ ] RED：未知页/错版本/旧观察拒绝动作；开始意图回执丢失不重发；旧会话/无稳定record ID/上传pending不能succeeded；取消只stop不finish/upload；离线恢复不产生第二次start。
- [ ] 按已取得样本实现4.3.1(231)/com.lptiyu.tanke支持部分，未知页进入needs_attention。本人登录/认证页由本人处理；正式学期规则、登录后页面和历史记录尚缺，逐项登记。XML139不可用时交有界截图采证/经校准识别的可测方案，不猜固定坐标点击。
- [ ] 将已独立接受的虚拟通道接入设备driver；仅在需要的通道、app_ui、record_read及规则都已验证时注册相应能力。先跑既有HTTP/fake故障回归，再按实际已有输入做设备业务验收；未取到本次有效记录继续pending/unknown，不能复制旧记录。
- [ ] 每个输入缺口给最小采集动作和负责方；不为补样本额外开跑或上传。缺B输入不阻塞N1–N3和可安装交付，也不把A称为B。

## N5：冻结交付与下一日验收

**Files:** 更新`scripts/build_local_https_delivery.py`、`scripts/check_local_https_delivery.py`及相关delivery测试；按实际新增selfProbe pair扩展清单与严格验证。更新`docs/status.md`和安装/支持矩阵，不把不同source的APK混成一包。

- [ ] 冻结source/tree；完整pytest、契约、Ruff/format/Schema、构建及普通Windows安装路径检查。只有最终准确HEAD的正常自动CI才计通过；排队/未授权/未运行分别报告，不重复触发工作流。
- [ ] 交wheel、实际所需ordinary/selfProbe/remoteQa配对APK、签名/哈希/manifest、PowerShell安装启动步骤、配置模板。复用原CA仅在仍有效且信任匹配时；需要更新时明确新旧来源，不放宽校验。
- [ ] Codex按同一冻结组合复测A及具备输入的B项目，#74/#77修复PR通过再合；#57按旧失败对应证据核查，不能用不同源绿灯抹去。保持软件、MuMu虚拟输入、乐跑记录三份结果。
- [ ] Dot在#86回报：1小时首个实现PR和本机命令；3小时执行器/读回入口及轨迹实现；6小时首份冻结可测包。目标2026-10-21 09:00交可安装候选及分项验收，提前完成提前交；失败给准确阶段/HEAD/最小下一动作，不预称全部完成。

## 自查与交接

范围已对齐原设计：N1–N3交MuMu虚拟控制器，N4保留完整乐跑/服务器目标，N0/N5处理集成和交付。五项Review Focus分别绑定了对应测试；纯编码、进程测试、探针观测、厂商语义和学校业务各自验收。建议的新增本地接口不改变wire契约；如果实现需要不同接口，Dot先在#86记录兼容理由。

本计划由用户明确要求交Dot执行，不再等待选择执行方式。GitHub发布只代表任务可读取，不代表Dot已接单；Dot首次开工需在#86回复实际环境、采用SHA和首个PR。Codex继续独立接受，不使用Matrix自动派发。
