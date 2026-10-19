# 协作状态

更新：2026-10-19（Asia/Shanghai）。Dot 主导实现和修复；本地 Codex 负责独立测试、设备观测和集成审核。本轮只使用 GitHub，没有发送 Matrix 消息。

## 下一轮执行入口

[e490后续设备交付计划](superpowers/plans/2026-10-19-post-e490-device-delivery.md)为最新接续：#52/#53/#58/#59已分别按范围接受；MuMu普通/可选版各30项历史离线流程通过，vendor139/135仍保留。新[#62](https://github.com/Maximora-byte/swu-happyrun/pull/62)和[#69](https://github.com/Maximora-byte/swu-happyrun/pull/69)已完成原账户真实JDK及原始XML验收并合入候选，详见[本轮回执](qa/2026-10-19-map-jdk-acceptance.md)。Dot继续收尾[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57)间歇失败诊断，推进真实通道、指定乐跑版本与服务器闭环；Codex接续冻结构建的MuMu现场验收，vivo/纯接口独立研究。旧[七任务](superpowers/plans/2026-10-19-next-stage.md)和[资源计划](superpowers/plans/2026-10-19-resource-guided-adaptation.md)保留历史基线，不再重派已接受的#39/#40。

用户已指定优先北碚一、二、四运动场的OSM/高德/腾讯地图输入。#69/ba6使用未裁剪的2,898,661-byte原XML三场地正式导入均通过，原hash、点序/节点版本摘要及revision一致；两类Windows新增测试失败也已修复并实际复测。[旧a091失败](qa/2026-10-19-map69-retest.md)保留，不由旧派生诊断覆盖。高德精度受限、腾讯无结果，尚未完成三源交叉核验；[#64](https://github.com/Maximora-byte/swu-happyrun/issues/64)、学校规则和真实记录门槛保持独立。

用户确认暂时没有现成材料后，已授权安装并取得**步道乐跑4.3.1(231) / com.lptiyu.tanke**的MuMu现场版本：官方应用宝渠道、签名检查、安装APK读回hash及首次启动/未登录页观察完成。仅登录前截图留本机，XML dump139未接受；未登录、认证、开始跑步或上传，实例已恢复停止并保留安装。详见[四项适配输入盘点](qa/2026-10-19-adaptation-input-inventory.md)。当前学期正式规则、本人业务页面/记录、高德/腾讯精确来源仍缺失；三条OSM路线未重采，不阻塞独立软件交付。

MuMu HTTPS最新接续：#75/0cea241的新validator对原完整bundle真实SDK检查及模块公有预检通过，#76/288ab69相关聚焦301通过/4权限skip/6 subtests通过，exit0。#75已按工具范围合入候选merge839faf8，#80按CRLF修复范围关闭。本次运行产品仍冻结9534，原APK/CA及来源manifest不变；真实首例已启动fixture/instrumentation，但Java guard第91行task.baseActivity为null失败，Android hello尚未发送，其他五例not_run，已交[#82](https://github.com/Maximora-byte/swu-happyrun/issues/82)。详见[第三轮现场回执](qa/2026-10-19-local-mumu-https-retest-v3.md)。#76暂不接受，#57/#78继续开放，#74/#77未叠入受测产品，所有实例已恢复停止。

