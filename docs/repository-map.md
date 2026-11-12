# 分支与 PR 地图 / Branch and PR map

> **当前入口更新（2026-11-12）：** 产品已通过 [PR #120](https://github.com/Maximora-byte/swu-happyrun/pull/120) 合入 main。下方 `main@f578b17d` 与开放 PR 数是合前快照，不是当前主分支状态；请读[集成记录](integration-candidate.md)和[文档导航](README.md)。
> Product integration is now on main. The inventory below remains a historical pre-merge snapshot.

盘点日期 / Snapshot date: **2026-11-12 UTC**。此表记录本次整理前的 **42 个开放 PR**，不是自动更新的看板，也不是合并批准；最新状态以 [GitHub PR 列表](https://github.com/Maximora-byte/swu-happyrun/pulls) 为准。本次复核仍为原 42 个开放 PR 加整理 PR [#119](https://github.com/Maximora-byte/swu-happyrun/pull/119)，共 43 个；#119 不计入下方基线表。
This snapshot lists the 42 open PRs inspected before this cleanup. A recheck found the same 42 plus cleanup PR #119 (43 total); #119 is excluded from the baseline table. This is not a live dashboard or merge approval.

## 默认分支与候选 / Default branch and candidate

| 入口 / Entry | 核对的提交 / Inspected commit | 用途与边界 / Purpose and limits |
| --- | --- | --- |
| `main` | [`f578b17d`](https://github.com/Maximora-byte/swu-happyrun/tree/f578b17dcb9cbebd1045a621a92c3dbea91017d3) | 共享模型、状态结构与 MuMu/ADB 只读诊断；无 `server/`、`agent/`、统一 CLI、网页或 Android 产品实现。Shared contracts and read-only diagnostics; no complete product entry point. |
| `dot/recheck-candidate` | [`94dcbfcc`](https://github.com/Maximora-byte/swu-happyrun/tree/94dcbfcce7b53630196d7b6f0868709eed7c7241) | 较早的候选集成线，其旧回放限制不代表所有后续候选。Earlier integration line; its legacy replay limits are not global candidate limits. |
| `dot/trusted-runtime-context`（[#109](https://github.com/Maximora-byte/swu-happyrun/pull/109)） | [`74d4aa3f`](https://github.com/Maximora-byte/swu-happyrun/tree/74d4aa3f224756d6083775bef9525feca8943e86) | 含独立桌面/MuMu 产品及 RC2/RC3 固定源码实测回执；后续修订不自动继承旧验收。Contains the desktop/MuMu product and version-bound evidence, not blanket acceptance of later changes. |

默认分支中实际存在：[`src/swu_happyrun/core/`](../src/swu_happyrun/core/)、[`drivers/mumu/`](../src/swu_happyrun/drivers/mumu/)、[`tests/contracts/`](../tests/contracts/)、[`tests/agent/`](../tests/agent/)、[`scripts/`](../scripts/)。`tests/agent/` 的名称不能据此证明产品代理已进入 main。
The listed directories exist on the inspected default branch. A test-directory name does not establish a shipped agent runtime.

### 不同执行路径与证据 / Execution paths and evidence

- 较早 `dot/recheck-candidate` 的[回放边界](https://github.com/Maximora-byte/swu-happyrun/blob/94dcbfcce7b53630196d7b6f0868709eed7c7241/docs/virtual-replay.md)描述该路径的限制，不代表后续独立桌面工具没有实际写入能力。Legacy replay limitations are path-specific.
- `dot/trusted-runtime-context` 已有[桌面入口](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/desktop.md)、[MuMu 工具说明](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/mumu-desktop.md)与固定源码回执：RC2 产品 `a7138c19` 的[421.476 米 / 116 次写入](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/qa/2026-10-23-local-product.md)；RC3 产品 `31b5d408` 的[14 次持续写入、暂停/继续和停止确认](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/qa/2026-10-23-rc3-delivery.md)。验收环境为 Windows/Python 3.13、MuMu 6.8.4.0 / Android 15 API35；RC2 与 RC3 不能互相冒称重跑结果。These are separate version-bound device test receipts, reviewed here without rerunning them.
- 较新 HEAD `74d4aa3` 修改了轨迹预算与 journal 读取，不能把前述产品实测直接归为它的全量实测；旧 CLI/enrollment 门禁及 #110 也仍需分别处理。Later changes and legacy gates require separate verification.
- [纯接口研究](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/research/direct-protocol.md)、小程序实际轨迹、上传与学校有效记录仍未验收。自身定位读回成功不证明第三方采纳位置或服务端认可成绩。Local positioning evidence does not establish third-party app or school-record acceptance.

## 如何阅读堆叠 PR / Reading stacked PRs

- 表中 `base` 是实际目标分支，不默认等于 main。The base column is the actual target branch, not necessarily main.
- 先核对基础分支与准确 HEAD，再评审增量；不要把旧 PR 逐个盲目重放到新候选。Review ancestry and the exact head before replaying old increments.
- Ready、无文本冲突和 CI 通过都不等于产品或设备验收通过。Ready status, conflict-free text and green CI are not device/product acceptance.
- #117/#118 都涉及 README；已做双语协调，但合并前仍须按最新 HEAD 复核。Both README PRs need an exact-head combination check before integration.
- 本次仅编制目录，保留全部开放 PR、分支、失败回执与历史。This cleanup retains all PRs, branches and historical evidence.

## 文档入口 / Documentation

| PR | 标题 / Title | base | HEAD | 状态 / State |
| --- | --- | --- | --- | --- |
| [#117](https://github.com/Maximora-byte/swu-happyrun/pull/117) | docs: add Chinese–English README navigation and English edition | `main` | [`5739fdc5`](https://github.com/Maximora-byte/swu-happyrun/commit/5739fdc5efe126a4cf3440cc14471a6a08811701) | 草稿 / Draft |
| [#118](https://github.com/Maximora-byte/swu-happyrun/pull/118) | docs: align README with current implementation and acceptance status | `main` | [`78aa1298`](https://github.com/Maximora-byte/swu-happyrun/commit/78aa1298618a48dac97d1de5b6e695867624e4ba) | 开放、非草稿 / Open, non-draft |

## 基础产品与集成 / Product foundations and integration

| PR | 标题 / Title | base | HEAD | 状态 / State |
| --- | --- | --- | --- | --- |
| [#18](https://github.com/Maximora-byte/swu-happyrun/pull/18) | S0: authenticated durable task API and identity isolation | `dot/c0-recovery-contract` | [`c474119c`](https://github.com/Maximora-byte/swu-happyrun/commit/c474119cdc18fa34fefffd5e8ea64c79f0106159) | 开放、非草稿 / Open, non-draft |
| [#20](https://github.com/Maximora-byte/swu-happyrun/pull/20) | L1: validate local routes and add session-bound fake fault driver | `dot/c1-recovery-protocol` | [`10b2172b`](https://github.com/Maximora-byte/swu-happyrun/commit/10b2172bebd8aba302cc8a0345503b32d38589f6) | 开放、非草稿 / Open, non-draft |
| [#21](https://github.com/Maximora-byte/swu-happyrun/pull/21) | feat: add recoverable agent runtime and JSON CLI (L2) | `dot/driver-validation` | [`e9356320`](https://github.com/Maximora-byte/swu-happyrun/commit/e935632079c805952e7b143e5438c7d829b34f22) | 草稿 / Draft |
| [#22](https://github.com/Maximora-byte/swu-happyrun/pull/22) | S1: fenced leases, conservative recovery and record binding | `dot/server-api` | [`e3ffab6a`](https://github.com/Maximora-byte/swu-happyrun/commit/e3ffab6a0309d2b7e484edfe9498f4e2aab9e1b2) | 草稿 / Draft |
| [#23](https://github.com/Maximora-byte/swu-happyrun/pull/23) | S2: persistent schedules, managed background ticks and readiness | `dot/server-leases` | [`561155a2`](https://github.com/Maximora-byte/swu-happyrun/commit/561155a24582c0e5bfcb4fbba7a9f2d2c53eaea9) | 草稿 / Draft |
| [#24](https://github.com/Maximora-byte/swu-happyrun/pull/24) | feat: add deployment package and candid acceptance guides | `dot/server-schedules` | [`cc81d124`](https://github.com/Maximora-byte/swu-happyrun/commit/cc81d124e4feab978ae60a694ae06391cb6cb728) | 草稿 / Draft |
| [#25](https://github.com/Maximora-byte/swu-happyrun/pull/25) | feat: deliver installable HappyRun candidate with real HTTP fault verification | `main` | [`77494e21`](https://github.com/Maximora-byte/swu-happyrun/commit/77494e21756e514f53e51b3a2c72f22555f0aae6) | 草稿 / Draft |
| [#26](https://github.com/Maximora-byte/swu-happyrun/pull/26) | feat: diagnose Android devices without requiring MuMu | `dot/candidate-review-base-19c15ba7` | [`5e841d1f`](https://github.com/Maximora-byte/swu-happyrun/commit/5e841d1fa8e231caa33608cdd689f0b79b1f9d8d) | 开放、非草稿 / Open, non-draft |
| [#27](https://github.com/Maximora-byte/swu-happyrun/pull/27) | feat: normalize explicit coordinate systems for offline route validation | `dot/candidate-review-base-19c15ba7` | [`9db9c8f3`](https://github.com/Maximora-byte/swu-happyrun/commit/9db9c8f31567b3300699e79b3a340f7bbaf3c22c) | 开放、非草稿 / Open, non-draft |
| [#28](https://github.com/Maximora-byte/swu-happyrun/pull/28) | fix: gracefully stop agents and retry only safe idle connections | `dot/android-diagnostics` | [`9c358125`](https://github.com/Maximora-byte/swu-happyrun/commit/9c358125a9724fafd3468a64f069e5ec92acab49) | 草稿 / Draft |
| [#29](https://github.com/Maximora-byte/swu-happyrun/pull/29) | feat: complete simulated routes before reporting successful execution | `dot/agent-shutdown-reconnect` | [`58264f22`](https://github.com/Maximora-byte/swu-happyrun/commit/58264f22ba8829ec707f2d1a07617332f42ef48d) | 草稿 / Draft |
| [#30](https://github.com/Maximora-byte/swu-happyrun/pull/30) | fix: prevent signal-handler deadlocks and synchronize fault regressions | `dot/route-engine` | [`585e1b06`](https://github.com/Maximora-byte/swu-happyrun/commit/585e1b0674022c8262109a7ea5e5720c0532eee9) | 开放、非草稿 / Open, non-draft |
| [#31](https://github.com/Maximora-byte/swu-happyrun/pull/31) | feat(console): add usable Chinese desktop and mobile task console | `dot/fix-signal-reentrancy` | [`f3d0699d`](https://github.com/Maximora-byte/swu-happyrun/commit/f3d0699d8923ce7d2325abedcb680fc70f650f4a) | 开放、非草稿 / Open, non-draft |
| [#32](https://github.com/Maximora-byte/swu-happyrun/pull/32) | feat(android): add native local diagnostic and simulation APK candidate | `dot/web-console` | [`0402c117`](https://github.com/Maximora-byte/swu-happyrun/commit/0402c11753af534e42af6bc24525cea115968198) | 草稿 / Draft |
| [#33](https://github.com/Maximora-byte/swu-happyrun/pull/33) | feat(android): add beginner setup guide and optional own-app Root/framework diagnostics | `dot/android-app` | [`091f2428`](https://github.com/Maximora-byte/swu-happyrun/commit/091f2428139176370390daa40b0570fcc9fa612a) | 草稿 / Draft |
| [#34](https://github.com/Maximora-byte/swu-happyrun/pull/34) | test(server): add real container API, lease and schedule acceptance | `dot/web-console` | [`260d0739`](https://github.com/Maximora-byte/swu-happyrun/commit/260d0739cbcc7c0b80dd91ca2573b1e6caab25dd) | 开放、非草稿 / Open, non-draft |
| [#35](https://github.com/Maximora-byte/swu-happyrun/pull/35) | Android: one-shot remote fake agent and isolated real HTTPS acceptance | `dot/integration-candidate` | [`2d0fcc55`](https://github.com/Maximora-byte/swu-happyrun/commit/2d0fcc550f9c1f6cf8cc6e0106dcafd106cf181a) | 草稿 / Draft |

## Android 与设备边界 / Android and device boundaries

| PR | 标题 / Title | base | HEAD | 状态 / State |
| --- | --- | --- | --- | --- |
| [#43](https://github.com/Maximora-byte/swu-happyrun/pull/43) | test(server): prove mid-write probe batch rollback | `dot/android-remote-agent` | [`a3fd8a6f`](https://github.com/Maximora-byte/swu-happyrun/commit/a3fd8a6f71a9745e68a2f235c34b6367bdf4aac6) | 草稿 / Draft |
| [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46) | Issue41: integrated foreground simulation, recovery and exact-head Android acceptance | `dot/android-remote-agent` | [`a49225d5`](https://github.com/Maximora-byte/swu-happyrun/commit/a49225d5f59ee2324d47275ab9d25e77cc645680) | 草稿 / Draft |
| [#48](https://github.com/Maximora-byte/swu-happyrun/pull/48) | R3: offline Budao version and record rejection gates | `dot/mumu-instance-binding` | [`320bfdff`](https://github.com/Maximora-byte/swu-happyrun/commit/320bfdffeb6d5d267262813e13851d4443d7e52c) | 开放、非草稿 / Open, non-draft |
| [#49](https://github.com/Maximora-byte/swu-happyrun/pull/49) | R2: synthetic calibration and confirmed-stop boundaries | `dot/mumu-instance-binding` | [`dbb78557`](https://github.com/Maximora-byte/swu-happyrun/commit/dbb78557e47070bbccf61e75f6e104067d3ee2ac) | 开放、非草稿 / Open, non-draft |
| [#51](https://github.com/Maximora-byte/swu-happyrun/pull/51) | R4: fail-closed MuMu composition and synthetic protocol integration | `dot/mumu-calibration-boundaries` | [`491a6eca`](https://github.com/Maximora-byte/swu-happyrun/commit/491a6eca195bbf7dc3356673c1e42a6f670d80dc) | 开放、非草稿 / Open, non-draft |
| [#61](https://github.com/Maximora-byte/swu-happyrun/pull/61) | docs(mumu): 6.8.4 通道探针设计与离线证据检查 | `dot/android-foreground-agent` | [`15870e11`](https://github.com/Maximora-byte/swu-happyrun/commit/15870e115d34403789c0caa267db6ca5e0357f25) | 草稿 / Draft |
| [#70](https://github.com/Maximora-byte/swu-happyrun/pull/70) | Issue57: bounded hello control error and fixture diagnostics | `dot/android-foreground-agent` | [`92cb81cf`](https://github.com/Maximora-byte/swu-happyrun/commit/92cb81cf868741f24b28378ebd3015a14a77f242) | 草稿 / Draft |
| [#74](https://github.com/Maximora-byte/swu-happyrun/pull/74) | test(android): 自身定位/重力只读观察器，注入能力保持关闭 | `dot/android-foreground-agent` | [`1377dc2a`](https://github.com/Maximora-byte/swu-happyrun/commit/1377dc2ae1076580e5181831eb21333ba9cbd0f8) | 草稿 / Draft |
| [#77](https://github.com/Maximora-byte/swu-happyrun/pull/77) | fix(server): return SQLite busy responses before HTTP timeout | `dot/android-foreground-agent` | [`45a2b9fd`](https://github.com/Maximora-byte/swu-happyrun/commit/45a2b9fde32f011f67eb62bf0c06c575188a18b2) | 草稿 / Draft |
| [#87](https://github.com/Maximora-byte/swu-happyrun/pull/87) | Bound read-only command capture and retain unconfirmed child/reader ownership | `dot/android-foreground-agent` | [`fb5e229e`](https://github.com/Maximora-byte/swu-happyrun/commit/fb5e229ef62b14c52a61f5fafa2c00255420391a) | 开放、非草稿 / Open, non-draft |

## 回放与本机诊断 / Replay and local diagnostics

| PR | 标题 / Title | base | HEAD | 状态 / State |
| --- | --- | --- | --- | --- |
| [#89](https://github.com/Maximora-byte/swu-happyrun/pull/89) | Add correlated private own-APK location and gravity readback | `dot/night-integration-base` | [`2d7000d8`](https://github.com/Maximora-byte/swu-happyrun/commit/2d7000d8dcdedf952bedff150abfdbe862d47ed4) | 草稿 / Draft |
| [#90](https://github.com/Maximora-byte/swu-happyrun/pull/90) | feat: bounded own-app MuMu 6.8.4 native invocation (N1) | `dot/night-integration-base` | [`6fe5fdb8`](https://github.com/Maximora-byte/swu-happyrun/commit/6fe5fdb820fbb6e804531cd4352312ac3291ed74) | 草稿 / Draft |
| [#91](https://github.com/Maximora-byte/swu-happyrun/pull/91) | feat(mumu): fail-closed local replay and controlled point probe (N3) | `dot/night-replay-deps` | [`1e419704`](https://github.com/Maximora-byte/swu-happyrun/commit/1e4197043046a34ffe329a89d4e796e057fd18ed) | 草稿 / Draft |
| [#92](https://github.com/Maximora-byte/swu-happyrun/pull/92) | fix(agent): validate cancellation and stop-ack response identity | `dot/night-integration-base` | [`17fe18d9`](https://github.com/Maximora-byte/swu-happyrun/commit/17fe18d91ff45fbfcecb118b627e96dc998ab3dd) | 开放、非草稿 / Open, non-draft |
| [#93](https://github.com/Maximora-byte/swu-happyrun/pull/93) | N5: same-source six-APK and wheel local delivery schema | `dot/night-virtual-run-candidate` | [`726ed1eb`](https://github.com/Maximora-byte/swu-happyrun/commit/726ed1ebc6b668cf9f662b4df4ca6ecd5c17c318) | 开放、非草稿 / Open, non-draft |
| [#94](https://github.com/Maximora-byte/swu-happyrun/pull/94) | fix(replay): always close session after cleanup persistence failure | `dot/night-virtual-run-candidate` | [`3f2e07c4`](https://github.com/Maximora-byte/swu-happyrun/commit/3f2e07c4ccd0cd0155d862258dcb4d258664e477) | 开放、非草稿 / Open, non-draft |
| [#95](https://github.com/Maximora-byte/swu-happyrun/pull/95) | fix: retain capture ownership across interrupted reader bootstrap | `dot/night-virtual-run-candidate` | [`f0651bf9`](https://github.com/Maximora-byte/swu-happyrun/commit/f0651bf9316c9d7f679a5e7afa8ba5aee1c4dd35) | 开放、非草稿 / Open, non-draft |
| [#96](https://github.com/Maximora-byte/swu-happyrun/pull/96) | test(smoke): retain bounded HTTP status failure diagnostics | `dot/night-virtual-run-candidate` | [`010c984d`](https://github.com/Maximora-byte/swu-happyrun/commit/010c984d5fb1dbcf8b8291eaaa281a4276e75d87) | 开放、非草稿 / Open, non-draft |
| [#103](https://github.com/Maximora-byte/swu-happyrun/pull/103) | test: synchronize interrupted capture fixture reader cleanup | `dot/recheck-candidate` | [`d09b926d`](https://github.com/Maximora-byte/swu-happyrun/commit/d09b926d7106bd770bad9f31defc3c92cdaeec71) | 开放、非草稿 / Open, non-draft |

## 登记、运行上下文与 CI / Enrollment, runtime context and CI

| PR | 标题 / Title | base | HEAD | 状态 / State |
| --- | --- | --- | --- | --- |
| [#107](https://github.com/Maximora-byte/swu-happyrun/pull/107) | feat: wire independently fixed enrollment entry points | `dot/recheck-candidate` | [`20c76257`](https://github.com/Maximora-byte/swu-happyrun/commit/20c762576ed104066f767e54122f536248ea19b3) | 开放、非草稿 / Open, non-draft |
| [#108](https://github.com/Maximora-byte/swu-happyrun/pull/108) | feat: add bounded full-scope enrollment reinspection | `dot/reviewed-runner-entry` | [`e4a37327`](https://github.com/Maximora-byte/swu-happyrun/commit/e4a3732784c61f9e178d5ef4e1aa1d10b4684bb5) | 开放、非草稿 / Open, non-draft |
| [#109](https://github.com/Maximora-byte/swu-happyrun/pull/109) | feat: bind runtime storage context and original uncertainty retention | `dot/bounded-scope-coverage` | [`74d4aa3f`](https://github.com/Maximora-byte/swu-happyrun/commit/74d4aa3f224756d6083775bef9525feca8943e86) | 草稿 / Draft |
| [#111](https://github.com/Maximora-byte/swu-happyrun/pull/111) | ci: account for every Python node in bounded Windows shards | `dot/trusted-runtime-context` | [`e9cdc554`](https://github.com/Maximora-byte/swu-happyrun/commit/e9cdc55481432937f17ecbafc4d674afe4021b24) | 开放、非草稿 / Open, non-draft |

## 下次更新 / Next refresh

发生合并、关闭、重定向或新验收时，重新读取 PR 的 state、draft、head SHA 和 base ref，再更新本页日期及表格。历史测试结果仍留在原始回执，不能复制为新 HEAD 的验收结论。
Refresh state, draft status, head SHA and base ref after merges, closures, retargeting or new acceptance. Keep historical test results at their original receipts; do not reuse them as proof for a new head.
