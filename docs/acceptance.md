# 统一候选验收记录

本文件跟随 Issue41 七任务计划。最终源 HEAD、tree、测试事件和产物链接由交付 PR 正文绑定；发布前不得把旧 HEAD 的结果当作本候选通过。以下为冻结前状态，不是验收勾选表。

## 组合来源与接受边界

- 产品基线：PR35 `28871b2d599a8ec8335570effb3207d2564639ab`，继承 PR25。
- main：`5377c70b3af02dd954b8e2f81666ccab78b330ce`；保留独立 QA 报告、复现脚本、服务器矩阵和七任务计划。新增[资源细化 R1–R5 计划](superpowers/plans/2026-10-19-resource-guided-adaptation.md)作为后续范围，当前候选不纳入正在独立开发的资源适配实现。计划内早期 HEAD 是原记录，本节给出当前准确来源。
- 探测批次事务修复：PR39 `5d52d78acf6d0f7e7064e1209810746dd05b93d7`，已合原候选 `0bb9344ddefe8054177101583282c57f27f5b38a`；额外中途写失败与精确映射测试 PR43 `a3fd8a6f71a9745e68a2f235c34b6367bdf4aac6`。
- Python 持久完成恢复：PR40 `8aef593dd89ca47d63a702ee1cf6952382169bbd`。
- 后续持续前台、原生恢复、Windows 夹具、CI 分阶段、MuMu 观察入口与输入门槛，以最终组合文件清单和 PR 依赖为准。

Issue37 已由 Codex 限定接受并关闭；Issue36 新修订仍需 Codex 在准确候选上独立接受；原始缺陷复现脚本成功退出只证明曾复现缺陷，不等于修复验证。产品 PR 尚未自动合入 main。

## 结果填写规则

每条记录必须包含源 HEAD/tree、环境版本、实际命令、退出码、passed/skipped/failed 数量、证据路径或 Actions 链接。软件测试、设备观察、实际学校记录分列。当前组合已完成下列本地回归；hosted CI、Android 编译/仪器和 MuMu 仍按各自结果填写。

| 检查 | 本轮状态 | 验收范围 |
| --- | --- | --- |
| 源码全套、契约、Schema、Ruff、锁文件 | Linux/Python3.12.14：885 passed / 186.89秒，1继承warning；Schema/Ruff/frozen通过 | Python 软件，含pre-bind修订 |
| 源码外同一 wheel 的 HTTP、daemon、生命周期、日程、容器 guard | 新wheel 74 passed / 129.00秒；同wheel fake smoke 通过，含真实回环HTTP与重启持久化 | 安装包软件，非Docker runtime |
| 浏览器 12 组、容器持久化和权限 | 同 HEAD Actions 待运行 | 浏览器/容器软件 |
| Windows 普通账户 symlink 夹具 | Linux 合成错误与实际 symlink 先验证；Windows 待 CI/Codex | OS 条件明确 skip，不等于防护通过 |
| Android API31/35 普通及可选包 | 同 HEAD 构建/静态/仪器待运行 | 官方 AVD，不是 MuMu |
| Android 原 15 HTTPS、14 前台 Activity、新 1 持久恢复与 1 存活旧进程 fence 场景 | 同 HEAD 实际仪器待运行，分别报告 | 仅 synthetic simulation |
| MuMu6.8.4.0 / Android15 多显示器完整闭环 | 旧774 APK现场完成/重启/中断不重跑/attention停止持久已核；运行中直接stop、新候选与远程仍待验收 | 本应用有限范围 |
| 实际步道乐跑、vivo、学校有效记录 | 未验收，输入不足处执行能力关闭 | 不借用 fake/框架诊断结论 |

## 本地修订证据与开放诊断

- pre-bind 历史身份不能被新 bind 覆盖的最终三文件修订已经显式纳入；修后完整883项通过（180.55秒）。修前854项仅保留为历史，不能代替该修订验收。
- 精确组合重新编译纯 Java，105项 JUnit通过（5.913秒），包括成功/尝试 tick 两种诊断计数。Android源/host断言不计为真实仪器通过。
- 已安装验证的wheel SHA256 `36bcc69a67676902b84ae87b80388ad0723be73935de2b06971aa1bae5779370`；core/server/agent三独立新环境安装通过，Playwright不进入普通组件。文档更新后的wheel为 `683fde1cab459483530cdbf244b954fba14609eae8f80f0ffeb32e8bd3643d62`，逐成员仅METADATA/RECORD变化，生产代码/资源完全一致；新wheel源码外74项重新执行通过（129.00秒）。两份分发的显式隐私检查均通过。
- 隐私检查脚本原先忽略显式参数：目录/不存在/未知文件三项RED后修复，五项回归通过；错误输入现非零退出。
- 原生恢复真实双进程HTTPS的正负语义都有实际通过，但同host顺序夹具出现过ADMIN ReadTimeout与一次负向子进程非零，根因尚未确定，状态 `intermittent_unresolved`。保留失败和成功索引，不以最后一次通过/隔离运行解释为解决。此诊断与Python pre-bind问题分别跟踪。

