# 2026-10-19 夜间成果独立验收

执行：本地Codex，Windows/PowerShell；Dot负责产品实现和修复。原始设备导出、截图、数据库、私有状态和日志留在Git忽略的本地目录。本报告不声称学校有效记录或完整兼容。

## 版本与决定

| 对象 | 准确提交 | 决定 |
| --- | --- | --- |
| C0 #17 | `6ed02c29924ccc3ab26c028fbf46d15477d84eb0` | 合入，merge `dc1c041a84118ab0de85df4cf5bfc74d0d05ec91` |
| C1 #19 | `a82e4d97a5a7e1de5112eabeecac6e97312089a7` | C0后合入，merge `6c588296f807e0a1f24c0fc216e281fd5642d6a7` |
| 测试设计 #12 | `cd508ceb0e75b8615213e0f9054cfe848b6493cc` | 文档合入，merge `aa1cced50dbe3356607067e90d127dc699ce58ea` |
| 集成 #25 | `77494e21756e514f53e51b3a2c72f22555f0aae6` | #17–#34均为其祖先；保持未合并 |
| Android增量 #35首次 | `e5b3b973f9e055fc8bcb4a9e3261cf6320568787` | 本轮源码评审和Windows完整套件版本 |
| #35 CI/TLS修订 | `28871b2d599a8ec8335570effb3207d2564639ab` | 9文件差异，无Python生产模块修改；仅有下述追加检查 |

