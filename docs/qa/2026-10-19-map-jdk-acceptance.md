# #69原始地图与#62真实JDK接续验收

2026-10-19，本地Codex，原普通Windows账户（Administrator=false），未提权。Dot负责产品修订；本轮只执行主机和离线地图验收、读取既有授权CI证据及集成审核。没有操作MuMu/vivo、真实乐跑、学校记录或生产系统，没有发送Matrix消息或扩展runtime/KVM授权。

## 准确源码与主机检查

| 范围 | 准确HEAD / tree | 本机结果 |
| --- | --- | --- |
| #69地图 | `ba6d37d989126afe86787312e72685610c6a250e` / `08d7238a890bb03ce64ea767b9b6f40adf1a6c11` | Python3.11.16、3.13.15的地图+契约各162 passed /1 permission skip，exit0 |
| #62导航输出 | `6afecb02a553d2aa8ae0f8e72dd27ac1e9864bde` / `98cf045787357d9820c6f09f3dfc465c8f765066` | Python3.11.16聚焦47 passed；Python3.13.15聚焦+契约168 passed，均exit0、无skip |

测试命令分别为：

```text
python -m pytest tests/agent/test_map_candidates.py tests/contracts -q
python -m pytest tests/delivery/test_android_native_navigation.py tests/delivery/test_navigation_output_capture.py -q -W error::pytest.PytestUnhandledThreadExceptionWarning
python -m pytest tests/delivery/test_android_native_navigation.py tests/delivery/test_navigation_output_capture.py tests/contracts -q -W error::pytest.PytestUnhandledThreadExceptionWarning
```

父子进程以绝对PYTHONPATH绑定受测工作树。地图两版本各唯一skip为普通账户WinError1314无法创建符号链接；未改权限/系统保护，超大参数、4MiB边界、模拟GBK与正式CLI用例均实际执行。托管Windows无地图skip和原机器这一权限skip分别保留，不能混报。

## #69：无裁剪原始XML三条实际通过

原输入仍为PR66冻结的完整校园XML，**2,898,661 bytes**，SHA256 `0d974b582d0883c2d4a23dc95d8177c5af3da95379560c6db649fd41f044f354`，导入前后独立核对相同。没有裁剪、重新下载或修改原来源摘要/获取时间。

| 目标 | 跑道版本 | 点数含闭合端点 | 正式API / CLI |
| --- | --- | --- | --- |
| 一运 | way843421789 v1 | 29 | 均通过，CLI exit0 |
| 二运 | way846878928 v2 | 39 | 均通过，CLI exit0 |
| 四运 | way368577141 v3 | 22 | 均通过，CLI exit0 |

全部点序与此前本地RouteProfile逐点相等；从原XML独立重算有序node/version/geometry摘要，分别为 `f068767a7d51491a9247f99f96bb40a7eaf1d7ea1e84b67225318c6bf9e0b5e4`、`a2eaa7c9c89e9fef6f94d59b9c4d88198902218255a0886effe73ead9c73b807`、`fecf63a6d793340c7b3d4fbaf63ba531e55c05ecd0b39ba6e3a1531bb5c04c06`，与新报告一致。canonical revision重算一致，source_ref绑定完整原文件摘要。三次重复CLI均exit2且已有route/report字节不变，未覆盖文件。

基于同一真实源的错SHA、GCJ02标记、颠倒轴及高德verified声明四项反例均按预期拒绝。固定4MiB上限、limit+1读取、最多1000节点及原解析/身份门槛保留。旧a091的真实失败和六次派生诊断仅保留在[历史回执](2026-10-19-map69-retest.md)，没有改写成旧版本通过。

新route/report只在当前账户独占ACL的本机私有目录。公开回执不含精确几何、route UUID/revision或账号/设备数据。OSM为WGS84/lon-lat，保留© OpenStreetMap contributors / ODbL-1.0；高德precision_limited、腾讯empty、cross_source_status=not_cross_verified。school_rules_confirmed、device_execution_enabled、record_verified仍false。顶点关系不证明当前通行、正式400m中心线或学校认可区域；地图适配#64的高德/腾讯正式来源和交叉核验仍未完成。

## #62：原普通账户真实Oracle JDK25通过

