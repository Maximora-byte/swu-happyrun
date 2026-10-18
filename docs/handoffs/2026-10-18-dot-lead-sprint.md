# Dot 主导开发：今晚至次日的交付任务

生效日期：2026-10-18（Asia/Shanghai）。用户最新指令：“dot负责主要开发 你负责实测……争取一天把这个项目开发完”。这是角色调整与冲刺目标，不是任何功能已经完成的证明。

## 分工与交付目标

**Dot 负责全部主要实现和修复**：C0/C1、S0-S2、L1-L3、CLI、实现测试、依赖与 CI、部署包、可复现示例。**本地 Codex 负责实测和独立验收**：Windows 安装、MuMu Android 15、可用的 vivo 无 Root 路径、实际 HTTP 联调、故障复现、证据和 PR 集成审核。

以发出任务为起点争取 24 小时交付 v1。目标是明早 2026-10-19 09:00 前有可测试候选版本，白天实测和修复，2026-10-19 23:30 前完成一次发布候选验收。时间节点是目标；出现真实阻塞时说明影响和已交付范围，不能删断言或返回占位成功赶进度。

v1 必须能安装、启动服务器与代理，并通过真实 HTTP + fake driver 完成任务创建、领取、续租、取消、恢复、结果查询和日程去重；Windows/MuMu 驱动可交给本地运行探针；CLI、部署和故障处理文档齐全。具体乐跑版本的实际流程与有效记录按独立证据验收。学校规则、点位、app 版本、本人会话或设备能力未取得时，明确阻塞，不能把 fake 任务当作西大有效记录。

## 已有基线与第一件事

