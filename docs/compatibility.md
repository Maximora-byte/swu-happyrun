# 环境探测与兼容性记录

日期：2026-10-18（Asia/Shanghai）。以下是 C0/L0 的证据，尚未开始 L1 的定位写入或 L3 的应用流程。

## 已交付的只读探测

```powershell
uv sync --all-extras --frozen
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

通过标准安装目录和 Windows 卸载登记发现 MuMu；多安装时必须指定 `--manager`，多实例时必须指定 `--index`。宿主版本来自匹配安装位置的 `DisplayVersion`，不使用 MuMuManager 内部文件版本代替产品版本。

管理器路径可以通过 `--manager` 显式传入，带空格路径用引号包裹。可选的 ADB 查询需要同时提供 `--adb` 与 `--serial`；默认不会连接端口、启动模拟器、启动应用、安装 APK 或修改设备设置。`--package` 仅对明确指定的包查询版本。

退出码 0 表示所选择的只读查询完成；2 表示仍需处理连接、实例选择或命令错误。`android_not_started` 是可解释的环境状态，不能通过自动启动设备来把探测改成绿灯。JSON 的 `capabilities` 始终以实际证明的能力为准。

MuMu 的 `info --vmindex all` 返回索引映射，单实例 `info --vmindex 0` 返回平铺对象；两种形状均有对应测试。未知结构、非零错误码、超时和进程错误返回原因码，原始输出不会进入异常信息。

## 本机结果

| 检查 | 实际结果 | 验收范围 |
| --- | --- | --- |
| Windows Python | 3.13.15 与 3.11.16 均运行自动测试 | host_verified |
| MuMu 产品版本 | 6.8.4.0；由本机卸载登记读取 | host_verified |
| 实例查询 | 索引 0，Android 15.0，管理器返回 error_code=0 | host_verified |
| 运行状态 | Android 与宿主实例进程均未启动 | 仅主机观测 |
| `adb devices -l` | 没有设备连接 | 设备检查 not_tested |
| 定位读取/写入、传感器 | 未调用控制命令，能力列表为空 | not_tested |
| 步道乐跑版本、界面、记录 | 未连接应用 | not_tested |
| vivo 无 Root | 尚未连接 | not_tested |

完整 JSON 保留在 Git 忽略的 `local/mumu-report.json`。此表仅保留脱敏摘要，不包含设备 serial、个人目录、账号或路线。

## 身份与限制

每台主机首次生成随机 UUID 命名空间并持久保存，Windows 默认在 `%LOCALAPPDATA%/swu-happyrun/host-id`，Linux 默认在 `${XDG_CONFIG_HOME:-~/.config}/swu-happyrun/host-id`。同一主机的多个代理必须共用该文件；可用 `SWU_HAPPYRUN_HOST_ID_FILE` 指定共同路径。探测可以写入这一份本地主机元数据，不写模拟器或应用状态；损坏/不可读时明确报错，不自动换一个身份。测试使用临时文件隔离。

MuMu UUID 从主机命名空间、规范化管理器路径和实例索引派生；ADB UUID 从同一主机命名空间与明确选定的 serial 派生。因此不同电脑使用相同安装路径或 loopback serial 时不会冲突。同一设备更换管理器安装位置或 namespace 会改变 ID，重新登记前必须确认旧任务已结束，不自动迁移活动租约。

MuMu 与 ADB 两者不是自动等价的身份。L0 将 ADB 结果放在独立 observation 中；L1 必须核实映射，才能把具体 Android 设备能力绑定到 MuMu 任务设备。远程代理归属、已登记设备别名去重和设备级 fence 属于 S1/C1，不能只凭客户端 UUID 声明授予执行权。

ADB 的 get-state/getprop 和可选包版本查询只证明连接和版本，不证明 `app_ui`、定位或记录读取能力。测试使用的假设备不能提高兼容性等级。有效乐跑记录仍需 L3 单独实测。
