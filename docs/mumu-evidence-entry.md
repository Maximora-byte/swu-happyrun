# MuMu 自身应用采证入口（#58）

本入口用于普通账户、无个人数据的独立 QA 实例，仅 `org.happyrun.app`。
优先使用 native 观测，不依赖 vendor `uiautomator`。它不清库、不卸载、不修改
Root/系统保护，不放宽 `android_acceptance.sh` 的 CI AVD 限制。
它不是定位/传感器 transport、真实乐跑适配或学校记录验收。

## 1. 本地实例与产物前置检查

由本地 Codex/操作者核对 MuMuManager 的实例 index/name/创建时间及当前 ADB
映射，选择新建、无个人数据 QA 实例。不要克隆个人实例，不要只凭端口猜映射。
每次操作前重查；映射不明确、多实例混淆或原实例意外启动时停止。以下 `SERIAL`
必须是这次核对得到的值；工具只按显式 `-s` 选设备，不会自动选择第一台设备，
也不声称验证了 MuMuManager↔ADB 的物理身份绑定。

使用同一次构建的 app/test 配对，在本地以官方 `apksigner verify --verbose
--print-certs` 分别核验哈希和证书。记录准确 source HEAD/tree、构建 run/artifact
及两个 APK 的 SHA256。证书冲突停止，禁止通过卸载/清库绕过。旧 e490 产物不得
重标为本次新 HEAD 产物。安装或升级由独立现场流程负责，本入口不会安装 APK。

在自身界面处于空闲且没有待恢复任务时，独立检查 `dumpsys activity activities`
和 `dumpsys window windows`，确认唯一自身 MainActivity task、当前 focused display，
记录实际 task/display。输出全部留私有本地目录。未知焦点、其他应用窗口、多个
自身 task、非默认 display 不继续；现有 native 恢复入口明确不支持非默认 display。
不要套用示例数字，不要通过移动 task 来满足预期。

## 2. 复制运行 native 观测

PowerShell 示例，先替换所有占位符。使用受信任的本机官方 ADB；不下载新工具：

```powershell
$Adb = 'C:\PATH\TO\adb.exe'
$Serial = 'EXPLICIT_QA_SERIAL'
$Display = 'OBSERVED_DISPLAY'
$Task = 'OBSERVED_TASK'
$Certificate = 'VERIFIED_LOWERCASE_CERT_SHA256'
$Private = 'C:\PRIVATE_OUTSIDE_REPOSITORY\mumu-qa'
New-Item -ItemType Directory -Force $Private | Out-Null
python scripts/check_mumu_observation.py --adb "$Adb" --serial "$Serial" --display "$Display" --task "$Task" --signature-sha256 "$Certificate" --isolated-no-personal-data --output "$Private\native.json"
$NativeExit = $LASTEXITCODE
Write-Output "Native checker exit: $NativeExit"
```

必须同时满足 checker exit0、`result=observed`、fresh observation UUID、准确
signature/task/display、唯一 task、焦点及可见控件。shell exit0 本身不够。
`writes=0` 只指测试发出的模拟/控制/输入动作；instrumentation 可重启自身进程、
将既有自身 task 恢复前台并触发正常生命周期持久化，故不能用于个人安装或
活动任务。此命令只运行一个观测测试，不代表普通/optional各30项验收已运行。

失败保留 `reason` 和白名单 `diagnostics`：错签名 `signature_mismatch`、
不存在显示 `display_missing`、错误 task `task_id_mismatch`；未知错误不能成功。
`host_timeout_device_runner_may_still_be_active` 时停止后续测试，由现场人员在
所选 QA 实例确认 runner/自身进程状态，不能自动重试或宣称 runner 已停止。
ADB 不可用为 `adb_unavailable`。输出文件仍留本地，分享前只摘录固定原因、
退出码和测试数量，不上传原始窗口、实例标识、UUID、数据库或 XML。

## 3. 可选 XML：仅本地离线排错

