# API31 background-transition regression

Evidence: push run 39193629343, HEAD 491019d0b68802fdcf0c67fbe4bd3b846a9eae82, ordinary API31 job 117871553348 failed at `PollingAcceptanceTest.awaitForeground(false)` after HOME injection. The failure log reports 6.743 seconds and contains no contemporaneous HOME-resolution or top-activity dump. It does not establish that the emulator lacks a launcher or that the product's onStop handler is broken. API35 success cannot replace API31 acceptance.

This QA-only delta replaces HOME key injection with the official Activity `moveTaskToBack(true)` request on the main thread. It requires the task-manager operation to return true, still requires the real onStop-driven foreground flag to become false within the unchanged five-second deadline, and adds loss-of-window-focus/not-finishing assertions. No lifecycle callback is manually called and no state flag is assigned. Returning through the existing Activity intent must still drive onStart, advance the read serial, retain the task ID, and support stopping. The fifteen-test count and remaining assertions are unchanged.

Bounded instrumentation status records now identify task ID, foreground, window focus, finishing/destroyed state and read serial before/after transition and on timeout. These synthetic diagnostics are part of the existing method log. For any future failure, collect the disposable emulator's activity/window dump through the existing CI diagnostic mechanism; do not convert a failed transition into a pass or blindly retry HOME.

Official API semantics: https://developer.android.com/reference/android/app/Activity#moveTaskToBack(boolean)

This replacement has not yet executed on Android. It removes dependence on delivery of a synthetic HOME key; it does not assume a successful background transition. A system image that refuses or fails to stop the Activity still fails the test. No production code, Root command, framework activation or device setting is changed.


本轮继续验收只允许从 491019d0b68802fdcf0c67fbe4bd3b846a9eae82 开始的下一受信 push / PR33 synchronize 使用临时 runner 当前 uid 的 KVM ACL；仓库、分支、真实 before/after、Linux hosted、API31/35 与旧 ACL mask 限制保留。旧6427事件及未来其他父提交均拒绝；本地只测 mock。Artifact 名增加 run_attempt，防止同一 run 重试产物重名。

491 的 API35 两变体 native15、wizard4、inactive1 已实测通过；API31 在 HOME 后等待 foreground=false 失败。这里的 moveTaskToBack 替代仍须新 HEAD 的实际 Android 验证，不能将旧 API35 结果当作新候选完整验收。
