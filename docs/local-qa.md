# 本地独立验收清单

这是交付候选的操作清单，不是已经完成的设备验收。记录日期、操作系统、Python、不可变 commit SHA、命令、退出码与脱敏结果。Linux fake 证据不能替代 Windows 或设备证据。

## 第一阶段：安装与协议

1. 在独立目录检出指定候选 HEAD，按 [安装说明](installation.md) 安装冻结依赖。
2. 运行完整 pytest、Schema 漂移检查、ruff、构建及独立安装检查。
3. 按 [服务启动说明](server.md) 用临时数据库和测试凭证启动单进程服务。
4. 运行 [fake 联调与恢复清单](fake-e2e.md)。保存任务 ID、状态和退出码，不保存 token、请求头或租约 token。
5. Docker 可用时补 Compose config、build、启动健康、任务创建、重启后读取同一任务及 volume 权限验证。未运行项目逐项写 `not_tested`。

## 设备测试前最小输入

- MuMu 宿主版本、Android 引擎版本、指定实例索引、ADB serial 与授权状态。
- vivo 型号、Android/系统版本、ADB 可用性；保持无 Root，不改变系统安全设置。
- 步道乐跑精确版本与包名，以及本人已经完成的登录状态。不要提交密码或会话凭证。
- 实际校区、当前学期规则来源/日期、允许时段和要求；未知内容保持未知。
- 用户确认的路线与打卡点来源、明确 CRS、配置 revision、学校边界；不猜坐标。
- 特定版本界面的脱敏样本；原图、连续路线、数据库和账号信息只留本地私有目录。

## 证据分级与停止条件

- `host_verified`：只证明指定宿主安装/只读诊断结果。
- `device_verified`：必须有指定设备上的实际能力观测；命令返回 0 不等于位置或传感器已生效。
- `record_verified`：必须复查本次任务绑定的实际有效记录；上传提示和 fake `completed` 均不足。
- 未知版本、规则、坐标、应用页面或授权时停止并记录 blocker；不得用占位成功代替。
- `needs_attention`、上传不确定、旧租约或停止未确认时禁止重新创建任务绕过占用。

## 缺陷交接模板

候选 HEAD / 系统与版本 / 精确命令（删除凭证） / 预期与实际 / 退出码 / job ID / 最后状态 / 是否可能已经开始或上传 / 脱敏复现附件 / 修复后复测 HEAD。

## MuMu 自身应用：保留数据与隔离验收分开

任务5的逐步命令、签名核对和失败边界见 [Android验收](android-qa.md#mumu-task-5-explicit-displaytask-observation-not-yet-device-accepted)。
存量安装只读观察，不运行 instrumentation、清库、卸载或Root操作；签名不符时保留原数据并使用独立无个人数据的新实例。
新观察入口必须指定已核实的serial/task/display和同构建签名，返回`observed`仅证明自身窗口/控件观测，不代表模拟完成。
MuMu6.8.4.0/API35 的8秒20米模拟完成、显式停止、完成后重启及中断后needs_attention/no-replay仍由本地Codex逐项实测。
原`android_acceptance.sh`含`pm clear`，只用于明确的一次性官方AVD，禁止复制到用户MuMu运行。
