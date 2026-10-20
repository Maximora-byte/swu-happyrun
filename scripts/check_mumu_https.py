"""Explicit own-app MuMu simulation acceptance, separate from the official AVD harness.

Never installs, resets app data, discovers a serial, or changes any device setting.
Raw instrumentation, binding data and credentials must remain local and unreported.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

PACKAGE = "org.happyrun.app"
CLASS = PACKAGE + ".remoteqa.RemoteMumuHttpsAcceptanceTest#testScenario"
CASES = ("completed", "two_jobs", "disconnect_running", "lost_renew", "cancel", "restart")
CAPABILITY = "mumu-own-simulation-v1"


def execution_gate(execute, force_stop):
    if execute is not True or force_stop is not True:
        raise ValueError("explicit_own_simulation_and_force_stop_required")


def private_host(value):
    try:
        host = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("explicit_private_numeric_host_required") from None
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
    if host.version != 4 or not any(host in ipaddress.ip_network(n) for n in networks):
        raise ValueError("explicit_private_ipv4_host_required")
    if host.is_unspecified or host.is_multicast or host.is_link_local:
        raise ValueError("unsafe_bind_address")
    return str(host)


def serial_value(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:\[\]-]{0,127}", value
    ):
        raise ValueError("explicit_safe_serial_required")
    return value


def apk_path(output):
    lines = output.strip().splitlines()
    if len(lines) != 1 or not re.fullmatch(
        r"package:/data/app/[A-Za-z0-9_./~+=-]+/base\.apk", lines[0]
    ):
        raise RuntimeError("single_installed_base_apk_required")
    path = lines[0].removeprefix("package:")
    if ".." in path.split("/"):
        raise RuntimeError("invalid_installed_apk_path")
    return path


def parse_result(output, code, case):
    if code != 0 or len(re.findall(r"OK \(1 test\)", output)) != 1:
        raise RuntimeError("instrumentation_failed")
    if output.count("INSTRUMENTATION_CODE: -1") != 1 or re.search(
        r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)|Exception|shortMsg=", output
    ):
        raise RuntimeError("instrumentation_failed")
    matches = re.findall(
        r"^MUMU_HTTPS PASS case=([a-z_]+) starts=(\d+) stopped=true$", output, re.M
    )
    if len(matches) != 1 or matches[0][0] != case:
        raise RuntimeError("ambiguous_result")
    starts = int(matches[0][1])
    expected = {"two_jobs": 2, "restart": 0}.get(case, 1)
    if starts != expected:
        raise RuntimeError("unexpected_start_count")
    return {"starts": starts, "stopped": True}


def not_run_report(reason):
    return {
        "schema_version": 1,
        "runtime_status": "not_run",
        "cases": [{"case": case, "result": "not_run", "reason": reason} for case in CASES],
        "simulation_only": True,
        "device_verified": False,
        "activity_ui_verified": False,
        "school_record_verified": False,
    }


def private_run_directory(root):
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("symlink_private_directory_rejected")
    if not root.is_dir():
        raise ValueError("existing_private_directory_required")
    result = root / str(uuid4())
    result.mkdir(mode=0o700)
    return result


class BoundSession:
    """Monotonic freshness is local to this process, never serialized or invented."""

    def __init__(self, instance, serial, boot, signature):
        self.instance, self.serial, self.boot, self.signature = instance, serial, boot, signature
        self.checked_at = time.monotonic()

    def assert_fresh(self):
        age = time.monotonic() - self.checked_at
        if not 0 <= age <= 30:
            raise RuntimeError("binding_observation_expired")


def require_adapter(manifest):
    relative = (
        "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
        "RemoteMumuHttpsAcceptanceTest.java"
    )
    expected = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / relative).read_bytes()
    ).hexdigest()
    adapter = manifest.get("adapter") or {}
    if manifest.get("runtime_capabilities") != [CAPABILITY] or adapter.get("files") != [
        {"path": relative, "sha256": expected}
    ]:
        raise RuntimeError("guarded_adapter_missing_or_mismatched")


def instrument_command(args, binding, fixture, case, run_id, stage="run"):
    if case not in CASES or stage not in {"run", "recover"}:
        raise ValueError("unknown_case_or_stage")
    values = {
        "scenario": case,
        "stage": stage,
        "origin": fixture["origin"],
        "agent": fixture["agent_id"],
        "device": fixture["device_id"],
        "token": fixture["agent_token"],
        "runId": run_id,
        "signatureSha256": binding.signature,
        "bootId": binding.boot,
        "taskId": str(binding.task),
        "displayId": str(binding.display),
        "allowOwnSimulation": "yes",
        "isolated": "yes",
    }
    # adb shell forwards arguments through a device shell. Even with shell=False,
    # permit only this fixed grammar; no quotes, whitespace or shell operators.
    if any(not re.fullmatch(r"[A-Za-z0-9_./:-]+", value) for value in values.values()):
        raise ValueError("unsafe_instrumentation_argument")
    command = [
        str(args.adb),
        "-s",
        serial_value(args.serial),
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        CLASS,
    ]
    for key, value in values.items():
        command.extend(["-e", key, value])
    return [*command, PACKAGE + ".test/android.test.InstrumentationTestRunner"]


def canonical_android_release(value):
    """1–3 ASCII components, 0..999; positive major; only trailing zeros collapse."""
    if (
        not isinstance(value, str)
        or len(value) > 11
        or re.fullmatch(r"[1-9][0-9]{0,2}(?:\.(?:0|[1-9][0-9]{0,2})){0,2}", value) is None
    ):
        raise RuntimeError("android_release_format_unknown")
    components = tuple(int(part) for part in value.split("."))
    while len(components) > 1 and components[-1] == 0:
        components = components[:-1]
    return components


def validate_current(binding, pair, observed):
    expected = {
        "state": "device",
        "boot": binding.boot,
        "engine_version": canonical_android_release(binding.engine_version),
        "host_version": binding.host_version,
        "instance_running": True,
        "app_sha256": pair["app"]["sha256"],
        "test_sha256": pair["test"]["sha256"],
    }
    comparable = dict(observed)
    comparable["engine_version"] = canonical_android_release(observed.get("engine_version"))
    if comparable != expected:
        raise RuntimeError("current_instance_or_installed_pair_mismatch")


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def assert_recovery_identity(recovered, session_id, previous_fence):
    require(recovered["run_session_id"] == session_id, "recovery_session_changed")
    require(recovered["fence"] > previous_fence, "recovery_fence_not_advanced")


def assert_server_result(case, views, evidence):
    require(len(views) == (2 if case == "two_jobs" else 1), "unexpected_job_count")
    if case in {"completed", "two_jobs"}:
        require(all(v["state"] == "completed" for v in views), "server_not_completed")
    elif case == "cancel":
        require(views[0]["state"] == "cancelled", "cancel_not_final")
        require(
            any(r["path"].endswith("/stop-ack") and r["status"] == 200 for r in evidence.records),
            "stop_ack_not_observed",
        )
    elif case == "restart":
        require(views[0]["state"] == "needs_attention", "uncertain_restart_cannot_complete")
        require(views[0]["reason_code"] == "verification_pending", "verify_only_not_observed")
    elif case == "lost_renew":
        require(evidence.fault_used and evidence.renew_count == 4, "fault_not_exercised")
        require(views[0]["state"] in {"running", "needs_attention"}, "unexpected_lost_renew_state")
    elif case == "disconnect_running":
        require(views[0]["state"] in {"running", "needs_attention"}, "unexpected_disconnect_state")
    else:
        raise ValueError("unknown_case")


def reserve_report(args):
    import os

    output = args.output.absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("symlink_report_path_rejected")
    inputs = (args.bundle, args.ca_cert, args.server_cert, args.server_key, args.binding)
    if any(value is not None and output.resolve() == value.resolve() for value in inputs):
        raise ValueError("report_aliases_input")
    if output.resolve().is_relative_to(args.bundle.resolve()):
        raise ValueError("report_inside_bundle_rejected")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output, flags, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def case_report(case, result, body_error, fixture_error, cleanup_error, controller_error):
    errors = (body_error, fixture_error, cleanup_error, controller_error)
    return {
        **(result or {}),
        "case": case,
        "result": "passed" if result is not None and not any(errors) else "failed",
        "body_error_type": body_error,
        "fixture_error_type": fixture_error,
        "cleanup_error_type": cleanup_error,
        "controller_error": controller_error,
    }


class OwnAdb:
    def __init__(self, executable, serial):
        self.prefix = [str(executable), "-s", serial_value(serial)]

    def raw(self, *arguments, timeout=20):
        result = subprocess.run(
            [*self.prefix, *arguments],
            check=True,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
        return result.stdout

    def query(self, *arguments):
        return self.raw(*arguments).decode("utf-8", errors="strict").strip()

    def installed_hash(self, package):
        if package not in {PACKAGE, PACKAGE + ".test"}:
            raise ValueError("own_packages_only")
        path = apk_path(self.query("shell", "pm", "path", package))
        return hashlib.sha256(self.raw("exec-out", "cat", path)).hexdigest()

    def stop(self):
        self.raw("shell", "am", "force-stop", PACKAGE)


def open_binding(args, pair):
    from swu_happyrun.drivers.mumu.binding import resolve_binding

    raw = json.loads(args.binding.read_text(encoding="utf-8"))
    binding = resolve_binding(instance_index=args.instance, adb_serial=args.serial, observation=raw)
    if binding.package != PACKAGE or binding.app_version != pair["version_name"]:
        raise RuntimeError("own_package_binding_required")
    bound = BoundSession(
        binding.instance_index, binding.adb_serial, binding.boot_id, pair["certificate_sha256"]
    )
    bound.engine_version, bound.host_version = binding.engine_version, binding.host_version
    bound.task, bound.display = binding.task_id, binding.display_id
    return bound


def refresh_binding(args, binding, pair, adb):
    from swu_happyrun.drivers.mumu.discovery import host_version
    from swu_happyrun.drivers.mumu.manager import MuMuManager

    instances = MuMuManager(args.manager).inspect(args.instance)
    running = (
        len(instances) == 1
        and instances[0].index == binding.instance
        and instances[0].android_started
        and instances[0].process_started
    )
    observed = {
        "state": adb.query("get-state"),
        "boot": adb.query("shell", "cat", "/proc/sys/kernel/random/boot_id"),
        "engine_version": adb.query("shell", "getprop", "ro.build.version.release"),
        "host_version": host_version(args.manager),
        "instance_running": running,
        "app_sha256": adb.installed_hash(PACKAGE),
        "test_sha256": adb.installed_hash(PACKAGE + ".test"),
    }
    # Keep source observations distinct; normalization never rewrites evidence or running flags.
    binding.engine_version_evidence = {
        "manager": {"raw": instances[0].android_version if len(instances) == 1 else None},
        "adb": {"raw": observed["engine_version"]},
        "binding": {"raw": binding.engine_version},
    }
    for evidence in binding.engine_version_evidence.values():
        evidence["canonical"] = canonical_android_release(evidence["raw"])
    if (
        binding.engine_version_evidence["manager"]["canonical"]
        != binding.engine_version_evidence["binding"]["canonical"]
    ):
        raise RuntimeError("manager_android_release_mismatch")
    validate_current(binding, pair, observed)
    # A fresh set of reads on the unchanged identity, NOT a rewritten local-review timestamp.
    binding.checked_at = time.monotonic()


def verify_public_bundle(args):
    from check_local_https_delivery import verify_bundle

    return verify_bundle(
        args.bundle,
        args.ca_cert,
        args.server_cert,
        args.host,
        openssl=args.openssl,
        apksigner=args.apksigner,
        apkanalyzer=args.apkanalyzer,
        aapt2=args.aapt2,
        source_root=getattr(args, "source_root", None),
        expected_source_commit=getattr(args, "expected_source_commit", None),
        expected_source_tree=getattr(args, "expected_source_tree", None),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--ca-cert", type=Path, required=True)
    parser.add_argument("--server-cert", type=Path, required=True)
    parser.add_argument("--host", type=private_host, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--apksigner", default="apksigner")
    parser.add_argument("--apkanalyzer", default="apkanalyzer")
    parser.add_argument("--aapt2", default="aapt2")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-source-tree")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-own-app-simulation", action="store_true")
    parser.add_argument("--allow-own-package-force-stop", action="store_true")
    parser.add_argument("--isolated-no-personal-data", action="store_true")
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--manager", type=Path)
    parser.add_argument("--serial", type=serial_value)
    parser.add_argument("--instance")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--server-key", type=Path)
    parser.add_argument("--private-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        output = reserve_report(args)
    except (OSError, ValueError):
        print("MUMU_HTTPS_REPORT blocked_output")
        return 2
    report = not_run_report("preflight_incomplete")
    code = 2
    try:
        manifest = verify_public_bundle(args)
        report["artifact_preflight"] = "passed"
        require_adapter(manifest)
        if args.execute_own_app_simulation:
            execution_gate(args.execute_own_app_simulation, args.allow_own_package_force_stop)
            if not args.isolated_no_personal_data or any(
                value is None
                for value in (
                    args.adb,
                    args.manager,
                    args.serial,
                    args.instance,
                    args.binding,
                    args.server_key,
                    args.private_dir,
                )
            ):
                raise ValueError("explicit_execution_inputs_required")
            if not re.fullmatch(r"[0-9]+", args.instance):
                raise ValueError("invalid_instance")
            if not 0 <= args.port <= 65535:
                raise ValueError("invalid_port")
            report = execute_suite(args, manifest)
            code = 0 if report["runtime_status"] == "passed" else 1
        else:
            report = not_run_report("operator_execution_not_requested")
            report["artifact_preflight"] = "passed"
            code = 0
    except Exception:
        # Never echo exception text, paths, credentials or external tool output.
        report = not_run_report("preflight_or_execution_blocked")
        report["artifact_preflight"] = "not_passed"
        code = 2
    with output:
        output.write(json.dumps(report, indent=2) + "\n")
    print("MUMU_HTTPS_REPORT", report["runtime_status"])
    return code


def bounded_wait(check, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise RuntimeError("bounded_observation_missing")


def stop_bound_package(binding, adb):
    binding.assert_fresh()
    if adb.query("shell", "cat", "/proc/sys/kernel/random/boot_id") != binding.boot:
        raise RuntimeError("boot_changed_before_stop")
    adb.stop()


class InstrumentationFailure(RuntimeError):
    def __init__(self, diagnostics):
        super().__init__("instrumentation_failed")
        self.diagnostics = diagnostics


def instrumentation_failure(output, timed_out=False):
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    allowed = {
        "AssertionFailedError",
        "AssertionError",
        "IOException",
        "IllegalStateException",
        "ControlException",
        "InterruptedException",
        "other",
    }
    result = {"body": [], "cleanup": [], "timed_out": timed_out}
    for phase, kind in re.findall(
        r"^MUMU_HTTPS FAILURE phase=(body|cleanup) kind=([A-Za-z]+)$", output or "", re.M
    ):
        if kind in allowed and len(result[phase]) < 4:
            result[phase].append(kind)
    return result


def run_instrumentation(command, case):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=90, shell=False
        )
    except subprocess.TimeoutExpired as error:
        raise InstrumentationFailure(instrumentation_failure(error.stdout, True)) from None
    try:
        return parse_result(result.stdout, result.returncode, case)
    except RuntimeError:
        raise InstrumentationFailure(instrumentation_failure(result.stdout)) from None


class OwnedProcessFailure(RuntimeError):
    def __init__(self, body_error, cleanup_errors):
        super().__init__("owned_process_interruption_failed")
        self.diagnostics = {
            "scope": "host_owned_process",
            "body_error_type": body_error,
            "cleanup_error_types": cleanup_errors,
        }


def interrupt_after_durable_start(command, binding, adb):
    import threading

    from remote_https_fixture import error_type

    ready, overflow, reader_failed = threading.Event(), threading.Event(), threading.Event()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
    )
    reader, reader_started = None, False
    body_error, cleanup_errors = None, []

    def read_markers():
        count = 0
        try:
            for line in iter(lambda: process.stdout.readline(4096), ""):
                count += len(line)
                if count > 1024 * 1024:
                    overflow.set()
                if line.strip() == "MUMU_HTTPS READY restart starts=1 persisted_start=true":
                    ready.set()
        except BaseException:
            reader_failed.set()

    try:
        reader = threading.Thread(target=read_markers, daemon=True)
        reader.start()
        reader_started = True
        if (
            not ready.wait(20)
            or overflow.is_set()
            or reader_failed.is_set()
            or process.poll() is not None
        ):
            raise RuntimeError("durable_start_not_observed")
        stop_bound_package(binding, adb)
        process.wait(timeout=10)
    except BaseException as error:
        body_error = error_type(error)
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except BaseException as error:
                cleanup_errors.append(error_type(error))
            try:
                process.wait(timeout=5)
            except BaseException as error:
                cleanup_errors.append(error_type(error))
        if reader_started:
            try:
                reader.join(timeout=5)
            except BaseException as error:
                cleanup_errors.append(error_type(error))
        if reader_started and reader.is_alive():
            cleanup_errors.append("reader_still_alive")
        else:
            try:
                process.stdout.close()
            except BaseException as error:
                cleanup_errors.append(error_type(error))
    if reader_failed.is_set():
        cleanup_errors.append("reader_decode_failed")
    if overflow.is_set():
        cleanup_errors.append("reader_output_limit")
    if body_error or cleanup_errors:
        raise OwnedProcessFailure(body_error, cleanup_errors[:5])


def exercise_case(case, args, binding, pair, adb, fixture, client, run_id):
    import threading

    from check_foreground_activity_https import create_job
    from check_remote_https_android import current, prepare_job
    from remote_https_fixture import error_type

    errors, controller = [], None
    result = body_error = controller_error = instrumentation = None
    try:
        job, headers = prepare_job(client, fixture)
        jobs = [job]
        if case == "two_jobs":
            jobs.append(create_job(client, fixture, headers, "second-own-simulation"))
            require(jobs[0] != jobs[1], "two_distinct_jobs_required")
        if case == "cancel":

            def cancel_controller():
                try:
                    if not fixture["evidence"].barrier.wait(12):
                        raise RuntimeError("cancel_barrier_missing")
                    response = client.post(
                        fixture["origin"] + "/api/v1/jobs/" + job + "/cancel", headers=headers
                    )
                    response.raise_for_status()
                    require(response.json()["state"] == "cancelling", "cancel_ack_not_pending")
                except Exception:
                    errors.append("cancel_controller_failed")
                finally:
                    fixture["evidence"].release.set()

            controller = threading.Thread(target=cancel_controller, daemon=True)
            controller.start()
        binding.assert_fresh()
        command = instrument_command(args, binding, fixture, case, run_id)
        if case == "restart":
            interrupt_after_durable_start(command, binding, adb)
            view = bounded_wait(
                lambda: (
                    v
                    if (v := current(client, fixture, job, headers))["state"] == "needs_attention"
                    else None
                ),
                40,
            )
            session_id, previous_fence = view["run_session_id"], view["fence"]
            require(bool(session_id), "missing_original_session")
            response = client.post(
                fixture["origin"] + "/api/v1/jobs/" + job + "/resume",
                headers=headers,
                json={"expected_revision": view["revision"], "action": "verify_only"},
            )
            response.raise_for_status()
            fixture["evidence"].scenario = "normal"
            refresh_binding(args, binding, pair, adb)
            binding.assert_fresh()
            result = run_instrumentation(
                instrument_command(args, binding, fixture, case, run_id, "recover"), case
            )
            recovered = current(client, fixture, job, headers)
            assert_recovery_identity(recovered, session_id, previous_fence)
        else:
            result = run_instrumentation(command, case)
        views = [current(client, fixture, j, headers) for j in jobs]
        assert_server_result(case, views, fixture["evidence"])
        result = {**result, "server_states": [v["state"] for v in views]}
    except BaseException as error:
        body_error = error_type(error)
        if isinstance(error, (InstrumentationFailure, OwnedProcessFailure)):
            instrumentation = error.diagnostics
    finally:
        if controller:
            try:
                controller.join(timeout=15)
                if controller.is_alive() or errors:
                    controller_error = "cancel_controller_failed"
            except Exception:
                controller_error = "cancel_controller_failed"
    return result, body_error, controller_error, instrumentation


def run_case(case, args, binding, pair, adb, private_root):
    from mumu_https_fixture import local_fixture
    from remote_https_fixture import error_type, trusted_client

    result = body_error = fixture_error = cleanup_error = controller_error = instrumentation = None
    fixture_cleanup_error = None
    selected = False
    try:
        refresh_binding(args, binding, pair, adb)
        selected = True
        stop_bound_package(binding, adb)
    except BaseException as error:
        body_error = error_type(error)
    if body_error is None:
        fault = {"lost_renew": "lost_renew", "cancel": "cancel", "restart": "restart"}.get(
            case, "normal"
        )
        try:
            with (
                local_fixture(
                    private_root / case,
                    args.server_cert,
                    args.server_key,
                    args.host,
                    args.port,
                    fault,
                ) as fixture,
                trusted_client(args.ca_cert) as client,
            ):
                result, body_error, controller_error, instrumentation = exercise_case(
                    case, args, binding, pair, adb, fixture, client, str(uuid4())
                )
        except BaseException as error:
            fixture_error = error_type(error)
            if getattr(error, "fixture_cleanup_error_type", None) == "FixtureLifecycleError":
                fixture_cleanup_error = "FixtureLifecycleError"
    if selected:
        try:
            # Revalidate rather than guessing which device an old serial now addresses.
            refresh_binding(args, binding, pair, adb)
            stop_bound_package(binding, adb)
        except BaseException as error:
            cleanup_error = error_type(error)
    report = case_report(case, result, body_error, fixture_error, cleanup_error, controller_error)
    report["fixture_cleanup_error_type"] = fixture_cleanup_error
    if fixture_cleanup_error is not None:
        report["result"] = "failed"
    if instrumentation is not None:
        report["instrumentation_failure"] = instrumentation
    return report


def execute_suite(args, manifest):
    pair = manifest["pairs"]["remoteQa"]
    adb = OwnAdb(args.adb, args.serial)
    binding = open_binding(args, pair)
    root = private_run_directory(args.private_dir)
    report = not_run_report("prior_case_not_passed")
    report["product_source"] = manifest["source"]
    report["artifact_preflight"] = "passed"
    report["runtime_status"] = "running"
    for index, case in enumerate(CASES):
        try:
            report["cases"][index] = run_case(case, args, binding, pair, adb, root)
            if report["cases"][index]["result"] != "passed":
                report["runtime_status"] = "failed"
                break
        except Exception:
            report["cases"][index] = {
                "case": case,
                "result": "failed",
                "reason": "case_or_cleanup_failed",
            }
            report["runtime_status"] = "failed"
            break
    else:
        report["runtime_status"] = "passed"
        report["device_verified"] = True
    return report


if __name__ == "__main__":
    raise SystemExit(main())
