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
