# SWU HappyRun 下一轮开发与验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，按任务逐项执行。用户已指定 ChatGPT Dot 主导实现、本地 Codex 主持独立实测和集成；本轮不自动发起 Matrix 或其他代理会话。

**Goal:** 收尾已提交的两项修复，交付一个可复测的 Python/服务器/网页/Android 统一候选，并取得 MuMu 自身应用模拟闭环的现场证据；实际步道乐跑与学校记录另按版本进入适配验收。

**Architecture:** 保留同一控制协议与持久状态机。先修复并验证不确定恢复和事务原子性，再补原生 Android 的同类缺口、环境验证与现场测试入口；真实设备驱动和应用适配只能消费已核实的本地版本/能力/样本。

**Tech Stack:** Python3.11+、Pydantic v2、FastAPI/Uvicorn、SQLite、HTTPX、pytest；Android Java/JDK17、既有 Gradle/AGP 固定组合；Windows/MuMu6.8.4.0/Android15 API35。

**Spec:** [设计](../specs/2026-10-18-swu-happyrun-design.md)、[控制协议v1](../../contracts/control-plane-v1.md)、[最新分工](../../../AGENTS.md)、[上轮独立验收](../../qa/2026-10-19-overnight-review.md)。APK/网页的新增范围沿用 #31–#35 已记录的用户方向，旧设计“不做APK/网页”不再限制当前交付。

**10/19 复测回执：** 见[修复与 MuMu 报告](../../qa/2026-10-19-fix-retest-mumu.md)。任务 1 的 #39 已接受并合入原候选，#37 已关闭；下文开工快照保留历史。任务 2 的 #40 新 HEAD 69182c7 仍有 pre-bind 历史 agent 被覆盖的阻塞，优先补完整重建/runner 负例与校验，不重写已通过的正常恢复。任务 5 已取得 #25 自身模拟完成、重启、中断不重跑及待处理停止的 MuMu 证据；运行中停止仍受慢速 dump 时序限制，匹配签名的 instrumentation 交付仍需推进。复测报告不代表 #35 远程原生或真实学校记录通过。

## Global Constraints

- Python>=3.11；包名`swu_happyrun`、CLI`swu-happyrun`、API`/api/v1`、协议主版本`1`。
- HTTP超时5秒、心跳10秒、租约30秒；UTC存储，日程Asia/Shanghai；单服务进程、单调度器。
- 共享模型/Schema唯一；不兼容改动先提交契约PR。本计划不新增远程pause/resume、后台常驻或第三方业务协议。
- 服务器接受running → 本地持久意图 → 设备动作；开始/上传不确定不得重做。needs_attention可恢复；取消须有停止确认。
- simulation只能completed，不生成app_record；本地fake持久状态、框架回执和学校有效记录是不同证据。
- Dot用`dot/*`实现、提交小PR；Codex用`codex/*`独立QA。不得写另一方分支；产品合并由Codex完成审核后处理。
- 不自动Root、不改系统/模拟器保护、不放松TLS、不把一次性KVM授权扩展到新事件；本计划不包含生产部署/DNS/Release。
- 账号、token、原始截图、真实路线、数据库/抓包留本地；公开夹具仅合成数据或已脱敏样本。未知版本/坐标/选择器/签名一律关闭对应执行能力。

## Review Focus

1. 同一hello批次的新旧probe冲突、重传和事务中途失败：整批接受或整批回滚，首收时间不被重放刷新（任务1）。
2. 已完成模拟与开始/上传不确定混淆：恢复只读证明必须匹配原会话，不能仅看simulation_only（任务2、4）。
3. 普通Windows无symlink权限、无KVM的PR事件：缺环境不伪装成通过，也不修改保护赶绿灯（任务3）。
4. Android进后台/真实进程中断、MuMu多显示器、dump写出后崩溃：旧页面和旧XML不得充当当前任务状态（任务4、5）。
5. 同版本不同debug签名覆盖、QA证书混入普通APK、真实记录pending被当valid：保留数据、区分产物并限制能力（任务6、7）。

---

## 0. 开工快照与交付顺序

发布计划时已重新读取GitHub；以下是快照，开工须复查，不覆盖新的修复。

