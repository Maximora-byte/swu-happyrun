# PR #12 acceptance-design coverage map

This maps all 50 original planned IDs to executable checks. Mapping is not a passing claim: the final candidate run report supplies immutable composition, commands, platform, and results. Component API tests use FastAPI TestClient; `tests/integration/test_http_*` use actual uvicorn loopback TCP. The runner suite also uses real HTTPX and packaged FakeDriver; crash/lock cases launch independent Python processes. Schedule integration creates via HTTP and observes durable rows with read-only SQLite queries. No physical device, real login/upload, or accepted school record is exercised.

Abbreviations: `api/auth/idem/leases/records/scheduler` are `tests/server/test_api.py`, `test_auth.py`, `test_idempotency.py`, `test_leases.py`, `test_record_binding.py`, `test_scheduler.py`; `http/runner/sched` are the three `tests/integration/test_http_*.py` modules. `models` is `tests/contracts/test_models.py`.

| Original ID | Executable coverage | Remaining distinction |
|---|---|---|
| S0-01 | api.test_health; HTTP fixture health readiness | None in synthetic scope |
| S0-02 | auth.test_invalid_auth_is_401; duplicate authorization headers | No credential is real |
| S0-03 | auth agent-create/admin-hello; API invalid command roles | Role guard shared; not every route/role pair individually enumerated |
| S0-04 | auth.test_agent_cannot_impersonate | hello tested; heartbeat uses same identity guard |
| S0-05 | auth assigned/unassigned owner tests; http.test_wrong_agent_lease_and_recovery_cannot_read_or_claim | Ownership transfer intentionally absent from final C1 |
| S0-06 | idem.test_create_replay_returns_same_job; delivery real CLI smoke | None |
| S0-07 | idem.test_key_reuse_with_changed_body_is_409 | None |
| S0-08 | idem.test_two_connections_create_one_job | Two SQLite store connections, not TCP creation race |
| S0-09 | api.test_restart_reads_same_job; delivery smoke restart | None |
| S0-10 | api validation/malformed JSON; models naive/window/unknown/wire constraints | Full input matrix is shared-model level |
| S0-11 | api.test_hello_and_heartbeat; http.test_renew_heartbeat_and_wrong_lease | None |
| S0-12 | idem.test_busy_database_returns_retryable_503 | Real SQLite writer lock through TestClient |
| S0-13 | auth public-view/database/repr tests; models token repr; delivery smoke logs | Log scan covers smoke and redacted failures, not every possible third-party log |
| S1-01 | leases two-store-connection claim; http.test_two_independent_tcp_claim_connections | None |
| S1-02 | http.test_two_jobs_same_device_only_one_grant; expired-running reservation test | None |
| S1-03 | http start-not-before/unknown capability; leases stale/replayed/backward probe tests | Backend/capability are assertions, never physical proof |
| S1-04 | http.test_renew_heartbeat_and_wrong_lease | None |
| S1-05 | http wrong lease/wrong agent; stale fence stop-ack and expired event replay | None |
| S1-06 | leases/http duplicate event snapshot | None |
| S1-07 | http.test_event_duplicate_payload_and_old_snapshot | None |
| S1-08 | same test replays old accepted snapshot after ready | None |
| S1-09 | same test after expiry; stop-ack newer device fence | None |
| S1-10 | http.test_stale_revision_and_terminal_resume_rejected; leases illegal recovery edges | None |
| S1-11 | runner.test_running_receipt_loss_no_start; server running receipt loss | HTTP commit succeeds then response is deliberately discarded by wrapper |
| S1-12 | http.test_safe_pre_running_expiry_requeues [leased/preflight/ready] | None |
| S1-13 | http expired-running restart; leases retry-preflight historical phase; runner process crash | Running covered end-to-end; full finishing/verifying phase Cartesian matrix not separately TCP |
| S1-14 | runner upload_uncertain recovery; process crash; HTTP verify-only past deadline | Fake uncertainty only; no real upload adapter/record service exists |
| S1-15 | http wrong-agent recovery + verify-only identity/fence; leases action restrictions | None |
| S1-16 | http recovery-expiry/new-approval/started retry refusal; stale revision | None |
| S1-17 | leases.test_cancel_noop_does_not_increment_revision | None |
| S1-18 | http cancel-first vs success-first; leases cancel requires ack | Both commit orders controlled; no probabilistic thread race needed |
| S1-19 | http.test_offline_cancel_requires_explicit_stop_recovery; lease expiry/restart reservation | None |
| S1-20 | http lost-ack replay/new-fence; runner lost-ack exact UUID replay; stop-only beyond deadline | Response-loss injection is after a real HTTP commit |
| S1-21 | http complete rejects fake succeeded; records simulation evidence rejection; models | None |
| S1-22 | models record/evidence consistency; runner unknown remains attention; records bound valid checks | Device success fixture is structural, not school acceptance |
| S1-23 | records wrong fields/cross-job digest/record reuse; C1 conflicting canonical alias tests | No real adapter record provenance claim |
| S2-01 | scheduler.test_schedule_duplicate_and_path_mismatch | None |
| S2-02 | models.test_schedules_reject_ambiguous_inputs | Shared-model validation rather than every malformed case over TCP |
| S2-03 | scheduler.test_midnight_shanghai_is_previous_utc_date | None |
| S2-04 | scheduler template duration; sched.test_automatic_schedule_tick_restart_once | None |
| S2-05 | scheduler.test_two_schedulers_atomic_occurrence; sched automatic tick/restart once | Two stores plus actual background lifespan path |
| S2-06 | scheduler.test_expired_occurrence_skipped; sched expiry no backfill | None |
| S2-07 | scheduler disabled and downtime skipped-date tests | Re-enable/edit semantics should be checked in local acceptance if used |
| S2-08 | scheduler.test_schedule_update_does_not_modify_generated_job | None |
| S2-09 | scheduler.test_occurrence_insert_failure_rolls_back_job; restart once | SQLite abort trigger tests rollback; no power-loss durability claim |
| S2-10 | leases restart reservation/probe age; http expired-running restart/offline cancel | None |
| S2-11 | delivery smoke credential log scan; API redaction tests | Real personal configuration never loaded |
| S2-12 | delivery static Dockerfile/Compose assertions | Docker unavailable: config/build/container health NOT RUN |
| S2-13 | delivery subprocess server restart/idempotency and HTTP restart | Container/volume restart NOT RUN because Docker absent |
| S2-14 | installed core/server/agent isolated venv verification; build/frozen install | Linux Python version recorded separately; Windows hosted CI is not real device acceptance |

## Explicit unverified acceptance levels

- MuMu Android 15 location/sensor/app interaction and vivo no-Root paths: not exercised.
- Real app selectors, school profile/route/rules, signed-in session, upload, and accepted record: not exercised and never inferred from fake completion.
- Docker image build/runtime/volume restart: unavailable in this execution environment.
- Windows local installer/device execution: must be independently run by local Codex. Hosted Windows unit CI, if green, proves only its named checks.
