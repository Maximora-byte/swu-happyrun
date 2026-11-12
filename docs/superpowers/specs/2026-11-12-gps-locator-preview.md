# GPS Locator 可选适配预览

## 目标与边界
用户希望把类似 FakeLocation 的开源能力集成进 HappyRun 并看看效果。用户委托 Dot 全权开发，本轮选择保持现有 MuMu，不引入 Root，不操作真实账户或设备。

## 方案比较与本轮选择
1. 整体复制 Android 应用：会引入独立构建、数据许可及设备生命周期，范围过大。
2. 直接包装上游 start/stop：接口存在，但 START_STICKY 自动恢复、缺少会话身份和截止期限，不符合 HappyRun 的恢复约束。
3. **本轮选择：离线路线转换 + 显式单设备只读检查**，在 CLI 提供可用的兼容性预览；不开放任何定位写入，不冒充完整运行后端。

上游基线 `0xfnzero/gps-locator@7845ff8c94fef7d0afd2bcc4fa34ad3575635f29`，HappyRun 基线 `f6242c2e495634fc4ca91570b1595754c80dc205`。

## 实现决策
- 新增 `gps-locator export-route`，验证 HappyRun RouteProfile 的 revision，将显式 CRS 转成 WGS84，输出上游 JSON route，速度 m/s 转 km/h，禁止循环。已有输出不覆盖。
- 新增 `gps-locator inspect`，显式 adb 路径、一个 serial，只发送 GET_DEVICE_STATUS，不安装/授权/设时区/开 Activity/开始或停止服务。返回经过校验的有限脱敏字段；不返回 deviceId/organization/serial。
- 不增加运行依赖、不改控制协议、不注册 location_write 能力，不改变 MuMu/网页/服务器默认行为。
- 只读检查反映应用自报，不是新鲜 GPS、设备所有权或学校记录验收。

## 未开放执行的原因
应用 START_STICKY 可能自动重放；status 无 session/route/位置时间戳，mockLocationReady 只代表 AppOp；start route 持久保存路线。安全后续需要设备端非重放会话、期限和失联停止、独立新鲜定位与停止回执，以及授权设备测试。
