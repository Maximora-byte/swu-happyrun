# Native completed-simulation recovery delta

This independent delta extends the reviewed foreground-session runtime. It is separate from Python Issue36 and from the currently frozen Android/HTTPS integration candidate.

The only newly successful path is an explicitly server-approved `verify_only` grant for a simulation whose token-free journal already contains a valid durable bind → start intent → finished-stop sequence. Start and finished-stop must have the same original fence. The current authorized binding must retain the exact job, session and full JobSpec digest, use the device's highest fence, and have a strictly newer fence than that completion stamp.

The runner first stops the fresh in-memory fake driver, transitions directly to verifying, checks the journal proof, renews/checks the lease, then reports completed. Recovery never prepares, starts, ticks, emits finishing or uploads. It does not use a generic reason string as proof, and does not reconstruct old motion. Missing/incomplete evidence remains verification_pending. Cancellation and lease loss retain their existing fail-closed paths.

Journal APIs and replay both enforce bind-before-start/stop and current-fence ordering. A recovery stop cannot invent a finished stamp under a newer fence. An explicit incomplete stop clears a prior completion claim. Successful read-only recovery does not append an incomplete stop that would destroy valid history. Existing production journals containing the proper ordering remain readable; invalid legacy/orphan records fail closed rather than being repaired or discarded. Credentials and tokens are not journal fields.

The journal's checksum detects accidental corruption, not malicious rewriting by the same local account/process. A caller able to fabricate complete records can fabricate local synthetic data; this is not evidence of accepted school records or a physical run. Per-device file locking, durable writes and healthy storage remain mandatory.

Evidence: the old runner failed a real-journal-reopen test after actual synthetic-route completion and stopped persistence; expected completed, observed needs_attention. The amended runner completes without new start or motion, and emits only verifying/completed. Tests also check fresh-fence and identity/spec binding, start-only/incomplete histories, stale record writes, valid-checksum orphan records and mismatched start/stop fences. Pure JVM tests are not ART or device acceptance. Separate cross-process real HTTPS verification is required before integration; current candidate files are unchanged.
