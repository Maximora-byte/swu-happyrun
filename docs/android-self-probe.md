# Optional self-scope framework diagnostic (follow-up only)

This independent source set is not part of the first APK candidate. It hooks only
`org.happyrun.app.selfprobe.SelfProbe.response(String)` in package AND process
`org.happyrun.app`. Both code and suggested scope reject other applications,
including the running app and Android system. No app-control, location/sensor
injection, upload, Root hiding, authentication or signature bypass is implemented.

Normal `SelfProbe.inspect()` returns inactive without any framework dependency.
The user may install the separately built selfProbe variant, enable its module in
their already configured framework, select only HappyRun's own scope, and restart
HappyRun. We do not enable Root, install frameworks or modify device settings.

A live hooked response must echo a fresh per-call random challenge and a positive
Xposed bridge/API version. Nothing reads SharedPreferences, files, broadcasts or
`su` presence to infer activation. No result is persisted. This is a local method
activation diagnostic, NOT security attestation: another malicious module in the
same process can fabricate a result. It cannot prove framework brand, LSPosed
release/version, target-app compatibility, device permissions or school acceptance.
The UI must label the integer `Xposed bridge/API version`, never `LSPosed version`.

## Build integration proposed for a separate PR

The following changes require the packaging owner to apply to the then-current
base; they have NOT been applied to the frozen first candidate:

1. In android/settings.gradle, add the narrowly scoped official repository to
   dependencyResolutionManagement.repositories:
   `exclusiveContent { forRepository { maven { url 'https://api.xposed.info/' } }; filter { includeGroup 'de.robv.android.xposed' } }`
   Use exclusiveContent, not merely a repository content filter: other repositories
   must not supply this dependency group.
2. In app/build.gradle's android block, add a dedicated build type:
   `buildTypes { selfProbe { initWith debug; matchingFallbacks = ['debug']; minifyEnabled false } }`
   Keep the same application ID. This optional variant replaces the same app only
   with a compatible signing identity; installation/update remains user-controlled.
3. Add only `selfProbeCompileOnly 'de.robv.android.xposed:api:82'`.
   Never use implementation: framework API classes must not be packaged.
4. Build `:app:assembleSelfProbe`; inspect merged manifest and APK to verify its
   sole scope is org.happyrun.app and Xposed API classes are absent. Normal debug
   build must have no xposedmodule metadata or module entry asset.
5. Wire a read-only diagnostic UI to `SelfProbe.inspect()` in a separate reviewed
   change; inactive is expected until actual framework loading succeeds. Do not
   enable any ExecutionAdapter based on this result.

Dependency retrieved only from official host:
https://api.xposed.info/de/robv/android/xposed/api/82/api-82.jar
SHA256: f48c635f1c7469fdec0e00ad2ea0b7a6b2f5b55065784a35b7ca3a84615e8e25
This is a recorded artifact digest, not a publisher signature. Gradle dependency
verification must pin that digest before release; no random mirror fallback.
No dependency binary is included in source or runtime APK.

## Official API references

- [Xposed API use](https://github.com/rovo89/XposedBridge/wiki/Using-the-Xposed-Framework-API)
  requires a provided/compile-only API, with implementation supplied by framework.
- [XposedBridge](https://api.xposed.info/reference/de/robv/android/xposed/XposedBridge.html)
  documents getXposedVersion and hookMethod.
- [LSPosed module scope](https://github.com/LSPosed/LSPosed/wiki/Module-Scope)
  documents xposedscope metadata as recommended scope; runtime code independently
  enforces own package/process even if a user selects a broader scope.

The legacy API is chosen because these exact entrypoints and artifact are verified.
It does not establish compatibility with every current LSPosed fork/build. Modern
libxposed repository links returned 404 in this review; no replacement API was
invented.

## Verification boundaries

Pure Java tests: own package/process accepted; third-party/system/subprocess/null
rejected; no framework inactive; stale/malformed challenge and invalid version
rejected. API82 entrypoint compiled against the official jar. These tests do not
execute an ART hook. Actual optional APK build, no-framework launch, own-scope
activation, disable/restart returning inactive, and broad selected scope causing
no hooks outside HappyRun require Android/framework-device validation. Record
exact emulator image, Android build and framework version independently.
