# 资源驱动的 MuMu 与步道乐跑适配实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项实施。用户指定真实 ChatGPT Dot 主导产品开发，Codex 负责本地实测和集成审核；本计划发布在 GitHub，不另外创建代理会话或自动发送 Matrix 消息。

**Goal:** 将已核实的开源项目、fork 和教程转化为可测试的设备后端与版本适配工作，交付一个受当前协议约束的真实适配候选。

**Architecture:** 沿用服务器、代理、`DeviceDriver` 和版本适配器分层。先完成现有可靠性工作，再固定实例身份、观测与校准边界；设备动作必须服从已有持久意图、执行 guard 和恢复协议。外部资源是实现线索，实际能力由指定版本的本地观测决定。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest、既有 MuMuManager/ADB 包装；MuMu 6.8.4.0 / Android 15 API35；既有 Java/JDK17 Android 测试入口。

**Spec:** [设计](../specs/2026-10-18-swu-happyrun-design.md)、[控制协议 v1](../../contracts/control-plane-v1.md)、[执行端计划](2026-10-18-agent.md)、[下一轮七项任务](2026-10-19-next-stage.md)、[角色交接](../../handoffs/2026-10-18-dot-lead-sprint.md)。本计划细化 #41 的任务5/7，不替换其任务1–6。

## Global Constraints

- 包 `swu_happyrun`、CLI `swu-happyrun`、API `/api/v1`、协议主版本 `1`；共享模型唯一，不兼容修改先走契约 PR。
- 请求超时5秒、心跳10秒、租约30秒；UTC存储、Asia/Shanghai日程。副作用前再次检查当前设备锁、fence、取消与剩余动作预算。
- `prepare` 只读；服务器接受 running 后先持久化 start_intent 再动设备。开始/上传不确定不得重做，恢复不得隐式开始第二次运行。
- simulation 仅 completed；pending/unknown 不得 succeeded。学校最终有效记录需要当前 job/session/profile/app_version 的实际关联证据。
- Dot 在 `dot/*` 开发；Codex 在 `codex/*` 做独立 QA。产品实现、合同/依赖/CI变更先记录关联 Issue，不写对方分支。
- 不自动 Root、不改变系统保护、TLS、定位权限或电池白名单。第三方教程中的提权、隐藏检测、系统设置命令不构成本项目安装步骤。
- 本地控制端口仅由 Windows 代理使用，不把 MuMu/ADB 暴露给服务器或公网。禁止从任务载荷接受任意网关 URL。
- 原始页面、坐标、设备标识、账号、token、数据库留在忽略目录 `local/`；GitHub 只接收合成/脱敏夹具及证据摘要。

## Review Focus

1. MuMu实例和ADB别名、display/task不一致：不能把两份随机UUID视为同一设备；R1覆盖错误绑定与旧观测。
2. Android12坐标补偿被用于Android15：必须重新绑定版本、通道和读回误差；R2覆盖未知/过期校准。
3. 传感器命令积压在取消后仍执行：停止线程不等于设备停止；R2/R4覆盖队列和停止不确定。
4. 旧页面、成功toast或其他会话记录：不能产生本次有效记录；R3/R4覆盖证据关联与延迟状态。
5. fork的推送/构建成功被当作产品维护或设备兼容：来源和实际接受结果分别记录；资源表及R5覆盖版本/ABI限制。

## 0. 当前执行基线与先后顺序

本次 GitHub 核对日期：2026-10-19（Asia/Shanghai）。发布后若 HEAD 变化，Dot 先记录采用的新 SHA，不能沿用旧结果。

