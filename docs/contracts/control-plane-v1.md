# 控制协议 v1

状态：设计基线；按 2026-10-18 用户最新分工，由云端 ChatGPT Dot 主导协议及产品实现，本地 Codex 实测和集成审核。协议实现后的机器可读模型与 JSON Schema 由共享模型导出，双方不能维护两套相似但不同的类型。

## 固定约定

- Python >=3.11，包名 `swu_happyrun`；所有 HTTP 路径前缀 `/api/v1`；`protocol_version=1`。
- JSON 使用 UTF-8；ID 为 UUID 字符串；网络时间为带 `Z` 的 UTC RFC3339，日程输入时区为 `Asia/Shanghai`。
- `ADMIN` 与 `AGENT` bearer token 分离。AGENT token 固定绑定 `agent_id`；令牌来自环境/本地私有配置，不进入命令行示例、日志或返回对象。
- HTTP 请求超时 5 秒；代理心跳 10 秒；租约 30 秒；服务器使用自己的时钟判断租约。
- 初版单服务进程、单调度器、SQLite 本地持久卷。并发领取使用短写事务、唯一活动设备锁与 fence 校验。数据库忙最多等待 5 秒，然后返回可重试的 503。
- 错误体为 `{error:{code,message,retryable},request_id}`；401 鉴权失败，403 角色不允许，404 资源不属于该代理或不存在，409 状态/租约/幂等冲突，422 输入不合法，503 暂时不可用。错误不得回显 token。

## 共享模型（`src/swu_happyrun/core/models.py`）

| 类型 | 必需字段与约束 |
| --- | --- |
| `JobSpec` | `protocol_version: Literal[1]`、`mode: Literal['simulation','device']`、`profile_id: str`、`profile_revision: str`、`route_id: str`、`route_revision: str`、`device_id: str`、`not_before: datetime`、`deadline: datetime`、`expected_app_version: str|None`（device 非空，simulation=null）；deadline 必须晚于 not_before；未知字段拒绝 |
| `JobView` | `job_id: str`、`spec: JobSpec`、`state: JobState`、`revision: int`、`desired_state: Literal['run','cancel']`、`fence: int`、`agent_id: str|None`、`reason_code: str|None`、`resume_phase: JobState|None`、`recovery_action: Literal['retry_preflight','verify_only','stop_only']|None`、`run_session_id: str|None`；公开对象无 lease token |
| `AgentHello` | `protocol_version: Literal[1]`、`agent_id: str`、`devices: list[DeviceCapability]`；与令牌绑定一致 |
| `DeviceCapability` | `device_id: str`、`backend: Literal['fake','mumu','android']`、`app_version: str|None`、`capabilities: list[str]`、`observed_at: datetime`、`probe_id: str`；未知能力不默认启用 |
| `LeaseGrant` | `job: JobView`、`lease_token: str`、`fence: int`、`expires_at: datetime`；只有领取响应返回 token |
| `LeaseCommand` | `lease_token: str`、`fence: int`；续租/事件/停止确认均必须携带；不允许跨代理使用 |
| `JobEvent` | `event_id: str`、`expected_revision: int`、`state: JobState`、`reason_code: str|None`、`evidence: list[EvidenceRef]`、`resume_phase: JobState|None`；无个人自由文本日志 |
| `EvidenceRef` | `kind: Literal['host_check','device_probe','app_record']`、`sha256: str`（64 小写十六进制）、`captured_at: datetime`、`app_version: str|None`、`profile_revision: str`、`record_status: Literal['valid','invalid','pending']|None`、`job_id/run_session_id/record_namespace/record_id: str|None`（app_record 必填）；引用脱敏证据，不能任意指定服务器文件路径/URL |
| `ScheduleSpec` | `schedule_id: str`、`job_template: JobSpec`、`timezone: Literal['Asia/Shanghai']`、`local_time: str`（HH:MM）、`weekdays: list[int]`（ISO 1..7）、`enabled: bool`；实际日期由调度器产生，不复用模板日期 |
| `GeoPoint` | `latitude: float`（-90..90）、`longitude: float`（-180..180）；必须为有限数 |
| `RouteProfile` | `route_id: str`、`revision: str`、`input_crs: Literal['WGS84','GCJ02','BD09']`、`points: list[GeoPoint]`（至少 2 点）、`source_ref: str`；source_ref 是本地登记引用，不允许自动下载任意 URL |
| `SchoolProfile` | `profile_id: str`、`revision: str`、`campus: str`、`app_package: str`、`app_version: str`、`confirmed: bool`、`allowed_region: list[GeoPoint]`（至少 3 点，WGS84）、`rules: dict[str,float]`、`checkpoint_source: Literal['manual_confirmed','adapter_verified']`；初版规则键仅允许 `minimum_distance_m`、`maximum_duration_seconds`、`minimum_speed_mps`、`maximum_speed_mps`，值为有限非负数；实际必需规则未采集或出现其他规则时阻止 device 执行，进入适配流程 |
| `VerificationResult` | `status: Literal['valid','invalid','pending','unknown']`、`evidence: list[EvidenceRef]`、`reason_code: str|None`；unknown/pending 不能导向 succeeded |

