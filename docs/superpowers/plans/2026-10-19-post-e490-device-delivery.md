# e490 后续开发与设备交付计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项执行。Dot 主导产品实现，本地 Codex 负责取样、现场测试、独立接受和集成；本计划不发起 Matrix 或新代理会话。

**Goal:** 收尾当前软件阻塞，先接受新候选在 MuMu 上的自身模拟闭环，再实现有现场依据的真实通道、指定乐跑版本适配及服务器端到端流程。

**Architecture:** 保留控制协议、AgentRunner、设备驱动和版本适配器分层。R1–R5 已交付的是观测/合成校准/拒绝门槛/合成组合；后续真实执行不能通过改一个布尔值、注册空样本或把 FakeDriver 改名获得。软件候选接受与真实设备、学校记录分别交付。

**Tech Stack:** Python>=3.11、现有 FastAPI/SQLite/HTTPX/pytest、Android Java/JDK17、既有 MuMuManager/ADB；现场基线 MuMu6.8.4.0 / Android15 API35，vivo X200 Pro 无 Root。

**Spec:** [设计](../specs/2026-10-18-swu-happyrun-design.md)、[控制协议](../../contracts/control-plane-v1.md)、[七任务计划](2026-10-19-next-stage.md)、[资源适配计划](2026-10-19-resource-guided-adaptation.md)。本文件更新执行顺序，历史计划快照保留；当前结果以准确 HEAD 的 GitHub 回执为准。

## Global Constraints

- 包 `swu_happyrun`、CLI `swu-happyrun`、API `/api/v1`、协议主版本 `1`；HTTP超时5秒、心跳10秒、租约30秒；UTC存储、Asia/Shanghai日程。
- 持久意图在副作用之前；每次写入边界核验当前归属、fence、取消和预算；失租仍可 stop，停止不确定不能确认取消或完成。
- `needs_attention` 可恢复；未知开始/上传不重做；simulation 仅 completed，unknown/pending 不得 succeeded。
- 不改 Root、系统保护或 TLS；不把一次性 CI/KVM 授权推广到新事件。生产服务器/DNS变更不包含在本轮实现中。
- 原始截图、路线、账号、token、设备数据库留 `local/`；公开资料只用合成或审核后的脱敏夹具。同签名才可无损覆盖，不自动卸载/清库。
- Dot 用 `dot/*`，Codex 用 `codex/*`；共享契约、依赖、CI修改先记录关联 Issue。不兼容 wire 变更先独立契约 PR。

## Review Focus

1. 同一 source 的不同 job/debug 签名不可混配；任务1核对 app/test/hash/签名并保留旧数据。
2. 多显示器、应用重启和旧 XML 不得误导输入；任务1固定包/版本/task/display/观测时效。
3. 校准仍有效但租约已失效、或停止请求发生在校准期间；任务0/2要求实际写前核验与零新增动作。
4. 旧记录、待定上传和进程重启不得变成本次成功；任务3/4固定记录关联、只核验恢复和设备锁。
5. 服务器恢复在线不等于设备可执行；任务4覆盖代理离线/过期探针/取消未确认/错版本拒绝调度。

## 当前基线与推进顺序

10/19 核对：#46 为 `e490dce3b8eec56d2db5ccad939ec49fb3fa73ed`，保持 Draft。普通/optional API31/35、四 Python CI 矩阵、浏览器和容器已通过；API35 HTTPS 前台场景5项失败，后续两项恢复未运行。独立 Windows 全套1089通过/12跳过/2失败；新问题为 #52/#53，Dot 正在修复。

#39/#37 已接受；#40 的 `8aef593dd89ca47d63a702ee1cf6952382169bbd` 已独立接受并合入原候选 `2d0fcc550f9c1f6cf8cc6e0106dcafd106cf181a`，#36已关闭，不再派发旧问题。接受回执与 e490 评审见 [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46#issuecomment-6262758607)。完整产品尚未合入 main。

**10/19 后续执行回执：** #55/#56 已独立接受并合入原候选 `f705f91409df88df9614aa4dd53c136dd00ed8a0`，#52/#53关闭，不再重复修复。任务1的MuMu6.8.4.0/Android15自身离线检查完成：普通/可选APK各30项instrumentation和独立界面完成、重启、中断、不重跑、待处理停止通过；联网部分仍未完成。详见[现场报告](../../qa/2026-10-19-mumu-field-acceptance.md)。Dot优先处理[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57) API35 HTTPS、[#58](https://github.com/Maximora-byte/swu-happyrun/issues/58) MuMu采证、[#59](https://github.com/Maximora-byte/swu-happyrun/issues/59) Windows输出诊断；任务2的本机location/gyro帮助已回写#7，读回及停止确认仍待实现。下列未完成的任务级检查不因离线通过而整体勾选。

顺序：**任务0 → 任务1的软件/现场接受；任务2与任务3的只读样本可并行；真实执行依赖任务2+3，再完成任务4。任务5独立研究。** Dot 修当前阻塞时，可以准备样本工具、MuMu无损测试步骤和服务器故障测试，不必等设备输入才能继续全部工作。

