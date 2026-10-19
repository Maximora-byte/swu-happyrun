# 服务器验收用例与结构评审（C0 前置准备）

日期：2026-10-18。评审基线：`39cdcc05503e2c1c0f1190efd2e1b3c268976819`。

本文只准备 S0–S2 的测试设计和存储边界，不实现第二套共享模型，不修改协议、依赖锁或 CI。下列用例全部为**待实现、未运行**；不是已经通过的产品测试。进入实现前须重新读取 main、AGENTS.md，并记录 C0 实际合并 SHA。

## 已验证事实与执行限制

- 使用 GitHub 连接读取基线完整树（非截断），将 13 个 blob 保存到独立云端工作目录，逐个按 Git blob SHA-1 验证一致。
- 基线仅含文档和仓库配置；没有 `src/`、`tests/`、`pyproject.toml`、锁文件或部署产物。不能把零测试发现当成验收通过。
- #2 是开放的 C0 Issue，不是已合并 PR。其关闭状态本身也不足以证明共同代码基线；须取得对应 PR 和实际合并 SHA。
- 实际云端执行 Python 3.12.14，Linux 6.18.55 x86_64 / glibc 2.41，SQLite 3.53.1。仓库外标准库环境探针验证了 SQLite 关闭后重开读取、Asia/Shanghai 时区转换：2 项通过，进程退出码 0。
- 上述仅证明当前环境可执行 Python 和基础依赖能力；没有导入项目，没有运行服务器、共享契约或设备测试。Python 3.11/3.13、Windows、Docker 构建、真实 HTTP 联调与设备/记录验收均未运行。

## 实施门槛与测试夹具

1. 本地 Codex 完成 C0，双方固定同一合并 SHA，导入其 `JobSpec`、`JobView`、状态表、规范化算法和 `Clock`，不在测试或 server 内复制替代模型。
2. 复核可选 server/dev 依赖与锁文件，运行该基线的 contracts、schema 和安装检查；缺失依赖先在 #2 协调，不自行改锁或 CI。
3. 使用临时 SQLite 文件、两个独立连接、注入 fake clock、虚构设备/配置引用和显式合成凭证。禁止真实账号、位置、截图、token 入库或入 Git。
4. 测试通过 HTTP 层验证状态码/错误体，并从 store 验证持久化不变量；不只断言 mock 返回值。并发测试用 barrier/事件协调，不用 sleep 碰运气。
5. 时间测试分别推进 UTC 和 monotonic，覆盖精确到期前、到期点、到期后。未明确的边界先由 C0/协议评审确认，不能由服务器暗自定义。
6. 每个测试记录用例 ID、命令、不可变 HEAD、平台和实际结果；失败、未运行、仅环境探针分开记录。

所有相对 HTTP 路径均加 `/api/v1`。未明确的行为以协议协调后的决议为准。

## S0：API、认证与持久化（#4）

| ID / 建议文件 | 输入与故障注入 | 必须断言 |
| --- | --- | --- |
| S0-01 / test_api | 无凭证 GET health | 200；仅公开 status/protocol_version，不泄漏配置路径 |
| S0-02 / test_auth | 缺失、错误、格式错误的 bearer | 401；契约错误体；不回显 bearer 或请求头 |
| S0-03 / test_auth | AGENT 调用创建/取消/恢复/日程接口；ADMIN 调用仅 AGENT 接口 | 已认证但角色不允许为 403；无持久化副作用 |
| S0-04 / test_auth | token 绑定 A，hello/heartbeat 声称 B | 拒绝身份冒用；不得登记或更新 B；具体错误码待明确 |
| S0-05 / test_auth | 非所属代理读取任务及不存在任务 | 均 404；不通过响应差异暴露任务数据；重新绑定后旧代理也不能读取 |
| S0-06 / test_idempotency | 同 key、同规范化 JobSpec 重放 | 首次 201，再次 200；相同 job_id；数据库只一条任务 |
| S0-07 / test_idempotency | 同 key、改变一个有效字段 | 409；原任务与 revision 不变 |
| S0-08 / test_idempotency | 两个连接并发提交同 key | 单一任务；返回同 job_id；不出现重复创建或未处理唯一键异常 |
| S0-09 / test_idempotency | 关闭全部连接并重建 app 后重放 | 同 key 仍返回原任务；证明幂等信息不在进程内存 |
| S0-10 / test_api | 无时区/倒置时间窗、未知字段、协议版本不符 | 422；使用 C0 模型校验；错误信息不能含凭证 |
| S0-11 / test_api | 合法 hello、heartbeat | 心跳 10 秒/租约 30 秒；heartbeat 只更新代理，不暗中续任务租约 |
| S0-12 / test_api | SQLite 写锁被另一连接持有 | 有限等待后 503、retryable；不暴露堆栈；释放锁后正常重试 |
| S0-13 / test_auth | 公共 JobView、错误、日志、持久库扫描 | 无 ADMIN/AGENT 原始 token；JobView 无 lease_token；测试凭证为合成数据 |

