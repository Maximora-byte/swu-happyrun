# Bounded traceback reporter comparison

This branch is diagnostic evidence only, not a product fix or native acceptance.
The main CI reporters and all product code remain unchanged. Each arm runs one
fixed test, with a 60-second observation and a 10-minute outer job budget.

## Original failure

- Product HEAD: ed87ddc6fd07831115ab16108c9a4093c7c7290d.
- Windows CPython 3.11.9 job: https://api.github.com/repos/Maximora-byte/swu-happyrun/actions/jobs/118629320285
- Node: tests/agent/test_enrollment_transaction.py::test_diagnosis_missing_stage_or_candidate_never_repairs[candidate-v1.json].
- At 12:42:24 UTC, the 60-second dump printed a pathlib stat frame and then
  faulted midway through another pathlib filename line. The Windows access
  violation reporter faulted again during its own traceback. No pytest summary.

## First isolated comparison

- Diagnostic HEAD: ae481caa73d1134cb53c7aab2a47018b894a161d.
- Run: https://github.com/Maximora-byte/swu-happyrun/actions/runs/39428545105
- Same original node, Windows CPython 3.11.9, separate fresh runner per arm.
- Async arm passed in 45.391 seconds; Python-thread arm passed in 44.078 seconds.
- Neither reached the 60-second observation. This result does not test either
  reporter's dump path, establish a root cause, or demonstrate a fix.

## New independent failure and next comparison

- Current PR 106 HEAD prefix: c6ab2ce.
- Job: https://github.com/Maximora-byte/swu-happyrun/actions/runs/39428735087/job/118647872472
- Node: tests/agent/test_enrollment_review_pin.py::test_journal_intent_and_result_changes_preserve_pin_not_ready.
- At 13:16:01 UTC the 60-second timeout again faulted after a pathlib filename.
  Its fatal traceback continued through enrollment_transaction._observe,
  enrollment_review_pin._frozen/revalidate/load_review_pin and test line 110.
  The process exited 1 without a pytest summary.
- This node and its product implementation are unchanged between the original
  diagnostic base and c6ab2ce. It uses the same synthetic transaction fixture.
- The next comparison selects this newly failing node; threshold, fatal handler,
  interpreter, dependencies and outer budget stay unchanged. No added load,
  retry, skipped errors, or altered production validation.

A Python-thread reporter acquires the GIL before faulthandler.dump_traceback.
It cannot fire while another thread indefinitely holds the GIL. One run per arm
cannot establish an intermittent crash's cause, even when both reporters fire.
Native crash-stack evidence would be stronger than Python-only stack metadata.
