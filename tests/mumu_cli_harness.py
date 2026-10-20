"""One explicit raw vendor point plus independent own-APK observation.

This experiment neither needs nor creates calibration, never retries a write,
and never releases its unresolved reservation or enables trajectory playback.
"""

import json
import math
import os
from dataclasses import asdict
from uuid import uuid4

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.command import ProbeError, run_readonly
from swu_happyrun.drivers.mumu.binding import resolve_binding
from swu_happyrun.drivers.mumu.virtual_replay import (
    VirtualReplaySession,
    _read_calibration,
    _read_control_commands,
    _run_control_loop,
    read_private_json,
)


def _synthetic_run_probe_point_cli(args, *, point, clock, emit, native_factory, probe_factory):
    from swu_happyrun.agent.lifecycle import Shutdown

    if args.private_output is not None and (
        args.private_output.exists() or args.private_output.is_symlink()
    ):
        raise DriverError("private_output_exists")

    binding = resolve_binding(
        instance_index=args.instance,
        adb_serial=args.serial,
        observation=read_private_json(args.binding),
        now=clock.utcnow(),
    )
    shutdown = Shutdown()
    report = {
        "status": "needs_attention",
        "command_status": "not_attempted",
        "observation_status": "not_attempted",
        "stop_status": "not_attempted",
        "sample_count": 0,
        "private_evidence_saved": False,
        "replay_enabled": False,
        "record_verified": False,
    }
    native = None
    permit = None
    session_id = str(uuid4())
    # Local experiment budget only. Native writes are separately capped to 5s.
    deadline = clock.monotonic() + 45.0

    def binding_check():
        binding.assert_current(read_private_json(args.binding), now=clock.utcnow())
        boot = run_readonly(
            args.adb,
            "-s",
            args.serial,
            "shell",
            "cat",
            "/proc/sys/kernel/random/boot_id",
            timeout=5,
        ).strip()
        if boot != binding.boot_id:
            raise DriverError("binding_changed")

    with RunJournal(args.journal) as journal, shutdown.signals():
        try:
            with journal.device_lock(args.device_id):
                permit = journal.reserve_replay(args.device_id, session_id, generation=1)
                journal.record_intent(session_id, 1, "start")

                def check():
                    shutdown.check()
                    journal.verify_replay(permit, generation=1)
                    if not journal.has_intent(session_id, "start"):
                        raise DriverError("replay_intent_missing")
                    now = clock.monotonic()
                    if type(now) not in (int, float) or not math.isfinite(now) or now >= deadline:
                        raise DriverError("probe_budget_expired")
                    shutdown.check()

                try:
                    native = native_factory(
                        args.manager,
                        binding,
                        adb=args.adb,
                        binding_check=binding_check,
                        authorization_check=check,
                        clock=clock,
                    )
                    try:
                        native.write_location(point, deadline=min(deadline, clock.monotonic() + 5))
                        report["command_status"] = "command_acknowledged"
                    except DriverError as error:
                        report["command_status"] = error.reason_code
                        # A timeout or uncertain child/pipe cleanup never authorizes
                        # another command, including an observation invocation.
                        delivery = native.last_delivery
                        if (
                            error.reason_code != "write_ack_unconfirmed"
                            or delivery is None
                            or delivery.command_completed is not True
                        ):
                            raise
                        check()
                        journal.update_replay(
                            permit, generation=1, status="active", probe_pending=True
                        )
                        probe = probe_factory(
                            args.adb,
                            binding,
                            binding_check=binding_check,
                            authorization_check=check,
                        )
                        try:
                            samples = probe.sample("location", duration_ms=args.duration_ms)
                        except ProbeError as failure:
                            report["observation_status"] = failure.code
                            raise
                        journal.update_replay(
                            permit, generation=1, status="active", probe_pending=False
                        )
                        report["observation_status"] = "samples_observed"
                        report["sample_count"] = len(samples)
                        if args.private_output is not None:
                            # Explicit local-only evidence; exclusive create never
                            # overwrites an existing file or follows a symlink.
                            descriptor = os.open(
                                args.private_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                            )
                            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                                json.dump(
                                    {
                                        "schema": 1,
                                        "binding_digest": binding.digest,
                                        "binding_identity_digest": binding.identity_digest,
                                        "boot_id": binding.boot_id,
                                        "target": point.model_dump(mode="json"),
                                        "coordinate_semantics": "raw_vendor_unverified",
                                        "samples": [asdict(sample) for sample in samples],
                                    },
                                    stream,
                                )
                                stream.flush()
                                os.fsync(stream.fileno())
                            report["private_evidence_saved"] = True
                finally:
                    journal.record_result(session_id, 1, "start", "uncertain")
                    if native is not None:
                        try:
                            native.stop()
                            report["stop_status"] = "native_stop_confirmed"
                        except DriverError as error:
                            report["stop_status"] = error.reason_code
                    # Even a future native stop acknowledgment cannot turn this
                    # raw-parameter experiment into calibration or replay authority.
                    journal.update_replay(permit, generation=1, status="uncertain")
        except (Exception, KeyboardInterrupt) as error:
            code = (
                error.reason_code
                if isinstance(error, DriverError)
                else error.code
                if isinstance(error, ProbeError)
                else "probe_reservation_unresolved"
                if isinstance(error, UnsafeReplay)
                else "probe_interrupted_or_local_error"
            )
            report["reason_code"] = code
        emit(report)
        return 3


