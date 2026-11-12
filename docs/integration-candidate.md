# 2026-11-12 产品集成记录 / Product integration record

## 当前结果 / Current result

[PR #120](https://github.com/Maximora-byte/swu-happyrun/pull/120) 已以 merge commit [`1431a4f`](https://github.com/Maximora-byte/swu-happyrun/commit/1431a4f4328659c45a405a0d82b149487c3e84c6) 合入 main；合入 tree 为 `b7eb99fee77ada0464a5163b5705a6fa8fc402ff`，与合前准确 HEAD [`c850586`](https://github.com/Maximora-byte/swu-happyrun/commit/c850586071f93e67e90bcf7e590ba0867caf93d2) 一致。main 现包含桌面/MuMu 产品、服务器、代理、统一 CLI 和 Android 源码。本次未发布新安装包，未运行真实设备或学校业务。
PR #120 merged the product into main. This is a software integration, not a new package release or fresh device/school acceptance.

- 合前 [`c850586`](https://github.com/Maximora-byte/swu-happyrun/commit/c850586071f93e67e90bcf7e590ba0867caf93d2)：托管检查 69 项 success、1 项预期 skipped（`compile-adapter`）；[push 检查](https://github.com/Maximora-byte/swu-happyrun/actions/runs/43219462088)、两份 PR 检查 [43219471327](https://github.com/Maximora-byte/swu-happyrun/actions/runs/43219471327) / [43219473640](https://github.com/Maximora-byte/swu-happyrun/actions/runs/43219473640) 已完成。Linux 全量软件测试 3195 passed、16 skipped、1 warning、6 subtests passed（458.89 秒）；Windows/Python 3.13 定向 19 项及共享契约 121 项通过。跳过不算通过，设备验收不在此范围。
- 合后 `main@1431a4f`：2026-11-12 13:11 UTC 核验 23 项检查全部 success；[main checks](https://github.com/Maximora-byte/swu-happyrun/actions/runs/43222204881) 与 [main container smoke](https://github.com/Maximora-byte/swu-happyrun/actions/runs/43222204576) 均 completed/success。Windows/Python 3.11 与 3.13 各六个分片及 completeness 检查通过。该结果仅绑定[合并提交 1431a4f](https://github.com/Maximora-byte/swu-happyrun/commit/1431a4f4328659c45a405a0d82b149487c3e84c6/checks)，不代表后续 PR #122 或其他新 HEAD 已通过。
- 2026-11-12 用户取消强制本地 Codex 交接，由 Dot 全权开发并协调独立审查。实现与审查仍分开，精确提交检查、真实设备授权和学校有效记录证据不省略，见 [AGENTS.md](../AGENTS.md)。
- 旧 CLI/enrollment 门禁、#110 历史故障与设备/学校验收限制保持不变。旧 PR 的包含关系与逐项处置分开核实，不按编号批量合并或关闭。

## 合前记录（原文保留） / Archived pre-merge record

以下整段是合前候选说明及当时的 PR 快照。其中“尚未合入”“保持草稿”和分工/待办语句已由上面的当前结果取代；它们不是今天的操作指令。历史失败、未纳入工作和版本限定证据仍保留原含义。
The following pre-merge text is retained unchanged. Its draft/promotion instructions are historical, not current workflow gates.

# 2026-11-12 单一集成候选 / Single integration candidate

## 选择与范围 / Baseline and scope

本候选以 `dot/complete-windows-suite@e9cdc55481432937f17ecbafc4d674afe4021b24` 为基线；它完整继承 `dot/trusted-runtime-context@74d4aa3f224756d6083775bef9525feca8943e86`，额外四个提交仅涉及七个 CI/测试/验收说明文件，`src/` 产品代码相同。合入默认分支 `f578b17d` 作为第二条祖先，保留其 14 份历史 QA/计划及机器人配置；状态文档的双方正文分别保留在 [产品历史状态](status.md) 和 [main 历史快照](status-main-20261020.md)。本候选是供审查的整合入口，不是发布、main 合并或真实设备验收。
This candidate preserves the complete product ancestry and the Windows suite-accounting work. It does not declare release, main merge, or fresh device acceptance.

- 保留本地中文工作台、HTTP/SQLite 模拟任务、独立 MuMu 桌面定位工具及原安全门禁。Preserve product functionality and fail-closed gates.
- 补入 #103 的 `d09b926` 测试收尾修复：等待 reader 退出，再恢复捕获；不修改运行时代码。Carry the focused reader-cleanup test delta, not the entire old branch.
- 从 #119 `09caa171` 复用文档导航和日期化 PR 地图，并加本候选限定；不直接覆盖产品 README 或历史验收正文。
- #117/#118 是旧 main 的 README 改动，不能把“main 无产品”当成此候选的状态；它们仍独立开放，不在此自动关闭或合并。The main-only README updates remain separate.

## 使用入口 / Entry points

- [本地工作台 / Local workstation](desktop.md)
- [MuMu 独立工具 / MuMu tool](mumu-desktop.md)
- [服务器与代理 / Installation](installation.md)
- [文档导航 / Documentation](README.md)
- [原 PR 分层地图 / Original stack](repository-map.md)

从这个候选的准确提交安装，不混用不同分支的“最新文件”。Windows 本地产品历史交付采用 Python 3.13；旧 Windows 3.11 问题 #110 不因切换版本而被宣称修复。
Install one immutable commit; do not mix files from branches. Historical Windows delivery used Python 3.13, which does not close issue #110.

## 证据边界 / Evidence boundary

RC2 的 421.476 米 / 116 次写入对应 `a7138c19`；RC3 的 14 次跨前台写入对应 `31b5d408`。后续 `74d4aa3` 还修改了轨迹预算、停止边界与 journal 读取，不能继承为同 HEAD 实测。本轮不登录学校、不写真实设备、不开始或上传运动记录。
RC2/RC3 device receipts remain pinned to their own source versions. This integration does not repeat them. Mini-program activity, uploads and school-valid records remain unverified.

旧 native CLI/enrollment 与独立桌面 MuMu 工具是不同路径。前者保持关闭；停止只证明本工具的发送线程/在途命令结束，不证明清空厂商队列或恢复真实 GPS。不得因旧 PR #91 中有执行入口而恢复它。
The legacy native path remains closed. Desktop stopping does not clear vendor location state. Do not restore the old #91 executor.

## 逐 PR 处置 / PR-by-PR disposition

以下是**整合前 e9cdc554 基线**的 2026-11-12 快照，共 43 个已有开放 PR，并非最终候选缺项表。最终处置：#103 的单个测试修复已补入；#119@09caa171 的导航与地图已复用并添加候选范围说明。其他分类保持基线审计含义。祖先或内容包含不等于通过独立审查，也不是关闭这些 PR 的授权。`superseded_by_candidate` 仅表示较新实现覆盖相关意图，不代表逐字相同。机读记录见 [JSON](integration-prs-20261112.json)。
This dated inventory is not a live dashboard or permission to merge/close PRs. Ancestry and patch equivalence do not substitute for acceptance.

| PR | HEAD | 分类 / Classification | 原因 / Reason |
| --- | --- | --- | --- |
| [#119](https://github.com/Maximora-byte/swu-happyrun/pull/119) | `09caa171` | `documentation_in_progress` | Current #119 cleanup is being revised separately; integrate only its reviewed exact head. |
| [#118](https://github.com/Maximora-byte/swu-happyrun/pull/118) | `78aa1298` | `documentation_independent` | Main-relative README state fix, may conflict semantically with candidate product README. |
| [#117](https://github.com/Maximora-byte/swu-happyrun/pull/117) | `5739fdc5` | `documentation_independent` | Main-relative bilingual README; preserve candidate product guidance when reconciling. |
| [#111](https://github.com/Maximora-byte/swu-happyrun/pull/111) | `e9cdc554` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#109](https://github.com/Maximora-byte/swu-happyrun/pull/109) | `74d4aa3f` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#108](https://github.com/Maximora-byte/swu-happyrun/pull/108) | `e4a37327` | `superseded_by_candidate` | Bounded read product changes present byte-for-byte; newer tests and CI supersede old branch. |
| [#107](https://github.com/Maximora-byte/swu-happyrun/pull/107) | `20c76257` | `superseded_by_candidate` | Bounded read product changes present byte-for-byte; newer tests and CI supersede old branch. |
| [#103](https://github.com/Maximora-byte/swu-happyrun/pull/103) | `d09b926d` | `missing_test_fix` | d09b926 reader-thread join/delayed-exit fixture changes absent; candidate for small cherry-pick and focused tests. |
| [#96](https://github.com/Maximora-byte/swu-happyrun/pull/96) | `010c984d` | `alternative_diagnostics` | Old route-label diagnostics absent, but candidate uses newer ApiStatusFailure and bounded busy polling; do not overwrite. |
| [#95](https://github.com/Maximora-byte/swu-happyrun/pull/95) | `f0651bf9` | `alternative_diagnostics` | Same final diagnostics delta as #96; newer error classification exists. |
| [#94](https://github.com/Maximora-byte/swu-happyrun/pull/94) | `3f2e07c4` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#93](https://github.com/Maximora-byte/swu-happyrun/pull/93) | `726ed1eb` | `not_included_optional_delivery` | local_delivery_v2 six-APK packaging/checking tools and tests absent. Separate optional scope, not required for desktop baseline. |
| [#92](https://github.com/Maximora-byte/swu-happyrun/pull/92) | `17fe18d9` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#91](https://github.com/Maximora-byte/swu-happyrun/pull/91) | `1e419704` | `superseded_native_path` | Bounded private input reader upgraded; old executable native CLI deliberately replaced with closed enrollment gate. Do not restore. |
| [#90](https://github.com/Maximora-byte/swu-happyrun/pull/90) | `6fe5fdb8` | `superseded_by_candidate` | Native adapter unchanged; capture enhanced with binary evidence and tests use synthetic adapter. |
| [#89](https://github.com/Maximora-byte/swu-happyrun/pull/89) | `2d7000d8` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#87](https://github.com/Maximora-byte/swu-happyrun/pull/87) | `fb5e229e` | `superseded_by_candidate` | Capture/newline/reader ownership integrated in evolved binary capture implementation; legacy tests updated. |
| [#77](https://github.com/Maximora-byte/swu-happyrun/pull/77) | `45a2b9fd` | `exact_changed_files_present` | All files touched by non-ancestor final commit are byte-identical to candidate. |
| [#74](https://github.com/Maximora-byte/swu-happyrun/pull/74) | `1377dc2a` | `superseded_by_candidate` | Observer exists with tighter 5-second window, gravity accuracy checks and further updates. |
| [#70](https://github.com/Maximora-byte/swu-happyrun/pull/70) | `92cb81cf` | `exact_changed_files_present` | All files touched by non-ancestor final commit are byte-identical to candidate. |
| [#61](https://github.com/Maximora-byte/swu-happyrun/pull/61) | `15870e11` | `not_included_optional_probe` | Offline channel_probe_plan model/trace validator absent; no transport or capability grant. Separate optional research. |
| [#51](https://github.com/Maximora-byte/swu-happyrun/pull/51) | `491a6eca` | `superseded_by_candidate` | Encoding/ID fixtures retained; navigation checker enhanced with bounded raw-byte diagnostics. |
| [#49](https://github.com/Maximora-byte/swu-happyrun/pull/49) | `dbb78557` | `superseded_by_candidate` | Portable fixtures retained, supplemented by current capture stubs, symlink policies and explicit IDs. |
| [#48](https://github.com/Maximora-byte/swu-happyrun/pull/48) | `320bfdff` | `superseded_by_candidate` | Portable fixtures retained, supplemented by current capture stubs, symlink policies and explicit IDs. |
| [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46) | `a49225d5` | `patch_equivalent` | All branch-only nonmerge commits patch-equivalent to complete-windows-suite. |
| [#43](https://github.com/Maximora-byte/swu-happyrun/pull/43) | `a3fd8a6f` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#35](https://github.com/Maximora-byte/swu-happyrun/pull/35) | `2d0fcc55` | `patch_equivalent` | All branch-only nonmerge commits patch-equivalent to complete-windows-suite. |
| [#34](https://github.com/Maximora-byte/swu-happyrun/pull/34) | `260d0739` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#33](https://github.com/Maximora-byte/swu-happyrun/pull/33) | `091f2428` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#32](https://github.com/Maximora-byte/swu-happyrun/pull/32) | `0402c117` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#31](https://github.com/Maximora-byte/swu-happyrun/pull/31) | `f3d0699d` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#30](https://github.com/Maximora-byte/swu-happyrun/pull/30) | `585e1b06` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#29](https://github.com/Maximora-byte/swu-happyrun/pull/29) | `58264f22` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#28](https://github.com/Maximora-byte/swu-happyrun/pull/28) | `9c358125` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#27](https://github.com/Maximora-byte/swu-happyrun/pull/27) | `9db9c8f3` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#26](https://github.com/Maximora-byte/swu-happyrun/pull/26) | `5e841d1f` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#25](https://github.com/Maximora-byte/swu-happyrun/pull/25) | `77494e21` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#24](https://github.com/Maximora-byte/swu-happyrun/pull/24) | `cc81d124` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#23](https://github.com/Maximora-byte/swu-happyrun/pull/23) | `561155a2` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#22](https://github.com/Maximora-byte/swu-happyrun/pull/22) | `e3ffab6a` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#21](https://github.com/Maximora-byte/swu-happyrun/pull/21) | `e9356320` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#20](https://github.com/Maximora-byte/swu-happyrun/pull/20) | `10b2172b` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |
| [#18](https://github.com/Maximora-byte/swu-happyrun/pull/18) | `c474119c` | `ancestor_included` | Exact PR head is ancestor of complete-windows-suite. |

## 不纳入的独立工作 / Work kept separate

- #61：离线通道计划模型，当前产品不依赖它。Keep the optional offline probe model separate.
- #93：六 APK 同源交付工具，当前 RC3 桌面包是另一条交付路径，未据此发布新包。Keep optional six-APK tooling separate.
- #95/#96：旧诊断方案不能覆盖新错误分类/有界重试。Do not revert newer diagnostics.
- #117/#118：需按最终 main 产品内容重新协调英文完整 README；不把旧 main 说明机械合并到本候选。Reconcile main-only language work against the eventual product main.

## 验证与放行 / Verification and promotion

见本 PR 正文的准确 HEAD/tree、命令与结果。测试中的 fake、回环 HTTP 和静态 Android 检查不是学校或设备验收。托管检查必须绑定本 PR 的新 HEAD；继承的绿灯只证明其原提交。
Use the PR's exact-head receipt. Fake/loopback/static checks do not establish device or school acceptance. Inherited CI is not a pass for the new commit.

保持草稿，直到完整软件检查、独立差异审查及必要的 Windows/设备回执均明确。不要将 43 个旧 PR 按编号批量合并；先评审这个固定树，再由用户决定 main 整合和历史 PR 处置。
Keep this integration draft until its gates are reviewed. Review the fixed tree before deciding main promotion or old PR disposition.
