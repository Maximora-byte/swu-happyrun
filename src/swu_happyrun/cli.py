"""JSON-first command line. Credentials come only from private environment variables."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from swu_happyrun.core.models import JobSpec, RouteProfile, ScheduleSpec, SchoolProfile


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError("invalid arguments; use --help")


def _emit(value):
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def _read(path, model):
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _parser():
    parser = Parser(prog="swu-happyrun")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--backend", choices=["mumu", "android"], default="mumu")
    doctor.add_argument("--samples", action="store_true", help="Optional read-only Android samples")
    for arg in ["manager", "index", "adb", "serial", "package"]:
        doctor.add_argument("--" + arg)
    profiles = commands.add_parser("profiles")
    checks = profiles.add_subparsers(dest="operation", required=True)
    check = checks.add_parser("check")
    check.add_argument("--root", type=Path, required=True)
    check.add_argument("--job", type=Path, required=True)
    check.add_argument("--app-version")
    routes = commands.add_parser("route")
    route = routes.add_subparsers(dest="operation", required=True).add_parser("check")
    route.add_argument("--route", type=Path, required=True)
    route.add_argument("--school", type=Path, required=True)
    server = commands.add_parser("server")
    server.add_argument("--database", type=Path, default=Path("local/server.sqlite"))
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    agent = commands.add_parser("agent")
    agent.add_argument("--url", default="http://127.0.0.1:8080")
    agent.add_argument("--agent-id", required=True)
    agent.add_argument("--device-id", required=True)
    agent.add_argument("--backend", choices=["fake", "mumu", "android"], default="fake")
    agent.add_argument("--profiles", type=Path, default=Path("local/profiles"))
    agent.add_argument("--journal", type=Path, default=Path("local/agent.sqlite"))
    agent.add_argument("--fake-state", type=Path)
    agent.add_argument("--app-version", default="test-1")
    agent.add_argument(
        "--scenario",
        default="normal",
        choices=[
            "normal",
            "start_crash",
            "upload_uncertain",
            "stop_failure",
            "inspect_timeout",
            "tick_failure",
        ],
    )
    agent.add_argument(
        "--run-seconds", type=float, default=1, help="Maximum simulation time budget"
    )
    agent.add_argument(
        "--route-speed-mps", type=float, help="Synthetic route speed within profile rules"
    )
    agent.add_argument("--once", action="store_true")
    devices = commands.add_parser("devices")
    devices.add_argument("--url", default="http://127.0.0.1:8080")
    device_actions = devices.add_subparsers(dest="operation", required=True)
    device_actions.add_parser("list")
    register = device_actions.add_parser("register")
    register.add_argument("--agent-id", required=True)
    register.add_argument("--device-id", required=True)
    for command in ["jobs", "schedules"]:
        group = commands.add_parser(command)
        group.add_argument("--url", default="http://127.0.0.1:8080")
        actions = group.add_subparsers(dest="operation", required=True)
        if command == "jobs":
            create = actions.add_parser("create")
            create.add_argument("--file", type=Path, required=True)
            create.add_argument("--idempotency-key", required=True)
            for name in ["get", "cancel", "resume"]:
                action = actions.add_parser(name)
                action.add_argument("job_id")
                if name == "resume":
                    action.add_argument("--expected-revision", type=int, required=True)
                    action.add_argument(
                        "--action",
                        choices=["retry_preflight", "verify_only", "stop_only"],
                        required=True,
                    )
        else:
            actions.add_parser("list")
            for name in ["create", "update"]:
                action = actions.add_parser(name)
                action.add_argument("--file", type=Path, required=True)
    return parser


def _token(name):
    value = os.environ.get(name, "")
    if not value.strip():
        raise UsageError("required private environment setting is missing")
    return value


def _execute(args):
    if args.command == "doctor":
        if args.backend == "android":
            if not args.adb:
                raise UsageError("Android diagnostics requires an explicit adb path")
            from swu_happyrun.drivers.android_diagnostics import collect_report

            report = collect_report(
                adb=Path(args.adb), serial=args.serial, package=args.package, samples=args.samples
            )
            _emit(report)
            return 0 if report["status"] == "ok" else 2
        if args.samples:
            raise UsageError("Samples require the android diagnostics backend")
        from swu_happyrun.drivers.mumu.discovery import collect_report

        report = collect_report(
            manager=Path(args.manager) if args.manager else None,
            index=args.index,
            adb=Path(args.adb) if args.adb else None,
            serial=args.serial,
            package=args.package,
        )
        report["record_verified"] = False
        _emit(report)
        return 0 if report["status"] == "ok" else 2
    if args.command == "profiles":
        from swu_happyrun.core.profiles import LocalProfileStore

        school, route = LocalProfileStore(args.root).resolve(
            _read(args.job, JobSpec), app_version=args.app_version
        )
        _emit(
            {
                "status": "ok",
                "profile_id": school.profile_id,
                "profile_revision": school.revision,
                "route_id": route.route_id,
                "route_revision": route.revision,
            }
        )
        return 0
    if args.command == "route":
        from swu_happyrun.core.geo import validate_route

        errors = validate_route(_read(args.route, RouteProfile), _read(args.school, SchoolProfile))
        _emit({"status": "blocked" if errors else "ok", "reasons": errors})
        return 2 if errors else 0
    if args.command == "server":
        import uvicorn

        from swu_happyrun.server.app import create_app
        from swu_happyrun.server.settings import ServerSettings

        args.database.parent.mkdir(parents=True, exist_ok=True)
        settings = ServerSettings(
            database_path=args.database,
            admin_token=_token("HAPPYRUN_ADMIN_TOKEN"),
            agent_tokens=json.loads(_token("HAPPYRUN_AGENT_TOKENS")),
            bind_host=args.host,
            port=args.port,
        )
        uvicorn.run(
            create_app(settings), host=args.host, port=args.port, access_log=False, log_level="info"
        )
        return 0
    if args.command == "agent":
        if args.backend != "fake":
            _emit(
                {
                    "error": {
                        "code": "adapter_not_verified",
                        "message": "Device backend needs a verified adapter and probe evidence",
                    }
                }
            )
            return 2
        from swu_happyrun.agent.client import ControlClient
        from swu_happyrun.agent.journal import RunJournal
        from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested, idle_liveness
        from swu_happyrun.agent.runner import AgentRunner
        from swu_happyrun.core.clock import SystemClock
        from swu_happyrun.core.models import AgentHello
        from swu_happyrun.core.profiles import LocalProfileStore
        from swu_happyrun.drivers.fake import FakeDriver

        UUID(args.agent_id)
        UUID(args.device_id)
        token = _token("HAPPYRUN_AGENT_TOKEN")
        options = {
            "app_version": args.app_version,
            "state_path": args.fake_state or args.journal.with_suffix(".fake.json"),
        }
        if args.route_speed_mps is not None:
            if not hasattr(FakeDriver, "route_progress"):
                raise UsageError("This fake driver does not support route execution")
            options["route_speed_mps"] = args.route_speed_mps
        if args.scenario != "normal":
            options["scenario"] = args.scenario
        driver = FakeDriver(args.device_id, LocalProfileStore(args.profiles), **options)
        shutdown = Shutdown()
        with (
            shutdown.signals(),
            ControlClient(args.url, token) as client,
            RunJournal(args.journal) as journal,
        ):
            runner = AgentRunner(
                client,
                driver,
                journal,
                SystemClock(),
                device_id=args.device_id,
                run_seconds=args.run_seconds,
                sleep=shutdown.wait,
                shutdown=shutdown,
            )
            try:
                while True:
                    shutdown.check()
                    hello = AgentHello(
                        protocol_version=1, agent_id=args.agent_id, devices=[driver.inspect()]
                    )
                    # Retry the same probe; a retransmit must not fabricate freshness.
                    if args.once:
                        client.hello(hello)
                    else:
                        idle_liveness(lambda hello=hello: client.hello(hello), shutdown)
                    runner.hello = hello
                    result = runner.run_once()
                    _emit({"status": "idle"} if result is None else result.model_dump(mode="json"))
                    shutdown.check()
                    if args.once:
                        return (
                            0
                            if result is None
                            or result.state in {"completed", "succeeded", "cancelled"}
                            else 3
                        )
                    # There is no active execution here. Active heartbeat/renewal failures
                    # remain fail-closed inside the runner, without reconnect retries.
                    idle_liveness(lambda hello=hello: client.heartbeat(hello), shutdown)
                    shutdown.wait(10)
            except ShutdownRequested:
                _emit({"status": "interrupted"})
                return 128 + shutdown.signum
    from swu_happyrun.agent.client import ControlClient

    with ControlClient(args.url, _token("HAPPYRUN_ADMIN_TOKEN")) as client:
        if args.command == "devices":
            if args.operation == "list":
                result = client.request("GET", "devices")
            else:
                UUID(args.agent_id)
                UUID(args.device_id)
                result = client.request(
                    "POST", "devices", {"device_id": args.device_id, "agent_id": args.agent_id}
                )
        elif args.command == "jobs":
            if args.operation == "create":
                result = client.request(
                    "POST",
                    "jobs",
                    _read(args.file, JobSpec).model_dump(mode="json"),
                    idempotency_key=args.idempotency_key,
                )
            else:
                UUID(args.job_id)
                path = f"jobs/{args.job_id}"
                if args.operation == "get":
                    result = client.request("GET", path)
                elif args.operation == "cancel":
                    result = client.request("POST", path + "/cancel", {})
                else:
                    result = client.request(
                        "POST",
                        path + "/resume",
                        {"expected_revision": args.expected_revision, "action": args.action},
                    )
        elif args.operation == "list":
            result = client.request("GET", "schedules")
        else:
            spec = _read(args.file, ScheduleSpec)
            path = "schedules" if args.operation == "create" else f"schedules/{spec.schedule_id}"
            result = client.request(
                "POST" if args.operation == "create" else "PUT", path, spec.model_dump(mode="json")
            )
        _emit(result)
        return 0


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
    except UsageError:
        _emit({"error": {"code": "usage_error", "message": "Invalid arguments; use --help"}})
        return 2
    try:
        return _execute(args)
    except ImportError:
        _emit(
            {
                "error": {
                    "code": "missing_dependency",
                    "message": "Install swu-happyrun[server,agent] for this command",
                }
            }
        )
        return 2
    except ValidationError:
        _emit({"error": {"code": "validation_error", "message": "Input failed strict validation"}})
        return 2
    except (UsageError, ValueError, OSError):
        _emit(
            {
                "error": {
                    "code": "configuration_error",
                    "message": "Check local configuration and environment",
                }
            }
        )
        return 2
    except KeyboardInterrupt:
        _emit({"status": "interrupted"})
        return 130
    except Exception:
        _emit(
            {
                "error": {
                    "code": "operation_failed",
                    "message": "Operation failed; inspect local state before retrying",
                }
            }
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
