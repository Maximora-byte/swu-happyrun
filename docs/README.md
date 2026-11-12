# 文档导航 / Documentation index

先确认你阅读的是哪一个分支。默认分支的文档、候选分支的功能和历史验收记录不能混用。
Start by checking the branch. Default-branch documentation, candidate features and historical acceptance records are not interchangeable.

## 从这里开始 / Start here

| 目的 / Goal | 入口 / Read first |
| --- | --- |
| 判断当前能做什么 / Understand available functionality | [状态入口 / Status guide](status.md)、[分支与 PR 地图 / Branch and PR map](repository-map.md) |
| 运行主分支环境诊断 / Run default-branch diagnostics | [根目录 README / Root README](../README.md)、[兼容性与诊断 / Compatibility](compatibility.md) |
| 查看独立桌面/MuMu 产品 / Find the separate desktop/MuMu product | [固定候选使用说明 / Candidate desktop guide](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/desktop.md)、[RC3 版本限定实测 / Version-bound RC3 receipt](https://github.com/Maximora-byte/swu-happyrun/blob/74d4aa3f224756d6083775bef9525feca8943e86/docs/qa/2026-10-23-rc3-delivery.md) |
| 理解协议和边界 / Understand contracts and boundaries | [控制平面 v1 / Control-plane contract](contracts/control-plane-v1.md)、[生成 Schema / Generated schema](../contracts/protocol-v1.schema.json) |
| 了解设计背景 / Understand the design | [设计说明 / Design](superpowers/specs/2026-10-18-swu-happyrun-design.md)、[设计评估 / Design review](design-review.md) |
| 准备改动 / Prepare a contribution | [贡献约定 / Agent instructions](../AGENTS.md)、[PR 模板 / PR template](../.github/pull_request_template.md)、[第三方来源 / Third-party notices](../THIRD_PARTY_NOTICES.md) |

主分支安装与诊断不代表其已包含可执行服务器或统一 CLI。另一个候选已收录桌面/MuMu 连续写入和读回的版本限定实测，不能忽略，也不能外推为最新 HEAD 或学校业务已通过。候选文档请从地图中的准确提交进入，核对对应产品源码和验收范围。
Default-branch diagnostics do not ship a server or unified CLI. A separate candidate contains version-bound desktop/MuMu write/readback evidence; neither ignore it nor extrapolate it to the latest head or school acceptance. Open the recorded commit and check the tested product source and scope.

## 目录与维护方式 / Directories and maintenance

- `contracts/`：协议文档；根目录 `contracts/` 中的 Schema 从源码生成。Protocol documentation; the root schema is generated from source.
- `qa/`：按日期、版本记录的证据，失败与通过记录均保留。Dated evidence, including both failures and passes.
- `handoffs/`：历史交接与角色背景，不是今天的待办清单。Historical handoffs, not a current task queue.
- `superpowers/specs/`：设计基线。Design baselines.
- `superpowers/plans/`：当时的阶段计划，时间目标不是已完成证明。Dated plans; deadlines are not completion evidence.
- [服务器测试矩阵 / Server test matrix](server-test-matrix.md)：测试设计，不是运行通过回执。Test design, not executed acceptance.

为保留既有链接，本轮不移动或删除历史文件。新证据使用明确日期和准确源码 SHA；新计划须区分设计目标、已实现软件和独立设备/学校记录验收。不要把历史失败改写成成功。
Historical files stay in place to preserve links. New evidence needs a date and exact source SHA. Distinguish planned work, implemented software, and independent device/school-record acceptance; never rewrite a historical failure as a pass.

## 历史交接与计划 / Historical handoffs and plans
- [2026-10-18-dot-lead-sprint](handoffs/2026-10-18-dot-lead-sprint.md)
- [dot-server](handoffs/dot-server.md)
- [2026-10-18-agent](superpowers/plans/2026-10-18-agent.md)
- [2026-10-18-development](superpowers/plans/2026-10-18-development.md)
- [2026-10-18-server](superpowers/plans/2026-10-18-server.md)
- [2026-10-19-next-stage](superpowers/plans/2026-10-19-next-stage.md)
- [2026-10-19-post-e490-device-delivery](superpowers/plans/2026-10-19-post-e490-device-delivery.md)
- [2026-10-19-resource-guided-adaptation](superpowers/plans/2026-10-19-resource-guided-adaptation.md)
- [2026-10-20-dot-virtual-run-night](superpowers/plans/2026-10-20-dot-virtual-run-night.md)

## 验收与复现目录 / Acceptance and reproduction index

下列记录只适用于各自注明的平台、版本和 SHA；不汇总为“全项目已通过”。复现脚本是历史诊断材料，不是新手启动入口。
Each record applies only to its stated platform, version and SHA. Reproduction scripts are historical diagnostic material, not beginner startup commands.

- [2026-10-19-adaptation-input-inventory.md](qa/2026-10-19-adaptation-input-inventory.md)
- [2026-10-19-fix-retest-mumu.md](qa/2026-10-19-fix-retest-mumu.md)
- [2026-10-19-local-mumu-https-acceptance.md](qa/2026-10-19-local-mumu-https-acceptance.md)
- [2026-10-19-local-mumu-https-attempt.md](qa/2026-10-19-local-mumu-https-attempt.md)
- [2026-10-19-local-mumu-https-retest-v2.md](qa/2026-10-19-local-mumu-https-retest-v2.md)
- [2026-10-19-local-mumu-https-retest-v3.md](qa/2026-10-19-local-mumu-https-retest-v3.md)
- [2026-10-19-map-jdk-acceptance.md](qa/2026-10-19-map-jdk-acceptance.md)
- [2026-10-19-map69-retest.md](qa/2026-10-19-map69-retest.md)
- [2026-10-19-mumu-field-acceptance.md](qa/2026-10-19-mumu-field-acceptance.md)
- [2026-10-19-overnight-review.md](qa/2026-10-19-overnight-review.md)
- [2026-10-19-swu-map-inputs.md](qa/2026-10-19-swu-map-inputs.md)
- [2026-10-19-swu-map-sources.json](qa/2026-10-19-swu-map-sources.json)
- [2026-10-19-tools-retest.md](qa/2026-10-19-tools-retest.md)
- [2026-10-20-candidate628-local-acceptance.md](qa/2026-10-20-candidate628-local-acceptance.md)
- [repro_finished_recovery.py](qa/reproductions/repro_finished_recovery.py)
- [repro_probe_batch.py](qa/reproductions/repro_probe_batch.py)
