# 协作状态

更新：2026-10-19（Asia/Shanghai）。Dot 主导实现和修复；本地 Codex 负责独立测试、设备观测和集成审核。本轮只使用 GitHub，没有发送 Matrix 消息。

## 下一轮执行入口

[e490后续设备交付计划](superpowers/plans/2026-10-19-post-e490-device-delivery.md)为最新接续：#52/#53已由#55/#56接受；MuMu普通/可选版各30项历史离线流程通过。新[#65](https://github.com/Maximora-byte/swu-happyrun/pull/65)采证入口已实测接受并关闭#58，vendor139/135仍失败；[#62](https://github.com/Maximora-byte/swu-happyrun/pull/62)原普通账户真实javac失败，#59继续开放。Dot优先修#62及[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57)的API35 fixture退出，再推进真实通道、指定乐跑版本与服务器闭环，vivo/纯接口独立研究。旧[七任务](superpowers/plans/2026-10-19-next-stage.md)和[资源计划](superpowers/plans/2026-10-19-resource-guided-adaptation.md)保留历史基线，不再重派已接受的#39/#40。

用户已指定优先北碚一、二、四运动场的OSM/高德/腾讯地图输入。Codex已取得三条OSM跑道并生成本地RouteProfile候选；[#69真实回放](qa/2026-10-19-map69-retest.md)发现原XML超过2MB限制及两类Windows新增测试失败，已交Dot修订，暂不合并。保留来源链的派生XML/GeoJSON各三条导入通过，不豁免原文件失败。高德精度受限、腾讯无结果，尚未完成三源交叉核验；[#64](https://github.com/Maximora-byte/swu-happyrun/issues/64)、学校规则和真实记录门槛保持独立。

## 已合入 main

| 范围 | PR / 准确 HEAD | 独立验收 |
| --- | --- | --- |
| C0/L0与verify_only结构修复 | [#17](https://github.com/Maximora-byte/swu-happyrun/pull/17)，`6ed02c29924ccc3ab26c028fbf46d15477d84eb0` | Windows Python3.11.16：112 tests、Schema、Ruff、构建、core-only干净安装通过 |
| C1恢复/归属/记录会话契约 | [#19](https://github.com/Maximora-byte/swu-happyrun/pull/19)，`a82e4d97a5a7e1de5112eabeecac6e97312089a7` | Windows Python3.11.16与3.13.15各163 tests通过；3.11的Schema、Ruff、构建、干净安装通过 |
| 原始50项服务器验收设计 | [#12](https://github.com/Maximora-byte/swu-happyrun/pull/12)，`cd508ceb0e75b8615213e0f9054cfe848b6493cc` | 文档审核；[原始矩阵](server-test-matrix.md)保留当时基线，不是产品通过记录 |

以上使用merge commit保留依赖祖先关系，合并后基线为 `aa1cced50dbe3356607067e90d127dc699ce58ea`。旧 #13 由修复后的 #17 替代关闭。接入 #1、共享模型 #2、只读探测 #3、契约 #14 已按上述有限范围完成。**main尚未合入服务器、执行代理、网页或Android产品实现。**

## 候选和阻塞

- [#25](https://github.com/Maximora-byte/swu-happyrun/pull/25) `77494e21756e514f53e51b3a2c72f22555f0aae6` 包含 #17–#34 的全部祖先提交，无需逐个重复集成；保持未合并。
- [#35](https://github.com/Maximora-byte/swu-happyrun/pull/35) 的原 CI/TLS 修订为 `28871b2d599a8ec8335570effb3207d2564639ab`；#39/#40合入原候选后为 `2d0fcc550f9c1f6cf8cc6e0106dcafd106cf181a`，整个产品仍待接受。采用版本须重新核对实际 HEAD。
- [#39](https://github.com/Maximora-byte/swu-happyrun/pull/39) `5d52d78acf6d0f7e7064e1209810746dd05b93d7`：独立接受，merge `0bb9344ddefe8054177101583282c57f27f5b38a` 到原候选分支；[#37](https://github.com/Maximora-byte/swu-happyrun/issues/37) 已关闭。冲突整批回滚、合法精确映射与重传通过；非阻塞错误列断言已交 Dot 改进。
- [#40](https://github.com/Maximora-byte/swu-happyrun/pull/40) 新修订 `8aef593dd89ca47d63a702ee1cf6952382169bbd`：独立恢复正反例通过，相关222项通过/1权限skip，已合入原候选；[#36](https://github.com/Maximora-byte/swu-happyrun/issues/36)关闭。旧69182c7失败保留在历史QA报告。
- [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46) 最近完整Windows复测仍为 `6dda2a4e74e40b92387bcbede2ec4db28abb7662`：1193通过/16跳过/2警告，不算真实JVM接受；#62未合入。Dot集成#68实验的新联网候选 `8f9f3351ee2d297f58c55b8b1c1dcf31ff33ff17`，API35首个completed在hello_begin失败，fixture本次closed，其余14项协议通过；未到连续前台及两组恢复。#57仍开放，完整候选保持Draft；不由本次cleanup正常豁免此前two_jobs退出失败或[历史e490问题](https://github.com/Maximora-byte/swu-happyrun/pull/46#issuecomment-6262758607)。
- [#55](https://github.com/Maximora-byte/swu-happyrun/pull/55) `98057f986bef87138385d5643d91d19a2bc10aac`：普通Windows账户全套1093通过/15精确跳过，合入原候选merge `5eb00e27f59a7fe927dff389e4cdd6d8d8665a55`，#52关闭。
- [#56](https://github.com/Maximora-byte/swu-happyrun/pull/56) `090f7eea6479cd5ce094741b4730aec6697543dd`：原失租复现零写入；组合全套1125通过/15跳过，tree与最终merge `f705f91409df88df9614aa4dd53c136dd00ed8a0`一致，#53关闭。两修复的Android CI仅build/static，runtime未授权/未执行，不计设备通过。
- [#65](https://github.com/Maximora-byte/swu-happyrun/pull/65) `c7e260b7eafe58d06277afc106f167db5dd3a2ba`：Windows聚焦39通过/1skip、准确HEAD全套1177通过/16skip；同源新APK普通/optional实际入口共14项正反例符合预期，实际dump139仍exit1。合入原候选merge `6dda2a4e74e40b92387bcbede2ec4db28abb7662`，#58按自身采证范围关闭。
- [#62](https://github.com/Maximora-byte/swu-happyrun/pull/62) `7aeddd4cd21df8adeb78154e2c50d74404e4afba`：原普通Windows/Python3.11.16/JDK25复测31通过/1失败；真实javac stderr214字节被准确拒绝为invalid_utf8，JVM声明stderr.encoding=GBK。未改系统/flags/预算，未合并，#59开放；托管绿灯不能覆盖。
- [#69](https://github.com/Maximora-byte/swu-happyrun/pull/69) `a0916d6b418138ab07c5df31657d1714833811ae`：普通Windows聚焦155通过/1失败/2错误/1权限skip，exit1；真实2,898,661-byte冻结XML三场地均input_too_large。新增大参数ID超Windows限制、测试默认GBK读取UTF-8报告均已交Dot；不合并，#64开放。六次派生诊断导入通过不代表原文件或与8f9组合已接受。
- #25准确HEAD的四项Android CI失败未获豁免；#35新push与PR事件必须分别核对，旧绿灯不覆盖新失败。

## 最新独立证据

最新回执见[#69真实地图与8f9联网](qa/2026-10-19-map69-retest.md)和[#62/#65复测与#63诊断](qa/2026-10-19-tools-retest.md)；早先证据保留在[e490 MuMu现场](qa/2026-10-19-mumu-field-acceptance.md)、[39/40复测](qa/2026-10-19-fix-retest-mumu.md)和[夜间成果报告](qa/2026-10-19-overnight-review.md)。以下旧数量均是各自历史源码结果，不是当前候选验收数量。

- e5b Windows/Python3.11全套：688 passed、7 skipped、2 failed；两项是本机symlink夹具的WinError1314，未改系统权限，未计为全绿。
- 安装/Schema/Ruff/构建/分发隐私、真实TCP fake路线完成和服务重启通过。28871b2的Python3.13 TLS专项6项通过；本机浏览器实际12组通过。
- #39 Windows/Python3.11 的 contracts/server/HTTP 协议 269 项通过；初版 #40 聚焦 Python3.13 为 211 passed / 1 deselected。本地组合 e62c1af 为 709 passed / 7 skipped / 2 deselected；不将已知权限夹具排除视作其断言通过。新 #40 的四项补充测试通过，但不覆盖失败的完整重绑定路径。
- MuMu6.8.4.0 / Android15 API35、#25 普通 APK：8 秒 20 米本地模拟完成、完成后重启、进程中断后 needs_attention、不自动重跑、待处理任务确认停止及持久化均已现场核对。运行中直接停止仍待稳定测试入口验收；uiautomator 非零退出保留为工具异常。本机 apksigner 独立 v2/证书核验通过。执行能力仍为空，MuMu/ADB身份映射未验证。
- 本轮新建独立MuMu15验收实例，保留原实例。e490同构建普通/可选app/test配对、哈希与证书核验通过；各30项instrumentation通过，包含运行中直接停止、重复start不重叠、存储故障、进程恢复与实际窗口观测。两版不调用instrumentation的界面完成/重启/中断/不重跑/待处理停止通过；同签名升级保留两条合成记录。另三项实际错签名/task/display准确拒绝。只读采样仍blocked、capabilities=[]；物理执行、联网恢复与学校记录未接受。uiautomator139/135和Windows输出解码告警已交#58/#59。
- 未修改Root/框架配置、系统位置/传感器或生产环境。实际步道乐跑、vivo、学校配置与最终有效记录均未验收。

## 剩余任务

| Issue | 下一步 |
| --- | --- |
| #4 S0 | 已有#18/候选实现；按C1兼容的最终组合验收，不任意拼装旧S0与新模型 |
| #5 S1 | #37 已在候选修复并关闭；最终组合继续保留租约/fence/取消/记录绑定回归 |
| #6 S2 | #25真实容器CI有成功证据；依赖S1修复与最终组合验收，本机Docker daemon未运行 |
| #7 L1 | 合成profile/fake/离线转换有实现；已取得MuMu6.8.4.0 location/gyro帮助，真实读回/停止/坐标语义仍缺实现和验收，不能由命令帮助授予能力 |
| #8 L2 | #40模拟恢复已接受；真实驱动接入与恢复继续按新计划任务2–4验收，不新增不确定start/upload |
| #9 L3 | 一/二/四运原XML三条均因#69上限拒绝；六次派生导入通过，Dot修输入路径和Windows测试，#64继续开放。高德/腾讯、精确应用版本、正式规则、本人会话和脱敏页面仍待核验，真实适配及记录独立接受 |
| #10 I0 | #52/#53/#58已按范围接受；MuMu自身离线模拟通过，#62原账户失败/#59及8f9首次hello失败/#57仍阻塞完整候选，连续前台和两组恢复未补齐；真实闭环另按任务2–4验收 |
| #11 R0 | vivo无Root/真实业务纯接口没有有效执行证据，不由fake或其他学校协议推断支持 |
| #16 冲刺 | 保持开放；软件、设备与学校记录分别验收 |

旧分工和阶段事实从Git历史、[冲刺交接](handoffs/2026-10-18-dot-lead-sprint.md)及原Issue/PR回执追溯；不以历史“未接单/无代码/实例停止”覆盖今日观测。