历史[首轮201通过/1失败及guard阻塞](qa/2026-10-19-local-mumu-https-attempt.md)与[第二轮271通过/1失败及CRLF阻塞](qa/2026-10-19-local-mumu-https-retest-v2.md)完整保留；本轮有限通过不覆盖旧失败或代表整体验收。

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
- [#46](https://github.com/Maximora-byte/swu-happyrun/pull/46) 最近完整Windows组合仍对应 `9534f51efe3a557e6b4bda5605426e4004a34783`：已含#62/#69，1298通过/17平台权限跳过/1既有依赖警告，最终tree与本地完整受测组合一致。当前候选已加#75工具merge `839faf87cb0180f0732f2ef4278e4944bf1ccf70`，不将旧全套写成此新树重跑结果。4c已有授权API35归档的协议15/UI3/前台14及两组恢复通过仍仅属其原范围；本机MuMu首例被#82阻塞。#57旧间歇失败未逐项定因，保持开放，完整候选仍Draft，不抹去[历史e490问题](https://github.com/Maximora-byte/swu-happyrun/pull/46#issuecomment-6262758607)。
- [#55](https://github.com/Maximora-byte/swu-happyrun/pull/55) `98057f986bef87138385d5643d91d19a2bc10aac`：普通Windows账户全套1093通过/15精确跳过，合入原候选merge `5eb00e27f59a7fe927dff389e4cdd6d8d8665a55`，#52关闭。
- [#56](https://github.com/Maximora-byte/swu-happyrun/pull/56) `090f7eea6479cd5ce094741b4730aec6697543dd`：原失租复现零写入；组合全套1125通过/15跳过，tree与最终merge `f705f91409df88df9614aa4dd53c136dd00ed8a0`一致，#53关闭。两修复的Android CI仅build/static，runtime未授权/未执行，不计设备通过。
- [#65](https://github.com/Maximora-byte/swu-happyrun/pull/65) `c7e260b7eafe58d06277afc106f167db5dd3a2ba`：Windows聚焦39通过/1skip、准确HEAD全套1177通过/16skip；同源新APK普通/optional实际入口共14项正反例符合预期，实际dump139仍exit1。合入原候选merge `6dda2a4e74e40b92387bcbede2ec4db28abb7662`，#58按自身采证范围关闭。
- [#62](https://github.com/Maximora-byte/swu-happyrun/pull/62) 新 `6afecb02a553d2aa8ae0f8e72dd27ac1e9864bde`：原普通Windows/Python3.11.16/Oracle JDK25聚焦47通过无skip，3.13聚焦+契约168通过；真实javac中文279-byte严格UTF-8通过，系统默认GBK未改，拒绝逻辑/预算保留。合入候选merge9534f51，#59关闭；旧7aed的31pass/1fail及214-byte拒绝保留历史。
- [#69](https://github.com/Maximora-byte/swu-happyrun/pull/69) 新 `ba6d37d989126afe86787312e72685610c6a250e`：原完整XML三路线API/CLI通过；普通Windows/Python3.11和3.13聚焦各162通过/1symlink权限skip，原大参数/GBK测试失败已实际消除。合入候选mergec4118d5，#64整体继续开放；旧a091的155pass/1fail/2error及派生诊断保持原记录。
- #25准确HEAD的四项Android CI失败未获豁免；#35新push与PR事件必须分别核对，旧绿灯不覆盖新失败。

## 最新独立证据

最新回执见[#69原始地图/#62真实JDK接续接受](qa/2026-10-19-map-jdk-acceptance.md)；此前[#69真实地图与8f9联网](qa/2026-10-19-map69-retest.md)、[#62/#65复测与#63诊断](qa/2026-10-19-tools-retest.md)及[e490 MuMu现场](qa/2026-10-19-mumu-field-acceptance.md)、[39/40复测](qa/2026-10-19-fix-retest-mumu.md)、[夜间成果报告](qa/2026-10-19-overnight-review.md)保留历史。以下旧数量均是各自源码结果，不是当前候选验收数量。

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
| #9 L3 | #69已接受原XML三条离线导入；步道乐跑4.3.1(231)已在MuMu安装/读回/登录前观察，XML139未接受。#64剩高德/腾讯正式来源和交叉核验；正式规则、本人会话及业务记录样本仍缺，真实适配及记录独立接受 |
| #10 I0 | #52/#53/#58/#59已按范围接受；MuMu历史离线自身模拟通过，4c托管API35协议/前台/两组恢复本次通过，旧间歇失败#57及本机MuMuHTTPS仍待闭环；完整#46保持Draft，真实闭环另按任务2–4验收 |
| #11 R0 | vivo无Root/真实业务纯接口没有有效执行证据，不由fake或其他学校协议推断支持 |
| #16 冲刺 | 保持开放；软件、设备与学校记录分别验收 |

旧分工和阶段事实从Git历史、[冲刺交接](handoffs/2026-10-18-dot-lead-sprint.md)及原Issue/PR回执追溯；不以历史“未接单/无代码/实例停止”覆盖今日观测。
