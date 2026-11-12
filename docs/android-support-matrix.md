# Android 官方版本与支持矩阵

核查日期：2026-10-19（UTC）。这是官方页面证据和待验收范围，不是设备兼容性通过证明。用户此前要求按官方最新稳定版推进，随后明确将下述第三方视频改版指定为兼容目标。本轮同时保留官方基线和改版研究对象，不将第三方改版称作官方发行；构建工具版本与目标应用版本分开记录。

| 对象 | 当前可核实事实 | 未知 / 待验证 |
| --- | --- | --- |
| MuMu Windows 当前完整稳定版 | [国际官方下载页](https://www.mumuplayer.com/download/)提供普通 Windows 下载；Windows ARM 明确标为 Beta，本轮稳定版目标不包含它 | 页面未展示完整当前版本号/发布日期；国内 `mumu.163.com` 本次读取失败。历史设备 6.8.4.0 不是“最新”的证据 |
| MuMu Android 系统 | [官方 Windows 升级说明](https://www.mumuplayer.com/help/win/how-to-upgrade-mumuplayer.html)，发布于 2026-07-03：MuMu 6.0 引入 Android 15，并可保留 Android 12 实例；[首页](https://www.mumuplayer.com/)仍说明两者可并存 | 用户实际实例的 Android/API/补丁版本未读取；不能从下载页面推断现有实例已升级 |
| MuMu Android 15 ABI | 同上官方说明明确不支持 ARM32 应用 | 未取得完整 guest ABI 列表，不能把宿主 Windows 架构当作 guest ABI；需读取实际 `Build.SUPPORTED_ABIS` |
| 步道乐跑 Android 商店版本 | [腾讯应用宝](https://a.app.qq.com/o/simple.jsp?pkgname=com.lptiyu.tanke)在核查日显示 **4.3.1**、175.33 MB，开发者/运营者均为乐跑体育互联网（武汉）有限公司；链接标识包名 **com.lptiyu.tanke** | 页面没有发布日期、完整 ABI/最低 API 或签名指纹；这是当前应用宝展示版本，不保证所有渠道同步，也不证明设备已安装此版 |
| 步道乐跑开发商官网 | [产品页](https://www.lptiyu.com/lptiyu_web_new/public/portal/product/lp_app.html)确认产品和开发商；官网未展示 Android 当前版本号 | 不用 Apple 版本或第三方 APK 聚合站版本填补 Android 证据空缺 |
| HappyRun 本候选 | 原生 Java/SDK 本地模式；compile/target API 35、min API 26；无 NDK，未引入第三方 hook 依赖；构建工具详见[APK 说明](android-apk.md) | 真正 APK 构建、官方 emulator 软件流程、MuMu 设备观测、目标应用操作、学校有效记录各自按实际证据验收，不相互替代 |

## 只读应用版本诊断

Manifest 仅通过 `queries/package` 声明 `com.lptiyu.tanke` 的精确可见性，依据为上述应用宝产品链接；没有 `QUERY_ALL_PACKAGES` 权限，也不扫描任意已安装应用。诊断读取该包的实际 `PackageInfo`，展示真实安装的版本号；未安装和读取失败均不能变成版本匹配或“适配通过”。商店显示的 4.3.1 不作为伪造的本机检测值。

## 可选 Root / 模块兼容性

MuMu 官方 2026-07-03 Android 15 说明明确列出 **Magisk 不支持**，因此当前不能承诺“MuMu Android 15 + Magisk”受支持。不把此产品限制外推为 Android 平台永久不可能，也不据此推断所有其他 Root/模块路线结论。

LSPosed 及 Magisk 自身的官方当前版本、平台要求和组合兼容性另待专项官方来源核查；本阶段未验证、未安装、未启用任何模块。存在 Root 或模块仅是能力线索，不是执行能力或目标应用有效记录证明；本 APK 不默认更改这些设置。

## 固定验收组合

最终设备验收须记录官方安装渠道、MuMu 完整版本、具体实例 Android/API 与 ABI、步道乐跑实际 versionName/versionCode、HappyRun 提交和 APK SHA256，以及每项能力观测。未知项保留 unknown/needs_samples；出现官方组件冲突时明确列组合限制，不用更旧或修改版本暗中替换用户要求的最新稳定版。

## 用户指定的第三方 MuMu 兼容目标

来源：[李甜虾的原视频](https://www.bilibili.com/video/BV1bDkYB1E5G/)，标题“MuMu终极重置版：国际内核+大陆功能，ROOT级净化打造安卓模拟器完全体”，2026-01-19 发布，230 秒。2026-10-19 只读 HTTP 302 已核用户短链 `https://b23.tv/H8zzdGp` 指向该 BV；官方 B站 view API 与云浏览器页面核对作者 UID 310791868、标题和简介。不是仅依赖标题匹配。

- **03:13 实际画面**：MuMu 管理器中“MuMu安卓设备”和“HYZB”两实例均显示 **Android 12**，4 核/5 GB。这是视频中实例标签，不是对用户设备或网盘现有包的检测。
- **03:24 实际字幕/画面**：要求打开 Root 文件夹内的 **Kitsune Mask** 应用。只能确认视频演示该应用名称，不等于官方 Magisk 当前稳定版或已验证 Root 执行。
- **约03:35–03:38**：出现 LSPosed 样式设置页，版本主体可读 **1.9.2** 和 **(7412)**；低清画面后缀未可靠辨清，不能据此认定精确构建或上游来源。
- 简介链接到第三方夸克共享资料，名称为“2026MuMu模拟器 国际版融合大陆版优化”。未下载、运行安装包或脚本；没有核验包签名、哈希、完整 MuMu 版本、ABI、Android 补丁版本及模块来源。也未完整审计视频每一帧或把弹幕反馈当作实测结论。

候选 CI 因此增加 **API 31 / Android 12**，保留 **API 35 / Android 15** 官方 AVD 安装和软件流程检查，compile/target35/min26 不变。官方 AVD 通过不代表该改版 MuMu 通过；需该实际环境只读版本/ABI/模块信息及明确设备验收。2026 年 1 月发布的视频不作为 10 月“最新版本”证据。官方 MuMu Android15/Magisk 限制仅适用于相应官方组合，不自动套用于这个 Android12 第三方组合。
