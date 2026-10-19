# 协作状态

更新：2026-10-19（Asia/Shanghai）。Dot 主导实现和修复；本地 Codex 负责独立测试、设备观测和集成审核。本轮只使用 GitHub，没有发送 Matrix 消息。

## 下一轮执行入口

[下一轮开发与验收计划](superpowers/plans/2026-10-19-next-stage.md)继续作为 Dot 执行入口。#39 已独立接受并合入候选，#37 已关闭；#40 正常恢复通过，但 pre-bind agent mismatch 负例失败，#36 保持开放。新回执、命令和 MuMu 观测见[修复复测报告](qa/2026-10-19-fix-retest-mumu.md)。历史归属覆盖已由后续 PR40 `8aef593` 最小修订，候选软件组合通过，仍等待 Codex 独立复测；Dot 继续推进 Android 恢复、CI/Windows 可复现性、MuMu 测试入口及统一候选。

## 本轮统一候选接续（尚未发布）

本候选以 PR35 `28871b2d599a8ec8335570effb3207d2564639ab` 产品为基础，纳入 main `5377c70b3af02dd954b8e2f81666ccab78b330ce` 的最新 QA、复现脚本和七任务计划。main 的历史验收范围与下方候选软件进展分别保留；最终 HEAD/tree 由发布 PR 绑定。

PR39 `5d52d78acf6d0f7e7064e1209810746dd05b93d7` 与 PR40 `8aef593dd89ca47d63a702ee1cf6952382169bbd` 的已审修复已显式纳入，Issue37 已由 Codex 限定接受后关闭；Issue36 的新 pre-bind 修订仍待独立接受。持续前台连接、原生持久完成恢复、CI 构建/运行分阶段正组成同一候选；新 Android 用例尚待实际执行。Windows 夹具与 MuMu 显示器观察入口正在按计划接入，不借旧 APK 的通过结论。

原生恢复正负双进程 HTTPS 有实际通过，顺序host复跑仍出现过读取超时/子进程非零，状态为 intermittent_unresolved；保留成功与失败证据，不宣布稳定全绿。Python pre-bind身份覆盖缺口的独立最小修订已纳入，修后组合最终885项通过（186.89秒）；Java105项通过。AVD脚本管道SIGPIPE已确定性修复。PR46准确481的API31/35 HTTPS、前台Activity与两项恢复/旧fence实测通过；普通display观察首项失败，使后续native/导航尚未执行。当前后续候选只修Windows测试编码/ID并补严格安全诊断，仍待同HEAD复验，未称display根因已确认。完整结果和未验收环境见[统一验收记录](acceptance.md)。


## 已合入 main

