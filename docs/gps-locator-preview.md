# GPS Locator 可选适配预览

**这不是已经能运行的第二个定位后端。** 当前交付只有离线路线转换与只读兼容性检查，没有开始、停止或重播命令，没有接入网页按钮或服务器任务。原有 MuMu 路径不变。

## 现在能看到什么效果

- 把已有的 HappyRun `RouteProfile` JSON 转为 GPS Locator 的 route JSON。
- 校验输入 revision，按输入 CRS 转为 WGS84；速度从 m/s 转成 km/h，保留点序。
- 导出的路线固定不循环、点停留 0 秒，名称为预览名，`createdAt=0` 用于确定性离线结果，不代表真实采集时间；不带原始 `source_ref`。
- 可查询单台已授权设备上的应用自报状态；不把这些状态转为执行能力。

例如输入速度 `2 m/s`，输出 `speedKph` 为 `7.2`。这是格式转换结果，不是设备实测移动速度。

## 1. 离线导出

按[新手教程](tutorial-zh.md)安装包含本功能的准确提交。只需要核心 Python 依赖，不需要 Node、Android APK、ADB、手机或学校账号。

假设 `local/route.json` 是已登记、revision 正确的 HappyRun RouteProfile 文件：

```sh
uv run --no-sync swu-happyrun gps-locator export-route --route local/route.json --output local/gps-locator-preview.json --speed-mps 2
```

成功回执：

```json
{"status":"exported","execution_enabled":false,"device_contacted":false}
```

输入不是普通 GPX、网页导出的任意 JSON 或上游自己的 route JSON。必须含 `route_id`、`revision`、`input_crs`、`points`、`source_ref`，遵守[控制协议](contracts/control-plane-v1.md)的 RouteProfile；修改点位后需要重新登记 revision，不能随便填摘要。

两个点不能完全相同，速度必须落在上游 0.5–500 km/h 的格式范围。这个范围只是编码允许值，不是运动建议或校方规则。数据量受上游广播大小限制，过大时拒绝导出。

输出已存在会拒绝覆盖，包含输出路径与输入相同的情况。另选一个新文件名即可。文件含坐标，应存放于本地私有目录，不要提交 Git；Windows 目录 ACL 应自行保持私有。导出不自动上传或导入 Android 应用。

## 2. 可选只读检查

仅当你已经自行准备好可信 ADB、拥有设备授权且设备上已安装 GPS Locator 时使用。不自动安装 APK、连接设备、授予权限、设置模拟位置应用、Root 或改变时区。

```sh
uv run --no-sync swu-happyrun gps-locator inspect --adb /absolute/path/to/adb --serial YOUR_SINGLE_DEVICE_SERIAL
```

Windows 将 `--adb` 换为实际 `adb.exe` 路径，包含空格时加引号。`YOUR_SINGLE_DEVICE_SERIAL` 要替换成你确认的一个设备；拒绝 `all`、逗号列表或空值。

此命令向固定 Receiver 发送 `GET_DEVICE_STATUS`，会唤起状态接收器，但不打开 Activity 或开始定位服务。执行预算 5 秒，沿用项目有界进程捕获；没有失败重试。输出不含 serial、deviceId 或组织名。

- `mock_location_appop_reported`：应用自报模拟位置 AppOp，不保证位置权限、前台服务或 GPS 能用。
- `simulation_active_reported`：应用保存的 active 标志，不证明属于本次 HappyRun，也不是新鲜 GPS。
- `reported_version_matches_reference`：只比较自报版本 2.1.0/code 5，**不是源码、签名或完整性验证**。
- `execution_enabled`、`fresh_location_verified`、`record_verified`：始终 `false`。
- 未安装、无授权、超时或协议不匹配时失败；不要把失败解释为“没有运行”。

## 为什么没有直接开放运行

审查基于 [gps-locator 7845ff8](https://github.com/0xfnzero/gps-locator/tree/7845ff8c94fef7d0afd2bcc4fa34ad3575635f29)：

1. `MockLocationService` 使用 `START_STICKY`。Android 重启服务时可能从头重播路线，主机断开也不会保证停止；关闭界面不是停止。
2. 状态无会话 ID、路线 ID、设备端期限或新鲜位置时间戳。主机上的锁或 finally-stop 不能补足这些设备端约束。
3. `START_ROUTE` 先将路线保存进应用，再异步开始服务，接收成功不等于 GPS 写入成功。
4. STOP 接收器提前返回，清理还吞掉 provider 移除异常。因此不能把命令接受当成“恢复真实 GPS”。

后续需要独立 Android 协议改造：会话身份和原子闲置检查、持久记录未知状态但禁止自动重播、设备端截止期限/续约 watchdog、绑定会话的新鲜定位与停止回执。期限到达或重启必须停止并等待显式恢复；主机丢失或确认丢失不能新建第二次运行。然后在授权隔离设备上测试崩溃、重启、断连和并发控制，才能考虑接入 HappyRun。此改造超出本次离线预览，尚未实现。

## 许可与验证边界

上游代码 MIT；区划数据库单独 ODbL 1.0。本次不复制 APK、区划数据或地图瓦片，不运行上游 CLI，不削弱 Receiver 的 DUMP 权限。来源与许可见[第三方记录](../THIRD_PARTY_NOTICES.md)。

本功能只有合成输入的离线/协议测试，不包含 Android 构建或安装、MuMu/vivo 设备测试、新鲜定位、第三方轨迹或学校有效记录验收。不能用这里的测试通过替代原 MuMu 的校准与安全门禁。
