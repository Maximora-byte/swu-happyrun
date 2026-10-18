# Fake 联调与故障验收

只对临时测试服务、独立 journal 和 simulation 任务运行。测试不接触真实设备，不产生学校有效记录。成功 simulation 必须为 `completed`，不能是 `succeeded`，不能带 `app_record`。

## 必须验证的实际 HTTP 流程

在完整集成候选根目录运行 `uv run --no-sync python deploy/smoke_fake.py`（实际执行状态见 [交付验证记录](delivery-validation.md)），启动回环服务并运行 fake agent。脚本首先用 ADMIN 注册 device_id 到 agent_id 的不可变归属，再 hello/claim；不能靠代理自行声明取得所有权。保留同一任务 ID 验证：创建、幂等重放、领取、状态事件、查询最终 `completed`。必须实际通过 TCP HTTP；TestClient 或 mock 单独通过不代表该路径已验收。

完整验收还应覆盖续租、取消、恢复和日程去重。每项记录相同候选 HEAD、命令、结果；缺失脚本或未执行检查写 `not_tested`，不得从正常完成推断。

## 故障矩阵

| 故障 | 复现边界 | 必须观察 | 禁止行为 |
| --- | --- | --- | --- |
| 领取竞争 | 两个连接同时 claim 同一设备 | 只有一个有效租约；另一个无任务或冲突 | 两个执行者并行 start |
| 旧 fence | 租约更新/恢复后重放旧命令 | 409；设备不再执行旧指令 | 用旧事件恢复权限 |
| 开始后崩溃 | 已持久化 start intent 后中止 fake agent | 重启后不再次 start；needs_attention/受限恢复 | 清空 journal 后重跑 |
| 断线/续租失败 | 活动 fake 任务中让测试服务不可达 | 本地停止 ticks；未知状态保存；不补发积压动作 | 假装任务正常完成 |
| 取消 | 活动任务 cancel | 先 cancelling；驱动停止后 stop-ack 才 cancelled | 把 HTTP cancel 接受等同已停止 |
| 停止回执丢失 | stop 后丢弃 ack 响应并重试 | 相同 event ID 幂等；未确认保持待处理 | 换任务绕过设备锁 |
| 上传不确定 | 结束请求已发出但响应丢失 | verify_only 回查；不得再次 start 或上传 | 自动重跑 |
| 服务重启 | 创建任务后停止/重新启动同一 DB | 相同 job 仍可查；日程 occurrence 不重复 | 使用临时 DB 冒充持久化 |
| 错过时间窗 | fake clock 推进过 deadline | 过期实例 skipped/失败，不补跑 | 重启后补跑旧日程 |
| 凭证/日志 | 错 token、他人任务、坏 JSON | 401/403/404/422 按契约；不回显 token | 保存完整 Authorization |

使用 fake clock 做到期/日程测试，不依靠长时间睡眠。进程中断测试只终止本轮启动的测试进程，不改现有服务或其他用户进程。

## 恢复操作

先读取任务状态、revision、最近原因和本地 journal，确认设备是否可能仍活动。`needs_attention` 是可恢复状态，不是终态。

- `retry_preflight`：仅明确从未产生副作用且服务器允许时使用。
- `verify_only`：已运行或上传不明时，只核验已有结果，路径不进入 running。
- `stop_only`：取消或停止未确认时；先确认设备停止，再提交 stop-ack。

恢复请求带最新 `expected_revision`；冲突时重新读取状态，不盲目重复动作。数据库和 journal 都不是可随意删除的缓存。需要实际设备确认时交给本地验收者，不能通过改数据库伪造成功。
