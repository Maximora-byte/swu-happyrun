# 存活旧进程跨新 fence 的真实 Android 验收

本场景独立于原 15 HTTPS、14 Activity 和持久完成恢复 1 场景计数。源码/host 边界检查不能代替实际 Android 执行。

`RemoteLiveFenceAcceptanceTest` 启动真实 `RemoteAgentRunner` 和 `RemoteFakeDriver`。首次成功 tick 后，测试时钟以真实 `Thread.sleep(5200)` 模拟一次调度延迟，单调时间与 UTC 都继续正常走。下一次正常 maintain renew 到期时，真实 HTTPS 夹具在第四次 renew 注入无响应；保留平台五秒请求预算，不手动停止或冻结 driver。

runner 自然因失联停机，测试必须观察 running、attention_unconfirmed、一次 start、成功 tick 大于零、路线尚未完成且 stopped。原 instrumentation/app 进程随后保持存活，只用另一个只读客户端查询同一个真实服务端 job；不重开执行器。

host 等待实际 30 秒租约过期和 lease_expired，ADMIN 批准 verify_only，再由真实 AGENT claim 获取同 job/session 更高 fence。新旧阶段均核旧 PID 存活，旧 lease/token 的 completed 事件必须得到409且 revision 不变。旧进程看到真实高 fence 后，连续两秒核 startCount、tickCount、tickAttemptCount 均不增长且 driver stopped。

成功 tickCount 定义为正常 guard 通过并更新模拟进度后的调用数；tickAttemptCount 在 tick 入口记录，包括被拒绝调用。两者都是只读诊断计数，不能由测试伪造成功值。停止后尝试调用也不能被“距离没有增加”掩盖。

`check_android_live_fence.py` 仅在既有一次性官方 AVD guard 通过后运行。token/旧 lease 仅临时内存；不输出原始仪器日志、命令或密钥。artifact 仅 `qa/android-live-fence/report.json`。异常为失败，不把任意错误当作失租证明。

当前 Android 编译、真实 TLS/ART 执行尚待本轮准确 HEAD 的 CI。MuMu、真实步道乐跑和学校记录未由此场景验证。
