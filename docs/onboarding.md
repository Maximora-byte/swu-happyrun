# 实际应用接入：最小输入与离线门槛

更新：2026-10-19。对应 [下一阶段 Task 7](superpowers/plans/2026-10-19-next-stage.md)。
本页只准备合法、只读、离线的适配输入；未取得实际页面样本，未实现该版本选择器。
当前候选的真实应用执行为 `unsupported_by_this_candidate`，实际设备/学校记录为
`not_tested`。普通 fake 或自身 APK 模拟通过不能改变这些结论。

## 本地验收者需要保留的最小证据

| 输入 | 必须明确的内容 | 缺失时 |
| --- | --- | --- |
| 精确环境 | 指定实例、MuMu 完整版本；Android/API/系统版本；vivo 型号与系统构建；目标 package、versionName、versionCode | 不从其他设备或 latest 推断 |
| 学校配置 | 学校/校区/学期与正式规则来源、发布日期；距离/时长/速度/时间窗；确认者；绑定 profile_id 与 revision | 不猜学校 ID 或默认达标值 |
| 点位 | 正式来源、获取时间与用途；明确 WGS84/GCJ02/BD09、轴顺序、单位；绑定来源及路线 revision | CRS 未知不转换、不写入 |
| 页面 | 本人已登录会话的开始、运行、结束、上传待定、有效、无效、未知/异常页面结构；绑定同一 package/version 与采样时间 | 未取得写未取得，不能用合成页代替 |
| 记录 | 稳定记录身份的语义；本次 job/session/profile/app_version 的关联依据；查询与 pending→最终状态的观测 | pending/unknown 不能 succeeded |
| 能力 | 本机帮助、实际参数与只读读回结果；位置/传感器/页面/记录能力分别报告 | 没有观测保持关闭 |

页面结构需区分“按钮存在”“按钮可操作”“当前属于哪个 task/display”。本地原截图、
XML、日志与协议原文留私有目录，不提交 Git、不上传群聊。没有某状态的样本就列为缺失，
不得为填满清单而进行真实开始、上传、重跑。读样本不授权执行写入。

## 脱敏与交付

1. 在本地移除账户、姓名、学号、电话、真实设备 serial/唯一标识、token、Cookie、
   Authorization、密码、签名值及查询串秘密。仅替换可见文字不足以处理 XML 属性、
   图片元数据、URL、嵌套 JSON、日志附件中的秘密；需要逐项人工复核。
2. 真实路线、精确点位、原截图、数据库和抓包始终不进入仓库。当前回归夹具仅使用
   synthetic 数据；合成 ID、版本、哈希不代表学校或应用实际事实。
3. 关联关系用一致的合成占位 ID 表达，避免独立替换破坏 job/session/record 关系。
   协议仅交已合法取得、人工审阅的字段名/类型与时序语义，不提交可复用签名或凭证。
4. 对私有证据记录摘要/哈希与版本绑定；哈希不是来源真实性或脱敏完成的证明。
   公开前仍须人工逐项检查，校验器不能证明不含个人信息。

## 离线元数据校验器

`swu_happyrun.drivers.adapter_inputs.validate_sample_inventory(text,
expected_app_version=..., expected_profile_revision=...)` 接受最多 64 KiB UTF-8 JSON 文本。
这是独立本地审核工具，不是控制协议模型、真实适配器或 CLI 执行入口。

允许且必须提供的键：

- schema_version：整数 1；provenance：synthetic 或 locally_redacted
- app_package、app_version、android_version、environment_version：精确值，不用 unknown/latest
- profile_id：本地标准 UUID；profile_revision、rules_digest、point_source_digest：64位小写 SHA-256
- crs：WGS84、GCJ02 或 BD09
- states：start、running、ended、upload_pending、valid、invalid、unknown，恰好各一次
- record_binding_reviewed：真正审阅关联语义后才填 true

