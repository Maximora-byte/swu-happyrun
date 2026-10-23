# 2026-10-23 RC3 本地交付验收

## 交付结论

交付 `HappyRun-Local-0.2.0rc3`：中文本机工作台、离线安装启动器、独立合成任务、MuMu 实际定位与轨迹、配套自身观察 APK、暂停/继续、停止确认和中断后显式停止恢复。已安装后的工作台、MuMu 定位及托管 CI 分别验收。**智慧体育小程序实际运动和学校有效记录未完成，本报告不是完整学校业务验收。**

本机文件为 `dist/HappyRun-Local-0.2.0rc3.zip`，4,371,963 字节，SHA256：

```text
a2c9f4dc95c08f73eb1641de1110079eb5e884444d66c47537d0460c718807fe
```

ZIP 内含 39 个清单文件与 `SHA256SUMS.json`，CRC 及逐文件摘要通过；19 个 wheel 离线安装成功，98 个已装项目文件与 wheel 一致。包内含自身配对 APK、中文说明和本机私有路线，不含第三方 APK、账号、原始截图、数据库、journal、已安装 `.runtime` 或虚拟机备份。路线不是学校官方打卡点。

Windows x64 已装 Python3.13 的用户解压后运行 `Start-HappyRun.cmd`。已有服务运行时使用原浏览器会话；需要重启时先在服务窗口按 Ctrl+C，待受控退出后再运行启动器。MuMu 安装与操作见 [工作台说明](../desktop.md) 和 [MuMu 工具说明](../mumu-desktop.md)。启动器与定位功能不要求或设置 Root。

## 固定源码与集成

| 对象 | 不可变标识 |
| --- | --- |
| wheel / APK 产品源码 | `31b5d40865c92daff5ef9bc78d77ac1d950dd224` |
| 产品 `src` tree | `033645d56148a9d0c1e3c73b2988228d7e4b2bd9` |
| 产品 `android` tree | `f403669074698732258af54cdbbf6b2af7bb3372` |
| PR114 最终接受 head | `adef79812a3aa745611fcaf52a7a5fd65d8c4ea4` |
| PR114 合并提交 | `3c80b1373256b08f59243b35fb83fdce04d989b0` |
| head 与合并的相同整树 | `85fd7bf0ca0d9d16f59a9242c548fe761273c1e6` |