## 任务0：收尾当前修复，冻结一个可验收的软件候选

**Owner:** Dot修复，Codex接受；关联 #46/#52/#53，沿用现有修复分支，不重写候选。
**Files:** `tests/agent/test_mumu_binding.py`、`tests/delivery/test_android_ci_phase.py`、共享测试夹具；`drivers/mumu/location.py`；HTTPS fixture/Activity采证脚本及各自回归测试，按已确认根因改动。
**Interfaces:** 保留现有执行 guard、`MuMuLocation.write(point, *, input_crs)`、停止语义及 fixture 生命周期；无新 wire 字段。

- [ ] 先保留 #52 的 WinError1314 RED、#53 的真实 AgentRunner guard/合成时钟零写 RED；修最小代码。权限不可用只精确skip，校准后实际写前重查 authority/halted，覆盖期间停止请求。
- [ ] 分开定位 API35 fixture shutdown 残留线程/连接与 Back/Home 的输入/生命周期失败；主测试与cleanup分别报告。不得通过增加预算、跳过场景或重跑碰绿代替根因。
- [ ] 跑相关回归、契约、完整源码检查及安装包检查；普通 Windows 无提权复测。最终在已有合法门禁下取得同 HEAD 六组合，未授权/未运行不计通过。
- [ ] 交付 source/tree、wheel、普通 app/test 配对、哈希/签名和测试矩阵；更新文档当前状态，不把折叠历史当本轮结论。提交小修复并交 Codex 复测。

## 任务1：让新候选在 MuMu 上完成自身应用闭环

**Owner:** Codex现场执行；Dot补测试入口/工具缺陷。关联 #10/#41，前置任务0相应修复。
**Files:** `scripts/check_mumu_observation.py`、`scripts/collect_device_context.py`、`android/app/src/androidTest/java/org/happyrun/app/AndroidAcceptanceTest.java`；`docs/android-qa.md`、`docs/local-qa.md`，Codex新增脱敏QA报告。
**Interfaces:** 消费同构建 delivery/provenance、`MumuBinding.assert_current(...)` 与精确包/签名/task/display；产出绑定候选 HEAD 的现场结果，不授予物理执行能力。

- [ ] 核对安装签名；保留已有实例和数据。数据清理型场景只在独立验收实例执行；普通安装/观察路径不调用清库。普通包与 remoteQa 测试信任包分别交付。
- [ ] 使用现场观测定位自身窗口，精确确认框及UUID；新文件、dump失败/旧XML、错display/task/签名都须拒绝。复跑已有 display/native/namespace 测试及后台/返回场景。
- [ ] 现场接受：模拟完成、**运行中直接停止**、完成重启、开始后进程中断、不自动重跑、待处理停止、两任务不重叠、断线/失租/远程取消及stop-ack恢复；不沿用旧774包结果。
- [ ] 本地/隔离测试服务使用可验证HTTPS；无合适TLS时明确阻塞联网项，继续离线检查，不改普通包或系统信任绕过验证。完整通过后，按“软件+自身模拟”的准确范围审核单一候选合入 main，真实功能Issue保持开放。

## 任务2：实现并实测 MuMu 真实定位/传感器通道

**Owner:** Dot实现，Codex取得本机帮助/读回并测试；关联 #7/#53，细化既有 R1/R2/R4。
**Files:** `drivers/mumu/{manager,binding,calibration,location,sensors}.py`（均在 `src/swu_happyrun/`）；新增 `drivers/mumu/physical.py` 与 `tests/agent/test_mumu_physical.py`；更新 `docs/mumu-calibration-boundary.md`。
**Interfaces:** 先在 #7 固定本机确认的命令、版本、超时与停止确认依据；本地 transport 提供 `write(...)`、读回和 `stop_and_confirm_empty()->bool`。`physical.py` 的真实实现遵守现有 DeviceDriver 方法，不能依赖 FakeDriver 运行 device 任务；未核实组合保持关闭。

- [ ] Codex只读取指定实例/ADB/boot/app/窗口与可用通道信息；Dot将真实输入和缺失项转成版本专用设计小PR。没有已核实命令的通道保持 unsupported，不猜端口、命令或Android12补偿。
- [ ] 先补 fake-clock/transport 回归：错实例/boot/version、过期校准/租约、取消发生在校准窗口、写入超时、读回不符、停止无确认均拒绝；停机路径尝试全部通道且不重新开始。
- [ ] 按已核实通道实现最小真实transport；在自有探针应用内做有界写入→读回→停止→无后续写入观察。定位/传感器分别验收，不以命令exit0代替读回，不把合成elapsed标量当步数。
- [ ] 记录当前版本、CRS、误差、停止确认和候选HEAD；通过的能力才进入设备支持矩阵。提交独立PR，不将自身探针通过写成乐跑有效记录。