states 是必须核对的状态清单，不证明已取得这些页面；须同时提供上方人工证据/缺失表。
该格式只接收元数据，不接受截图、路线、请求响应 payload 或任意扩展字段。重复 JSON
键、未知字段、缺失字段、类型错误和无效值一律拒绝；校验错误不回显输入。调用者必须
提供本轮预期版本与 profile revision 才会进行上下文对比。生产 profile 的 ID/revision、
实际 app 版本、路线合法性仍由已有 LocalProfileStore 校验，不能由这份清单代替。

通过校验仅表示清单结构合法。不会授予 capabilities、产生 app_record 或 succeeded，
也不会联网、读取私有文件、猜选择器、发请求或上传。元数据字段仍可能被人为滥用储存
秘密，不能把该工具当作通用 DLP/自动脱敏器；禁止将真实输入或验证异常原文直接写日志。

## 后续实现与验收

输入齐全后，在对应 Issue 固定精确版本、合法来源、接口与测试，再实现该组合的
只读 prepare、写前 guard、失租可 stop、未知页 fail closed 和稳定记录回查。
不确定上传只核验已有记录，不盲目重传或重新开始。现场检查应记录准确候选 HEAD、
版本、命令、退出码以及 host/device/record 证据层级。

- [vivo 无 Root](research/vivo-noroot.md)：保持现有安全设置。
- [纯接口](research/direct-protocol.md)：等待合法协议语义，不使用其他学校协议。
- [控制协议](contracts/control-plane-v1.md)：现有状态与证据绑定为唯一运行契约。

## R1：MuMu 实例绑定与私有只读取样

本轮工具只做指定实例的元数据采集和本地证据结构校验，不合并 MuMu/ADB 的随机
UUID，不启动应用、不安装、不点击、不读取账号会话/token、不写位置或传感器。
ADB 本身可能隐式启动已有 host daemon；工具不执行 connect/pair，也没有任意
命令或网关 URL 参数。真实 Windows/MuMu 仍由 Codex 现场验收。

在已安装本项目及其依赖的 checkout 根目录，用已核实的本机路径替换示例：

```powershell
python scripts/collect_device_context.py --manager "C:\Program Files\MuMu\nx_main\MuMuManager.exe" --adb "C:\Program Files\MuMu\nx_main\adb.exe" --instance 0 --serial "<现场确认的serial>" --package org.happyrun.app --private-output local/context-001.json
```

实例、serial、package 必须显式填写；示例路径和 serial 不是自动发现结果。
工具复用 MuMuManager.inspect 与 AdbClient.inspect，只查询元数据；stdout 仅输出
固定 reason/missing 项，不含真实 serial、package、版本、UUID、路径或稳定 digest。
私有输出只允许此 checkout 的 local/ 下新建文件，拒绝覆盖、越界及符号链接。
POSIX 文件以 0600 创建；Windows 仍须先由操作者确认 local/ 继承的 ACL 仅允许
本人，禁止放到共享/自动同步目录。工具不能代替 Windows ACL 审核。

未指定 --private-output 时不保存采样。底层完整 dumpsys 输出在内存解析后丢弃；
保存的私有文件仅含选择参数及两个现有适配器的结构化元数据。不采集原始页面、
屏幕截图、路由、数据库或会话信息。不可把私有文件作为公开附件上传。

成功读取元数据也返回 exit 2、binding_evidence_required，并列出还缺的当前别名
映射、host/engine版本、boot身份及display/task证据。这是预期的保守结果，不能
把两个读命令成功当成同一实例证明；命令非零/超时同样不能获得能力。

R1 复用 Task5 scripts/check_mumu_observation.py 的 accepted 纯解析入口：
collect_device_context.validate_display_replay 只解析现有私有回执，不调用其 main，
不自动运行 am instrument。Task5 的独立自身应用观测仍按原先隔离测试要求执行。
该回执不会证明目标乐跑页面或学校记录。多 task 必须明确当前 display/task；无法
唯一关联时不能绑定。现场操作者还须核对 index 到 serial 的依据，不能猜 ADB 端口。

