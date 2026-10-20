# #100 第一批：只读发现与生产入口封闭

基线 `628c23da47a6e1a9bde5a917568e8cbf5f99b7cd`，设计及原机技术复核见
[#100](https://github.com/Maximora-byte/swu-happyrun/issues/100#issuecomment-6287324348)。
本批不初始化任何产品状态，不签发执行 capability，也不实现首用写事务。

## 本批行为

- `enrollment_inspection.inspect_enrollment` 记录每根路径的身份、计数、排除、错误、
  显式历史参数/配置来源及未检查类别；只读现有 host-id，保持原 device-id 派生式。
  默认未确认历史使用范围，因此结果为 `unknown`。
- 范围声明完整且无候选时仅返回 `first_use_review_required`，不等于登记通过或
  全盘不存在历史状态。扫描只识别 `.sqlite/.sqlite3/.db` 候选名及已知状态文件；
  任意命名或遗漏的自定义状态必须在原机实际历史清单中声明。达到深度/条目/根数
  上限、读失败、路径重定向、多历史映射均保留 `unknown`。
- `existing` 仅表示一个明确映射的原库和设备锁通过有限文件检查；
  `runtime_state=unverified`、`launch_allowed=false` 始终保留。
  不打开 SQLite（包括 `mode=ro`），不声称验证了 SQL 内容、未决 intent 或 reservation。
  journal 变化不会因永久全文 hash 不等而被误判；本批没有持久 DB hash pin。
- 静态 XML/prev 解析绑定同域文件身份、完整哈希、name、目录、index、manager；
  supplied manager version 只是输入来源，不是软件实际版本证明。重复 UUID、复用 index、
  文件替换、路径变化拒绝。静态 UUID 绝不推出 PID；进程归属仍 `unknown/conflict`。
- Python stat 与 Win32 legacy NTFS 身份明确标域，完整保留整数，不截低位或跨域相等。
- `resolve_control_root()` 只通过当前用户 Known Folder API 计算固定 LocalAppData
  子路径，不读取环境变量作控制根，不创建目录。返回位置不等于已验证 NTFS/ACL；
  那些验证、账户准入锁、独立 authority/plan/pin 在第二批实现。
- production `run_experiment`、point/replay 入口（含 recover-stop 新调用）、
  `MuMuNative684`、`OwnProbe` 构造均在任何 I/O 前通过同一门并拒绝。
  普通 Registration、旧 schema1 receipt、字典/布尔/调用者 guard 无法解锁。
  没有 CLI/env 测试开关。MuMu inventory 不再隐式创建 host-id。
- 原合成生命周期与命令协议覆盖保留在 `tests/mumu_*`，不随 wheel 安装；生产协议
  核心必须显式注入 transport，无原生命令默认。测试 harness 不是原机执行工具。
  已启动后的 cleanup finally/45 秒预算的断言保留，不把新启动门禁插入其中。

## 原机只读复测

两个脚本均只向 stdout 输出脱敏摘要，不创建输出文件、不启动进程、不读学校账号。

```powershell
python scripts/mumu_static_inspect.py --config <原.nemu绝对路径> --index <索引> --manager <manager绝对路径> --manager-version 6.8.4.0
python scripts/mumu_enrollment_inspect.py --manifest <本机私有清单.json绝对路径>
python -m pytest -q tests/agent/test_mumu_enrollment_gate.py tests/agent/test_mumu_enrollment_inspection.py tests/drivers/test_mumu_instance_attribution.py
```

清单的准确字段及 JSON 示例在 `scripts/mumu_enrollment_inspect.py` 的说明中。
路径和 UUID 留在原机，不贴 GitHub。API 返回的完整私有 dataclass 可供独立复核工具
留存逐根记录；脚本只显示状态/计数，不能把摘要当完整历史账本。`known` 或 `existing`
的退出 0 仅表示相应只读检查完成，绝不是 Windows 运行验收、stop ACK 或清队列。

尚未交付：受控首用事务、跨目录准入竞争、可变 SQLite 原锁接线、独立批准及 pin
装载、真实配置到 PID 桥接、原机设备执行。schema1 单固定 receipt 的首轮单实例限制
继续有效。第二批必须落实原机复核五项约束，不能凭本批静态成功开放执行。
