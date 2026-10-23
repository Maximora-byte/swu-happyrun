# Issue 110：默认关闭探针的可信加载、监督与私有结果集成

状态：整体设计草案，供一次性审核；尚未开始本设计的实现，不是运行授权。

## 1. 目标与事实边界

基线为 `72e9aec0f4c3385c566fef3f7813c078bfb70abd`，tree `afada151e5c13cbd2a2e7ed9ce2f0b6e75988bf7`。[原 Windows 回执](https://github.com/Maximora-byte/swu-happyrun/issues/110#issuecomment-6355678179) 已证明该源码的真实 Windows 分支通过 MSVC 19.44.35229 严格编译和 x64 链接。它没有执行产物或加载引擎，不证明运行时 ABI、加载信任、生命周期或旧 AV 根因。旧 EXE 的已记录哈希不得套用于改动后的构建。

本次把已有固定无目标实验补成可审核的软件集成：准确引擎加载、独立宿主的期限与所有权、私有证据及公开摘要分离。保留固定注册→getter A→sx→getter B、唯一 AV 过滤器枚举、无 target 检查和失败拒绝。A/B 不稳定仍阻断，sx 格式仍 unknown，产品 passed/execution_ready 始终 false。

不运行用户电脑、不加载 DbgEng、不调用 CDB、不启动被调试目标、不触发异常、不安装工具、不改 ACL、不读取旧 raw、不发布或启用 CI。现有 C++ main 和新增监督入口均保持无条件关闭，不新增参数、环境变量或编译开关绕过；未来启用须另一个准确候选和单次授权。

## 2. 选择与组件边界

推荐 **独立 Python 父监督 + C++ 固定宿主**，沿用标准库和官方 Windows SDK 声明。相比把 ACL、签名、父监督全部搬进 C++，它保留已审的只读权限模型，减少重写；相比沿用旧 CDB Session，它没有 READY/g/目标握手和旧文件覆盖行为。纯 Python ctypes COM/vtable 路线不采用。

拟三个可分别审查、共同交付的接口：

1. `issue110_filter_bundle`：`prepare_bundle(reviewed_build, private_root, deadline, api)`，返回持有文件/目录身份锁的 `PinnedBundle`。负责身份、当前签名、精确复制、只读依赖准入与一次性目录；不创建进程、不加载 DLL。
2. `issue110_filter_supervisor`：`observe_once(bundle, deadline, api)`，返回 `HostObservation`。只监督一个固定 EXE，处理创建/恢复/退出/收尾，不含 CDB/AV/动态 target；底层 Windows 调用通过可替身的窄接口隔离。
3. C++ 可信加载及结果编码：`load_verified_engine(stage, evidence)` 产生不可由任意函数指针冒充的模块持有对象；已有适配器只从它取得 DebugCreate。`write_private_capsule` 编码固定结果，父端独立 `parse_capsule` 与 `public_projection`。保留官方接口，不手写 COM ABI。

不修改旧 `issue110_win32.Session`、五工作流、原工具 pins 或实验命令。对 ACL helper 仅允许增加显式、默认行为不变的新固定子目录角色；不得修改全局 CHILD 后让旧入口改用新目录。准备根工具和既有观察入口不隐式创建/修复根。若为新增只读接口必须更新旧调用者的 helper 哈希，作为显式审查差异，不借机改其行为。

## 3. 构建与信任绑定

`ReviewedBuild` 由后续准确 Windows 构建与外部审核绑定：child 源文件哈希、实际 SDK/header/toolchain、EXE SHA256/PE x64、协议版本。不是 CLI 自报 commit，不接受任意 manifest 就宣称认证。推荐构建后生成只含 child 构建事实的固定 manifest，并由父源码 pin 该 manifest 摘要；manifest 不包含父自身哈希，避免递归。最终父源码、manifest 与 child 源的身份再由准确提交/文件清单外部核对。

若没有新 EXE 的精确审核身份，`prepare_bundle` 失败，零进程。旧 72e9aec EXE 仅属于旧关闭源码，不能作为新宿主的身份。

复用 V6 当前验签逻辑与固定三文件身份；在本次新私有环境内重新验证，不复用旧回执。签名 PowerShell 子进程及其后代清理沿用原事实限制，不能用后续宿主 Job 的 owned_cleanup 结果替代。cdb.exe 只参与原三文件身份合同，绝不启动，也不放入宿主 stage。只把新 EXE、固定 dbgeng.dll、dbghelp.dll 独占复制进 stage；创建时拒覆盖，复制后重新核验 SHA256、完整版本、x64，以及与刚验签源的精确内容绑定。V6 保持一次针对现有安装位置的签名阶段，不谎称旧 helper 已直接验了 stage；stage 的签名信任依据是其 bytes/SHA256 与仍持有锁的已验签源一致，不增加第二次签名调用。新 EXE 是经准确构建审核的自有产物，不冒称微软签名。

EXE/DLL 使用新的只读文件 pin：同一打开句柄读取 SHA256/卷与文件身份，仅允许 READ 共享，禁止 WRITE/DELETE 共享，保留到宿主终态与收尾完成。旧目录 helper 的 share=READ|WRITE 和即开即关 file_identity 不能替代它。来源读取、复制和 stage 核验都失败即停，不安装、搜索替代版本或修复 ACL。

## 4. DLL 依赖准入，不把事后检测当先验授权

信任基线明确分层：当前可信 Windows 安装及其系统加载机制；准确审核的自有 EXE；固定微软工具 DLL。不是通用沙箱，也不承诺防已被攻陷的 OS、当前用户、SYSTEM 或管理员。

加载前检查 EXE 和两 DLL 的 PE import/delay-import、路径别名、激活上下文/manifest/.local 等重定向。非系统依赖仅可为 stage 中固定审核文件；系统依赖仅可为已核对的 Windows 系统/API-set/KnownDLL 范围。未知外部依赖、未知重定向、不能证明的系统映射均阻断。实际依赖清单必须由准确文件的只读检查确定，不能凭三个工具哈希声称闭包已齐；若缺少事实，形成 blocked，而不是临时放宽名单。

独占 stage 不含其他 DLL/脚本，不把整个 Kits 目录、PATH、工作目录或用户插件目录加入搜索。子进程设置进程局部的受限搜索，主 DLL 以绝对路径配合 `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32`；不修改系统环境或持久设置。父先审 EXE 初始导入，因为这部分在 child main 前已执行。子进程加载前核对自身目录/固定文件身份及初始模块，再加载；加载后记录实际主模块/依赖的真实路径、文件身份、哈希并拒绝非预期模块。

加载后拒绝只能说明检测到偏差，不能撤销已经执行的 DllMain；所以绝不把事后枚举称为加载前信任证明。未确定的 OS/API-set/SxS 可解析依赖边界保持显式阻塞。

**本设计不是完整动态 DLL 执行沙箱。** 静态/delay-import 检查仅覆盖可解析导入表，搜索限制仅覆盖遵循该策略的请求；已经被信任的微软引擎仍可能自行按绝对路径加载、改变搜索策略或执行其他代码。本轮不增加 DLL hook/系统策略，不能保证所有未知动态模块都在执行前被阻止。事后枚举还可能漏掉已加载又卸载的瞬态模块。准确 pins 表示信任这些已核代码，不等于强制限制其一切行为；如果要求“零未知动态模块执行”，本设计不满足，必须保持 blocked，不能用事后检查替代。该限制须在设计审核和未来运行范围中明确。

引擎接口释放与模块生命周期分开：先注销 callback、释放 owned 引用，模块保持映射直到宿主退出，不在无法证明全局销毁时 FreeLibrary。Release 数值不等于 engine 已销毁。

## 5. 私有目录及一次性状态

仅使用已批准、重新核验的 prepared-top-level 根；复用严格卷根/NTFS/无 reparse/owner/DACL/继承角色检查，不改权限。新实验子目录固定为 `issue110-filter-probe-1`，与旧观察目录不同。创建为独占操作；已存在、创建结果未知或任何残留都停止，不 adopt、不换名、不重试、不删残留。

新目录独占创建就是 reservation。在签名与宿主动作前写不可覆盖的 attempt 记录，写入/flush 失败亦停止。reservation 不是用户授权。真正 CreateProcess 前单独记录 invocation intent；异常、取消、断电、缺收据均保留 unknown，不重新尝试。私有保留期限必须在未来具体运行授权中确认；软件不自动删除、迁移、设提醒或制造到期时间。

## 6. 父监督及预算

共享期限 `D = monotonic_start + 300s`，不重置。V6 整个三文件签名阶段只有一个截止点 `S = min(D, stage_start+30s)`，每次等待扣同一剩余预算，不按文件续期；不足完整 15 秒宿主窗口时不创建。宿主窗口从创建尝试之前起算，`H = min(D, now+15s)`，包含创建、映像核对、DLL 验证/加载及整个实验，不仅计算 getter 时间。

使用一个 fresh unnamed kill-on-close Job，active-process-limit=1，不允许 breakaway。优先官方 `PROC_THREAD_ATTRIBUTE_JOB_LIST` 在创建时纳入 Job，并配合受限 `HANDLE_LIST`；属性初始化/更新时已发现平台或 API 不支持则零 CreateProcess；只有在 CreateProcess 时才报告的兼容失败如实记录调用尝试/返回句柄，不虚称零调用。两者均无 fallback/retry，不降级到存在父崩溃孤儿窗口的事后 assign。固定 EXE 使用绝对 `lpApplicationName`，CREATE_SUSPENDED；核对实际进程映像与已 pin 的 EXE 为同一文件，再 resume 一次。未知/不符时只用 CreateProcess 返回的 owned handle 收尾，不按 PID 搜索/重开/终止其他进程。

request、result、stdout、stderr 都是新目录内独占文件；仅这四个指定角色句柄可继承，request 为只读，result/stdout/stderr 为只写，父保有独立读句柄；child 不得凭请求另开任意输出路径。目录、Job、父进程、其他 pin 句柄不继承。request 只包含固定 schema/mode、nonce 和本次绑定信息，不接受动态 target/script/命令。数字句柄只是传输路由，不是授权。无 stdin g 控制。

父监督分别观察进程 signaled、自然退出码、文件增长、最终结果。超时/异常/输出超限触发 owned Job 收尾。进入收尾时建立唯一 `C = now+5s`，全部终止/等待/关闭共享该期限，不每分支续期。创建请求/创建返回、resume 请求/resume 返回分别记录；intent不等于调用完成，suspended创建不等于引擎已执行，丢失最终事实保持unknown。记录注入终止码之前的自然退出观察；未观察到就 null，不能把强杀码当自然退出。清理失败/取消保留未知，主错误不被普通 close 错误覆盖。

300/15/5 是被监控阶段预算，不是 OS 硬实时保证。父自身同步文件系统、签名进程创建或 CreateProcess 调用阻塞，不能被同一线程的计时器可靠中断；调度延迟、失去执行能力和未知收尾仍可能存在。不得用这些数值宣称无泄漏或绝对墙钟上限。

## 7. 结果合同与隐私

child result 与 stdout 分离。采用固定 ASCII magic/version、字节长度、UTF-8 JSON body 和固定 completion footer 的私有 capsule，包含 nonce、真实 child PID、有限阶段/HRESULT、getter 实际可确认字节的 hex、sx callback 字节的 hex、A/B 比较、owned release 观察。getter 无法证明实际有效长度时仅记录 reported_length/错误类别，不把整个 4096 字节预填数组冒充引擎输出。sx 仅保存有界实际收集字节及 overflow/association 状态，不猜正向显示解析。原生字节及需保真的 UTF-16 路径使用有界 hex 字段，不借有损解码构造 JSON；公开投影不含这些字段。

capsule 解析拒绝阈值为 256 KiB；stdout/stderr 各 64 KiB 检测阈值。父有界读取并监测长度，超限收尾，不截断后声称完整；普通文件轮询不能阻止检测前已写入更多字节，`disk_hard_cap=false`。这是读取/解析/检测阈值，不是磁盘配额。需要硬配额将是另一个设计，不在本批偷加 pipe 框架。

父仅在真实进程退出、结果长度/终止标记完整、nonce/PID/协议关联正确时接受 capsule 结构；结构有效、观察完整、进程退出与清理完成四者分离。重复字段、未知字段、尾随内容、无效编码、越界数值、NaN、bool 冒充整数及缺字段均拒绝。child 返回 0 不单独代表完成。

公开摘要由父从固定 allowlist 构造，不直接转发 child JSON/stdout。字段只含 schema/mode/status/stage/blocker、三态 host_execution_attempted、engine_creation_attempted、child_result_valid、child_exit_before_cleanup、host_owned_cleanup、signature_cleanup、observation_complete、a_expected/b_expected/ab_stability，以及恒定 passed=false、execution_ready=false、display_comparison=format_unknown。getter/sx/HRESULT trace、绝对路径、nonce、PID、模块映射及原始异常文字只留私有。host_execution_attempted 仅在成功恢复后为 true，未恢复为 false，不确定恢复为 null；它只表示宿主有机会执行，不证明已进入引擎。engine_creation_attempted 只有完整收据中 DebugCreate 调用证据才为 true，确认未恢复时可为 false，已恢复但无有效收据为 null。host_owned_cleanup 仅指本次 Job/宿主，signature_cleanup 独立保留其未知，不能宣称全局无残留。取消 traceback 只允许私有控制台，不包装进公开回复。

## 8. 必测失败矩阵及交付边界

用纯逻辑/替身覆盖：错误启动标志/构建 manifest/EXE 身份→零进程；错误工具签名/hash/依赖/路径→零加载；原目录已存在或 reservation 不确定→零重试；Job 属性前置不支持→零创建调用，创建时才发现的失败→如实保留attempt、无重试；创建不确定→不重试；映像不匹配→零 resume；每个 engine 阶段异常/target出现/S_FALSE/A-B变化→阻断并收尾；共享预算不足/截止相等/超时→不得延长；自然退出与强杀分开；结果缺失/伪造/截断/超限/坏nonce/未知字段→无完整观察；写入、flush、关闭和取消双故障→保留主异常与unknown。旧 Session/门禁和新 main 恒关闭另有回归。

交付由三个窄实现片段及共同的失败矩阵组成，不先写一个未审大模块。整体设计获审核后，再给一个实施计划并选执行方式；不逐项重复索取设计批准。云端完成 TDD、定向/相关旧合同检查、独立审查和准确差异。随后新的 Windows 编译/静态导入清单、新 EXE 身份及实际平台支持仍需验证，不沿用旧构建结果。只有完整准确候选、依赖准入、预算/私有留存交接和新的单次运行授权齐备，才可考虑未来启用。

## 9. 一手接口依据

- [进程创建属性](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)：JOB_LIST 与受限 HANDLE_LIST；不支持即拒绝。
- [LoadLibraryExW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw)：绝对主路径不等于所有依赖都来自该路径。
- [DLL 搜索顺序](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)：API-set、SxS、已加载模块、KnownDLL 影响解析，不能只检查PATH。