本地 resolve_binding 的 observation 使用严格字段集合：instance_index、adb_serial、
host_version、engine_version、app_version、package、display_id、task_id、boot_id、
observation_id（UUID）、observed_at（带时区ISO时间）、mapping_source（local_review）、
mapped_instance_index、mapped_adb_serial、observed_display_id、observed_task_id、
matching_task_count（必须为1）。缺失或额外字段（包括 token/session/raw/url/command）
一律拒绝且错误不回显值。时间窗为30秒，未来时间也拒绝；assert_current 先验证新观测
的新鲜度，再核对稳定 identity_digest（实例/serial/boot/版本/package/display/task）。
同身份的新观测ID/时间允许刷新；旧缓存超时、实例重启或版本/display/task变化拒绝。
完整 digest 仍包含最初观测ID/时间，作为原始校准证据锚点，不因刷新偷偷重写；
identity_digest 与完整 digest 都仅限本地，不公开。R2/R4 应保留校准所锚定的原
MumuBinding，在每次写前对该对象调用 assert_current(本次新观测)，不能用新
binding 替换旧证据来规避校准检查；身份改变后须重新采样、审阅与校准。

该结构校验不认证手工输入的来源，也不是通用DLP；可信调用者必须提供本次实际
观察并持续重新检查 boot 身份与上下文，不能重放缓存。MumuBinding 仅本地使用，
capabilities 恒为空，不增加 wire 字段；即使结构有效也不授予执行权限或证实定位、
传感器、真实页面、有效记录。R2/R4 仍需独立执行 guard 与现场证据。

## R3：离线版本与记录拒绝门槛

本轮 `drivers/budao` 只提供 L3 接口和离线拒绝检查。真实版本注册表为空；无版本选择器、无 ADB 调用、无真实开始/结束/上传能力，也不发出 `app_record`。全部新增夹具均是合成负例。即使所有候选字段匹配，仍返回 `unknown / needs_samples`。库存 metadata 检查通过不能激活此适配器。

页面观察必须包含精确 package、versionName、正整数 versionCode、带时区的采集时间、本人授权、当前会话和动态点确认。30 秒及以上或未来页面拒绝；候选状态标签和布尔确认不构成实际观察的证明。成功 toast 不是记录页。当前适配器不把任何候选标签解释为可信状态。

记录离线检查拒绝 pending、invalid、未知状态、旧记录、错误会话、缺 app 会话关联、缺 identity/namespace。即使候选会话和时间相同，也不能证明记录由本次执行产生；截图 hash、调用方附加的 job/session ID 均不能替代稳定记录身份。当前没有已验证的规范化 artifact/namespace 算法，因此结果始终没有记录证据。

后续真实样本最小清单（本地私有保存，勿上传原页面/账号）：
- 精确 package/versionName/versionCode 及实际观测来源
- 开始前、运行中、结束确认、上传待定、记录详情和未知页面的脱敏结构
- 本人授权、学校配置 revision、规则及当前会话动态点来源/CRS
- 当前开始观察与应用会话、最终记录之间可验证的关联规则
- 稳定 record namespace/identity 与 canonical artifact 规则；时间和 pending→valid 变化不能改变身份

样本齐全后先在 Issue #9 固定来源、选择器、版本和关联规则，另行实现并验收真实版本。页面回放、设备 UI 流程、学校最终记录分别报告，不能相互替代。

R4 接线建议：由现有 `DeviceDriver` 组合此 `BudaoAdapter`，沿用共享 `SchoolProfile` 和 `VerificationResult`。代理继续负责持久 intent、lease/fence 与恢复授权；未来每次写入前执行 guard 并限制 transport 时间。不得将此离线适配器直接注册成具有 app_ui/record_read/location_write 的物理驱动。`finish()` 不是取消时的 `stop()`；停止须由现有驱动独立保证，不能因页面/版本门禁阻止停机。verify_only 不调用 start/finish；真实记录关联缺失仍保持 needs_attention。