`JobState`：`queued, leased, preflight, ready, running, finishing, verifying, cancelling, needs_attention, completed, succeeded, failed, cancelled`。

模型使用 Pydantic v2，禁止 NaN/Infinity、无时区时间和未知字段。默认类型不做有损字符串到数字转换。

规则上下限必须自洽；minimum_speed_mps 不得大于 maximum_speed_mps。SchoolProfile.confirmed 仅表示用户确认了配置，不代表设备或学校后台已验证。日程时间窗由 JobSpec 负责，距离、速度和持续时间由 SchoolProfile 负责，缺失要求不能自动补为默认达标值。

`profile_id/route_id` 在代理本地私有配置库解析；服务器只保存引用。代理在 preflight 校验 ID、revision、实际应用版本与配置内容一致，缺少配置或版本不匹配进入 `needs_attention`，不得静默使用最新版。revision 使用规范化配置 JSON 的 SHA-256；具体规范化算法由 C0 固定并提供跨端测试向量。初版通过受控本地文件配置，尚不提供远程配置下载接口。

### C0 实现约定

- 所有 ID 是小写标准 UUID 字符串；配置 revision 是 64 位小写 SHA-256。网络输入时间严格接受以 `Z` 结尾的 RFC3339（最多 6 位小数）；Python aware datetime 会统一为 UTC，序列化输出 `Z`。
- `core.canonical.profile_revision()` 对已校验模型的 `model_dump(mode='json')` 内容计算哈希：只删除顶层 `revision`，按键排序，紧凑分隔符，UTF-8、不转义 Unicode、禁止非有限数。数组顺序和数字表示（`1` / `1.0`）保留；这是 Python JSON v1 规范，不宣称兼容 RFC 8785。跨端测试向量在 `tests/contracts/test_canonical.py`。
- 能力名称固定为 `location_read/location_write/sensor_probe/app_ui/record_read`；空列表表示未证实任何执行能力。主机安装发现不是设备执行能力。
- `core.states.transition_allowed()` 仅检查结构边，不能代替 S1 中的租约、原代理身份、设备占用、开始意图、取消回执和证据绑定检查。例如 preflight → queued 仍须证明没有副作用且无取消意图；needs_attention → leased 仍须批准恢复动作。
- nullable 字段也必须显式提供。`lease_token` 保留真实 wire 值但从模型 repr 排除；HTTP 层仍必须脱敏验证错误，不能把原始输入或错误堆栈直接回显。
- `contracts/protocol-v1.schema.json` 从统一共享模型（含 C1 组合请求）生成；Schema 只表达静态约束，时间顺序、状态/证据关系等仍以模型验证为准。修改模型后运行导出命令，`--check` 用于拒绝漂移。
- C0/L0 交付不等于 S1 所需上下文授权已经完备。Dot PR #12 提出的恢复例外、动作边、归属与证据会话绑定在 [C1 #14](https://github.com/Maximora-byte/swu-happyrun/issues/14) 通过独立协议 PR 固定；S1 在该任务完成前保持阻塞。现有 EvidenceRef 结构本身不能证明记录属于本次运行，禁止直接据此放开 succeeded。