| 对象 | 核对结果 |
| --- | --- |
| main | `24958d8074be36e9170beb2ff8b2eca6622838be`，已有 #42 计划，尚未接受完整产品 |
| #35 候选 | `0bb9344ddefe8054177101583282c57f27f5b38a`，目标为 `dot/integration-candidate`，不是 main |
| #39 / #37 | #39 的 `5d52d78acf6d0f7e7064e1209810746dd05b93d7` 已合入 #35；#37 有 Codex 独立复测回执并关闭，不重写此修复 |
| #43 增补测试 | `a3fd8a6f71a9745e68a2f235c34b6367bdf4aac6`，向 #35 增补中途写入回滚和精确映射断言，仍须独立接受 |
| #40 / #36 | `69182c7128941feb0d6d9e0b512c988b024c1b03`；#44独立复测仍发现磁盘历史agent在runner bind时被覆盖后错误completed，保持阻塞，不能以直接proof测试代替完整恢复路径 |
| #44 独立QA | `7ad594157f12e0fe3de6a66d3c621f20b3ef7dc1`；报告及脚本见该PR，包含MuMu自身应用模拟/重启/中断证据，尚不能代替真实乐跑接受 |

先完成 #41 既有恢复、Windows/CI、原生Android生命周期和自身应用 MuMu 入口；R1、R3 的离线部分可同时准备。#43/#40 不替代 Java 恢复或真实设备验收。单一候选组装仍按 #41 任务6执行。

**当前P0是修复#40完整恢复路径的历史身份覆盖。** Dot继续更新现有PR：先落盘正常状态→修改合成agent→重建driver→经AgentRunner执行verify_only，必须拒绝且无新设备动作；正常同agent、新fence恢复仍应completed。修复后用#44的 `repro_finished_recovery.py --source-root <修复checkout> --expect-persisted-agent-rejected` 和 `--expect-recovery-completed` 分别验证，均须exit0，再交Codex接受。不要重复关闭/修复已接受的#37。

