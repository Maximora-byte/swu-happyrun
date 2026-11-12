# Android onboarding integration candidate

Baseline: 629f2e9b86d7a72502f528abd1c1edf999d6a842; rebased from the independently reviewed cf3 onboarding combination. Final immutable candidate HEAD is bound by the PR and Actions, not inferred from this document.

## Composition and ownership

The independent combination preserves the baseline's API31 stable default image, API35 Google APIs image, private Android/AVD home, explicit AVD path, creation visibility checks and early emulator-process failure checks. The emulator script adds only parameterized instrumentation APK and acceptance-script paths.

Sources: self-scope module f0dd4762fc699d4032dd48fde6d46d301ad5356b; read-only Root diagnostic and three-state receipt 3f26fdeaf9cf046aa9e663dd956fb5507da794b6; self-probe UI followed by novice-wizard UI (the latter replaces MainActivity and IDs); independent four-case wizard QA; separately reviewed optional build/packaging delta. Integration manifests record exact file hashes and overridden owners. Worker .gitignore snapshots are not copied over the newer baseline.

## One entry point

Both builds show the same native wizard. BuildConfig.SELF_PROBE_ENABLED describes whether this APK packages the optional self-only module entry. Runtime inactive/unknown/active is a separate live receipt. The intended user-facing candidate is one optional APK that also starts without a framework, but it is not recommended or accepted until same-HEAD no-framework installation and same-signature replacement tests pass. Ordinary debug remains an internal comparison build.

The read-only Root check requires its explicit confirmation button; opening the app, refreshing diagnostics and cancelling the confirmation must not invoke it. No automatic framework installation, Root setting modification, external-package scope or real execution is enabled. Framework API receipt is not a framework release version or a security attestation.

## Evidence boundaries

CI keeps the original eleven native APK cases separate. The optional job first checks one inactive/installed-variant case and four wizard cases on debug, then replaces it with the same-job signed optional APK and repeats. Wizard reports and inactive reports are separate. Wizard tests cancel the Root confirmation; active/pending states are explicitly injected UI fixtures. They never authorize a real su command.

The optional and debug APK share one application ID, so they cannot coexist. Only matching signatures support replacement. Never automatically uninstall a user's app to overcome a signature mismatch or erase local history. CI uses disposable synthetic state and temporary debug signing; this is not a production signing identity.

Local Java/Python checks and artifact inspection are listed separately from hosted Android builds and AVD runs. MuMu, the user's modified image, ART activation/disable/restart, live Root-manager decisions and school records remain outside these software checks.


## Bounded launch profiles

The startup probe retains its default core profile (app_scroll, task_state, start_simulation). This onboarding candidate explicitly selects the allowlisted wizard profile (app_scroll, framework_probe, wizard_refresh) for the ordinary CI job and both optional-job installations. Unknown profiles and the wrong/empty first screen fail. Root controls are not required to be visible and the launch probe performs no UI clicks.

The same resumed MainActivity, exact package, positive bounds, deadline, ANR/crash and command-error checks apply to both profiles. The optional replacement gets its own diagnostic subdirectory and exact artifact whitelist. Stable API31/default, private AVD directories and early process failure checks from the launch baseline are retained.

## Following the first hosted run

The next candidate is based on6427e91b7099cdf2233983ff55a5bcf9718e6b61. Real hosted variant compilation/lint passed, but numeric scope-reference inspection and Windows default decoding failed. These are corrected with exact compiled-resource ID binding and UTF-8 fixtures. API31 screenshots show a SystemUI ANR overlay above the rendered wizard; they do not establish an application ANR or successful instrumentation.

Idle/terminal unconditional polling is removed while active progress polling remains. This reduces unnecessary work without asserting the cause of that system failure. Explicit user refresh can queue behind a background read. Root confirmation and conservative evidence wording are retained.

Each optional-job installation now uses its matching test APK. Both variants run native15 (original11 plus4 isolated polling cases), wizard4 and inactive1 separately. Native fixtures use disposable synthetic state; tests do not authorize Root. Reports and exact allowlisted logs remain distinct. User-approved one-transition KVM gating is documented in the packaging guide; no local ACL grant or actual Root check was performed.