def _synthetic_run_local_cli(args, *, execution, clock, emit, native_factory, probe_factory):
    """Test-only orchestration; caller injects synthetic adapters."""
    import sys
    from queue import Queue
    from threading import Thread

    from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested
    from swu_happyrun.drivers.command import ProbeError, run_readonly
    from swu_happyrun.drivers.mumu.binding import resolve_binding

    binding = resolve_binding(
        instance_index=args.instance,
        adb_serial=args.serial,
        observation=read_private_json(args.binding),
        now=clock.utcnow(),
    )
    calibration = None if args.recover_stop else _read_calibration(args.calibration, binding, clock)

    def binding_check():
        binding.assert_current(read_private_json(args.binding), now=clock.utcnow())
        boot = run_readonly(
            args.adb,
            "-s",
            args.serial,
            "shell",
            "cat",
            "/proc/sys/kernel/random/boot_id",
            timeout=5,
        ).strip()
        if boot != binding.boot_id:
            raise DriverError("binding_changed")

    def calibration_check():
        if calibration is None:
            raise DriverError("replay_location_calibration_required")
        calibration.validate(binding, now=clock.utcnow(), channel="location")

    shutdown = Shutdown()
    commands = Queue(maxsize=16)
    with RunJournal(args.journal) as journal, shutdown.signals():
        session = VirtualReplaySession(
            execution,
            journal=journal,
            device_id=args.device_id,
            native_factory=lambda check: native_factory(
                args.manager,
                binding,
                adb=args.adb,
                binding_check=binding_check,
                authorization_check=check,
                clock=clock,
            ),
            probe_factory=lambda check: probe_factory(
                args.adb,
                binding,
                binding_check=binding_check,
                authorization_check=check,
            ),
            authorization_check=shutdown.check,
            calibration_check=calibration_check,
            max_error_m=calibration.max_error_m if calibration else 1.0,
            clock=clock,
        )

        try:
            if args.recover_stop:
                emit(session.recover_stop())
                return 0
            emit(session.start())
            if not args.no_interactive:
                Thread(
                    target=_read_control_commands, args=(sys.stdin, session, commands), daemon=True
                ).start()
            _run_control_loop(session, shutdown, commands, emit)
            return 0 if session.progress["stop_confirmed"] else 3
        except (
            DriverError,
            ProbeError,
            UnsafeReplay,
            ShutdownRequested,
            KeyboardInterrupt,
        ) as error:
            reason = (
                error.reason_code
                if isinstance(error, DriverError)
                else error.code
                if isinstance(error, ProbeError)
                else "replay_interrupted_or_unresolved"
            )
            emit(
                {
                    "status": "needs_attention",
                    "reason_code": reason,
                    "stop_confirmed": False,
                    "record_verified": False,
                }
            )
            return 3
        finally:
            # A failed start still left durable intent before any device action.
            try:
                if session._native is not None and not session.progress["stop_confirmed"]:
                    try:
                        emit(session.stop())
                    except DriverError:
                        emit(session.progress)
            finally:
                # Storage/reporting failures must not skip process-lock release.
                # Closing never clears the durable marker or acknowledges stop.
                session.close()