| 范围 | PR / 准确 HEAD | 独立验收 |
| --- | --- | --- |
| C0/L0与verify_only结构修复 | [#17](https://github.com/Maximora-byte/swu-happyrun/pull/17)，`6ed02c29924ccc3ab26c028fbf46d15477d84eb0` | Windows Python3.11.16：112 tests、Schema、Ruff、构建、core-only干净安装通过 |
| C1恢复/归属/记录会话契约 | [#19](https://github.com/Maximora-byte/swu-happyrun/pull/19)，`a82e4d97a5a7e1de5112eabeecac6e97312089a7` | Windows Python3.11.16与3.13.15各163 tests通过；3.11的Schema、Ruff、构建、干净安装通过 |
| 原始50项服务器验收设计 | [#12](https://github.com/Maximora-byte/swu-happyrun/pull/12)，`cd508ceb0e75b8615213e0f9054cfe848b6493cc` | 文档审核；[原始矩阵](server-test-matrix.md)保留当时基线，不是产品通过记录 |

以上使用merge commit保留依赖祖先关系，合并后基线为 `aa1cced50dbe3356607067e90d127dc699ce58ea`。旧 #13 由修复后的 #17 替代关闭。接入 #1、共享模型 #2、只读探测 #3、契约 #14 已按上述有限范围完成。**main尚未合入服务器、执行代理、网页或Android产品实现。**

## 候选和阻塞（独立 QA 时点与后续修订）

- [#25](https://github.com/Maximora-byte/swu-happyrun/pull/25) `77494e21756e514f53e51b3a2c72f22555f0aae6` 包含 #17–#34 的全部祖先提交，无需逐个重复集成；保持未合并。
- [#35](https://github.com/Maximora-byte/swu-happyrun/pull/35) 增加 Android 单次远程 fake 代理；原 CI/TLS 修订为 `28871b2d599a8ec8335570effb3207d2564639ab`。本轮 #39 合入其分支后为 `0bb9344ddefe8054177101583282c57f27f5b38a`，整个产品仍待接受。采用版本须重新核对实际 HEAD。
- [#39](https://github.com/Maximora-byte/swu-happyrun/pull/39) `5d52d78acf6d0f7e7064e1209810746dd05b93d7`：独立接受，merge `0bb9344ddefe8054177101583282c57f27f5b38a` 到原候选分支；[#37](https://github.com/Maximora-byte/swu-happyrun/issues/37) 已关闭。冲突整批回滚、合法精确映射与重传通过；非阻塞错误列断言已交 Dot 改进。
- [#40](https://github.com/Maximora-byte/swu-happyrun/pull/40) `69182c7128941feb0d6d9e0b512c988b024c1b03`：正常 verify_only→completed 通过；损坏历史 agent 在 bind 时被覆盖后仍获 completed，负例失败，暂缓合并。[#36](https://github.com/Maximora-byte/swu-happyrun/issues/36) 保持开放；新复现为 `repro_finished_recovery.py --expect-persisted-agent-rejected`。后续 `8aef593dd89ca47d63a702ee1cf6952382169bbd` 已修此缺口并纳入本候选；以上失败保留为修前独立证据，不自动关闭 #36。
- #25准确HEAD的四项Android CI失败未获豁免；#35新push与PR事件必须分别核对，旧绿灯不覆盖新失败。

## 最新独立证据

修复复测与现场证据见[最新验收报告](qa/2026-10-19-fix-retest-mumu.md)；之前版本的命令与失败记录保留在[夜间成果报告](qa/2026-10-19-overnight-review.md)。

- e5b Windows/Python3.11全套：688 passed、7 skipped、2 failed；两项是本机symlink夹具的WinError1314，未改系统权限，未计为全绿。
- 安装/Schema/Ruff/构建/分发隐私、真实TCP fake路线完成和服务重启通过。28871b2的Python3.13 TLS专项6项通过；本机浏览器实际12组通过。
- #39 Windows/Python3.11 的 contracts/server/HTTP 协议 269 项通过；初版 #40 聚焦 Python3.13 为 211 passed / 1 deselected。本地组合 e62c1af 为 709 passed / 7 skipped / 2 deselected；不将已知权限夹具排除视作其断言通过。新 #40 的四项补充测试通过，但不覆盖失败的完整重绑定路径。
- MuMu6.8.4.0 / Android15 API35、#25 普通 APK：8 秒 20 米本地模拟完成、完成后重启、进程中断后 needs_attention、不自动重跑、待处理任务确认停止及持久化均已现场核对。运行中直接停止仍待稳定测试入口验收；uiautomator 非零退出保留为工具异常。本机 apksigner 独立 v2/证书核验通过。执行能力仍为空，MuMu/ADB身份映射未验证。
- 未修改Root/框架配置、系统位置/传感器或生产环境。实际步道乐跑、vivo、学校配置与最终有效记录均未验收。

## 剩余任务

| Issue | 下一步 |
| --- | --- |
| #4 S0 | 已有#18/候选实现；按C1兼容的最终组合验收，不任意拼装旧S0与新模型 |
| #5 S1 | #37 已在候选修复并关闭；最终组合继续保留租约/fence/取消/记录绑定回归 |
| #6 S2 | #25真实容器CI有成功证据；依赖S1修复与最终组合验收，本机Docker daemon未运行 |
| #7 L1 | 合成profile/fake/离线转换有实现；MuMu写入/传感器/坐标校准未实现或未验收 |
| #8 L2 | PR40 8aef 已补 pre-bind 历史 agent 校验，待 Codex 复测，#36 继续开放；恢复不得新增 start/tick/upload |
| #9 L3 | 缺精确应用版本、校区正式规则、本人会话和脱敏页面；真实适配仍需实现 |
| #10 I0 | #36、MuMu 测试入口及准确 HEAD 的 Android 检查完成后再作产品集成决定 |
| #11 R0 | vivo无Root/真实业务纯接口没有有效执行证据，不由fake或其他学校协议推断支持 |
| #16 冲刺 | 保持开放；软件、设备与学校记录分别验收 |

旧分工和阶段事实从Git历史、[冲刺交接](handoffs/2026-10-18-dot-lead-sprint.md)及原Issue/PR回执追溯；不以历史“未接单/无代码/实例停止”覆盖今日观测。

---

## 候选开发与交付历史

以下按原交付时点保存；当前结论以上方统一候选和最终 PR 证据为准。

更新日期：2026-10-19（Asia/Shanghai）。当前结论以下方“当前首阶段远程候选”为准；末尾保存旧快照用于追溯，不能将旧“未接单/未开始”作为本轮状态。

## 当前首阶段远程候选（2026-10-19）

[PR #35](https://github.com/Maximora-byte/swu-happyrun/pull/35) 准确 HEAD `28871b2d599a8ec8335570effb3207d2564639ab`，tree `5bd5c563bd98000ae263faaf3ec1a189e3562704`，273文件逐blob核对。它继承集成 #25 的 `77494e2`，新增用户显式发起的单次 HTTPS simulation 代理；INTERNET 是该模式所需权限，token 只在内存。该288基线空队列或一次任务结束后不会持续领取，后台不常驻；本轮前台接续变化见下文。

准确 push [checks 39199236415](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39199236415) 九个 jobs 成功；[HTTPS 39199236452](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39199236452) API31/API35 各15场景+3远程UI测试成功，[container smoke 39199236390](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39199236390) 亦通过。证据详见[PR35验收记录](https://github.com/Maximora-byte/swu-happyrun/pull/35#issuecomment-6259724906)。PR临时合并 [checks 39199240147](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39199240147) 已终态：四个Android jobs失败（API31系统ANR、API35启动超时）；不能借用push结论。旧774集成Android软件模式曾因系统ANR/启动超时未验收，历史事实保留。

[Issue #36](https://github.com/Maximora-byte/swu-happyrun/issues/36) 的Python verify_only恢复、[Issue #37](https://github.com/Maximora-byte/swu-happyrun/issues/37) 的hello冲突批次原子性对应修复已纳入本轮候选，集成与独立验收仍开放，不能用测试总数代替逐项复测。当前候选未合并 main。MuMu本地仅有旧 #25 APK首屏报告，不是288设备或远程流程通过；学校记录未验收。

本轮叠加持续前台连接、多任务接续实现、14项新增Activity用例，以及原生持久完成恢复修订、1项独立两阶段恢复和1项存活旧进程跨新fence用例；准确新HEAD未生成，Android连续任务/Activity生命周期及持久完成恢复尚待CI验收。原生恢复已有独立52项JUnit和实际双进程HTTPS正反例，但不能代替Android执行；修订说明见[原生恢复](android-verify-recovery.md)。288的原15项HTTPS与3项UI成功仅为基线证据，不可借用为本轮通过。下方按时间保留的阶段快照均为历史，不是当前能力或长期KVM授权。

本地 Codex 独立审计见 [PR #38](https://github.com/Maximora-byte/swu-happyrun/pull/38)（cedd2d4254f446d85935d674ab442ed9b68abce1）的 [审计记录](https://github.com/Maximora-byte/swu-happyrun/blob/cedd2d4254f446d85935d674ab442ed9b68abce1/docs/qa/2026-10-19-overnight-review.md)；其main基线163项结果不属于此候选。Issue37修复见 [PR #39](https://github.com/Maximora-byte/swu-happyrun/pull/39)（5d52d78），Issue36修复见 [PR #40](https://github.com/Maximora-byte/swu-happyrun/pull/40)（28f8116）；本轮已按这两个独立已审 PR 的精确文件显式纳入组合，待本轮完整集成回归与 Codex 独立复测后更新验收；Issue 尚未关闭。后续组合必须保留本地审计历史文件和复现脚本。

## 向导 CI 修复与空闲轮询优化（2026-10-19）

基于已发布 6427e91b7099cdf2233983ff55a5bcf9718e6b61 的独立下一候选：修复已观测的编译后资源ID检查与Windows中文夹具编码问题；停止空任务/终态无条件轮询，活动任务继续有界更新，仅快照变化重绘，用户刷新可排队。此优化不声称已证实 SystemUI ANR 的根因。Root仍须显式确认，不自动调用。

用户已明确批准本轮临时测试机KVM访问。门禁仅匹配本仓库onboarding分支从6427开始的下一push或PR33 synchronize，使用当前用户ACL且保留旧mask；本地只运行mock，真实加速结果待CI。本地24项Java JUnit、101项交付fixture、lint/140格式通过。CI保留原11项并新增4项轮询回归，每变体native15、wizard4、inactive1独立计数，使用各自匹配的instrumentation APK。新仪器测试未在本地执行，旧失败不能标为已修复验收通过。

## 向导启动诊断重基（2026-10-19）

本轮向导组合已重基至 629f2e9b86d7a72502f528abd1c1edf999d6a842，保留稳定 API31 镜像、私有 AVD 路径、快速失败与有界启动诊断。启动探针仅增加固定 core/wizard 首屏控件配置，默认 core 不变；向导 CI 显式选择 wizard，两变体仍要求 resumed、精确包名、非零控件范围及无崩溃/ANR。不会点击 Root 确认按钮。

最终 Linux/Python3.12 完整 **612 passed**（95.17秒，1条继承warning），交付专项58项、Ruff/137格式、Schema、frozen、Node与分发隐私通过。34个Java源文件与上一向导组合逐字节相同，复用其23项JUnit实测，未伪称重跑。实际Android编译/AVD及ART仍以新提交CI/设备证据为准；下方584项保留为重基前证据。

## 单入口向导与可选自身模块候选（2026-10-19）

本轮独立基于 cf3cfee12701573b4a577225d66980bb2279a346，新增同一原生入口的环境向导、显式确认后只读 Root 诊断及自身 scope 模块变体。默认不调用 su；取消、刷新和打开说明不授权 Root 检查。模块打包标识与 inactive/unknown/active 实时回执分别展示，任何诊断状态都不解锁真实执行。组合来源、签名升级边界与证据分层见[向导组合说明](android-onboarding-integration.md)。

本地 Java 23 个 JUnit（最后两处文案改动后重新编译复跑）、最终完整 Python **584 passed**（124.76秒，1条继承warning）、交付专项30项通过；首次582项日志保留，未当最终数量。frozen、Schema、Ruff/135文件格式、Node helper、wheel/sdist隐私检查通过。Android 编译、实际 APK 资源检查、无框架安装/同签名替换及每变体四项向导仪器测试尚待本轮准确 HEAD 的 Actions；首次 APK 的11项保持独立。用户最终单包候选必须通过上述门槛后才能推荐。MuMu改版、ART激活/禁用重启、真实Root授权和学校有效记录未验收。

## 原生 APK 新阶段（2026-10-19）

用户最新目标是在 MuMu 内安装 APK 直接使用。本阶段新增无需 PC 服务的原生 Java/Android SDK 本地应用；旧计划“不做独立 APK”已由本次明确需求覆盖，旧软件证据保留。构建、安装与签名限制见[APK 交付说明](android-apk.md)。当前 APK/官方 emulator 结果必须按本轮集成 HEAD 的 Actions 单独核对，不借用此前 Python/网页测试通过结论。真实 MuMu、应用执行和学校有效记录仍未验收；Root/LSPosed 仅保留可选能力架构，不默认安装或配置。

本轮将原生UI、持久化本地simulation、只读能力诊断、独立本地状态边界和APK构建/测试脚本组合；本地simulation不伪装服务端JobView或AGENT。未知能力不启用真实执行，needs_attention须明确停止确认后才能新建模拟；历史任务保留。Python分发保护另经合成文件RED→GREEN验证，排除新增Android目录里的local.properties、签名材料和构建缓存，保留审查源码；旧已交付包没有这些敏感文件。

本轮初次冻结组合 Linux/Python3.12.14 完整 **564 passed**（90.58秒，1条继承warning）；frozen依赖、Schema/Android边界防漂移、Ruff、旧web Node生产脚本harness、Bash语法和4份XML解析通过。46个Python package/静态资源文件与f3d基线逐字节一致。上述结果不包含Android编译或仪器执行。

## 当前交付候选

Dot 已承担主要实现与修复；本地 Codex 负责 Windows、真实设备与集成独立验收。此分工覆盖旧计划中的负责人，详见 [冲刺交接](handoffs/2026-10-18-dot-lead-sprint.md) 与 [Issue #16](https://github.com/Maximora-byte/swu-happyrun/issues/16)。本文不宣称全部 v1 已验收，也不把提交、局部测试、软件联调、设备观测和学校有效记录合并为同一种“完成”。

### 控制台第二轮修订（2026-10-19）

首轮 [CI run 39184117989](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39184117989) 实际执行 Chromium，9组通过、3组失败；三处失败使用了不适用于 fieldset 的 Playwright disabled 判断，现改查原生属性与真实输入控件禁用状态。截图审阅还发现创建/详情入口位于长任务列表之后，现将入口前置，点击任务后滚动并聚焦详情；新增桌面/手机 viewport 断言。新浏览器结果以本轮同 HEAD Actions 为准，不能沿用首轮局部通过。

同次 Windows/Python3.11 的取消后停止失败用例出现 start_count=0。独立真实TCP诊断用可控26秒偏移复现固定服务UTC与实时agent时钟混用，使开始前租约预算不足；测试现保持服务UTC随单调时钟推进，并保留显式租约过期注入。修复只涉及测试，不改变生产租约防线；该重现不证明历史CI只有这一种原因。

本轮 Linux/Python3.12.14 完整 **557 passed**（97.91秒）；新wheel源码外 **35 HTTP passed**（43.32秒），包括新增0/26秒时钟回归。冻结依赖、Schema、lint/format和Node检查通过；同一wheel源码外 **7 daemon passed**（15.79秒），CLI smoke、console真实TCP、core/server/agent三extras隔离通过，Playwright不进入普通运行环境。下方556/34结果保留为首轮快照，不覆盖本轮修改。真实Chromium与Windows复验须查看本轮同HEAD Actions，不能用本地Linux结果代替。

### 本地管理控制台首轮快照（2026-10-19）

在准确基线 `585e1b0674022c8262109a7ea5e5720c0532eee9` 上增加同源控制台、ADMIN任务分页和显式 `server --open-browser`。内置HTML/JS/CSS随wheel分发，不引入服务器运行时前端下载；令牌只保留当前页面内存。操作与边界见[控制台](console.md)、[API](console-api.md)、[浏览器验收](console-browser-qa.md)。默认不打开浏览器，不启动agent，不解除真实设备限制。

本轮 Linux/Python3.12.14 完整 **556 passed**；新wheel源码外 **34 HTTP + 7 daemon**、CLI smoke与新增console真实TCP检查通过。新增检查核对三asset字节/安全头、静态白名单、ADMIN认证分页、重启cursor稳定。冻结依赖、Schema、lint/format、Node生产脚本harness、构建与三extras隔离通过；Playwright仅browser-test extra。

本地未执行Chromium，受现有IPC隔离限制；页面交互、布局和截图验收结果以同一候选HEAD的Actions `console-browser-qa` 及PR记录为准。HTTP/Node检查不替代真实浏览器验收。MuMu/vivo、具体乐跑、学校记录与容器实测仍受已列环境/样本限制。

### CI 测试同步修正（2026-10-19）

准确基线 `4d73f42ec15e0c2cc14371f8a4441ef2101e6e41` 的 [CI run 39179740749](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39179740749) 在 Windows/Python3.13 的 active-renewal 测试失败。独立延迟父进程检查后，确定性复现旧测试错过短暂 active 状态；这说明测试存在竞态，但未证明该次 CI 只有这一种原因。本轮只修测试同步：在启动前预设故障，由服务端处理首个已持久化 active 的 renew 时注入503；父进程退出后断言停止与不重试。

组合复测另暴露 readiness 测试直接改健康标志、被后台 tick 覆盖的竞争，原518通过/1失败日志保留。现以真实 tick 成功→异常→恢复和队列屏障验证503脱敏、health200、ready恢复与线程退出。两处都不修改生产模块。

最终完整 **519 passed**；同一已验收 wheel 的新 **7 daemon** 与 **15 scheduler** 场景在源码外安装环境复跑通过。生产源码与 wheel 字节不变，先前34 HTTP、9 lifecycle、50外部边界及CLI smoke证据按相同wheel SHA复用，不称本轮重新跑过。新远端CI结果仍须单独核对；设备/容器等已列阻塞不变。

### 信号处理重入修复候选（2026-10-19）

在准确基线 `58264f22ba8829ec707f2d1a07617332f42ef48d` 上追加最小修复：信号 handler 内原有 Event.set 可能重入正在持有的 condition 锁而死锁。现改为无锁记录 signum，等待使用单调时钟和最长 50ms 的检查间隔。新真实子进程回归先在旧安装 wheel 上以 3 秒超时复现，再在修复包通过。

本轮 Linux / Python 3.12.14：完整 **519 passed**；源码外安装 wheel **34 HTTP + 7 daemon + 9 lifecycle + 50 外部边界** 均通过，CLI smoke、三 extras 隔离、frozen/Schema/lint/build 通过。后文513/34/7属于上一轮路线修复证据，不覆盖此信号重入缺口。最终准确提交 SHA/Hosted CI 由集成 PR 绑定。

真实设备检查仍受环境阻塞：云端无 Docker/Podman/nerdctl/containerd/ADB 和 Docker socket，用户桌面离线、无已保存可用环境；没有实际容器、MuMu/vivo、步道乐跑或学校记录验收结论。

### 路线完整性与代理生命周期修复候选

在 PR #25 历史 HEAD `19c15ba7cfad7fc1039b7b552677a3bd3e82cf6b` 上继续修复。旧版 400/31 项检查是历史软件证据，未覆盖“计时预算耗尽但路线未走完”的缺口，不能作为路线完成证明。本轮成功路径使用短合成路线、2 m/s 合法速度和 2 秒预算；只有到达归一化路线端点才 completed，预算不足立即 needs_attention / simulation_incomplete，不产生学校记录证据。

- [Android 只读诊断 PR #26](https://github.com/Maximora-byte/swu-happyrun/pull/26)：`5e841d1fa8e231caa33608cdd689f0b79b1f9d8d`。新增模块与 [说明](android-diagnostics.md)，没有实测设备或启用位置写入。
- [坐标归一化 PR #27](https://github.com/Maximora-byte/swu-happyrun/pull/27)：`9db9c8f31567b3300699e79b3a340f7bbaf3c22c`。[转换约束](coordinate-conversion.md)明确离线近似、输入域与源 revision 保留。
- [代理生命周期 PR #28](https://github.com/Maximora-byte/swu-happyrun/pull/28)：`9c358125a9724fafd3468a64f069e5ec92acab49`。合作式停止、有限空闲重连、claim/renew 不盲目重试、诊断 CLI 接线。
- [路线执行](route-execution.md)与 I0 测试按逐文件 manifest 组合；最终集成 SHA 以 PR/Actions 准确 push HEAD 为准，不将本地变更 commit 当远程提交。
- 本轮 Linux / Python 3.12.14 完整 **513 passed**；源码外安装 wheel 的 **34 项真实 HTTP**、**7 项 daemon/TCP/subprocess** 和 CLI smoke 全通过。GCJ02/BD09 路线完整流程检查规范化端点、原文件/revision不变及无 record evidence。
- 三 extras 安装隔离、frozen、Schema、lint/format、wheel/sdist 构建通过。Windows 信号停止、MuMu/vivo、步道乐跑实际流程、有效学校记录和 Docker 容器仍未实测；最终 Hosted CI 另按不可变 HEAD 核查。

下表保留组成基线与阶段追溯；本轮结果以上述条目和[交付验证记录](delivery-validation.md)为准。

| 范围 | 代码交付状态 | 软件验证证据 / 剩余门槛 | 设备与记录 |
| --- | --- | --- | --- |
| C0/L0 继承与恢复结构边 | [替代 PR #17](https://github.com/Maximora-byte/swu-happyrun/pull/17)，HEAD `6ed02c29924ccc3ab26c028fbf46d15477d84eb0` | 修复 verify_only 恢复路径；基于旧 PR #13 继承，最终候选须保留修复 | 只读主机诊断不等于设备执行通过 |
| C1 恢复/归属/证据契约 | [PR #19](https://github.com/Maximora-byte/swu-happyrun/pull/19)，阶段 HEAD `a82e4d97a5a7e1de5112eabeecac6e97312089a7` | 摘要别名一致性与 ASCII 日程时间修复；该版本本地 163 tests 通过，最终集成重跑结果见 I0 记录 | 无设备/学校有效记录结论 |
| S0 API 与 SQLite | [PR #18](https://github.com/Maximora-byte/swu-happyrun/pull/18)，阶段 HEAD `c474119cdc18fa34fefffd5e8ea64c79f0106159`（继承 C0） | 本地 152 tests；该 HEAD 两个 CI run success 已核对；不代表 S1/S2 | 不依赖真实设备 |
| S1 租约、取消、恢复 | [PR #22](https://github.com/Maximora-byte/swu-happyrun/pull/22)，阶段 HEAD `e3ffab6a0309d2b7e484edfe9498f4e2aab9e1b2` | 本地 223 tests、独立审计 14 项；安装包实际 HTTP 故障矩阵已执行，见 I0 记录 | 不依赖真实设备 |
| S2 日程与重启 | [PR #23](https://github.com/Maximora-byte/swu-happyrun/pull/23)，阶段 HEAD `561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9` | 本地 252 tests、独立审计 6 项；ready/tzdata/schema3；最终软件集成结果见 I0 记录 | 无设备结论 |
| L1 profile / driver / fake | [PR #20](https://github.com/Maximora-byte/swu-happyrun/pull/20)，阶段 HEAD `10b2172bebd8aba302cc8a0345503b32d38589f6`，继承 C1 alias 修复 | 阶段本地 216 tests；新 HEAD CI 单列核对；fake 不产 app_record | 真实设备适配 `needs_samples` |
| L2 agent / journal / CLI | [PR #21](https://github.com/Maximora-byte/swu-happyrun/pull/21)，阶段 HEAD `e935632079c805952e7b143e5438c7d829b34f22`，已继承新版 L1 | Windows lock 与 attention 报告修复已包含；最终集成检查见下方 I0 与交付验证记录，最终提交 CI 单列核对 | 当前物理后端 `unsupported_by_candidate` |
| 安装/部署/文档 | 候选文件已准备，尚未据此声称容器可运行 | 7 项交付静态/fixture 测试与 lint/format 通过；Docker CLI 不可用，容器检查 `not_tested` | Windows 安装待独立验证 |
| I0 集成 | 组件不可变 HEAD 与逐文件 manifest 已固定；集成提交 SHA 以 PR/Actions 为准 | 历史基线 Linux完整 400 tests、wheel外部安装 31 真实HTTP用例；本轮513/34+7及CLI smoke见上方；冻结安装/Schema/lint/build/三extras隔离通过；最终提交CI/artifact另查 | 不替代本地设备验收 |
| L3 乐跑应用适配 | `needs_samples` / `unsupported_by_candidate` | 需要精确版本、本人会话、学校规则与脱敏页面样本，见 [Issue #9](https://github.com/Maximora-byte/swu-happyrun/issues/9) | `not_tested` |
| vivo 无 Root | 保留研究方向；当前候选 `unsupported_by_candidate` | 见 [证据矩阵](research/vivo-noroot.md)，不推断平台永久不可行 | `not_tested` |
| 纯接口直传 | 保留研究方向；当前候选 `unsupported_by_candidate` | 未取得西大真实业务协议/签名样本，见 [证据矩阵](research/direct-protocol.md) | `not_tested` |

上述阶段 HEAD 用于追溯已报告的检查，不是最终统一候选。最终安装与验收必须使用集成 PR 正文和对应 Actions `github.sha` 指定的不可变 HEAD；I0 manifest 记录组件来源，不能混用分支最新内容。

### 发布门槛与可复现资料

- 候选 HEAD 由集成 PR 正文/Actions `github.sha` 绑定，父基线、各 PR 继承关系和最终集成命令/结果在 I0 发布记录补齐；“推进中”不是验收通过。
- [50 项验收设计覆盖映射](acceptance-coverage.md) 标明实际测试方法与尚未覆盖范围；映射存在不等于通过。
- [交付验证记录](delivery-validation.md) 区分执行过和未执行的检查；[安装](installation.md)、[服务器](server.md)、[fake 与故障](fake-e2e.md)、[本地 QA](local-qa.md) 提供操作步骤。
- CI 只在既有检查和独立安装成功后生成候选 wheel/sdist/checksum artifact。未核对实际 run 和 artifact 前，不称已有可下载安装包；没有创建 Release。
- MuMu 已知历史证据仅为 6.8.4.0 / Android 15 实例可查询且停止、ADB 无设备。新的 device_verified / record_verified 必须来自指定版本的实际观测。
- 本轮不操作用户桌面，不修改生产服务器、DNS、账号、Root 或系统安全设置。原始截图、路线、数据库、账号与 token 留私有环境。

## 历史记录（下列内容已被上方当前状态覆盖）

以下原文保留当时接单与分工背景；“未开始”“旧负责人”“本轮交付仅设计”等表述仅适用于对应历史快照。


更新日期：2026-10-18（Asia/Shanghai）。此文件记录证据，不由收到消息或计划勾选自动推断完成。

### 当时的分工与证据

- 用户最新要求：Dot 主导主要开发，本地 Codex 负责实测与集成审核；见[冲刺任务](handoffs/2026-10-18-dot-lead-sprint.md)。目标明早候选版、24 小时内一次 v1 验收，不承诺未经实测的完整兼容性。
- 仓库已公开。当前 main 尚未合入业务代码；C0/L0 在 [PR #13](https://github.com/Maximora-byte/swu-happyrun/pull/13)，HEAD `3ff0a33a01c629432a2036f4e105bed52157bd9e`，109 tests 和四组 CI 已通过，但 Dot 报告的 verify_only 恢复路径问题仍是阻塞。
- Dot 已在 [Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 回报真实仓库/Python 能力，并提交 [PR #12](https://github.com/Maximora-byte/swu-happyrun/pull/12) 的 50 条待实现服务器测试设计；这不是 S0 产品实现。
- Dot 现在负责接管 C0 修复与 [C1 #14](https://github.com/Maximora-byte/swu-happyrun/issues/14)，随后实现 S0-S2、L1-L3 和 CLI；本地不再负责主要产品编码。新角色覆盖原 Issue/计划中的旧负责人。
- 本地 MuMu 6.8.4.0 / Android 15.0 实例查询通过，实例停止，ADB 无设备；定位/传感器、应用、vivo 与学校有效记录未验证。
- 本轮冲刺消息的实际送达与接单回执以 Matrix / Issue 为证；不能由这份计划的存在推断 Dot 已开始夜间任务。

### 初次建仓快照（历史记录）

以下是本轮角色调整前的历史快照；状态和负责人以本页上方、最新 AGENTS.md 与冲刺任务为准。

| 项目 | 当前状态 | 证据/下一步 |
| --- | --- | --- |
| 初版设计 | 已提交 | `687d0be` |
| 设计评估、v1 契约与双端计划 | 已发布，待 Dot 交叉评审 | [设计基线 015447d](https://github.com/Maximora-byte/swu-happyrun/commit/015447dc97637311874dda061cb5fe48babb21f5) |
| GitHub 仓库 | 已创建并推送 | [Maximora-byte/swu-happyrun](https://github.com/Maximora-byte/swu-happyrun)，私有，默认分支 main |
| Matrix Dot 入口 | 已识别，未派发 | 群名 `Matrix · ChatGPT Dot`；用户本次选择只准备交接任务 |
| Dot 接单与仓库访问 | 未确认，云端开发未启动 | [交接 Issue #1](https://github.com/Maximora-byte/swu-happyrun/issues/1) 与[待发送说明](handoffs/dot-server.md)已准备 |
| 服务器实现 | 未开始 | S0-S2 |
| 本地代理实现 | 未开始 | C0、L0-L3 |
| MuMu Android 15 兼容 | 未验证 | 已确认安装信息，无应用运行证据 |
| vivo 无 Root 兼容 | 未验证 | 缺实际 Android/app 版本和测试连接 |
| 西大学校规则与有效记录 | 未验证 | 需实际校区、规则、版本和本人会话 |

每次交接记录 Issue/PR URL、基线与 HEAD、运行的检查、未验证范围。旧 Workflow 连接器本轮返回内部错误；Matrix Dot 独立连接器能够列出群与连接状态，不把回调 HTTP 接收当作 Dot 接单。

### 初次任务清单（历史负责人）

负责人是计划分工，非 GitHub 用户指派；Dot 尚未实际接单。ready 表示可进入实施，不表示已经开工。

| Issue | 负责人 | 前置条件 |
| --- | --- | --- |
| [#1 Dot 接入与协议评审](https://github.com/Maximora-byte/swu-happyrun/issues/1) | Dot | 待发送交接；实际仓库访问与执行能力确认 |
| [#2 C0 共享模型与工具链](https://github.com/Maximora-byte/swu-happyrun/issues/2) | 本地 Codex | 设计基线已发布 |
| [#3 L0 MuMu/ADB 探测](https://github.com/Maximora-byte/swu-happyrun/issues/3) | 本地 Codex | 只读勘察可先行；模型集成依赖 C0 |
| [#4 S0 服务 API 与存储](https://github.com/Maximora-byte/swu-happyrun/issues/4) | Dot | #1、#2 |
| [#5 S1 租约与恢复](https://github.com/Maximora-byte/swu-happyrun/issues/5) | Dot | #4 |
| [#6 S2 日程与部署包](https://github.com/Maximora-byte/swu-happyrun/issues/6) | Dot | #5 |
| [#7 L1 配置与设备驱动](https://github.com/Maximora-byte/swu-happyrun/issues/7) | 本地 Codex | #2、#3 |
| [#8 L2 代理与 CLI](https://github.com/Maximora-byte/swu-happyrun/issues/8) | 本地 Codex | #7；真实 HTTP 验收依赖 #5 |
| [#9 L3 应用适配与记录核验](https://github.com/Maximora-byte/swu-happyrun/issues/9) | 本地 Codex | #8、实际校区/规则/版本/本人会话 |
| [#10 I0 双端联调](https://github.com/Maximora-byte/swu-happyrun/issues/10) | 本地 Codex，Dot 修复服务器 | #6、#8；设备验收依赖 #9 |
| [#11 R0 vivo/纯接口研究](https://github.com/Maximora-byte/swu-happyrun/issues/11) | 本地 Codex，Dot 评审接口样本 | 实际设备版本、连接和脱敏样本 |

本轮交付仅包含设计、协议草案、实施计划和协作任务。Markdown 相对链接、占位符扫描及 Git 空白检查通过；没有业务代码，因此未运行产品测试，也没有生成设备验收结论。

最后追加仅Android持久化故障锁存及UI/真实SQLite trigger回归：存储失败停止模拟、显示未保存状态并禁止继续开始/停止；不能把旧持久running当成仍在执行。另增加已核包名的只读PackageInfo诊断。Android CI分别运行API31/35官方AVD，记录debug签名指纹；这些均不能代替MuMu或目标应用执行验收。此前完整Python结果按原快照保留，最后变更另做目标测试/静态/分发检查。

最终五路更新后的Python目标检查（Android契约与delivery）**14 passed**，Schema/边界防漂移、Ruff、旧web Node、脚本/XML/接口静态检查和分发隐私检查通过；Python生产模块仍与f3d相同。APK构建与11项Android测试尚未在本地运行，须取同HEAD的API31/35 Actions证据。

### af3 后的单机显示诊断候选

`af3f2a089da594941bc752c88734fedd660de739` 的 Windows 3.11/3.13 push
均实际通过（各 888 passed、9 skipped）；普通 Android API31/35 的 debug 和
optional job 均在首次 display observation 失败。安全报告显示安装包、版本、
签名及唯一 task 匹配，随后停在 `base_activity` 的断言，尚不能区分空组件与
非预期组件；未到后续 native / wizard 验收，不把构建成功当运行通过。

本次仅增加两个布尔诊断和精确断言分类，保留原严格条件。临时诊断权限仅限
同分支、精确 before `af3f2a089da594941bc752c88734fedd660de739` 的下一次
可信 push、`android-apk` job、API31。其余 Android job 仍构建和静态检查，
runtime 显式 `not_run`。本次单机采证不能替代最终完整矩阵，也不表示已修复
显示问题。实际运行结果以新提交的 Actions 为准。

### b364 单机诊断与任务身份修订

`b3642f7215135fb90230b13ff1bdcfb5930ae227` 普通 API31 的实际报告明确
`base_activity_missing`，`base_activity_present=0`；安装身份及唯一 task 匹配。
其余 Android runtime 按计划未执行；Windows/Linux、浏览器、容器及 Android
构建/静态检查通过。此结果定位了失败断言，没有证明替代实现已通过。

修订先严格校验持久 `baseIntent` 的组件包名和类名；若 `baseActivity` 非空，
同样必须精确匹配。仅在原 `AppTask` 中启动本应用，启动后的同 task/display、
窗口焦点、可见控件、签名与时效门槛全部保留。候选继续只授权精确 before
`b3642f7215135fb90230b13ff1bdcfb5930ae227` 的普通 API31 验证，后续完整矩阵
仍待修订实际运行结果。资源 R1–R5 的独立候选未加入本次修订。

### 2107 启动阶段诊断

`2107bf7d10c6318652622bde0e35fc60efb920ea` 普通 API31 实际通过持久
baseIntent 精确身份校验，随后停在 `launch` / `NullPointerException`。
现有报告不足以定位框架调用栈，不推定 context 或 options 是根因。
本次仅增加固定白名单栈帧标签及有界行号，拒绝异常消息、任意类名与对象值；
Android 行为及接受条件未变。继续只在精确 before2107 的普通 API31 采证，
其他 Android runtime 明确 not_run。修复及最终全矩阵仍待实际结果。

### 09b 远端栈诊断

09b67d1f839d4b17d5b06114698cb18ec9fa0d7d 的普通 API31 安全栈确认异常经 Parcel/Binder 返回，仍未定位服务端精确行。本轮只补固定服务端栈帧标签、去重与 remote marker 布尔，最多 12 帧；不含异常消息或对象值，Android 行为与接受条件不变。精确 before09b 的单普通31用于最后一次纯结构化栈采证，其他 runtime 未执行。若服务端栈缺失，不将猜测写成根因。

### b4 后的默认显示 recent-task 恢复验证候选

b4 单机安全栈出现 `server_task_add_child:1725`，说明异常经服务端返回，
但现有 guest 源码版本未确定，不能把别的 AOSP tag 行号直接当空对象证明。
本次仅测试入口改用同一个已严格核验的 `AppTask.moveToFront()` 恢复 recent task；
必须先由系统查询确认默认 display 与独立期望相等，非默认或查询缺失在恢复前拒绝。
恢复后同 task/display、焦点、可见控件及其余身份/时效条件继续严格检查。

精确 before `b4ca97743f64a52b4981fbcf338899de008b52bc` 的普通 API31
用于实际验证；其他 runtime 明确未执行，完整矩阵仍待后续验收。隔离官方 AVD
额外保存限定公开 guest build 字段和镜像 revision，缺失写 unknown；不采集设备
序列号、账户或全量 getprop，不将此入口用于用户设备自动采集。

### 最终资源统一候选（源与软件验证阶段）

以 `005bb79058d434d9897a266868a1fbd5bae566b4` 为准确基线，保留已通过的
普通 API31 display7/native15/namespace3 修订，叠加以下独立受审资源来源的
21 个 owned 路径：

- R1 `3694b340d10776193d9b36822cf82fdabf211890`
- R2 / PR49 `6b66c2e20da808d920bc34a2f773d4888468e33b`
- R3 / PR48 `7ead96e12839d4baadd864cae8e397c918844809`
- R4 / PR51 `a341d214ea18b259c443aa9ff7d603e3233eddc3`
- R5 / PR50 `4dbc9ec1e1e034f9633930f9c6aae889a069039a`

旧 onboarding/vivo/direct 文档按全文前缀核验追加，无覆盖近期 Windows、
RESTORE、诊断或 CI 修复。真实适配注册表仍为空，真实 MuMu 能力默认关闭；
校准/绑定和 runner 协议链的软件测试不能证明实际位置、传感器、物理停止
或学校记录。旧间歇 HTTP/TLS 调查继续保留，不能用后续一次绿消除失败史。

完成原批准矩阵的精确门禁为本分支下一次 before005bb 的可信 push，三个
指定 job（ordinary/optional/HTTPS）各 API31/35，其他事件 runtime 未执行。
新 HEAD 的完整软件/设备结果见 PR 正文和 Actions；此处不预填通过结果。
普通 APK 与 instrumentation APK 必须同构建同签名配对；debug 签名跨次
可能不同，签名冲突不得自动卸载抹除数据。

### 234 显示附着等待修订

234 普通 API31 的 RESTORE 后读取到尚未附着的 display=-1，原循环立即退出，
最终严格门槛正确拒绝。该确定性测试入口缺陷已用旧谓词 JVM RED 复现。
修订仅允许未知 -1 在原有期限内只读等待；已知错误 display、错误 task 或
多 task 仍立即退出，最终接受条件及超时均不变。21 个资源路径保持原字节。
234 原完整矩阵新增 HTTPS API35 的 back_idle/rapid_toggle RuntimeError，
暂不能据仅异常类型判定 UI 或 fixture 根因。API31 HTTPS 全部通过，普通 API35、
optional API31/35 通过；历史 af3 同类成功与本次失败均保留。
本次收窄为本分支精确 before234 下一次可信 push 的两个组合：ordinary/API31
验证等待修订，HTTPS/API35 保留原完整顺序获取主错误与退出错误安全证据。
其他组合继续构建/静态检查，runtime 明确 not_run；不能称最终全矩阵通过。
后续完整验收仍需准确新 HEAD 的六组合实际结果。

### 73af 双组合结果与最终六组合验收

73af 普通 API31 实际 display7/native15/namespace3 通过；HTTPS API35
实际 15HTTP+3UI+14前台+持久恢复1+存活旧fence1 通过。本轮没有复现
234 的两个 RuntimeError，因此其根因仍 open；新增安全诊断未证明修复根因。
本候选仅更新门禁与状态，产品、QA判定、预算和资源字节不变。最终本分支
精确 before73af 的一次可信 push 恢复普通/optional/HTTPS × API31/35
完整六组合，旧 before234 拒绝，其他事件运行明确 not_run。最终结果以
准确新 HEAD 为准，不合并不同 HEAD 的绿灯冒充统一验收。
