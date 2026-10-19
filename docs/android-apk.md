# 原生 Android APK 候选

2026-10-19 用户要求在 MuMu 内安装 APK 直接使用，因此本阶段新增 `android/` 原生 Java/Android SDK 工程，替代旧设计“首版不做独立 APK”的范围限制。原 Python 服务端/CLI 保留；APK 本地模式无需 Python、外部 PC 服务或网页浏览器。

已核官方版本、明确未知及组合限制见[支持矩阵](android-support-matrix.md)。

## 安装与能力边界

只有对应提交的 `android-apk` Actions 全部通过，才可将其 `android-debug-candidate-api31-<SHA>` / `android-debug-candidate-api35-<SHA>` artifact 中的 `app-debug.apk` 作为已构建软件候选。下载后校验 SHA256，并查看 `signature.txt` 中 apksigner 验证结果和签名证书 SHA256，再由用户通过 MuMu 自带 APK 安装入口安装并打开 HappyRun。不自动更改模拟器安全设置；若系统要求安装来源授权，由用户审阅决定。

原生界面、本地任务、诊断和模拟体验不等于真实乐跑适配。模拟任务不会提交学校记录。MuMu Android 15、目标应用版本、账号会话及有效记录仍须各自实际验收；官方 Android 15 emulator 通过也不能替代 MuMu 实测。当前没有实际设备通过证据。

本候选不请求网络、定位、无障碍或 Root 权限，不打包第三方模块。Root/LSPosed 等未来能力必须独立诊断和显式选择；发现模块不等于能执行任务。APK 安装本身不会授予 mock-location app-op、跨应用私有数据读取或运动传感器注入能力。

候选使用 CI 自动生成的临时 **debug 签名**，不用于生产或 Play 发布。不同 CI 构建（包括同一提交的不同 API job）可能使用不同签名；只有签名相同且版本条件满足时才可覆盖升级。签名不匹配时不要自动卸载重装：卸载会删除应用本地任务，应保留现有安装和记录，待明确的数据保留/迁移方案。长期签名/迁移方案尚未建立。没有创建签名账号、保存生产密钥或发布 Release。

## 构建与验证

兼容组合：JDK 17、AGP 8.7.3、Gradle 8.9、compile/target SDK 35、min SDK 26、Build Tools 35.0.0。无 NDK 和 AndroidX 运行依赖。AGP 8.7 官方支持 API 35、Gradle 8.9/JDK 17；此为固定兼容组合，不宣称最新版本。

构建者准备官方 SDK 和已接受许可后运行：

```sh
bash scripts/android_gradle.sh lintDebug testDebugUnitTest assembleDebug assembleDebugAndroidTest
HAPPYRUN_ANDROID_API=31 bash scripts/android_emulator_test.sh
HAPPYRUN_ANDROID_API=35 bash scripts/android_emulator_test.sh
```

Gradle bootstrap 只下载官方 ZIP，并校验固定 SHA256；它不是伪造的 wrapper。依赖从 Google Maven/Maven Central/Gradle Plugin Portal 获取。CI 使用 GitHub Ubuntu runner 预装 JDK/SDK，不执行 `sdkmanager --licenses` 或 `yes` 自动接受新协议；缺少许可即失败并报告。SDK 自动下载由 Gradle 禁用。

Android QA 优先使用 runner 现有 KVM 权限启动官方 API 31（Android 12）和 API 35（Android 15）x86_64 emulator；没有现成权限时使用有界等待的 `-accel off` 软件模式，安装 app/test APK、实际启动并执行专用 instrumentation；不修改 KVM 权限或系统安全策略，超时明确失败并输出诊断。精确场景见 Android QA 文档。失败/未执行的 Actions 不能标为通过。构建、安装、软件流程、MuMu 观测、学校记录为不同证据层级。

APK、合成测试输出和截图只保留 7 天；本地数据库、SDK local.properties、Gradle 缓存、签名密钥不进入 artifact 或 Python sdist。普通 Python extras 不引入 Android/Java/PyInstaller 依赖。

## 官方依据

- [AGP 8.7 兼容矩阵和 8.7.3 修复](https://developer.android.com/build/releases/agp-8-7-0-release-notes)
- [Gradle 发行版 SHA256](https://gradle.org/release-checksums/)
- [Android 命令行构建](https://developer.android.com/build/building-cmdline)
- [SDK 包和许可](https://developer.android.com/studio/intro/update)
- [Android debug 签名与升级](https://developer.android.com/studio/publish/app-signing)
- [LocationManager mock-location 权限](https://developer.android.com/reference/android/location/LocationManager)