- 当前 main 的原设计基线：`39cdcc05503e2c1c0f1190efd2e1b3c268976819`；开工前重新读取最新 main 的 AGENTS.md 和本说明。
- 本地 C0/L0：[PR #13](https://github.com/Maximora-byte/swu-happyrun/pull/13)，交接 HEAD `3ff0a33a01c629432a2036f4e105bed52157bd9e`。109 个测试及四组 CI 已通过，但 **verify_only 恢复路径阻塞仍未修复**，不能仅因绿灯合并。
- Dot 测试设计：[PR #12](https://github.com/Maximora-byte/swu-happyrun/pull/12)，HEAD `cd508ceb0e75b8615213e0f9054cfe848b6493cc`，50 条用例是设计，不是已运行结果。
- [C1 #14](https://github.com/Maximora-byte/swu-happyrun/issues/14)：恢复、状态/revision、running 前副作用、设备归属/fence、app_record 会话绑定。

**Dot 先接管 C0 修复**：在自己的 `dot/*` 分支完整继承 #13 的源码和测试，合入最新 main 协作说明；补合法的 verify_only 恢复路径，证明完整路径不经过 running。结构边和持久授权必须分别校验，不通过绕过状态表修复。提交替代/集成 PR 指向 main，说明继承 #13 哪个 HEAD；由本地 Codex 审核后处理旧 PR，禁止直接写 `codex/contracts-mumu`。

## 今晚的实施顺序

| 阶段与目标时间 | Dot 交付 | 本地验收条件 |
| --- | --- | --- |
| 发出后约 0–2 小时 | C0 恢复路径修复；C1 共享契约与回归测试；L1 driver/profile 接口固定 | 不经过 running 的恢复测试；未知坐标/规则/能力拒绝执行；无共享模型副本 |
| 随后约 2–5 小时 | S0 API/认证/SQLite；L1 fake driver/路线校验；L2 agent/client/journal/CLI 可联接 | 可以从命令行启动，临时数据库持久化；模拟任务通过实际 HTTP 运行 |
| 随后约 5–8 小时 | S1 lease/fence/幂等/恢复/取消；S2 日程/重启；代理崩溃和失联清理 | 两连接竞争、旧 fence、重复事件、离线取消、开始后崩溃与不确定上传用例 |
| 明早 09:00 前 | 完整候选分支/PR、依赖锁、构建包、部署包、安装/联调说明、Windows 测试清单 | Linux 自测和 CI 结果齐全；本地可直接按命令安装与实测，未验证项列明 |
| 10/19 白天至 23:30 | 优先修复本地实测发现的问题；按实际样本推进 L3；更新验收矩阵 | 每个问题关联复现与修复 HEAD；指定版本的实际证据决定验收等级 |

阶段时间是优先级与检查点，不要求等待时钟再开始下一项。接口固定后可交错推进服务器和代理；不要只继续扩写计划或等待本地 Codex 实现通用模块。遇到必须设备/本人操作的阻塞，将最小探针和所需输入交给本地，其余不依赖设备的工作继续。

实施文件、接口和测试要求沿用[总计划](../superpowers/plans/2026-10-18-development.md)、[服务器计划](../superpowers/plans/2026-10-18-server.md)、[执行端计划](../superpowers/plans/2026-10-18-agent.md)，其中旧负责人列被本说明覆盖。不要为了省时间把所有变更堆在一个长期 PR；契约先评审，服务器/代理/集成按可验收范围交付。

## 关键技术门槛

1. C0/C1：先测试后实现。固定恢复 action 的状态序列、deadline 例外、批准消费、revision/fence 和 stop-ack 重放。当前 EvidenceRef 不足以单独证明本次 run；先以契约 PR 明确 job/session/profile/app_version 绑定，再让 S1 接受真实记录事件。
2. S0/S1：ADMIN/AGENT 隔离；AGENT 固定身份；事务性 claim；设备保留不同于租约期限；过期或不确定任务不能通过新 job 绕开设备锁。共享状态表不能代替上下文授权。
3. L1/L2：明确 CRS、规则与配置 revision；未知通道不写设备。服务器接受 running 后先持久化本地 intent，再产生设备副作用；续租失败或取消时停止线程，不能重复开始或盲目重传。
4. S2/I0：UTC 存储、Asia/Shanghai 日程；持久唯一 occurrence、不补跑过期任务；重启恢复与实际 HTTP 故障联调，不只 mock 返回值。
5. L3/R0：具体选择器、点位与协议只能来自实际脱敏样本。无 Root vivo 和纯接口分别给出 supported / unsupported / not_tested 及证据。来源未知 APK、其他学校协议或参考作者成功率不能成为本项目兼容结论。

## 明早交给本地 Codex 的内容

- PR URL、不可变 HEAD、基线与继承关系、变更契约、实际测试命令/平台/结果。
- Linux 冻结依赖安装、完整 pytest、Schema 漂移、ruff、构建和 core/server 独立安装结果；GitHub CI 状态单列。
- Windows 安装与启动命令、服务器环境变量样例（无真实凭证）、fake 联调命令、MuMu 探针命令和预期返回。
- 故障测试清单：断线、取消确认丢失、开始后崩溃、上传不确定、进程停止与重启、旧租约和重复事件。
- 本地需要采集的最小设备/app/学校信息；原始截图、账号、token 和路线不入 Git 或群消息。

本地实测使用自己的独立环境与指定版本，先验证主机/连接/坐标/传感器，再验证应用状态及最终记录；依次记录 host_verified、device_verified、record_verified。当前事实仅为 MuMu 6.8.4.0 / Android 15 实例可查且停止，ADB 无设备；不能据此宣称执行能力已通过。

## 接单与协作回报

请 Dot 收到后在冲刺 Issue 回复“已接单”、实际执行环境、采用的基线、首个工作分支/PR和第一检查点。此后以每个可验收里程碑回写 Issue/PR，遇阻写明复现、影响与下一步；接收、开工、提交、测试和实测分别记录。

用户已明确授权 Dot 主导主要开发，不再等待本地 Codex 写 core/agent/drivers。使用真正的 ChatGPT Dot，不替换成 OpenClaw/Hermes，也不冒用无关 Matrix 消息的 lease。代码审核和设备实测交给本地 Codex；生产服务器、DNS、账号与 Root/安全设置不在这次冲刺授权范围内。