## S1：租约、事件、取消与恢复（#5）

| ID / 建议文件 | 输入与故障注入 | 必须断言 |
| --- | --- | --- |
| S1-01 / test_leases | 两连接同时 claim 同一设备/任务 | 恰好一个有效 LeaseGrant；一个活动设备锁；失败方不修改 fence |
| S1-02 / test_leases | 同设备上两个 queued 任务并发 claim | 至多一个有效租约；不能通过另一个 job 绕过设备锁 |
| S1-03 / test_leases | 能力未知、设备不匹配、not_before 前、无任务 | 不发租约；无可领取任务为 204；未知能力不能视为可用 |
| S1-04 / test_leases | 当前租约续租；独立 heartbeat | renew 返回 expires_at/desired_state；heartbeat 不改变 expires_at |
| S1-05 / test_leases | 旧 fence、错误 token、已过期 token；另一个代理提交 | 按协议拒绝，状态/revision/锁不变；跨代理不泄漏资源 |
| S1-06 / test_events | 有效事件接受后同 event_id/同载荷重放 | 返回原事件结果；revision 只增一次，证据/副作用不重复 |
| S1-07 / test_events | 同 event_id 不同载荷 | 409；事件记录和任务保持原值 |
| S1-08 / test_events | 已接受事件在 revision 已推进后重放 | 有效租约下去重先于 revision 冲突，返回原结果，不回退当前存储状态 |
| S1-09 / test_events | 过期/旧租约重放曾成功的 event_id | 先验证当前租约，拒绝重放；不能借去重恢复权限 |
| S1-10 / test_events | 新 event_id 携带旧 expected_revision；非法迁移 | 409；原状态不变；终态不可被事件或 resume 改写 |
| S1-11 / test_recovery | 接受 running 后、代理开始动作前断线 | 按可能已开始处理；needs_attention，不能重派或自动 retry_preflight |
| S1-12 / test_recovery | leased/preflight/ready 到期且明确无副作用 | 仅协议允许的已知安全情况可回 queued；不确定则 needs_attention |
| S1-13 / test_recovery | running/finishing/verifying 到期或重启 | 保存 resume_phase/不确定性，保持设备占用，不自动开始第二次 |
| S1-14 / test_recovery | upload_uncertain 事件、重启、重新 claim | 不回 queued，不盲目再上传；只走已批准 verify_only/stop_only |
| S1-15 / test_recovery | 管理员批准恢复，原代理与新代理分别 claim | 仅原绑定代理获得恢复租约；fence 增加；旧 token 无效；动作受批准范围约束 |
| S1-16 / test_recovery | resume 携带旧 revision 或已产生副作用后 retry_preflight | 409；不得改变执行权限或释放锁 |
| S1-17 / test_cancel | queued cancel | 可立即 cancelled；以后不可新运行领取 |
| S1-18 / test_cancel | 活动任务 cancel，未收到 stop-ack | desired_state=cancel；cancelling；不能声称已停止；设备锁保留 |
| S1-19 / test_cancel | 取消后断线/租约过期/服务器重启 | needs_attention/stop_unconfirmed；不回 queued；恢复只允许 stop_only |
| S1-20 / test_cancel | 当前恢复租约有效 stop-ack；同请求重试 | 确认停止后 cancelled 并释放锁；重复处理语义先由协议明确；旧租约必须拒绝 |
| S1-21 / test_events | simulation 提交 succeeded 或 app_record | 拒绝；simulation 只能完成为 completed |
| S1-22 / test_events | device 无有效 app_record，或仅 host/device probe | 不允许 succeeded；pending/unknown 不提升验收等级 |
| S1-23 / test_events | 错 profile_revision、应用版本不匹配、跨 job/代理证据 | 按明确的绑定规则拒绝；校验通过也不声称学校后台已经认可 |

