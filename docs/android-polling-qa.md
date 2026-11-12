# Polling regression acceptance

Adds four platform instrumentation methods to the ordinary suite, retaining its eleven existing tests (total fifteen). Wizard acceptance remains four separate tests per installed variant. Never runs a Root command or clicks its positive confirmation.

Run each method of `org.happyrun.app.PollingAcceptanceTest` in a separate cleared disposable emulator app process:

1. `testEmptyUiStaysIdle`: initial and explicitly refreshed empty state; 1.4 seconds each, no new read serial or task TextWatcher events, both refresh buttons always enabled.
2. `testTerminalUiStaysIdle`: the real engine completes its synthetic route, then the same idle/text/button assertions.
3. `testActiveProgressBackgroundReturnAndStop`: real engine progress reaches the Activity; background polling never disables refresh buttons. Hold the actual runtime monitor to pause a real read, click explicit refresh, and verify it is queued then consumed. Send actual HOME key and return through an Activity intent; background has no further reads, foreground reads again, same task ID persists, explicit stop yields stable cancelled UI.
4. `testStorageLatchRemainsVisibleAndIdle`: a real SQLite INSERT-failure trigger forces tick/fallback failure. Polling must display “未保存”, mark current projection unpersisted, disable start/stop, then stay idle without hiding the alert. Trigger is removed in cleanup.

App resource IDs resolve by installed-target resource names. Private fields are observed solely to count real reads and validate presentation state; engine results are not mocked. Method-isolated app cleanup is required because storage failure intentionally latches until process restart. Keep the existing eleven-test screenshots before clearing for these cases.

These are Android instrumentation regressions awaiting CI, not executed Android evidence at source handoff. They do not assert true Root access, framework activation, MuMu compatibility, or accepted school records.
