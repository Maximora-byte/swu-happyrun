"""Guard the disposable container probe, without pretending Docker ran locally."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("container_smoke", ROOT / "deploy/smoke_container.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_private_loopback_only():
    assert smoke.BASE == "http://127.0.0.1:8080"
    for url in ["http://0.0.0.0:8080", "http://example.org", "http://127.0.0.1:8080@evil"]:
        with pytest.raises(smoke.SmokeFailure):
            smoke.Api(url, "synthetic-a", "synthetic-b", "synthetic-c")


def test_compose_cleanup_is_scoped_to_generated_project(tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0
            stdout = ""

        return Result()

    container = smoke.Container(tmp_path, {"HAPPYRUN_ADMIN_TOKEN": "secret"}, run=fake_run)
    container.cleanup()
    args, kwargs = calls[-1]
    assert args[:3] == ["docker", "compose", "--project-name"]
    assert args[3].startswith("happyrun-smoke-")
    assert args[-5:] == ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
    assert "secret" not in " ".join(args)
    assert kwargs["capture_output"] is True


def test_failure_report_never_serializes_raw_exception():
    report = smoke.failure_report(RuntimeError("Bearer highly-private"))
    assert "highly-private" not in str(report)
    assert report["status"] == "failed"
    assert report["container_verified"] is False


def test_runner_guard_prevents_local_or_existing_host_execution(monkeypatch):
    monkeypatch.delenv("HAPPYRUN_DISPOSABLE_DOCKER", raising=False)
    with pytest.raises(smoke.SmokeFailure, match="disposable GitHub-hosted"):
        smoke.run()


@pytest.mark.parametrize(
    "name", ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]
)
def test_remote_docker_overrides_rejected_before_any_command(name):
    def unexpected(*args, **kwargs):
        raise AssertionError("must not call Docker with override")

    with pytest.raises(smoke.SmokeFailure, match="overrides"):
        smoke.verify_docker_target({name: "remote-configuration"}, run=unexpected)


def test_docker_context_must_resolve_to_local_runner_socket():
    def remote(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "default" if args[0][-1] == "show" else "tcp://remote:2375"

        return Result()

    with pytest.raises(smoke.SmokeFailure, match="local runner"):
        smoke.verify_docker_target({}, run=remote)


def test_fake_agent_process_cannot_read_admin_or_other_agent_credentials():
    env = {
        "HAPPYRUN_ADMIN_TOKEN": "admin",
        "HAPPYRUN_AGENT_TOKENS": "mapping",
        "HAPPYRUN_AGENT_TOKEN": "own",
        "PATH": "unchanged",
    }
    assert smoke.agent_environment(env) == {"HAPPYRUN_AGENT_TOKEN": "own", "PATH": "unchanged"}
    assert env["HAPPYRUN_ADMIN_TOKEN"] == "admin"


@pytest.mark.parametrize(
    "changed,value",
    [
        (None, None),
        ("Privileged", True),
        ("ReadonlyRootfs", False),
        ("CapDrop", []),
        ("SecurityOpt", []),
        ("PortBindings", {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}),
    ],
)
def test_real_container_hardening_observations_fail_closed(tmp_path, changed, value):
    import json
    import subprocess

    config = {
        "ReadonlyRootfs": True,
        "Privileged": False,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
    }
    if changed:
        config[changed] = value

    def fake(args, **kwargs):
        if args[:2] == ["docker", "inspect"]:
            out = json.dumps(config) if "HostConfig" in args[3] else "healthy"
        elif "exec" in args:
            out = "private_sqlite_ok"
        elif "ps" in args:
            out = "only-generated-project-container"
        else:
            out = ""
        return subprocess.CompletedProcess(args, 0, out, "")

    container = smoke.Container(tmp_path, {}, run=fake)
    if changed:
        with pytest.raises(smoke.SmokeFailure):
            container.runtime_checks()
    else:
        container.runtime_checks()