没有必要为 native 验收运行 dump。确需复核 #58 时，操作者只在上述隔离实例
及自身空闲界面采样：前后分别独立核对唯一自身 task/display/焦点/证书，使用本次
新 UUID 命名的专用临时文件，先确认该文件不存在；不要复用旧文件或其他采样的路径。
按当前 SERIAL 执行一次 `uiautomator dump`，立即单独记录原始退出码，再检查新
文件。无论 XML 是否完整，139/135 都是 vendor 命令失败。不要 `|| true`，不要
以文件存在覆盖退出码，超时/未知状态不得取旧 XML。原始采集及文件复制仅由
现场人员执行；本离线分类器不调用 ADB、没有输入动作，也不采集其他应用。

可将已审查的本地采集事实写成私有 JSON（示例是合成格式，不是设备证据）：

```json
{
  "xml_file": "C:/PRIVATE_OUTSIDE_REPOSITORY/mumu-qa/current.xml",
  "capture_id": "1b07e57a-d891-4f1f-bbcb-52809b678ab7",
  "file_capture_id": "1b07e57a-d891-4f1f-bbcb-52809b678ab7",
  "absent_before": true,
  "dump_exit": 139,
  "before": {
    "package": "org.happyrun.app", "activity": "org.happyrun.app.MainActivity",
    "task_id": 42, "display_id": 0, "task_count": 1, "focused": true,
    "signature_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "after": {
    "package": "org.happyrun.app", "activity": "org.happyrun.app.MainActivity",
    "task_id": 42, "display_id": 0, "task_count": 1, "focused": true,
    "signature_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}
```

```powershell
python scripts/classify_mumu_xml.py --manifest "$Private\capture.json"
$ClassifierExit = $LASTEXITCODE
Write-Output "Offline classifier exit: $ClassifierExit"
```

UUID 必须每次新建，不能复制示例值。`file_capture_id` 由操作者确认这份 XML
确实来自当前采样；`absent_before` 是采样前实际检查事实，不能事后补填猜测。
分类器只检查这些陈述的一致性，不独立证明时间、文件来源、签名或窗口真实性。
不能把重新命名的旧 XML 当新采样；这些证据仍须本地人工复核。

新 XML、独占自身节点、同一前后身份/焦点且 exit139/135 时，输出
`manual_review_candidate=true` 仅表示值得人工查看，`dump_succeeded=false`，
分类器 exit1，原因 `vendor_dump_nonzero`。exit0 且上述条件齐备才报告操作者
声明的 dump 成功，仍 `independently_verified=false`。其他退出码、旧/缺失/损坏
XML、其他包节点、未知或变化焦点、多个 task 全部拒绝。文件最大2MiB，拒绝
DOCTYPE/ENTITY，XML与manifest只读普通文件，拒绝末级符号链接/FIFO等特殊文件。
仅支持严格UTF-8 XML，其他编码拒绝。输入目录须由操作者维护私有访问权限，
这些预检查不防御恶意并发替换或父目录符号链接，不能视为安全沙箱。任何结果始终 `driver_input_permitted=false`、
`record_verified=false`；不得注册执行能力、点击控件或替代 native gate。

## 4. 实际应用页面样本的最小审查方法

真实版本适配另走 #9 的输入审查，不把本入口的自身包 allowlist 改为任意包。
当前只准备清单，不真实登录、不自动导航或采样账号页面：由本人确认允许的
具体版本/校区/页面和采样目的；本人在本地查看指定页面，先排除账号、定位轨迹、
验证码、token 和个人记录。只手工转录最少必要的公开资源 ID/控件类型/状态结构，
用合成文本替换所有个人值，分别保留 unknown/pending/error 状态。原始截图、XML、
窗口和数据库留本地。先本地审查拟分享的脱敏样本及接收方，再提供给版本适配。
样本缺失或无法可靠脱敏就保持阻塞，不猜选择器、坐标或上传协议。

## 验证范围

PR60报告的 MuMu6.8.4.0/API35 普通与optional各30项是本地 Codex 对 e490 的
历史现场结果；本修订仅有合成主机回归，新的 MuMu 实测仍由本地 Codex负责。
新 HEAD 的 paired APK、Windows入口、错误签名/task/display拒绝和dump139/135
保留行为均需独立复测。CI runtime未授权时只计build/static，不计设备通过。