[PR114](https://github.com/Maximora-byte/swu-happyrun/pull/114) 合入 `dot/trusted-runtime-context`，不是 main。最终 head / 合并的 `src` 和 `android` 与产品源码相同；后续 CI 字体和文档变化不伪称重新构建了 wheel / APK。原包 `source.json`、`CI验收.json` 及安装验收文件保留这一关联。

## 实际安装、浏览器和 MuMu

Windows / Python3.13.15；MuMu6.8.4.0，Android15 / API35，专用 QA 实例 #5。

| 范围 | 结果及限制 |
| --- | --- |
| 实际安装 | 完整包校验、离线 wheel 安装、98 个文件一致、版本 0.2.0rc3、健康/就绪/工作台 HTTP200 |
| 已装代码 Chromium 工作台 | 5 项通过：服务与代理就绪、双击只创建一次并完成、刷新保持历史、运行取消须等确认、窄屏无溢出或脚本错误 |
| 已装代码 Chromium MuMu 面板 | 9 项通过；使用拦截的合成回执，生产控制器未实例化，不是设备证据 |
| RC3 自身探针、无 Root 基线 | 起点→分离点→起点，三次写入均新鲜读回；相同起点再次启动；系统设置前台期间持续写入，共 14 次，最大误差 0.8817081743346872m |
| 暂停/继续与停止 | 暂停稳定窗口写入 11→11，继续后推进；停止回执确认，自身定位前台服务注销 |
| 用户另行授权的 Root 环境 | 同一产品在 VM5 Root 后 14 次写入，最大误差 0.9114971648526398m，暂停/继续、停止确认通过；无第三方模块，未操作微信 |
| 历史 RC2 故障证据 | 完整 421.476m / 116 次写入和进程中断后 5→5 无自动重放、显式匹配实例停止已通过；这是前一版本证据，不称 RC3 重新跑了完整路线或中断试验 |

自身前台服务只在 SELF_PROBE 构建启用，非导出、普通 location 前台服务、无后台定位权限和自动重启。普通构建的权限/服务边界保持不变。真实设备成功只证明本工具写入、新鲜读回和停止，不证明第三方应用采纳位置或服务端接受成绩。

Root 环境前先对停止的 VM5 做离线副本，33 个文件、3,269,241,083 字节逐文件 SHA256 一致；恢复未演练。官方 export 两次失败不能计为成功备份；临时创建的自有克隆已核对身份并删除。副本及原始证据私存，未进入 Git 或产品包。系统盘只读设置保留。

## 软件与托管检查

RC3 产品源码的 Windows/Python3.13.15 组件与契约检查 275 项通过（47.27 秒）；另有 14 项 CLI/包/version/manifest 检查通过。Java 辅助检查 35 项、Android 离线配对构建、普通构建、unit/lint、实际 APK 静态边界及签名检查通过。Ruff、Schema、构建和分发隐私检查通过。原始命令/退出结果保存在本机私有 `local/budao-foreground/`，不提交原始页面或账号资料。

[PR113](https://github.com/Maximora-byte/swu-happyrun/pull/113) 修复完整回归的低效大缓冲读取并保留文件身份、增长和短读校验；本机 3121 个唯一用例分片后 3030 通过、91 个既有条件跳过，另 6 个 subtest，无失败。此结果属于 PR113 的固定树；RC3 的完整 Python 组合由下列准确 CI 检查覆盖。#110 的原机 Python3.11 AV 未因 CI 成功而关闭。

PR114 首轮浏览器 job 在 Ubuntu 镜像字体下载处超时，断言未执行。最终 head 将字体改为官方 Noto 固定提交的单文件，SHA256 核验、有限重试及字体匹配后运行原全部断言；保留 20 分钟 job 上限。首轮失败仍为失败历史。

| 固定 commit / 事件 | checks | container-smoke | 结果 |
| --- | --- | --- | --- |
| `adef798` push | [39944915939](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39944915939) | [39944916327](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39944916327) | 13+1 个 job 成功 |
| `adef798` PR114 | [39944921427](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39944921427) | [39944921328](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39944921328) | 13+1 个 job 成功 |
| `3c80b13` push | [39948521081](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39948521081) | [39948521072](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39948521072) | 13+1 个 job 成功 |
| `3c80b13` PR109 同步 | [39948527688](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39948527688) | [39948527684](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39948527684) | 13+1 个 job 成功 |

合并前 28 个、合并后 28 个 job 均为 completed/success；合并后的 PR 事件属于仍开放的集成 PR109，不是已合并的 PR114。两个阶段每个浏览器 job 原 12 项场景通过。Android build/static job 中依原授权门禁跳过的官方 emulator runtime / optional framework 验证保持未运行，不能把 job 成功外推为 runtime 通过。原生 MuMu 证据单列于上表。

## 尚未完成

- 已安装官方来源核验的步道乐跑4.3.1 /231 和微信8.0.79 /3200；用户登录后看到智慧体育的校园乐跑入口与学期规则，随后会话不可用，用户暂不能重新登录，并报告外挂/模拟器环境提示。没有启动或上传学校跑步记录。实际小程序轨迹、打卡点、结束与有效记录仍未验收，不安装反作弊绕过模块。
- 旧 native CLI/enrollment 的执行门禁、#110 的 AV/未知配置读回、其他 MuMu/Android 组合、vivo 与纯接口均保持各自原始未验收状态；本地交付不解除这些限制。
- 无生产部署、DNS 或现有服务器修改。不能根据本包验收直接合并全部历史集成到 main，或关闭所有学校业务 Issue。

控制协议 v1、可恢复 `needs_attention`、取消须停止确认和未知能力拒绝启动的约束保持不变。后续验收继续按准确源码、具体运行环境、设备读回和第三方有效记录分别记录。