## HTTP 接口

| 方法与路径 | 角色 | 输入/输出 |
| --- | --- | --- |
| `GET /health` | 无 | 200 `{status:'ok',protocol_version:1}`，不返回内部路径或配置 |
| `POST /jobs` | ADMIN | `JobSpec` + `Idempotency-Key`；首次 201 `JobView`；同 key 同规范化请求 200 原任务；同 key 不同请求 409 |
| `GET /jobs/{job_id}` | ADMIN / 所属 AGENT | 200 `JobView` |
| `POST /jobs/{job_id}/cancel` | ADMIN | 设置 desired_state；queued 可立即 cancelled，其余可能执行中的任务进入 cancelling；200 `JobView` |
| `POST /jobs/{job_id}/resume` | ADMIN | `{expected_revision, action:'retry_preflight'|'verify_only'|'stop_only'}`；仅 needs_attention；发生过设备副作用后不得 retry_preflight |
| `POST /agents/hello` | AGENT | `AgentHello`；200 `{agent_id,heartbeat_seconds:10,lease_seconds:30}` |
| `POST /agents/heartbeat` | AGENT | `AgentHello`；200 `{server_time}`；不续任务租约 |
| `POST /leases/claim` | AGENT | `{device_id}`；无可领取任务为 204；成功 200 `LeaseGrant`；必须匹配设备能力和时窗 |
| `POST /jobs/{job_id}/renew` | 所属 AGENT | `LeaseCommand`；200 `{expires_at,desired_state}`；旧 fence 或过期 token 为 409 |
| `POST /jobs/{job_id}/events` | 所属 AGENT | `{lease: LeaseCommand,event: JobEvent}`；200 `JobView`；同 event_id 同载荷重放无副作用，不同载荷 409 |
| `POST /jobs/{job_id}/stop-ack` | 所属 AGENT | `{lease: LeaseCommand,event_id,expected_revision}`；确认所有设备动作停止后转 cancelled |
| `POST /schedules` | ADMIN | `ScheduleSpec`；201；重复 schedule_id 冲突为 409 |
| `GET /schedules` | ADMIN | 200 `list[ScheduleSpec]` |
| `POST /devices` | ADMIN | `DeviceRegistration`；201；重复 device_id 为409，初版不可转移 |
| `GET /devices` | ADMIN | 200 `list[DeviceRegistration]` |
| `PUT /schedules/{schedule_id}` | ADMIN | `ScheduleSpec`；ID 必须一致；200；仅更新未来未生成执行日程 |

## 状态与恢复

