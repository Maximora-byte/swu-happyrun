# 候选 628c23d：Windows 本机构建、安装与只读调查

日期：2026-10-20，Asia/Shanghai。Codex 独立接受；Dot 继续负责产品实现。以下证据固定到候选分支，不表示这些产品增量已经合入 main。

## 准确来源

- 产品：`628c23da47a6e1a9bde5a917568e8cbf5f99b7cd`，tree `b8805236b46f79fe278bb3ce4c1a25af4598e788`，`dot/recheck-candidate`。
- #97 原始捕获/私有存储此前已接受；本轮接受 [#98](https://github.com/Maximora-byte/swu-happyrun/pull/98#issuecomment-6286214002)、[#99](https://github.com/Maximora-byte/swu-happyrun/pull/99#issuecomment-6286305164)。#99 受测 HEAD `7ed95fef37c2370853251fb6c6322c022a045322` 的文件树与候选完全相同。
- 本机 schema2 构建/校验工具独立固定为 `726ed1ebc6b668cf9f662b4df4ca6ecd5c17c318`（#93）；产品及 Java adapter 来自上述 628c23d。没有手工覆盖 adapter、修改校验器或将旧产物重标。
- 原机 Windows `10.0.26200`、非提权账户，Python 3.11.16 / 3.13.15、Temurin 17、Android SDK 35；未改 Root、系统信任、全局网络或生产服务。

## 软件复核与 CI

| 准确 HEAD | Windows 3.11 完整 pytest | Windows 3.13 专项 | 其他检查 |
| --- | --- | --- | --- |
| #98 e0907d7 | 1928 passed / 53 skipped / 6 subtests passed，280.18s | 309 passed / 4 skipped，12.71s | Ruff、283 文件 format、schema |
| #99 7ed95fe | 1993 passed / 55 skipped / 6 subtests passed，271.71s | 310 passed / 6 skipped，10.41s | Ruff、287 文件 format、schema |

以上 exit 均为 0，完整套件均有一条既有 warning。skip 原因详见逐 PR 回执，包括 Windows 信号/符号链接权限、POSIX 专项和 JDK19+ 流检查，不计为通过。tree 未变，不以重复跑相同全套替代新增的安装验收。

#97–#99 三个准确交付 HEAD 的 12 次工作流均 success。本轮合并 SHA 的 [checks / 39390127042](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39390127042) 九 job 及 [container / 39390127007](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39390127007) 也已成功，独立于各 PR HEAD 的绿灯。Android job 名称包含 conditional runtime，不据此追加原机或未执行 runtime 的验收结论。

## 本机交付与安装

以新的私有输出目录运行固定 #93 工具：

```console
python -m build_local_https_delivery --source-root <PINNED_628_CHECKOUT> --expected-source-commit 628c23da47a6e1a9bde5a917568e8cbf5f99b7cd --expected-source-tree b8805236b46f79fe278bb3ce4c1a25af4598e788 <LOCAL_CERT_AND_SDK_ARGUMENTS>
python -m check_local_https_delivery <SAME_SOURCE_AND_BUNDLE_ARGUMENTS>
python -m check_mumu_https <SAME_SOURCE_AND_BUNDLE_ARGUMENTS> --output <NEW_LOCAL_REPORT>
```

这是带本机私有参数的命令结构，不是可直接粘贴的无配置命令。完整 argv、stdout/stderr、SDK 检查及清单均留本机。

