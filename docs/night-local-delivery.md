# 同源夜间交付（本地 artifact schema 2）

本工具扩展是构建与离线校验，不是控制面 wire 协议变化，也不会启动设备、服务、KVM或修改系统设置。产品源与工具源分别固定：工具 checkout 提供脚本；产品 checkout 必须是明确提交及 tree 的干净 Git 工作区。不能把工具 HEAD 当产品 HEAD。

当前可构建的 N0–N4 产品快照：

- branch `dot/night-virtual-run-candidate`
- commit `25aea0177020eef34449764ddc5e3bf0e5afdd24`
- tree `d303879dab0dcd6b842430ba7a1c5791fc9af331`
- N0 c3dd、N1 PR90 8a73、N2 PR89 2d700、N3 PR91 489339、N4 PR92 17fe18；各 PR 的软件检查不等于 Codex 本机接受。

## 必要输入

本机已有的公有 CA、由它签发的公有 server leaf、实际私有服务 IP/SAN、Android SDK 工具和 Gradle。私钥不交给构建/验证工具，不装系统 CA。生成/维护本机信任与服务器私钥仍由本人完成；可以复用已核 CA/leaf，但不能混旧 9534 APK 或旧 manifest。Python 环境需安装仓库 dev/build 依赖；构建工具可能访问官方依赖仓库，不能称离线构建。

schema 2 必须同时提供 `--source-root`、`--expected-source-commit` 和 `--expected-source-tree`。验证工具实际检查 Git HEAD、tree 和全部 tracked/untracked 改动，且把 wheel 全部包文件与该 source checkout 逐字比较。清单中自己声明的哈希不能替代可信输入的 source pins。源码必须保留在本机用于每次离线验证和 MuMu runner 预检，路径不上传。

## Windows PowerShell 最短构建链

下例变量由本人填入；路径可以包含空格。`$Tools` 是本 PR 工具 checkout；`$Product` 是上述准确产品 checkout。`$Bundle` 必须是源码之外的新目录，旧完整 bundle 保留。以下只是命令说明，不代表已在本机执行。

```powershell
$Commit = '25aea0177020eef34449764ddc5e3bf0e5afdd24'
$Tree = 'd303879dab0dcd6b842430ba7a1c5791fc9af331'
$env:PYTHONPATH = "$Tools\scripts;$Product\src"
python -m build_local_https_delivery --source-root $Product --expected-source-commit $Commit --expected-source-tree $Tree --output $Bundle --ca-cert $Ca --server-cert $Leaf --host $HostIp --gradle $Gradle --openssl $OpenSSL --apksigner $ApkSigner --apkanalyzer $ApkAnalyzer --aapt2 $Aapt2 --gradle-stderr-encoding gbk
python -m check_local_https_delivery --source-root $Product --expected-source-commit $Commit --expected-source-tree $Tree --bundle $Bundle --ca-cert $Ca --server-cert $Leaf --host $HostIp --openssl $OpenSSL --apksigner $ApkSigner --apkanalyzer $ApkAnalyzer --aapt2 $Aapt2
```

仅实际 Gradle stderr 已确认为 GBK 时指定 `gbk`；默认两路 UTF-8，stdout/SDK机器输出始终严格 UTF-8。可选 `--private-build-evidence` 是源码、bundle 以外的新私有目录，保存精确原始 bytes，不自动上传。失败部分目录不能当交付；修复原因后换新目录构建，不覆盖原完整材料。

同次构建产出：

- `ordinary.apk` / `ordinary-test.apk`
- `selfProbe.apk` / `selfProbe-test.apk`
- `remoteQa.apk` / `remoteQa-test.apk`
- 同源 `swu_happyrun-…whl`、两份公有证书、`delivery.json`、`SHA256SUMS`

所有 app/test 必须同证书，三组版本一致。普通与 remoteQa 无定位权限；selfProbe 仅自身 scope、可选定位权限，未推断 ART 激活。只有 remoteQa 携带本机测试 CA；其 test APK 不含信任材料。生产 adapter 已在同一产品源中，schema2 拒绝外部 `--adapter` overlay。

## 安装与运行边界