## S2：日程、重启和部署（#6）

| ID / 建议文件 | 输入与故障注入 | 必须断言 |
| --- | --- | --- |
| S2-01 / test_scheduler | 创建重复 schedule_id；PUT 路径/正文 ID 不同 | 重复 409，ID 不一致拒绝；旧日程保持不变 |
| S2-02 / test_scheduler | 非 Asia/Shanghai、无效 HH:MM、非 ISO weekday | C0 模型拒绝；不生成实例 |
| S2-03 / test_scheduler | 上海周一 2026-10-19 00:00 | UTC 为 2026-10-18 16:00；使用本地星期一和本地日期去重 |
| S2-04 / test_scheduler | 模板使用不同日期，给定窗口长度 | 实例日期来自发生日；deadline=本次 UTC 开始+模板窗口长度 |
| S2-05 / test_scheduler | 同 tick 重试、两个连接竞争、进程重启 | `(schedule_id, occurrence_local_date)` 至多一条；job 与 occurrence 原子提交 |
| S2-06 / test_scheduler | deadline 之后首次 tick | 持久记录 skipped；不创建补跑任务；以后 tick 不补跑 |
| S2-07 / test_scheduler | disabled / 非选定 weekday | 不生成执行任务；重新启用时漏日处理先按明确策略验收 |
| S2-08 / test_scheduler | 编辑已经生成任务的日程模板 | 已生成任务 spec 不变；仅未来未生成实例受更新影响 |
| S2-09 / test_restart | 事务提交前/后故障注入，重建 store/scheduler | 全部提交或全部回滚；不能出现有任务无 occurrence 或相反的重复窗口 |
| S2-10 / test_restart | 重启时存在活动/不确定/取消任务 | 租约与恢复权限按服务器时钟重算；不确定设备锁不能因重启消失 |
| S2-11 / test_redaction | 正常请求及各类错误、启动/关闭日志 | 无 bearer、原始 token、个人配置或设备原始数据 |
| S2-12 / 部署检查 | Compose config、镜像构建、健康检查 | 非 root、单 worker/单 scheduler、主机回环发布端口、SQLite 持久卷 |
| S2-13 / 部署检查 | 临时容器创建任务、重启、重放创建/查询 | 原 job 与幂等信息仍在；不连接生产主机、DNS 或账号 |
| S2-14 / 安装检查 | 仅安装核心+server 所需依赖启动 | 不导入 Windows/ADB/MuMu 依赖；实际 Python/平台逐项记录 |

## 存储与结构评审清单

这些是实现评审建议，不是已定义的新共享契约。

- `create_app` 只装配 settings、Clock、store、路由和调度器生命周期；HTTP 层负责认证/错误转换，store 负责原子不变量。状态允许表直接消费 C0。
- jobs、幂等映射、当前租约/fence、设备保留、事件原结果、日程 occurrence 均需持久化；具体表结构可由 S0/S1 决定，不能仅以进程内字典保证唯一性。
- claim 在短 `BEGIN IMMEDIATE` 事务内联合校验任务时窗、绑定、设备锁、fence；异常必须 rollback。唯一约束是最终保障，不只先 SELECT 再 INSERT。
- 事件接受、revision 更新和事件结果存档在同一事务中；去重返回历史结果不能回写旧 JobView 覆盖新状态。
- cancel/resume/到期处理与 claim 共用事务边界，避免在取消与领取竞争中发出新运行权限。
- 持久化“可能已产生副作用”的保守信息，不只看当前 state；进入 needs_attention 后不能丢失曾 running/上传不确定历史。
- 设备保留的生命周期不同于租约有效期：租约过期不会自动证明设备停止。恢复租约只能授权已批准动作。
- job 创建与 occurrence 去重键必须原子提交；skipped 也需要持久记录。单调度器是部署约束，数据库仍需唯一性防护。
- 测试库使用假凭证；凭证摘要算法和恒定时间校验由实现安全评审确认，不能将原始 token 写入数据库/日志。