- 正常流程：queued → leased → preflight → ready → running → finishing → verifying。simulation 最终 completed，device 只有实际有效 app_record 证据才 succeeded。
- `failed/cancelled/completed/succeeded` 为终态；终态不可恢复或改写。非法迁移返回 409。
- `needs_attention` 是可恢复状态，记录 resume_phase。未知界面、本人授权、坐标缺失、结果不确定进入此状态。
- queued 过期转 failed / `window_expired`。领取后尚未进入 running 的租约过期：只有明确没有任何设备副作用时可回 queued；存在开始意图或状态不确定则 needs_attention。
- entering running 事件必须先获服务器接受，代理再在本地日志持久化 `start_intent`，最后执行设备开始。此后即便代理崩溃也按可能已开始处理。
- 每个设备副作用前检查本地设备锁、当前 fence、取消信号和保守的租约剩余时间；等待/进程暂停可能耗尽租约，不能只依赖先前的 running 回执。租约过期或状态未知时仅执行受控停止。
- running 之后失联/租约过期：needs_attention，禁止新代理重新开始。原代理重连后须取得同 job 的恢复租约，仅允许 verify_only / stop_only。恢复使用 `POST /leases/claim`，只向原绑定代理返回已获管理员批准的恢复任务；fence 增加，历史 token 失效。
- verify_only 的合法结构序列是 needs_attention → leased → verifying → succeeded（device）或 completed（simulation），不得经过 preflight、ready 或 running。leased → verifying 仅在原代理持有当前有效恢复租约、持久批准的 recovery_action=verify_only 且 desired_state=run 时可用；普通新领取任务不得走此边。状态表只提供必要结构条件，S1 必须额外检查这些持久上下文及完成证据；取消意图只允许 stop_only。下文 C1 修订固定批准消费、revision、deadline 例外和 stop-ack 重放细节。
- 旧租约禁止新的设备开始、路线更新、结束上传；持有设备的进程仍必须执行本地受控停止，恢复后报告观测，不能因失去租约而继续运行。
- 取消活动任务先 cancelling；只有 stop-ack 后 cancelled。断线没有确认时留 needs_attention / `stop_unconfirmed`，不能显示已停止。
- `desired_state=cancel` 的任务不能回 queued 或作为新运行领取；恢复租约只允许 stop_only。存在可能活动的设备时保留设备占用锁，直到确认停止或完成核验，不能用新 job 绕过旧任务的不确定状态。
- 上传请求已发出但结果未知：verifying 或 needs_attention / `upload_uncertain`，先回查记录，禁止盲目再上传或重跑。
- event_id 去重在验证当前租约后、revision 冲突检查前执行；相同载荷重试返回原先的事件结果。过期租约不能通过重放事件恢复权限。

## 调度与验证

每个 `(schedule_id, occurrence_local_date)` 最多生成一个任务，数据库唯一约束保证重启不重复。错过 deadline 的日程记为 skipped，默认不补跑。模板中 `deadline-not_before` 定义时窗长度；发生时间为该日 local_time，转换为 UTC 后加同样时窗长度。

所有测试使用假学校、假设备和 fake clock。设备/最终记录证据只由实际观测产生，simulation 不得附带 `app_record`。服务器只能校验证据结构、来源代理和绑定关系，不独立证明学校后台认可；最终验收仍须本地复核证据。


## C1 recovery and record binding

Prepared for Issue #14 under the updated Dot implementation ownership in main
`cb91204ebe18afbdc467084ea74aa4feb4b17414`. Source model baseline: PR #13
`3ff0a33a01c629432a2036f4e105bed52157bd9e`; C0 replacement
`6ed02c29924ccc3ab26c028fbf46d15477d84eb0` supplies the structural edge
`leased -> verifying` and is this C1 change's exact parent. This amendment defines the coordinated C1 contract. Its shared models are implemented
in this PR; the persistent server/agent behavior below is specified for S1/L2 and
is not claimed implemented or tested by C1 model tests.

Sources: Issue #14 and comments 6251574842 / 6251674710; Issue #16;
AGENTS.md and docs/handoffs/2026-10-18-dot-lead-sprint.md at the main SHA above.

## 1. Minimal shared-model changes

All fields below are required on the wire, including nullable fields. Existing
strict validation, explicit UTC-Z times, UUIDs, extra-field rejection and redaction
rules remain. Regenerate the single schema from these models, never copy models
into server or agent. This is a pre-release coordinated schema change; both ends
must use the same C1 commit. Do not silently accept old payloads with defaults.

| Model | Added fields | Static invariants |
| --- | --- | --- |
| JobSpec | expected_app_version: Text or null | Non-null in device mode; null in simulation. Immutable with the rest of spec. |
| JobView | run_session_id: UUIDString or null | Null before first grant; non-null for every granted/previously granted job; retained through requeue, recovery and terminal states. |
| DeviceCapability | probe_id: UUIDString | New UUID for each actually completed read-only probe; retransmission preserves its UUID and payload. |
| EvidenceRef | job_id: UUIDString or null; run_session_id: UUIDString or null; record_namespace: RecordNamespace or null; record_id: Digest or null | All four required and non-null for app_record; all four null for host_check/device_probe. Existing app_version/record_status requirements remain. |