## 任务3：实现一个明确版本、明确校区的真实乐跑适配

**Owner:** Codex取样/用户确认上下文，Dot实现；关联 #9，任务2和样本准备可并行。
**Files:** `drivers/budao/{adapter,selectors,records}.py`、`drivers/adapter_inputs.py`；`tests/agent/test_budao_states.py`、`test_record_verification.py`；`docs/onboarding.md`，新增已脱敏版本夹具。
**Interfaces:** 消费实际 package/versionName/versionCode、SchoolProfile/RouteProfile revision、`PageObservation`/记录关联依据；实现既有 prepare/start/finish/verify 语义。稳定 record identity 与 job/session/profile/app_version 共同绑定，拒绝门槛不能靠通用布尔注入绕开。

- [ ] 输入清单逐项标记：校区与当前学期正式规则、本人登录上下文、真实点位来源/CRS、七种页面状态、记录身份及关联方式。Codex采集设备信息；校区/规则/账号授权由用户确认。缺失只阻塞该组合，其余任务继续。
- [ ] 先写脱敏页面/记录解析失败用例：错版本/旧页面/缺打卡点/旧会话/无稳定ID→拒绝；upload_pending和unknown不能成功；未知页进入needs_attention。不存在的实际状态标“未取得”，不冒充样本齐全。
- [ ] Dot按真实样本实现该版本识别与UI操作，prepare保持只读；开始/结束上传持久意图分开，停止不隐式上传。版本支持通过审查后的专用代码开放，不能把空registry改成“全部支持”。
- [ ] 接入已验证物理驱动；Codex现场跑指定组合，核对本次任务的最终记录。pending继续核验，上传/开始不确定不重跑；只有有效且可关联记录才能record_verified/succeeded。

## 任务4：服务器、Windows代理和真实设备组成完整流程

**Owner:** Dot实现，Codex联调；关联 #4–#10，软件故障测试现在可准备，真实闭环依赖任务2/3。
**Files:** `src/swu_happyrun/cli.py`、`agent/{runner,lifecycle,journal}.py`、`server/{leases,scheduler,web}.py` 及现有网页资源；新增 `tests/integration/test_device_control_plane.py`，更新部署包和操作文档。
**Interfaces:** 沿用 JobSpec/DeviceCapability/LeaseGrant、记录证据和现有API；真实驱动只在已验证版本/能力匹配时注册。服务器不接收原始路线、账号或ADB公网入口。

- [ ] 先用受控驱动写真实HTTP故障回归：设备离线/探针过期/版本不符不执行；取消等stop-ack，失租/Windows代理重启不产生第二次start/upload，日程每个occurrence只创建一次。
- [ ] 接入真实驱动，完善网页对“不支持/待处理/上传待定/记录有效”的显示；不能把任务已派发或本地结束显示成学校记录成功。保持当前Android显式前台模式，不宣称已有后台常驻。
- [ ] 在隔离测试服务完成：网页或日程创建→Windows代理领取→MuMu执行→取消/失败恢复→本次记录查询。验证原始私有数据不外泄，容器持久化/重启及过期任务不补跑。
- [ ] 更新安装、故障恢复和支持矩阵，冻结同一wheel/APK/source后交Codex接受；生产部署另作具体环境/回滚交付，不在本计划中自动改现有服务器或DNS。

## 任务5：vivo 无 Root 和纯接口各自推进

**Owner:** Dot研究/离线实现，Codex只读设备验证；关联 #11，独立于MuMu主线。
**Files:** `docs/research/{vivo-noroot,direct-protocol}.md`、`docs/android-support-matrix.md`；仅在已确认方案与输入满足后新增对应版本实现/测试。

- [ ] vivo先记录系统/ABI/应用/ADB与普通权限能力，保持无Root；对候选可行通道给出可复制最小验证。不可用/缺输入分别记录，不用旧vivo教程结论代替X200 Pro证据。
- [ ] 纯接口先核对本人合法取得的脱敏协议、签名语义、幂等与记录查询；没有证据不猜请求或签名。离线解析/超时/不确定结果测试可先完成。
- [ ] 研究结果形成各自supported/unsupported/not_tested矩阵与下一最小证据；实际可行后另提交实现PR，继续服从既有状态、意图、恢复和记录核验契约。

## 交付检查点

- **第一交付：** 任务0/1的软件和MuMu自身模拟候选。Dot交构建与步骤，Codex复测后按范围集成。
- **第二交付：** 任务2的版本专用真实通道，加任务3已取得的适配输入/最小实现；不等待vivo或纯接口结论。
- **第三交付：** 任务3/4指定组合的真实闭环与记录核验，任务5独立报告。完成时点取决于实际样本和现场结果，不预先承诺一天全部支持。
- 每个PR/检查点回写 #41：采用HEAD/tree、变更、命令/平台/exit/数量、产物哈希、host/device/record范围、阻塞与下一步。Dot继续已有修复，Codex不抢写产品分支。
