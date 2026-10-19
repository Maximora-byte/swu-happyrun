# Optional selfProbe APK packaging

This follow-up is based on first-APK lint-fix candidate `d2862a84135edeb447c27ba3494d49ca4d00b001`. It does not modify that frozen candidate or claim its CI covers this variant.

The ordinary debug APK contains the inert, dependency-free `SelfProbe` diagnostic but no `SelfDiagnosticModule`, `assets/xposed_init`, or Xposed module metadata. Only the explicitly selected `selfProbe` build type includes those entrypoints. Both variants use application ID `org.happyrun.app`; they replace each other, not install side by side. Same-job builds use the same temporary debug signing certificate, verified from `apksigner --print-certs`; different jobs/runs may have different certificates. Never automatically uninstall an existing app or erase user tasks to resolve signing incompatibility.

## Dependency boundary

Only `selfProbeCompileOnly` resolves `de.robv.android.xposed:api:82`, without transitive dependencies. Gradle `exclusiveContent` resolves that group solely from `https://api.xposed.info/`; artifact-only metadata avoids trusting an unpinned POM dependency graph. `verifySelfProbeApi`, required by `preSelfProbeBuild`, validates exact coordinates, the independently recorded API JAR SHA256, and its absence from the runtime classpath before variant compilation. The CI also invokes verification explicitly. This is a narrowly scoped Gradle verification task, not a claim that all existing AGP/JUnit dependencies have global verification metadata. It does not disable existing dependency checks or trust a blanket artifact wildcard.

The recorded JAR digest is in `android/dependency-pins/xposed-api-82.json`. No JAR is vendored, and no Xposed framework implementation may be packaged in either APK. [Official API documentation](https://github.com/rovo89/XposedBridge/wiki/Using-the-Xposed-Framework-API) requires compile-only/provided API use; the runtime framework supplies its implementation.

## CI evidence

The independent `android-self-probe` job builds both APKs on API31/API35 test matrices, preserving the ordinary Android and Python/browser jobs. It:

1. Builds/lints/tests both variants and compiles the selfProbe instrumentation APK.
2. Uses official SDK `apkanalyzer` to inspect actual APK manifests, DEX class definitions and scope resources; verifies exact self scope and absence of packaged Xposed implementation. Source inspection alone is insufficient.
3. Verifies signatures and same certificate in that job; records both APK hashes.
4. Installs ordinary debug on a disposable official AVD, runs a no-framework inactive diagnostic, then replaces it with the same-signed selfProbe APK and repeats the inactive diagnostic.

No framework is installed or enabled, and no Root or external application scope is changed. These two inactive tests establish only the no-framework behavior. ART activation, disabling/restarting, actual LSPosed/Kitsune builds and broader user-selected scope require separate approved device validation. A successful build/install cannot establish them. Exact tests and APK inspection remain pending until this follow-up's own immutable Actions run succeeds.

The 7-day artifact allowlist contains only the two APKs, bounded synthetic reports, emulator logs/screenshots, certificate information and checksums; no database or signing private key. Android APK certificate digests are public identification metadata, not credentials.

## Variant identity

BuildConfig.SELF_PROBE_ENABLED is false by default and true only for selfProbe. The first-run UI may use it to identify packaged module capability; it does not establish framework installation, activation or a successful hook receipt. Runtime SelfProbe.inspect() remains the only in-process diagnostic receipt.