RecordNamespace is a bounded adapter namespace matching
`^[a-z][a-z0-9_.-]{0,63}$`. record_id is the SHA-256 of a stable, adapter-defined
record identity with an explicit issuer/account scope; never send a raw account
or student identifier. The namespace and identity normalization are adapter
contracts, not arbitrary caller text. An adapter lacking a stable record identity
and reliable run correlation cannot emit a valid app_record.

Add the following small shared request/registration models and export them:

- ClaimRequest(device_id: UUIDString)
- ResumeRequest(expected_revision: Counter, action: RecoveryAction)
- EventRequest(lease: LeaseCommand, event: JobEvent): composition only; no
  duplicate field definitions, validation rules or semantics.
- StopAckRequest(lease: LeaseCommand, event_id: UUIDString, expected_revision: Counter)
- DeviceRegistration(device_id: UUIDString, agent_id: UUIDString)

DeviceRegistration is immutable in this initial protocol. ADMIN `POST /devices`
registers it (201); duplicate device_id is 409. ADMIN `GET /devices` returns the
registered list. There is deliberately no alias or ownership-transfer endpoint
in v1. Register through the ADMIN HTTP endpoint and persist the registration.
Startup configuration, hello and heartbeat must not create or overwrite ownership.

No new public field for authorization consumption is needed: server persistence
must distinguish a pending approved action from the action on an issued lease.
JobView.recovery_action describes the pending/current recovery action, not a fresh
authorization merely because it is present.

## 2. Execution and recovery state semantics

Before accepted `running`, prepare/preflight/ready are strictly read-only. No
location writes, sensor writes, start, finish or upload is permitted. Once the
server accepts running, persist local start_intent before the first write. This
accepted event permanently marks the job as possibly started even if its response
is lost. Never erase this marker on recovery or infer safety from current state.

ADMIN resume is allowed only in needs_attention with matching expected_revision.
It persists one pending approval, leaves state needs_attention and increments
revision once. It invalidates any remaining lease for the job. stop_only approval
also sets desired_state=cancel in that same revision change. A second resume with
the stale revision is 409; it cannot create two approvals.

claim atomically checks ownership/reservation, consumes one pending approval,
increments the device-wide fence, binds a new token, and changes state to leased.
Preserve original resume_phase and historical uncertainty. Generate run_session_id
once, on the first successful claim; never replace it for the same job.

| Action | Claim conditions | Allowed successful sequence |
| --- | --- | --- |
| Normal run | queued; desired run; start window; fresh required capability report; no competing reservation | leased -> preflight -> ready -> running -> finishing -> verifying -> completed/succeeded |
| retry_preflight | original agent; approved; no historical running/start intent; desired run; within start window; fresh start capabilities | leased -> preflight -> ready -> running -> finishing -> verifying -> completed/succeeded |
| verify_only | original agent; approved; same reserved device; fresh record_read for device mode; synthetic verifier for simulation | leased -> verifying -> completed/succeeded, or needs_attention |
| stop_only | original agent; approved; same reserved device; desired cancel | leased -> cancelling -> cancelled through stop-ack only |

verify_only and stop_only ignore the original not_before/deadline. verify_only
never allows starting, route writes, finishing or upload. Missing verification
capability keeps the job in needs_attention without consuming its approval.
stop_only ignores start/read capability lists and their age; missing capability
metadata must not prevent attempting safe stop, but cannot be treated as proof
that stop succeeded. If stopped cannot be confirmed, remain needs_attention.