- ordinary/selfProbe/remoteQa 三组 app/test **六 APK**及同源 wheel 构建通过：exit 0 / **142.19s**。
- 独立签名/权限/scope/测试 CA/manifest 校验：exit 0 / **15.62s**。三组同签名，wheel **67** 个包文件、metadata 和 RECORD 与准确源码一致。
- 公有 HTTPS 产物预检：exit 0 / **15.47s**，`artifact_preflight=passed`、`runtime_status=not_run`。
- 本机 wheel SHA256：`ec03f187eb15ed6655eb4729d6622ca446665ddc13443abc991cc258246d6766`。
- 独立下载 [628c23d CI Python artifact 12248964464](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39390127042/artifacts/12248964464)，ZIP SHA256 `c38bcc57d3bffd11b0d77eaa52b0fe680fab7bec5d5c6d7a728eef713295ee75` 与 GitHub digest 一致；内部 SHA256SUMS 通过。CI wheel SHA256 `50bbe68f823f6510bc2f31f95e0ec3c6a46e13d88166e6ad37687fedef6cbb8b`，同样通过 67 文件/metadata/RECORD 源码检查。两次构建字节哈希不同，分别记录，未混写 manifest。
- 从源码目录外，在全新普通账户环境离线安装：3.11 使用本机 wheel，3.13 使用 CI wheel，均逐字核对安装后的 67 包文件并以 `python -I` 确认从目标 site-packages 导入。
- 另外独立 core-only / server-only 环境均通过，均不包含 httpx 或 win32api；core 环境不含 FastAPI，server 可导入 FastAPI/Uvicorn/本项目服务端。未引入 MuMu/Windows 工具运行依赖。
- 两套安装各运行一、二、四运动场已有 OSM 路线预览，六次均 exit 0、`processes_started=0`、`record_verified=false`。没有重采路线或生成学校规则。
- 两套安装各运行 `python -I <PINNED_SOURCE>/deploy/smoke_fake.py`：**exit 0 / 6.83s、6.14s**。真实 loopback TCP HTTP 的 health/readiness、设备登记、任务创建/幂等重放、fake agent 完成/合成路线结束、查询、重启持久化和令牌脱敏十项通过；临时服务和状态收拢。使用安装后的包，不依赖 PYTHONPATH 或仓库工作目录。
- 旧完整 bundle、59b 六包及 CA/leaf/key 逐哈希未变；原 host-id 未变。新包与含本机公有 CA/服务地址的 manifest 留私有目录；六 APK 尚未安装或执行。

保留两次 QA 准备问题：扩展静态调查时重复 provision 已存在目录被正常拒绝，改用新的输出目录；首次安装核验脚本写错进程事实模块的包路径，产生 ModuleNotFoundError。仅修正 QA 导入路径后，逐字检查同一安装包再继续，未改产品源码/产物或放宽断言；原失败输出保留。

## 原机只读调查

MuMu 6.8.4.0 管理器显示四个实例均停止；该输出没有执行 PID/UUID 字段。

静态读取发现：四份当前 `.nemu` XML 均有 `Machine@uuid`，四值互异，各自与 `.nemu-prev` 一致；`Machine@name` 均对应所在实例目录。原始文件、文件身份、哈希与相关小型配置共 **20** 份记录已私有保存并复读确认未变。仅使用既有 host namespace 和产品现行 manager path/index 推导，私有计算了四个候选 device-id；未创建正式 receipt、journal 或设备锁。

除默认状态目录外，另对九个已知仓库/测试状态候选根做深度四层的有限盘点，450 文件、未截断，没有 journal/lock 候选。不能把此范围外的状态推定为不存在，也不能认定这些候选映射已经绑定历史 journal。首用与历史状态发现的实现任务见 [#100](https://github.com/Maximora-byte/swu-happyrun/issues/100)。

原生 Windows 进程查询 0.39s 返回 493 条：316 ok、176 denied、1 unknown，整体保留 partial，helper cleanup 确认。当前没有活动 MuMu 执行进程归属证据。独立同 API 核对文件身份一致；Python stat 与 legacy native volume 数值域有差异，不能混用或截断后授权。

以上静态 UUID 不是进程归属、跨重建/克隆语义或退出证明。没有为补样本启动实例；没有安装、授权、位置/传感器输入或 shutdown 操作。

## 下一步与接受范围

Dot 接续 [#100](https://github.com/Maximora-byte/swu-happyrun/issues/100)：先设计首次登记/旧状态发现，再实现只读实例归属和可审核的受控登记入口。静态身份原机证据已补对应范围，不再泛称所有工作都需等待现场材料。涉及活动样本时，先交明确的最小动作、预算和退出判据，Codex 接续独立技术核验与有界实测。

当前接受软件、构建、安装、fake HTTP 和上述只读观察；真实 MuMu 执行适配器仍未接通。关闭观察不冒充 native stop ACK/清队列，不清 reservation，不解除重启、第二次输入或连续回放限制。[#57](https://github.com/Maximora-byte/swu-happyrun/issues/57) 历史 HTTP 未明失败继续保留；vivo、纯接口和学校有效记录没有由本报告验收。