依 [#41最新QA回执](https://github.com/Maximora-byte/swu-happyrun/issues/41#issuecomment-6260150974)，MuMu6.8.4.0/Android15上的现有#25普通APK已有8秒20米完成、完成后重启、中断后needs_attention且不重跑、待处理任务显式停止的现场证据。运行中停止仍未验收；匹配签名的app/test APK、多显示器/确认框/UUID观测仍需Dot交付。这些是自身模拟范围，实际位置/传感器写入、#35远程原生、乐跑/vivo/学校记录均未现场接受。本计划引用QA记录，不声称重新执行了这些检查。

候选 `drivers/mumu/location.py` 目前始终抛 `coordinate_mapping_unverified`；`MuMuManager` 和 `AdbClient` 返回的执行能力列表仍为空，`drivers/budao/` 尚未存在。这是后续产品缺口，不是可直接执行真实任务的后端。

## 1. 已核实资源与采用决策

| 来源 / 固定版本 | 核实到的内容 | 本项目如何使用 |
| --- | --- | --- |
| [budao-lepao-runner](https://github.com/EdmundMad0309/budao-lepao-runner/tree/53715ec80b3c5f0f99ef963e6cf5ed7be1a31e25) | MIT；`src/lepao/{mumu,geo,sensors}.py`、`tools/probe/`、`verify.py`；作者环境为MuMu12，开始仍需手动操作 | 优先审查通道发现、设备端读回和取消/限流结构；不继承其坐标补偿、步频、精度或有效记录结论。只审查源码，不运行仓库EXE |
| [RunInMumu](https://github.com/ranfey/RunInMumu/tree/845788296508a7094f5b9c7fd2d9f63b2a51a7f1) | MuMuManager与图像模板；固定1600×900，作者记录时序误差与上传不确定；根目录未见LICENSE | 参考显示器/模板失配与时序失败场景，不复制代码或采用固定屏幕点击 |
| [17Y9E81/happy-run](https://github.com/17Y9E81/happy-run/tree/c6f1deeb9efd8a4c38e2453833b0ce2a5a296480) | 2021年Windows键盘/剪贴板操作旧MuMu；未见LICENSE | 用于识别旧方案的焦点依赖；不纳入当前控制实现 |
| [hyper152/happy_run](https://github.com/hyper152/happy_run/tree/efda3c5530aa3c220415c55865d4c1f493f55fdf) | 教程、APK和视频；作者vivo Y93s/Android8.1，虚拟Android7.1，强调32位ABI；未声明许可证 | 给R5提供环境核对项；不分发其APK/视频，不据此宣称vivo X200 Pro可用 |
| [LocationSpoofer原仓库](https://github.com/HuangZhuoRui/LocationSpoofer) | 已归档，当前仅说明和许可文件 | 改用固定源码fork作为可选研究来源，不能依赖上游后续更新 |
| [sun-zihang](https://github.com/sun-zihang/LocationSpoofer/tree/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7) / [moxxie2](https://github.com/moxxie2/LocationSpoofer/tree/dcbe62037d0ac01df8d6b341b0da1ba438cdd2c7) | 同一main；六个模块、238个Kotlin文件；sun还保留GlobalSolution等历史分支；GPL声明 | 固定此SHA审查能力/外部接口；Root/LSPosed是前提，不作为无Root vivo后端。源码参考与实际复制分别记录 |
| [wyjhhhh](https://github.com/wyjhhhh/LocationSpoofer/tree/4f40e8ae0304999218a7de9ce36023ceec3ce391) / [wsw0803](https://github.com/wsw0803/LocationSpoofer/tree/4f40e8ae0304999218a7de9ce36023ceec3ce391) | 比上述main多5提交，仅README和build.yml；Build APK成功，Release流程失败 | 作为保留源码/构建线索，不称新增兼容性修复；不交付未经校验的第三方产物 |
| [boonlove v1.35.1](https://github.com/boonlove/LocationSpoofer/releases/tag/v1.35.1) | 衍生仓库；`cd8189acb7407af40c70c037120c33ac1c8eba6d`，2026-08-05，arm64 APK | 旧版对照资料，不自动安装或覆盖现有应用 |
| [2019年博客](https://blog.unclezs.com/pages/650fca/) / [2026年博客](https://www.cnblogs.com/lmy-hhhh/p/19721820) | Fake Location操作经验；没有当前西大/MuMu15可复现接受依据 | 只提取环境和人工步骤问题，不采用防护绕过或网盘包作为依赖 |

采用顺序：既有MuMuManager/ADB包装 → 指定实例的观测/校准 → 版本适配器 → 当前会话的记录核验。LocationSpoofer留作独立可选研究；手机虚拟机和其他学校业务协议不阻塞主线。

源码复用必须在PR写出来源SHA、具体文件、修改范围和LICENSE/NOTICE；MIT来源保留原声明。GPL代码或不明许可代码不直接加入本项目，实际复用另交范围和许可证处理方案。README所述效果均为作者陈述，本次没有构建或运行这些第三方项目。

## R1 / P1：实例绑定与私有取样工具（Dot现在可做）

**Files:** 修改 `drivers/mumu/{manager,discovery}.py`、`drivers/adb.py`（均在 `src/swu_happyrun/`）；新增 `drivers/mumu/binding.py`、`scripts/collect_device_context.py`、`tests/agent/test_mumu_binding.py`、`docs/onboarding.md`。复用 #41 任务5的display/task观测入口。

**Interfaces:** 消费 `MuMuManager.inspect(index: str) -> list[MuMuInstance]`、指定serial的`AdbClient.inspect() -> DeviceCapability`。新增本地 `resolve_binding(*, instance_index: str, adb_serial: str, observation: dict) -> MumuBinding`；`MumuBinding`固定实例/ADB、host/engine版本、package/app版本、display/task、观测ID/时间及digest。该对象只用于本地，不添加wire字段；对外仍用现有 `DeviceCapability`。

- [ ] 先写 `test_wrong_adb_alias_has_no_capabilities`、`test_wrong_display_or_stale_observation_blocks_actions`、`test_instance_restart_invalidates_binding`；断言拒绝时 `writes == 0`、能力不增加。覆盖同包多task、非零命令退出和路径有空格。
- [ ] 运行 `python -m pytest tests/agent/test_mumu_binding.py -q`，记录实际RED；实现显式绑定校验、只读取样和私有输出。不能从MuMu UUID与ADB UUID不同推断两台物理设备，也不能无依据自动合并。
- [ ] 采集器默认只读，要求显式实例/serial/package；缺信息返回结构化缺失项，不安装、点击、写位置或读账号会话。只公开脱敏摘要；真实映射和原始输出放 `local/`，加入敏感字段拒绝测试。
- [ ] 运行新增测试、既有discovery/manager/adb测试及 `python -m pytest tests/contracts -q`。交付首个小PR和复制命令给Codex；只有Codex现场一致观测才确认该绑定，记录它仍未证明执行能力。

## R2 / P1：可读回的定位通道与可停止的传感器边界

**Files:** `drivers/mumu/location.py`，新增 `drivers/mumu/{calibration,sensors}.py`、`tests/agent/{test_mumu_calibration,test_mumu_sensors}.py`；按需扩展自身Android探针，补 `docs/compatibility.md`。

**Interfaces:** 保留 `MuMuLocation.write(point: GeoPoint, *, input_crs: str) -> None`。本地 `CalibrationRecord`绑定R1的binding digest、host/engine/app版本、通道、显式CRS、时间与逐点目标/读回误差；误差阈值由该次测试方案明确提供，无默认“校准成功”。传感器控制复用 `configure_execution_guard(check: Callable[[], None])` 和幂等 `stop() -> None`，不新增共享能力名称。

- [ ] 先测未知CRS、过期/错版本校准、经纬度颠倒、NaN、错误实例：均拒绝且零写入；合成阈值用例同时覆盖内外边界，不把测试常量变成学校规则。运行 `python -m pytest tests/agent/test_mumu_calibration.py tests/agent/test_mumu_sensors.py -q`，记录新增行为的RED后再实现。
- [ ] 在现有失败关闭行为上实现校准记录/参数校验和可注入测试transport。真实命令/网关参数只能来自指定版本本机help、配置和受控读回；缺证据时真实通道仍明确不可用，不猜端口、命令或预补偿。
- [ ] 提供独立、显式的自身探针校准步骤给Codex；一次定位写入及传感器短测与默认只读取样分开。控制请求成功之后必须读回；该读回只证明自身探针，不证明乐跑或学校认可。
- [ ] 为队列积压、动作预算耗尽、取消/旧fence、停止超时写测试。每个写入前重新guard，取消后不追赶补发；无法证明设备端队列清空时保留 `stop_unconfirmed`，禁止启用该写通道或上报已停止。
- [ ] 运行两个新增测试文件与contracts；Windows由Codex按同一HEAD实测。报告每个 `location_read/location_write/sensor_probe` 的实际覆盖，不能把sensor_probe解释成已验证计步/传感器写入。

## R3 / P1：版本状态解释与记录核验（先离线，后真实样本）

**Files:** 新增 `drivers/budao/{adapter,selectors,records}.py`、`tests/agent/{test_budao_states,test_record_verification}.py`；补 `docs/onboarding.md`。命令与路径相对 `src/swu_happyrun/` 的约定同R1。

**Interfaces:** 沿用L3的 `BudaoAdapter(adb: AdbClient, profile: SchoolProfile)`、`inspect_state() -> str`、`start() -> None`、`finish() -> None`、`read_result() -> VerificationResult`。版本映射必须绑定package、versionName/versionCode及实际观测；稳定记录identity/namespace和当前会话关联规则在样本齐全后写入 #9，不能用截图hash替代。

- [ ] 先写未知/旧页面、版本变化、本人授权、动态点缺失、成功toast、pending/invalid记录、旧记录和错会话用例。断言未知/授权/点位缺失时零写入，pending/unknown不产生valid app_record；运行本任务末尾两项专项测试，记录RED后再实现。
- [ ] 无真实样本时实现严格版本门禁、状态解释器接口和明确标注的合成负例；真实版本注册表保持空。采样清单包含开始前/运行中/结束确认/上传待定/记录详情，不要求公开原页面或账号。
- [ ] Codex提供私有样本后，Dot在 #9 先固定具体版本的选择器、来源、坐标/规则和关联依据，再补该版本实现及脱敏回放。不能抄其他学校选择器或按固定屏幕坐标盲点。
- [ ] 运行 `python -m pytest tests/agent/test_budao_states.py tests/agent/test_record_verification.py tests/contracts -q`。真实页面回放、实际UI流程、最终记录分别验收；缺稳定identity或本次会话关联时，`record_read`不得支撑成功。

## R4 / P1：接入现有代理并交付一条完整设备链路

**Files:** 新增 `drivers/mumu/driver.py`、`tests/integration/test_mumu_driver_protocol.py`；仅必要时调整 `agent/runner.py`/CLI注册；补 `docs/acceptance.md`。先具备R1–R3对应接口与输入，组装遵守 #41 任务6。

**Interfaces:** 实现现有 `DeviceDriver.bind_session/configure_execution_guard/inspect/prepare/start/tick/stop/verify`，不复制状态机或新造第二套任务。消耗现有JobView/session/fence、SchoolProfile/RouteProfile和R1绑定。

- [ ] 用fake transport+fake clock先写准备零副作用、start_intent持久化在写入前、过期fence不写、失联后无tick、verify_only零start/tick/upload、取消未确认保持needs_attention的断言；运行 `python -m pytest tests/integration/test_mumu_driver_protocol.py -q`，记录RED后实现。
- [ ] 将不上传的受控停止与可能产生结束/上传的 `finish()` 区分。旧租约不得触发结束上传；若只能观察到本地线程退出而无法确认设备动作停止，不发stop-ack，不释放为“可再次运行”。
- [ ] 接入已校准定位、已核实传感器范围和实际版本适配器；任一必需能力、规则或样本缺失则拒绝device执行。实际支持范围不能用fake transport通过代替。
- [ ] 执行 `python -m pytest tests/integration/test_mumu_driver_protocol.py tests/contracts -q`，再做真实TCP代理/服务器故障联调；Codex在指定版本现场验收。开始/上传不确定时只回查，不重跑；先前任务记录不得补绑定为本次成功。
- [ ] 交付同一候选HEAD、wheel/APK及签名/hash、实际命令/退出码与版本矩阵，分别列host_verified/device_verified/record_verified及仍阻塞项。

## R5 / P2：vivo与LocationSpoofer的独立研究

**Files:** 更新 `docs/research/{vivo-noroot,direct-protocol}.md`，新增 `docs/research/location-backends.md`；关联 #11。此项不阻塞R1–R4可开展的工作。

- [ ] vivo X200 Pro先记录真实Android/ABI/应用版本及连接条件。以hyper教程的旧设备/32位要求列差异；未运行时not_tested，明确不匹配时unsupported_by_candidate，不安装网盘APK、不更改Root。
- [ ] 在固定LocationSpoofer源码SHA审查是否存在可验证的外部会话绑定、启动、受控停止、读回接口；输出具体文件/方法证据和缺口，不能从README功能名假定有RPC。没有接口时先交独立适配设计，不把fork直接塞进主APK。
- [ ] 纯接口维持本人当前版本、当前学校的实际脱敏请求/签名语义前置条件；其他学校、小程序和mock server不能证明可用，不发送猜测正式请求。
- [ ] 在 #11 回报每条路径的输入、来源SHA、实际执行范围、结果和下一最小证据；Root/框架或其他权限扩展需要独立用户方向，本计划不授予这些修改。

## Dot开工与GitHub回报

第一条回执请在 #41 写：已采用的main/候选HEAD、继续更新的 #40/#43、R1首个 `dot/*` 分支和首个小PR目标；不要等待Codex实现通用代码。R1/R3离线部分现在可做；缺实际样本只阻塞对应版本/通道激活。

每个检查点使用：`任务ID / PR / base+HEAD / 实际命令+环境+exit / 产物hash / 来源与许可 / 未验证路径 / 下一步`。已有实现不重复派发，产品合并与现场接受由Codex完成。GitHub文档发布、Dot接单、提交、测试与设备/记录接受分别记账。