Recovery lease expiry returns needs_attention, clears pending approval, retains
the historical phase/session/reservation and requires a new administrator resume.
A lost claim response does not issue a second token or grant. There is no token
recovery endpoint: the agent may query the job, wait for expiry and request the
appropriate recovery approval. This is conservative and avoids storing raw tokens.

An ordinary pre-running expired lease may requeue only with no accepted running,
no cancellation, no recovery action and no other uncertainty; otherwise attention.
queued expiry at deadline is failed/window_expired. A job that may have started
cannot become failed merely because of an exception/timeout. Keep attention and
the reservation until safe stop or completed verification. The structural
running -> failed edge is not sufficient authorization to release a device.

Claim and entry into running both check `not_before <= now < deadline` for a new
start. Recovery verification/stop is allowed beyond deadline; starting is not.
The execution engine also checks remaining lease conservatively immediately
before every side effect. Old-lease controlled stop remains a local safety duty;
only reporting the confirmed stop requires a current recovery lease.

## 3. Revision, lease and cancellation rules

Use server time. A lease is invalid at `now >= expires_at`. Renewal sets expiry
to server now plus 30 seconds; it never restores an expired lease. Heartbeat does
not renew leases. Expiry processing must run inside or before mutating transactions,
not only on a periodic timer.

Increment JobView.revision once per effective claim, new accepted event, resume,
cancel change, expiry transition and stop-ack. renew/heartbeat, no-op repeated
cancel and exact replay do not change it. Reject ordinary same-state events;
read-only pending verification can remain local and renew without fake transitions.

cancel on queued becomes cancelled. cancel on an active lease enters cancelling
and supersedes any verify_only/retry authorization with stop-only restrictions.
cancel on needs_attention without a live lease preserves needs_attention with
stop_unconfirmed and requires an explicit stop_only resume. desired cancel never
reverts to run. Cancellation cannot rewrite a terminal result.

Serialize cancel and terminal event commits: cancel first prevents later success;
success first preserves the terminal result. Return 200 unchanged for cancel on
an already terminal job. An ordinary agent event cannot produce cancelled:
stop-ack is its exclusive active-job entry point.

completed/succeeded events attest that execution workers/actions are stopped as
well as meeting result checks. The agent must stop/join workers before emitting
them. If this is uncertain, send needs_attention instead. The server atomically
releases a reservation only on a permitted completed/succeeded or stop-ack, or on
a definitely pre-start failed/cancelled transition. A terminal failed job must
never strand a possibly active device behind a released reservation.

## 4. Idempotency and stop-ack

For simulation, completed means the fake lifecycle finished with all workers
stopped. A fake VerificationResult may remain unknown/simulation_only with no
app_record. It never claims actual record validity.

For events and stop-ack: authenticate -> current job/agent/device fence/token/expiry
checks -> event_id deduplication -> expected_revision -> transition/context checks.
Use one `(job_id, event_id)` namespace for both endpoints; include operation kind
and canonical request payload in the stored fingerprint. Cross-endpoint reuse or
changed payload is 409. Exact replay returns the original result snapshot without
rewriting the current job. Never log or expose lease tokens in fingerprints.

On committed stop-ack, atomically cancel, increment revision and release exactly
that job's reservation. Keep the token digest/fence and result until the lease's
original expiry only for exact replay; this does not permit renew or new events
against a terminal job. A higher device fence invalidates even the replay.
Expired/older-fence replay returns 409; the original authenticated owner can GET
the terminal result. Never grant a recovery lease to an already cancelled job.

## 5. Device ownership, probes and fencing

An AGENT token is not device-registration authority. hello/heartbeat may report
only devices already registered to that agent. Unknown/unowned device references
are rejected without altering registration. Reports never transfer ownership.
Physical alias equivalence remains an operator registration responsibility; two
random UUIDs alone do not prove two physical devices. Do not claim otherwise.

For each device persist an integer fence independently of jobs. Every normal or
recovery grant increments it atomically. A lease check matches job, agent, device,
device-current fence, token digest and expiry together. The reservation persists
through lease expiry and server restart when a device may still be active. No
different job can claim that device while unresolved, even with a larger fence.