## 产物与安装

同一 CI 构建的普通 app APK 与匹配 instrumentation APK 随精确白名单交付；`qa/android/delivery-debug.json` 或 `delivery-optional.json` 记录包名、版本、同一签名摘要及各 APK SHA256，旁边的 `.signatures.txt` 和 `.SHA256SUMS` 可独立校验。构建 provenance 另外绑定源 commit/tree、run/attempt、job/API 和完整 APK 集。

只有相同签名才可覆盖更新；不同临时 debug 签名须保留原安装和数据，由用户决定后续操作，不自动卸载或清库。普通包不含 remoteQa 测试信任；remoteQa 只供一次性 CI，不能作用户安装包。测试入口运行前按[本地 QA 清单](local-qa.md)核对目标实例和数据保护条件。

Actions artifact 保留 7 天。到期后应由有权限人员对准确源版本正常重新构建并重新记录签名、SHA 和运行状态；不得把新签名冒充旧安装可直接升级。新硬件权限事件仍须独立授权，旧一次性 KVM 门禁不能自动复用。

## 旧基线证据

288 的准确 push checks `39199236415`、HTTPS `39199236452` 和 container `39199236390` 成功；PR 合成事件 `39199240147` 四个 Android 作业因系统 ANR/启动超时失败。它们保留为历史，不覆盖本轮新增代码。当前 CI 将构建/静态检查与有授权的 runtime 分开，`not_run`、`unknown` 和失败都不能当作设备验收成功。

## 最终修订运行记录

调度锁时钟单测的后台 ticker 竞态已用独立 store/Scheduler 夹具修复，保留锁内读时钟与单次写锁断言，生产代码未改；独立15项及同wheel源码外15项通过。随后全套为882 passed / 1 failed，失败定位到AVD启动脚本的printf管道SIGPIPE141，日志保留。确定性延迟写入夹具先复现，改用here-string后10专项通过，覆盖不读stdin、正常读取no、avdmanager退出7必须原样失败；SDK许可仍只读EOF。修后最终全套885 passed / 186.89秒 / exit0，1继承warning。此前883与882+1均保留为不同输入。

PR40 8aef 的合成PR事件在API31实际执行native-debug时，四项AndroidAcceptanceTest因找不到start_simulation/refresh_checks失败；测试前仅有320×640向导首屏证据，缺失败瞬间状态。旧辅助查找的内层1秒预算短路已确定性复现，并纳入独立导航修订：共享原5秒预算、真实目标滚入视窗、同包可见节点才点击，recreate跟随当前Activity。正常pytest入口实际编译并执行5项预算及8项源码提取adapter检查，另保留旧方法RED；组合定向11项通过，完整885在此纯测试修订前完成，产品源码未变化。Android实际失败根因尚未完全确认，必须用新候选真实AVD复验，不能归为无KVM启动失败或用本地Python通过代替Android验证。

QA44的原始复现脚本在当前受控源码独立本地Git快照运行：两个恢复期望模式和probe --expect-fixed均exit0。第一次直接使用非Git目录因脚本要求rev-parse失败，保留该执行错误；本地快照commit仅用于溯源，不等于已发布GitHub HEAD。

## 481 精确 HEAD 的首轮 hosted CI 与后续诊断候选

发布 PR46 HEAD `481098f124f0fb5ea054180d1ecb845008348003` 的[HTTPS run39205241706](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39205241706)在API31/35均真实通过：各15 HTTP +3远程UI、14前台Activity、1持久完成恢复、1存活旧进程新fence观察。最后一项使用明确5200ms受控调度延迟，真实renew4故障/租约过期后，旧PID仍活且停止、尝试/接受tick均不再增长；不外推任意设备链路。

同HEAD的push/PR container与Linux Python/浏览器通过；checks整体失败。Windows新增测试的长参数ID超过系统环境变量长度，以及默认字符编码读取源码失败，已在独立后续候选修正为短ID/显式UTF8，65537字节负例未缩小。普通/optional四Android作业构建/静态/配对通过，但新增display观察首项返回泛化ValueError（tests0），后续native/导航等没有执行。后续仅新增白名单phase/数字/布尔诊断以定位真实失败，接受条件不变；尚不能宣称观察入口已修复。未授权PR事件的runtime明确not_run，不当作通过。

本轮修复重试门禁只接受foreground分支、准确before481的下一push；旧before288拒绝。原481成功与失败均保留，[完整回执](https://github.com/Maximora-byte/swu-happyrun/pull/46#issuecomment-6260574805)。新修订仍需准确HEAD的Windows与AVD实际验证；既往JVM顺序HTTPS间歇和历史Windows HTTP超时根因保持未决。