| 对象 | 精确基线 / 当前状态 |
| --- | --- |
| 已验收main | `8373fd3e276ca10cedf769de715476a257e80ce2`，含C0/C1及QA #38；服务器/代理/网页/APK产品尚未合入 |
| 集成#25 | `77494e21756e514f53e51b3a2c72f22555f0aae6`，含#17–#34的祖先 |
| Android增量#35 | `28871b2d599a8ec8335570effb3207d2564639ab`；准确push有9组checks、容器、API31/35实际HTTPS通过；PR事件四个Android作业失败，保留失败 |
| #37已有修复PR #39 | `5d52d78acf6d0f7e7064e1209810746dd05b93d7`，基于28871b2；已提交，未独立接受 |
| #36已有修复PR #40 | `28f811664bdf0c50d21c37da5564d23b9a260f61`，基于28871b2；已提交，未独立接受 |

**不要重新实现#39/#40。** 先收尾准确修复，后续分支可基于明确依赖开发，不必空等Codex复测；最终组装必须同时包含最新main与两个修复，不能随意混装旧组件。

建议顺序：`任务1/2 → 任务3`，同时准备任务4/5；`任务1–5 → 任务6统一候选 → Codex现场验收`。任务7的输入清单现在即可准备；真实写入/学校流程等输入满足后再实施。完成任务1–6是软件候选目标，不能据此宣布全部真实功能完成。

## 任务1：收尾#39，证明探测批次原子性