三种 app 使用同一个包名，彼此替换，不是并存。不同 debug 签名不可覆盖升级；不卸载/清库来绕过，使用原签名构建或新的隔离实例。安装前比较 bundle 证书和已安装 app 身份；所有 APK 只取同一已验证 bundle 对应组。wheel 也取该 bundle，在新的 Python 环境安装并复核来源。

MuMu HTTPS 原有安全入口/绑定步骤不变，`check_mumu_https` 另外加上同样三个 source 参数。沿用 [本机 HTTPS 说明](mumu-https-qa.md) 的准确 instance、serial、binding、boot、版本、签名和显式本人隔离测试许可。其能力常量仍为 `mumu-own-simulation-v1`；本 schema 不自动开启 N3 replay 或第三方应用操作，不改变任何未知能力的 fail-closed 行为。

```powershell
python -m check_mumu_https --help
# 在原已审核完整命令上追加：
# --source-root $Product --expected-source-commit $Commit --expected-source-tree $Tree
```

不要直接复制9534旧例的 manifest/source参数来跑本轮新源。原 schema1 与9534四包路径仍兼容，且不得使用schema2参数覆盖schema1身份。

## 验证声明

本轮工具采用合成SDK输出/真实本地Git文件验证源 pin、六包配对、严格签名/权限/信任/自身scope、wheel字节与接口接线。合成APK不是实际构建结果；实际六APK/wheel交付和 Windows/MuMu运行须在准确工具/产品 HEAD 上另取证。CI已有各源的 Android 静态编译，也不能代替本机 CA 的同次六包构建。

## 同源 wheel 与本地预览

在新的普通用户虚拟环境安装该 bundle 中唯一 wheel（`$Wheel` 为完整本地路径），不要从另一个 checkout 的 `PYTHONPATH` 抢先导入旧源码：

```powershell
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
python -m pip install "${Wheel}[agent]"
python -m swu_happyrun.cli mumu replay --instance $Instance --route $PrivateRoute --speed-mps 2 --duration-seconds 30
```

最后一行仅预览，不启动进程/写 journal。数值是明确试验参数例子，不是学校规则。实际执行前阅读该产品 checkout 的 [virtual-replay.md](virtual-replay.md)，用同源 `scripts/start_mumu_virtual_replay.ps1`，准确绑定自身 app、相同 device ID/journal、真实本地校准与各项显式许可。目前 vendor write acknowledgment/stop/队列语义尚未验收，原生适配器仍会 `write_ack_unconfirmed`、`stop_unconfirmed` 并锁止；本轮不能宣传已有可用连续轨迹，也不能删除未决 intent 来强行继续。安装 selfProbe 不自动授予定位权限或启用框架。

wheel 校验另核 pyproject 中的 Name/Version/Requires-Python、依赖/extras、命令入口，唯一 dist-info、纯 Python WHEEL 标记和完整 RECORD 哈希；Git index 的 assume-unchanged/skip-worktree 不能藏住产品文件改动，忽略规则不能藏新增源码。验证工具需要 dev/build 环境中的 packaging。

Windows 源目录也必须保持原 Git blob 字节。该产品 `.gitattributes` 已指定 LF；如果旧 checkout 曾转成 CRLF，raw blob 校验会拒绝，请另建准确提交的干净 checkout，保留原目录，不强制覆盖未提交文件。需要时可在创建新 checkout 的单次 Git 命令中使用 `-c core.autocrlf=false`；不改系统 codepage 或全局 Git 配置。下载 ZIP/复制但没有 Git 身份的目录不能用于 schema2。

例如在未存在的独立目录建立产品 checkout，以下配置只作用于这两次命令：

```powershell
git -c core.autocrlf=false clone --no-checkout https://github.com/Maximora-byte/swu-happyrun.git $Product
git -C $Product -c core.autocrlf=false checkout --detach 25aea0177020eef34449764ddc5e3bf0e5afdd24
```

`source_git_blob_mismatch` 表示实际工作区字节与固定 tree 不一致，即使 Git status 干净也拒绝；不要归一化后跳过验证或修改清单。保留原目录，在新的目录按上述方式重建再验证。仓库属性若指定其他转换，仍需逐字节通过校验，命令成功本身不等于通过。