## PENDING_CONTRACT：与 C0 协调的五项门槛

下列为独立协议评审发现的未决项。只定义危险场景和应避免的结果，不在本文选择新的响应码、状态迁移或授权策略。S0 用例和存储准备可继续；运行时代码仍须等待 C0 共同基线，相关 S1 断言须在协议决议后落地。

| 门槛 | 必须补齐的契约 | 待落地用例 |
| --- | --- | --- |
| PC-01 恢复领取例外 | 已批准恢复任务越过原 deadline、原能力失效或不可再声明时，如何安全领取；普通新运行仍受时窗和能力限制 | fake clock 越过 deadline；能力列表变空；分别请求 verify_only/stop_only；既不能重新开始，也不能因普通 claim 过滤永久无法受控停止；对应 S1-03/15/19 |
| PC-02 恢复状态表与 stop-ack | 恢复后每个 action 的允许迁移、revision/fence 变化、重复恢复，以及 stop-ack 提交成功但响应丢失后的重试语义 | 各 resume_phase × action 参数化；相同/不同 event_id 载荷、旧 revision、旧 fence；数据库已 cancelled 后客户端重试；对应 S1-06/09/10/15/16/20 |
| PC-03 running 前副作用 | preflight/ready 是否严格只读；若 prepare 已有设备副作用，须有明确持久意图与安全回收依据，不能只用 ever-running 判断 | 在 prepare 产生副作用前后故障注入，租约到期和重启；仅明确安全的任务可重新排队；对应 S1-11/12/13 |
| PC-04 设备身份与能力 | 跨代理的规范设备身份、锁/fence 作用域、能力证据新鲜度和拥有权 | 两代理用不同别名指同物理设备、重新登记/过期 capability、不同 job 的 fence；不能形成两个有效执行者；对应 S0-04、S1-01/02/03/05 |
| PC-05 证据绑定 | app_record 如何绑定当前 job、profile_revision、应用版本和执行会话；仅有 digest 不证明本次成功 | 重用另一个 job 的结构合法证据、旧会话证据、版本不符、同 profile 下另一任务的证据；不得凭结构合法升为 succeeded；对应 S1-21/22/23 |

日程窗口由模板 `deadline-not_before` 推导、事件先校验租约再去重再查 revision 均已在 v1 明确，测试直接覆盖，不作为新缺口。五项门槛由本地 Codex 维护的协议/C0 测试统一解决；服务器不能独自修补共享语义。

## C0 合并后的真实验收命令

仅在对应代码/测试存在、依赖按共同锁文件安装后运行，当前均未运行：

- S0：`python -m pytest tests/contracts tests/server/test_api.py tests/server/test_auth.py tests/server/test_idempotency.py -q`
- S1/S2：`python -m pytest tests/contracts tests/server -q`
- 共享 Schema：`python scripts/export_schema.py --check`
- S2：`docker compose -f deploy/compose.yaml config --quiet`，再记录实际镜像构建和临时持久卷重启检查。
- I0 由本地 Codex 主持真实本机 HTTP + fake agent 联调；server 用例不代替代理动作日志/进程崩溃集成测试。

下一步：在 #1 完成协议反馈，并在 #2 确认 C0 PR/合并基线；之后从该基线建立 `dot/server-api`，先写失败用例再实现 S0。S1 依赖 S0，S2 依赖 S1。MuMu、vivo、西大学校有效记录继续分别标记未验证。