Python3.11.16实测utf8_mode=0、preferred_encoding=cp936；实际Oracle JDK `25.0.4.1+1-LTS-5`，默认native.encoding、stdout.encoding、stderr.encoding均GBK，file.encoding=UTF-8，语言zh/CN。没有修改系统codepage、locale、全局环境或默认JDK，未设置JVM编码环境变量；QA仅为父子Python进程显式绑定受测PYTHONPATH。

生产runner为四个Java子进程分别设置 `-Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8`，在主类之前生效；这是产生字节的进程内配置。[Java25官方System说明](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/System.html#getProperties())记录这两个标准流属性及UTF-8覆盖，不能仅凭属性存在认定实际输出正确。

本机另外在不改变命令/返回值的QA观察包装中运行准确脚本：真实javac返回0，stderr **279 bytes，含非ASCII中文且严格UTF-8解码成功**；三个运行阶段stderr均空，原RED复现、5项共享预算、8项提取适配器标记全部准确。与默认JVM比较，只有子进程stdout/stderr属性为UTF-8，native.encoding和语言未变；原始字节留本机私有目录。

新增真实非ASCII stdout/stderr探针在JDK25均执行；错字节、非零退出、超时、非预期stdout/stderr仍拒绝，没有ignore/replace或猜GBK回退。自查AST确认，相比7aed，run_checked除首个命令参数赋值外，拒绝、输出与预算逻辑完全相同。旧7aed的31 passed /1 failed及214-byte拒绝记录保留在[旧回执](2026-10-19-tools-retest.md)。本轮结论限原Windows/JDK25组合，不承诺旧JDK17输出属性同样生效；真实原导航测试没有因此跳过。

## 组合与合并回执

组合基于 `4c096f368534e11e68f0284b9b85676075228031`，仅增加两PR的7个拥有路径。地图3文件与ba6、导航4文件与6af逐字一致；未改变契约、CI、设备或调度代码。Scoped Ruff/format、schema漂移及whitespace均通过。

组合commit `2cd22febc1eced36e09646c9e402c85c67c38f6a` / tree `53d6858c01b982e1143436018d7201e934c4ee58`，Windows/Python3.11.16执行 `python -m pytest -q -W error::pytest.PytestUnhandledThreadExceptionWarning`：**1298 passed /17 skipped /1 warning，exit0，290.03s**。skip为3项POSIX信号、7项普通账户symlink权限、6项POSIX shell及1项FIFO；唯一warning是既有Starlette deprecation，未再出现旧JVM读取线程解码告警。受测源码结束后未变。

两PR准确HEAD的push/PR主机、容器、浏览器和Android build/static检查通过；bot为neutral。最后重查head、实际目标分支和mergeability后，#69合入原候选merge `c4118d5f1117d2493979250963cc093650e175de`，其tree与本地中间组合一致；#62随后merge `9534f51efe3a557e6b4bda5605426e4004a34783`，最终tree与上述完整回归组合**完全一致**，本地git diff再次确认无差异。没有把旧分支反向覆盖到候选。

[#69接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/69#issuecomment-6266394724)、[#62接受回执](https://github.com/Maximora-byte/swu-happyrun/pull/62#issuecomment-6266413701)均已发布；#59按该原Windows/JDK25问题范围关闭，#64整体仍开放。此次只是两增量集成到产品候选，未将完整产品合入main。

## 4c联网证据与接续边界

本轮独立下载既有API35 artifact12180385470，ZIP SHA256 `1f247445b7fc707c24ca1d18521a5e25c3ed327d3bd41bee4909cf53ae70781e` 与GitHub一致。runtime authorized=true / passed，结构化报告确认协议15项、UI计数3、前台14项、durable_finished_verify_only和live-fence各1项通过，恢复报告确实存在。来源仍为4c，不能借作新组合的Android运行结果。

simulation_only及未接受MuMu/真实设备的标志保留，未启动新的runtime。旧8f9首次hello、ba990退出等间歇失败仍未逐项定因；这次通过不擦除历史。#57继续开放，完整#46仍Draft；本轮按两PR范围接受也不表示本机MuMu HTTPS或学校记录通过。下一步仍是Dot收尾#57诊断与真实通道/指定版本输入，Codex对冻结构建推进MuMu现场验收。