独立只读评审覆盖共享/服务器、Python代理、Android三个范围。已确认两项P2并登记[#36](https://github.com/Maximora-byte/swu-happyrun/issues/36)、[#37](https://github.com/Maximora-byte/swu-happyrun/issues/37)，阻塞产品集成，不阻塞单独C0/C1契约验收。未观察到这两个触发条件导致重复开始或错误授予设备能力，但仍须修复。

## 实际执行

uv0.12.19。下表python均为该行环境的明确虚拟环境解释器。

| 版本 / 环境 | 命令和范围 | 实际结果 |
| --- | --- | --- |
| 6ed02c2 / Windows Python3.11.16 | `uv sync --all-extras --frozen`；`python -m pytest -q` | exit0，112 passed |
| 6ed02c2 / 同上 | `python scripts/export_schema.py --check`、`ruff check .`、`ruff format --check .`、`uv build`、`python scripts/check_install.py` | 全部exit0，源码外core-only新环境不含FastAPI/HTTPX |
| a82e4d9 / Windows Python3.11.16 | 同组安装、全套、Schema、Ruff、build、干净安装 | 全部exit0，163 passed |
| a82e4d9 / Windows Python3.13.15 | 冻结安装；`python -m pytest -q` | exit0，163 passed |
| e5b3b97 / Windows Python3.11.16 | 冻结安装；`python -m pytest -q --junitxml=...` | **exit1，688 passed / 7 skipped / 2 failed**，124.29秒，1条继承Starlette warning |
| e5b3b97 / 同上 | Schema、Ruff、`uv build`、`scripts/check_distribution_privacy.py`、core-only干净安装 | 全部exit0 |
| e5b3b97 / 同上 | `python deploy/smoke_fake.py` | exit0，真实回环TCP、fake路线端点完成、幂等、查询、重启持久化/凭据脱敏共10项 |
| e5b3b97 / Windows OracleJDK25.0.4.1，source/target17 | 临时目录编译非Android依赖的Java/JUnit | exit0，73 tests；不是ART |
| e5b3b97 / JDK及Python3.11 | `scripts/check_remote_protocol_interop.py <隔离classpath>` | exit0，16双向case和3出站载荷；先前全局Python缺pydantic的失败未算通过 |
| e5b3b97 / Windows Python3.13.15 | `python -m pytest tests/delivery/test_remote_https_fixture.py -q` | exit1，1 failed/4 passed，CA缺keyUsage，和准确HEAD托管CI一致 |
| 28871b2 / Windows Python3.13.15 | 同TLS专项 | exit0，6 passed，1.76秒，保留严格证书验证 |
| 28871b2 / Windows Python3.11.16，Chrome for Testing156.0.8078.4 | `HAPPYRUN_CHROMIUM_EXECUTABLE=<已安装浏览器>`；`python scripts/check_console_browser.py --output-dir <私有目录>` | exit0，12组实际桌面/手机视口验收通过 |

Windows全套失败为 `test_broken_state_symlink_is_not_fresh_state`、`test_profile_resolution_fail_closed[symlink]`，均在创建链接时出现WinError1314。没有改变权限或删断言；此结果不是全套通过。跳过3项POSIX信号、4项Bash harness。浏览器关闭连接时另出现一次Windows asyncio ConnectionResetError回调诊断，但断言和结果文件全部通过。最初浏览器启动因锁定版本的缓存缺失而失败，随后显式指定本机已安装浏览器复跑；未冒称使用锁定Chromium151。

### 可复现的产品问题

- [模拟恢复复现](reproductions/repro_finished_recovery.py)：候选解释器运行 `python -B docs/qa/reproductions/repro_finished_recovery.py --source-root <准确候选checkout> --expect-recovery-completed`，e5b3b97 **exit1**。fake已走完且停止，恢复仍为needs_attention/verification_pending；start/tick/stop计数各1，未增加开始或上传。默认模式exit0只表示复现前提成立，不是验收通过。
- [探测批次复现](reproductions/repro_probe_batch.py)：安装准确候选server代码的环境运行 `python -I docs/qa/reproductions/repro_probe_batch.py`，e5b3b97 **exit0复现缺陷**：首次200、相同重传409，只有第一个设备被更新；预期首次409且整批无写入。只用合成凭据与临时SQLite。

格式整理后，两份提交的复现脚本也已对28871b2复跑：probe脚本exit0复现相同缺陷；恢复脚本预期completed断言exit1，start/tick/stop仍各1。

脚本用于审核指定候选，不要求仅有C0/C1的main已经提供server/agent。不得向main复制未经审核产品模块来满足复现依赖。

## MuMu现场

MuMu6.8.4.0、索引0、Android15/API35。开始时实例停止，本轮启动后连接ADB。

- #25准确push run39196819883的普通APK artifact12162577508，实测SHA256 `e362b935ca058b6c7799b299f8bca458bca30ca7728e54f4971778628bf9f69e` 与包内清单一致。
- 该CI的签名报告v2验证通过，debug证书SHA256 `1db755f3b392173f2ffc9cc2c0c74ee68a408b7608c7f4a152817e8d609b2923`。本机无独立apksigner复核，签名验证来源明确为CI报告。
- 首次安装成功；MainActivity冷启动Status=ok，首次TotalTime449ms，中文向导可见。没有覆盖已有安装或卸载数据。
- a82e4d9运行 `python -m swu_happyrun.drivers.mumu.discovery --json --index 0 --manager <明确路径> --adb <明确路径> --serial <明确连接> --package org.happyrun.app`：exit0，观察自身APK版本0.1.0-candidate，capabilities为空，MuMu/ADB身份映射未验证。
- 完整模拟UI自动化**未通过**：MuMu给应用分配额外显示器，输入和默认导出窗口不一致；uiautomator也出现写出XML后退出139。新文件核对仍不能让点击后状态断言通过，未认定为应用逻辑缺陷，不声称模拟完成/停止/中断恢复通过。测试后force-stop自身测试应用，保留安装与数据。

只确认普通APK安装/首屏、只读库存。Root检查未点击，Root/框架配置未改；未写系统位置/传感器，未登录、运行或上传实际步道乐跑。远程HTTPS、MuMu完整模拟、vivo和学校记录继续独立验收。

## CI、部署与后续门槛

C0/C1准确HEAD的Ubuntu/Windows×Python3.11/3.13 push/PR均成功后才合并。#25准确HEAD的Python/浏览器/真实容器CI成功，但四个Android作业失败，组件旧绿灯不覆盖此结果。#35首次的Python3.13证书失败、HTTPS workflow初始化失败保留为历史；28871b2定向修复。本轮最终读取28871b2：push的Android四组及remote-https API31/35成功；PR事件的android-apk/API31、API35和android-self-probe/API31、API35均失败。没有将push成功覆盖PR失败，也没有盲目重跑或修改KVM权限。

本机Docker CLI存在但daemon未运行，未启动Docker Desktop或部署生产。容器运行证据来自对应Actions。本轮无Release、服务器/DNS/安全设置修改。

Dot先修#36/#37，并处理准确HEAD Android CI与新增INTERNET后的权限文档漂移；提供一个说明/HEAD一致的最终候选。Codex复测修复、不可变HEAD与各门槛后再作集成决定。实际应用版本、学校规则和本人会话由#9/#11追踪，软件测试不能代替这些输入。