**Owner/Issue:** Dot实现，Codex复测；[#37](https://github.com/Maximora-byte/swu-happyrun/issues/37)、[#39](https://github.com/Maximora-byte/swu-happyrun/pull/39)。

**Files:** 现有`src/swu_happyrun/server/leases.py`、`tests/server/test_probe_batch_atomicity.py`；核验`tests/server/test_leases.py`。不改共享wire模型。

**Interfaces:** 消费现有`AgentHello`/`DeviceCapability`与`POST /api/v1/agents/hello`；相同probe_id的canonical payload须一致。冲突返回契约409；agent/device/probe快照均不得部分改变。

- [ ] 核对#39当前HEAD与两文件范围；保留其已完成的RED→GREEN记录，若要追加修复先补失败用例。
- [ ] 复用`test_conflicting_new_probe_batch_is_atomic_across_restart`及`test_persisted_conflict_and_foreign_device_roll_back_complete_batch`，关键断言为`assert first.status_code == 409`、`assert after_snapshot == before_snapshot`、`assert replay.status_code == 200`。用合成A/B设备验证：同一新probe_id的不同payload首次409；数据库agent/device/probe整批快照不变。
- [ ] 验证合法多设备首次200、完全相同重放200且probe首收时间不变；重建服务实例后相同重放仍200。已有probe冲突和外属设备失败均无部分写入。
- [ ] 运行`python -m pytest tests/contracts tests/server/test_probe_batch_atomicity.py tests/server/test_leases.py -q`，预期全通过；再运行已有真实loopback HTTP回归。
- [ ] PR回报准确HEAD、命令/平台/退出码及原始/预期状态区别。Codex从QA #38的复现更新为预期409验收后，才关闭#37；旧“首次200即可复现”的脚本exit0不是修复通过。

## 任务2：收尾#40，完成Python模拟恢复成功路径

**Owner/Issue:** Dot实现，Codex复测；[#36](https://github.com/Maximora-byte/swu-happyrun/issues/36)、[#40](https://github.com/Maximora-byte/swu-happyrun/pull/40)。

**Files:** `agent/runner.py`、`drivers/fake.py`（均在`src/swu_happyrun/`）；`tests/agent/test_driver.py`、`test_runner.py`、`tests/integration/test_http_runner.py`、`docs/simulation-verify-recovery.md`。

**Interfaces:** 保留`AgentRunner._verify(self, *, recovery)`与`DeviceDriver.verify(job)`；#40提供`FakeDriver.has_persisted_completion(view: JobView) -> bool`，仅用于当前合成driver恢复证明，不变成device记录证明。

- [ ] 复用真实HTTP测试`test_finished_stopped_simulation_recovers_completed_without_motion`，断言`assert recovered.state == "completed"`、`assert after_counts == before_counts`、`assert not upload_intent`；同一测试保留退出屏障，不能退化成仅mock响应。核对#40当前HEAD，保留已有实际TCP+子进程RED→GREEN：走到端点并持久停止后，在completed上报前退出；新进程领取批准的verify_only。
- [ ] 断言原job/session不变、fence合法增长、状态到completed；恢复不新增prepare/start/tick/upload。验证设备保留可在完成后正常释放。
- [ ] 缺失/损坏/旧格式/只有内存状态，错job/session/spec/agent/device/fence，仍活动、路线未完成、start_crash或upload_uncertain都不能借此成功。共享driver接口或类型收窄的改动须说明，不复制第三套证明模型。
- [ ] 运行`python -m pytest tests/contracts tests/agent/test_driver.py tests/agent/test_runner.py tests/integration/test_http_runner.py -q`；再用QA #38的`repro_finished_recovery.py --source-root <修复checkout> --expect-recovery-completed`，预期exit0且没有新增动作。
- [ ] 小范围提交/更新#40，附准确HEAD和未验证路径。Python修复不自动代表Java原生恢复已修复；#36关闭取决于本Issue的Python验收，Java由任务4独立跟踪。

## 任务3：环境可复现的Windows与CI验证

**Owner:** Dot实现测试/CI修复；Codex执行普通Windows验收。关联#10/#16。

**Files:** `tests/agent/test_driver.py`、`test_profiles.py`、必要时`tests/agent/conftest.py`；`scripts/check_ci_kvm.py`、`tests/delivery/test_ci_kvm.py`、`.github/workflows/checks.yml`、`android-remote-https.yml`、`docs/delivery-validation.md`。仅改有复现依据的文件。

**Interfaces:** 保持实际产品的symlink拒绝；测试fixture只在OS明确无创建权限时报告精确skip。CI结果至少绑定`source_head/event/run_id/tested_revision/platform/result`，同时记录失败/未执行，不以skip作成功证据。

- [ ] 先复现普通Windows账户的WinError1314夹具失败；fixture仅捕获已知权限/不支持错误并说明skip，意外I/O错误仍失败。Linux与具权限Windows必须实际跑原symlink防护断言；禁止改产品安全判断。
- [ ] 为fixture的“支持/无权限/非权限错误”写可移植单测；用`python -m pytest tests/agent/test_profiles.py tests/agent/test_driver.py -q`核对通过与明确skip。
- [ ] 将#35的准确push成功与PR软件模式失败分别归因，保留run39199236415、39199236452、39199240147。检查无加速环境的启动/ANR输出，禁止反复重跑碰绿、删除Android断言或扩大KVM授权。
- [ ] 在既有权限内修可复现的脚本/资源问题；无法取得执行环境时交付具体阻塞和可审核方案，先继续其他开发。任何待授权权限变更只准备补丁，不执行；不能从本计划推断新事件已获许可。
- [ ] 运行相应`tests/delivery/test_ci_kvm.py`、workflow/TLS/package专项和契约检查。交付一张准确HEAD的Windows/Linux3.11/3.13、普通/可选APK API31/35、真实HTTPS、容器的结果表；未运行项标明原因。

## 任务4：补齐原生Android的只读恢复与真实生命周期回归

**Owner:** Dot；原生#35的独立后续PR，不归入#40的Python通过结论。

**Files:** `android/app/src/main/java/org/happyrun/app/remote/{runtime/RemoteAgentRunner,journal/RemoteJournal}.java`；对应`src/test/java/.../remote/`；`src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/RemoteHttpsAcceptanceTest.java`；`src/androidTest/java/org/happyrun/app/RemoteAgentActivityTest.java`；`docs/android-remote-runtime.md`。

**Interfaces:** 消费`RemoteAgentRunner.runOnce()`、现有journal的job/session/fence/spec绑定。新增本地只读`RemoteJournal.hasPersistedCompletion(String jobId, String sessionId, long fence, String specDigest): boolean`，只有重开并验证持久日志、匹配当前授权且历史finished+stopped时为true；不改wire协议、不构造app_record。

- [ ] 新增`testVerifyOnlyCompletedAfterProcessRestart`，关键断言`assertEquals("completed", recovered.state)`、`assertEquals(0, newStartCalls)`、`assertEquals(0, newTickCalls)`。加失败用例：新进程恢复已完成且停止的远程fake任务，批准verify_only后应completed且新增start/tick为0；28871b2当前无条件verification_pending不能作为预期成功。
- [ ] 加错origin/agent/device命名空间、job/session/fence/spec、截断/损坏日志、未完成和停止未持久等负例；保持needs_attention且不重放动作。旧日志缺证明字段保守拒绝，不清库重来。
- [ ] 实现最小持久证明与恢复分支；每次成功状态仍校验当前租约、revision和停止状态，取消只走stop_only/stop-ack。
- [ ] 用真实Activity重建/进后台和真实进程终止补充现有手动生命周期回调测试；加入旧运行租约失效后停止、恢复fence变化时旧进程不再tick的HTTPS场景，保留精确故障屏障和动作计数。
- [ ] 运行Java单测、正常APK构建与API31/35真实HTTPS新增场景。JVM/方法回调通过与ART/真实进程通过分别报告；账号token仍只在内存，不借本任务新增后台常驻执行。

## 任务5：为MuMu交付可安装、可定位到正确显示器的自身测试入口

**Owner:** Dot实现Android诊断/测试打包；Codex负责Windows/MuMu实际执行和独立QA脚本。不要改本地`local/`中的旧临时脚本冒充产品修复。

**Files:** `android/app/src/androidTest/java/org/happyrun/app/{AndroidAcceptanceTest,ProcessRecoveryTest,PollingAcceptanceTest}.java`；按需新增`DisplayObservationTest.java`；`scripts/check_android_launch.py`；`.github/workflows/checks.yml`的测试产物白名单；`docs/android-qa.md`、`docs/local-qa.md`。

**Interfaces:** 测试入口绑定显式package、activity、当前task/display、安装签名和一次观察ID。输出仅包含合成场景的状态/动作计数/证明摘要。原`scripts/android_acceptance.sh`会pm clear，只允许其既有一次性官方AVD，不扩成用户MuMu脚本。带清库/reset夹具只允许明确无个人数据的测试实例；用户存量安装提供不清库的观察/交互步骤，无隔离条件则保留相应阻塞。

- [ ] 新增`DisplayObservationTest.testWrongDisplayNeverClicks`和`testStaleObservationNeverCompletes`，断言失败时`writes == 0`且不得输出completed。为错误display/同包多task、旧XML、dump非零退出后的旧文件、无窗口、超时写失败测试；不得把已存在的XML当本次成功观测，也不能从139推断应用通过。
- [ ] 在进程内报告实际Activity/display与可见控件；主机不再硬编码display0/第一个task或屏幕点击坐标。无法一致定位时失败并导出最小诊断，不去点击其他应用。
- [ ] CI交付同一构建、同一临时签名的普通app APK与匹配的instrumentation APK、包名/版本/签名摘要及SHA256SUMS；不把remoteQa信任包发给用户当普通APK。
- [ ] 给Codex一份可复制执行清单：确认指定实例/已有安装；核对签名与数据保留；普通APK本地8秒20米模拟完成、显式停止、完成后重启、中断后needs_attention且不重启运动。新装/保留旧数据的路径分开，不自动清库/卸载/提权。
- [ ] Codex在MuMu6.8.4.0/Android15执行并记录现场结果。当前仅安装/首屏通过；完成本任务前不得将多显示器/dump问题武断归因于应用逻辑，也不标真实乐跑device_verified。

## 任务6：统一候选、安装体验与交接

**Owner:** Dot组装交付，Codex独立接受；依赖任务1–5的相关门槛，不在本计划中自动合并产品PR。

**Files:** `README.md`、`docs/{status,installation,android-apk,android-runtime-boundaries,android-support-matrix,delivery-validation}.md`，新增`docs/acceptance.md`；仅对真实缺陷修改`deploy/`和打包。既有代码不大规模重构。

**Interfaces:** 统一候选包含最新main、#25/#35、#39/#40与已接受的后续修复；以单一HEAD/tree及wheel/APK校验清单交付。保持server/core/agent可选依赖隔离，普通APK不含测试CA/私钥。

- [ ] 新建明确的`dot/*`候选分支，保留可核对祖先/组件SHA，合入main的QA资料。新候选必须同时实际运行两个修复，不用组件各自绿灯代替组合。
- [ ] 运行冻结安装、全套pytest、契约/Schema、Ruff、构建/分发隐私；源码外安装同一wheel运行真实HTTP故障、daemon、日程与`deploy/smoke_fake.py`；真实浏览器12组；既有容器持久化/权限检查。
- [ ] Android依次验证普通/可选包、真实HTTPS及任务4/5新增场景；核对最终HEAD而非旧288包。未具备某环境时保留blocked，不把本条勾成通过。
- [ ] 修正当前APK包含INTERNET但文档仍称无网络权限的漂移；Python/网页/原生本地模拟/单次远程fake的使用入口和能力表写清。当前原生不是无人值守常驻代理，不能把桌面daemon能力写到APK上。
- [ ] 每个普通APK标注临时debug签名和升级条件。同签名才覆盖；签名不同保留原安装/数据并说明选择，禁止自动卸载。长期生产签名/发布另立任务，不在此创建或上传生产密钥。
- [ ] 交付`docs/acceptance.md`：HEAD、操作系统/设备版本、命令、退出码/skip、证据摘要、host/device/record范围和阻塞；PR正文顶部为最新HEAD，旧结果收进历史。候选artifact是7天临时交付，说明失效后的重新构建入口。
- [ ] Codex按准确HEAD复测、审核合并后再关闭相应Issue/旧堆叠PR；main基础已通过163项不等于本轮新增产品已通过。#9/#11及真实记录未完成前不得关闭总目标为“全部支持”。

## 任务7：实际应用适配与vivo/纯接口的输入门槛

**Owner:** Dot提前完成工具/离线准备，Codex提供现场脱敏输入；关联#7/#9/#11。与任务1–6可独立的部分继续，不因缺设备停住全部工作。

**Files:** 先完善`docs/onboarding.md`、`docs/research/{vivo-noroot,direct-protocol}.md`；样本满足后在`src/swu_happyrun/drivers/budao/{adapter,selectors,records}.py`、MuMu实际驱动、`tests/agent/test_budao_states.py`、`test_record_verification.py`实现，版本专用计划须在对应Issue补齐后再写实际选择器/控制参数。

**Interfaces:** 真实驱动最终实现既有`DeviceDriver.bind_session/configure_execution_guard/inspect/prepare/start/tick/stop/verify`；`prepare`严格只读，`stop`失去租约仍可执行。`verify(job)->VerificationResult`的pending/unknown不得succeeded；只有可靠的本次job/session/profile/app_version和稳定record identity才可app_record。

- [ ] Dot先交一个最小输入清单：精确MuMu/Android/目标包版本、校区正式规则、本人已登录会话的页面结构、真实点位来源与CRS、开始/运行/结束/上传待定/有效/无效/未知状态、记录身份和关联依据。不要要求公开原截图/路线/token。
- [ ] 离线准备版本/profile校验、样本脱敏/拒绝敏感字段、未知页面→needs_attention与记录pending/unknown不成功的测试；缺实际页面时写“未取得，未实现该版本选择器”，不以假学校夹具表示适配完成。
- [ ] Codex取得样本与最小定位/传感器探针；命令参数、位置映射只来自本机帮助和读回。观察不到能力时保持关闭；只读取样与实际写入分开确认范围，不更改Root或安全设置。
- [ ] 输入满足后Dot在Issue固定版本专用接口/测试和来源，补实际MuMu写入/停止/读回及应用版本解析，再联接完整`DeviceDriver`。每次写入前调用现有guard，失败/停止/重启均有真实回归；不是继续保留空实现却称功能完成。
- [ ] 本人完成登录或授权；Codex验证实际应用流程与最终记录，pending继续等待/待核验，不能为求完成重新开始或盲目上传。成功范围绑定具体版本/学校规则/设备，不承诺跨版本100%。
- [ ] vivo X200Pro维持无Root，先取得系统/应用/ADB或普通APK观测；纯接口先有本人已合法取得的脱敏协议/签名语义。缺输入时分别报告unsupported_by_candidate/not_tested和下一最小证据，不发猜测上传、不复用其他学校协议。

## 交付节奏与回报格式

- 第一检查点：任务1/2收尾与准确修复SHA、CI/复现材料；已有#39/#40继续更新，不重开重复修复。
- 第二检查点：任务3、4、5各自可审查的PR；设备条件不足只阻塞相应现场验收，不暂停其他实现。
- 第三检查点：任务6单一候选、可下载安装包与完整结果表，交Codex；任务7单独记录输入和真实适配进度。
- 每个检查点在本轮总Issue回报：`任务ID / PR / base和HEAD / 实际命令与环境 / exit与数量 / artifact校验 / 未验证路径 / 下一步`。没有运行的检查写未运行。

这是执行清单和验收条件，不是预先勾选的成绩单。Dot可立即推进已授权开发；本计划发布者没有代替Dot接单或执行产品修复。用户将本轮Issue交给Dot后，以真实接单/提交回执跟进。
