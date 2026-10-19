# 原生 remote fake-agent 的真实 HTTPS 验收

这是独立测试工程，不修改已验收的 091 历史提交。组合基线 77494e21756e514f53e51b3a2c72f22555f0aae6；A协议/传输、B+C执行/journal、D单次任务界面均按冻结manifest组合。界面一次显式连接只尝试领取一个模拟任务，不是常驻代理，未证明无人值守调度全接通。

## 独立测试信任

普通 debug、selfProbe 和 release 不含测试CA或networkSecurityConfig。只有 remoteQa source-set 含debug-only信任配置，CA在每个临时runner生成，服务器IP SAN明确为10.0.2.2及127.0.0.1。平台HTTPS证书/主机名校验保持，私钥不进APK。构建检查逐个验证普通APK无测试信任资源/PEM，QA公有CA摘要等于本次临时文件。remoteQa APK不上传、不作为用户候选。

真实已安装Python wheel中的server绑定宿主loopback。AVD按官方10.0.2.2地址映射访问；不存在公网隧道、生产账户或持久信任安装。认证与设备ID全部临时合成。UI敏感页保持FLAG_SECURE，不能为截图关闭。

## 15场景每API

完成、未知CA、错SAN、HTTP拒绝、redirect拒绝、错误token、服务端取消、本地停止、renew响应超时、事件提交后响应丢失、真实force-stop后恢复、verify_only、stop_only、未知profile、未开始租约过期。最后一项明确为未开始lease安全回队及409，不冒充运行中设备租约丢失。

API31/35均使用真实Android HttpsAgentClient + RemoteAgentRunner + private journal连接真实Python server。host测试middleware只对真实API响应作屏障/延迟，不伪造成功JobView。取消在driver.start后的第四renew屏障注入；响应丢失必须命中故障标记，并核服务端状态和唯一事件；仪器兜底停止不得计为成功。进程恢复真实am force-stop，保留同一journal；新显式client重新连接，不复用超时已closed的client。

D的3项界面输入/生命周期测试单独计数。原native15、wizard4、inactive1回归仍保留。任何通过结论必须绑定最终HEAD及官方AVD实际结果，JVM/本机TLS不能替代Android。

## 本轮权限、成本与证据

用户2026-10-19明确批准新一轮Android12/15临时runner KVM，仅当前测试uid、保留旧ACL mask。根确认本轮包括旧四Android回归job与新两个HTTPSjob；唯一函数check_ci_kvm.py限定仓库、dot/android-remote-agent、本轮修复重试push before e5b3b973f9e055fc8bcb4a9e3261cf6320568787、真实after==GITHUB_SHA、hosted Linux及API31/35。未知PR编号不获授权；任何别的父提交/分支/事件拒绝。不执行本地ACL，不自动接受SDK协议。最终发布前根复核准确HEAD。

03:53:32UTC只读GitHub仓库API显示private=false、visibility=public；与初始私有预期不同，本轮没有改变可见性。官方说明标准公开仓库runner计算使用免费，但账户用量/存储账单不可见，不能承诺总账单零费用。无购买额度、付费大runner或新服务部署。

只上传固定JSON报告和启动前诊断文件，不上传QA APK、密钥、token、DB、journal或原始instrumentation参数。异常只记录类型与源文件行号，凭据不入报告。临时材料始终清理。正常UI截图不证明remote敏感页视觉覆盖。

本地阶段：完整 Python 697 项、delivery 116 项、Java 49 项及16个双向契约/3个出站载荷互验通过；真实Python TLS 5项通过，JVM生产A+B对真实Python HTTPS完成、取消、renew超时与提交响应丢失路径已跑通。Android构建与15场景尚待CI。运行中设备fence更替/旧事件拒绝尚未加入本轮实际HTTPS验收，不以场景数量覆盖此空缺。最终结果按实际记录更新。

官方资料：
- https://developer.android.com/studio/run/emulator-networking-address
- https://developer.android.com/privacy-and-security/security-config
- https://docs.github.com/en/billing/concepts/product-billing/github-actions

## 首次 CI 发现与同轮修复

e5b3b973 的普通 Android 构建已通过；新增 HTTPS workflow 被 GitHub 拒绝 job 级 runner.temp 表达式，未执行该两个 job。Python 3.13 严格 TLS 检查发现测试 CA 缺 keyUsage。修订将临时路径在 runner 步骤内写 GITHUB_ENV，给 CA 添加 critical keyCertSign/cRLSign、叶证书 critical digitalSignature/keyEncipherment，保留 serverAuth/SAN 和严格证书验证。两个新回归均对旧文件失败、修订通过；真实 CI 重试结果尚待确认。