hello carries completed read-only probe reports. Server persists each probe_id's
payload and first received_at. Exact retransmission is idempotent and does not
refresh received_at; conflicting reuse is 409. heartbeat updates agent liveness
only, never the probe freshness clock, even if it includes DeviceCapability data.
The agent must issue hello with an actually new probe report to refresh capability.
Persist consumed report IDs so replay after restart cannot refresh them.

Fresh means server `0 <= now - first_received_at < 30 seconds`; a backward wall
clock that makes age negative fails closed. observed_at is diagnostic metadata,
not freshness authority. Every claimed capability remains the authenticated
agent's assertion; a report UUID cannot cryptographically prove a physical probe.

simulation requires backend=fake and no physical write claims. device execution
requires backend mumu/android and the explicit known required set
location_read, location_write, sensor_probe, app_ui, record_read plus matching
expected_app_version. These are necessary checks, not proof of correct school
rules, calibrated CRS, adapter availability or accepted records. Agent preflight
still verifies those facts and fails closed. verify_only device recovery needs only
record_read plus matching app version; stop_only bypasses these capability gates.

## 6. Evidence/session binding

All app_record references in an event must match current job_id, run_session_id,
profile_revision and expected_app_version, regardless of the target state. Only
the current owning agent under a valid lease may submit them. simulation rejects
app_record in every state, not just completed. valid/invalid/pending records all
carry the binding fields; unknown has no fabricated record.

Store `(record_namespace, record_id) -> job_id` and canonical app_record sha256
ownership transactionally with first evidence acceptance. Existing ownership by
a different job conflicts; same-job repeat is allowed under event idempotency.
sha256 is the stable canonical record artifact digest, not a screenshot wrapper
or a serialization containing this job/session ID. Capture timestamps and mutable
pending/valid status must not produce a new underlying record identity. Adapter
documentation must define canonical artifact/record identity generation before
real app_record is accepted; no generic placeholder adapter may return success.

succeeded requires device mode, desired run, verifying state, matching valid
app_record and stopped execution. Contradictory statuses for the same record
identity OR canonical sha256 in one event are rejected, including digest aliases
with different record_id or namespace. This consistency check is per event;
separate events for the same job may legitimately evolve pending to valid.
No response/lease can change JobSpec or run_session_id.
The local adapter must correlate the actual observed record to start/session
observations; attaching server identifiers to an old record does not establish
provenance. Server checks are structural/binding checks, not independent proof of
school acceptance. Real records remain a separate evidence-based local acceptance.

## 7. Regression checklist and rollout gate

Contracts: static field presence/nullability, device/simulation app version rules,
record namespace/digest forms, app_record-only bindings, session roundtrip,
request schema export and unknown fields. Retain all C0 strict/UTC/schema vectors.

Server: action x phase, original agent, two independent claim connections,
approved-once consumption, grant response loss, exact expiry, same-device cross-job
fence, stale token replay, read-only recovery after deadline, fresh/stale/replayed
probes, heartbeat not refreshing capabilities, unknown ownership, terminal replay,
cancel/success races, recovery expiry/new approval, all wrong record binding fields,
cross-job record/digest reuse, conflicting statuses and crash/restart persistence.

Agent/integration: prepare read-only; durable intent before write; running receipt
loss; lease loss between check and side effect; controlled stop failure; stop-ack
response loss; no duplicate start/upload; verify_only full path excludes running;
actual local HTTP + fake driver. No real device/record claims from these tests.

Implementation ownership is Dot. Local Codex performs independent device and
integration acceptance. S0 can consume a reviewed C0 baseline; incompatible C1
fields need the reviewed C1 contract first. S1 execution waits for S0 and C1 merges.
Parallel preparation may target the exact frozen C1 interface in isolated branches,
but neither preparation nor green synthetic tests means contract acceptance/merge.
