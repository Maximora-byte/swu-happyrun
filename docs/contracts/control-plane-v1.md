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
| `JobSpec` | `protocol_version: Literal[1]`、`mode: Literal['simulation','device']`、`profile_id: str`、`profile_revision: str`、`route_id: str`、`route_revision: str`、`device_id: str`、`not_before: datetime`、`deadline: datetime`；deadline 必须晚于 not_before；未知字段拒绝 |
| `JobView` | `job_id: str`、`spec: JobSpec`、`state: JobState`、`revision: int`、`desired_state: Literal['run','cancel']`、`fence: int`、`agent_id: str|None`、`reason_code: str|None`、`resume_phase: JobState|None`、`recovery_action: Literal['retry_preflight','verify_only','stop_only']|None`；公开对象无 lease token |
| `AgentHello` | `protocol_version: Literal[1]`、`agent_id: str`、`devices: list[DeviceCapability]`；与令牌绑定一致 |
| `DeviceCapability` | `device_id: str`、`backend: Literal['fake','mumu','android']`、`app_version: str|None`、`capabilities: list[str]`、`observed_at: datetime`；未知能力不默认启用 |
| `LeaseGrant` | `job: JobView`、`lease_token: str`、`fence: int`、`expires_at: datetime`；只有领取响应返回 token |
| `LeaseCommand` | `lease_token: str`、`fence: int`；续租/事件/停止确认均必须携带；不允许跨代理使用 |
| `JobEvent` | `event_id: str`、`expected_revision: int`、`state: JobState`、`reason_code: str|None`、`evidence: list[EvidenceRef]`、`resume_phase: JobState|None`；无个人自由文本日志 |
| `EvidenceRef` | `kind: Literal['host_check','device_probe','app_record']`、`sha256: str`（64 小写十六进制）、`captured_at: datetime`、`app_version: str|None`、`profile_revision: str`、`record_status: Literal['valid','invalid','pending']|None`；引用脱敏证据，不能任意指定服务器文件路径/URL |
| `ScheduleSpec` | `schedule_id: str`、`job_template: JobSpec`、`timezone: Literal['Asia/Shanghai']`、`local_time: str`（HH:MM）、`weekdays: list[int]`（ISO 1..7）、`enabled: bool`；实际日期由调度器产生，不复用模板日期 |
| `GeoPoint` | `latitude: float`（-90..90）、`longitude: float`（-180..180）；必须为有限数 |
| `RouteProfile` | `route_id: str`、`revision: str`、`input_crs: Literal['WGS84','GCJ02','BD09']`、`points: list[GeoPoint]`（至少 2 点）、`source_ref: str`；source_ref 是本地登记引用，不允许自动下载任意 URL |
| `SchoolProfile` | `profile_id: str`、`revision: str`、`campus: str`、`app_package: str`、`app_version: str`、`confirmed: bool`、`allowed_region: list[GeoPoint]`（至少 3 点，WGS84）、`rules: dict[str,float]`、`checkpoint_source: Literal['manual_confirmed','adapter_verified']`；初版规则键仅允许 `minimum_distance_m`、`maximum_duration_seconds`、`minimum_speed_mps`、`maximum_speed_mps`，值为有限非负数；实际必需规则未采集或出现其他规则时阻止 device 执行，进入适配流程 |
| `VerificationResult` | `status: Literal['valid','invalid','pending','unknown']`、`evidence: list[EvidenceRef]`、`reason_code: str|None`；unknown/pending 不能导向 succeeded |

`JobState`：`queued, leased, preflight, ready, running, finishing, verifying, cancelling, needs_attention, completed, succeeded, failed, cancelled`。

模型使用 Pydantic v2，禁止 NaN/Infinity、无时区时间和未知字段。默认类型不做有损字符串到数字转换。

规则上下限必须自洽；minimum_speed_mps 不得大于 maximum_speed_mps。SchoolProfile.confirmed 仅表示用户确认了配置，不代表设备或学校后台已验证。日程时间窗由 JobSpec 负责，距离、速度和持续时间由 SchoolProfile 负责，缺失要求不能自动补为默认达标值。

`profile_id/route_id` 在代理本地私有配置库解析；服务器只保存引用。代理在 preflight 校验 ID、revision、实际应用版本与配置内容一致，缺少配置或版本不匹配进入 `needs_attention`，不得静默使用最新版。revision 使用规范化配置 JSON 的 SHA-256；具体规范化算法由 C0 固定并提供跨端测试向量。初版通过受控本地文件配置，尚不提供远程配置下载接口。

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
| `PUT /schedules/{schedule_id}` | ADMIN | `ScheduleSpec`；ID 必须一致；200；仅更新未来未生成执行日程 |

## 状态与恢复

- 正常流程：queued → leased → preflight → ready → running → finishing → verifying。simulation 最终 completed，device 只有实际有效 app_record 证据才 succeeded。
- `failed/cancelled/completed/succeeded` 为终态；终态不可恢复或改写。非法迁移返回 409。
- `needs_attention` 是可恢复状态，记录 resume_phase。未知界面、本人授权、坐标缺失、结果不确定进入此状态。
- queued 过期转 failed / `window_expired`。领取后尚未进入 running 的租约过期：只有明确没有任何设备副作用时可回 queued；存在开始意图或状态不确定则 needs_attention。
- entering running 事件必须先获服务器接受，代理再在本地日志持久化 `start_intent`，最后执行设备开始。此后即便代理崩溃也按可能已开始处理。
- 每个设备副作用前检查本地设备锁、当前 fence、取消信号和保守的租约剩余时间；等待/进程暂停可能耗尽租约，不能只依赖先前的 running 回执。租约过期或状态未知时仅执行受控停止。
- running 之后失联/租约过期：needs_attention，禁止新代理重新开始。原代理重连后须取得同 job 的恢复租约，仅允许 verify_only / stop_only。恢复使用 `POST /leases/claim`，只向原绑定代理返回已获管理员批准的恢复任务；fence 增加，历史 token 失效。
- 旧租约禁止新的设备开始、路线更新、结束上传；持有设备的进程仍必须执行本地受控停止，恢复后报告观测，不能因失去租约而继续运行。
- 取消活动任务先 cancelling；只有 stop-ack 后 cancelled。断线没有确认时留 needs_attention / `stop_unconfirmed`，不能显示已停止。
- `desired_state=cancel` 的任务不能回 queued 或作为新运行领取；恢复租约只允许 stop_only。存在可能活动的设备时保留设备占用锁，直到确认停止或完成核验，不能用新 job 绕过旧任务的不确定状态。
- 上传请求已发出但结果未知：verifying 或 needs_attention / `upload_uncertain`，先回查记录，禁止盲目再上传或重跑。
- event_id 去重在验证当前租约后、revision 冲突检查前执行；相同载荷重试返回原先的事件结果。过期租约不能通过重放事件恢复权限。

## 调度与验证

每个 `(schedule_id, occurrence_local_date)` 最多生成一个任务，数据库唯一约束保证重启不重复。错过 deadline 的日程记为 skipped，默认不补跑。模板中 `deadline-not_before` 定义时窗长度；发生时间为该日 local_time，转换为 UTC 后加同样时窗长度。

所有测试使用假学校、假设备和 fake clock。设备/最终记录证据只由实际观测产生，simulation 不得附带 `app_record`。服务器只能校验证据结构、来源代理和绑定关系，不独立证明学校后台认可；最终验收仍须本地复核证据。
