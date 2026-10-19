import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase", ROOT / "scripts/check_android_ci_phase.py")
phase = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase)


def grant():
    env = dict(
        GITHUB_ACTIONS="true",
        GITHUB_JOB="android-apk",
        RUNNER_ENVIRONMENT="github-hosted",
        RUNNER_OS="Linux",
        GITHUB_REPOSITORY=phase.REPOSITORY,
        GITHUB_EVENT_NAME="push",
        GITHUB_REF=phase.BRANCH,
        GITHUB_SHA="a" * 40,
        HAPPYRUN_ANDROID_API="31",
    )
    event = dict(
        repository={"full_name": phase.REPOSITORY},
        ref=phase.BRANCH,
        before=phase.BEFORE,
        after="a" * 40,
    )
    return env, event


def test_consumed_exact_grant_only():
    env, event = grant()
    assert phase.authorized(env, event)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REPOSITORY", "other/repo"),
        ("GITHUB_REF", "refs/heads/main"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        ("HAPPYRUN_ANDROID_API", "34"),
        ("GITHUB_JOB", ""),
        ("GITHUB_JOB", "unreviewed-job"),
        ("GITHUB_SHA", "b" * 40),
    ],
)
def test_other_context_is_not_authorized(key, value):
    env, event = grant()
    env[key] = value
    assert not phase.authorized(env, event)


@pytest.mark.parametrize(
    "key,value",
    [
        ("before", "b" * 40),
        ("before", "005bb79058d434d9897a266868a1fbd5bae566b4"),
        ("before", "b4ca97743f64a52b4981fbcf338899de008b52bc"),
        ("before", "09b67d1f839d4b17d5b06114698cb18ec9fa0d7d"),
        ("before", "2107bf7d10c6318652622bde0e35fc60efb920ea"),
        ("before", "b3642f7215135fb90230b13ff1bdcfb5930ae227"),
        ("before", "af3f2a089da594941bc752c88734fedd660de739"),
        ("before", "481098f124f0fb5ea054180d1ecb845008348003"),
        ("before", "28871b2d599a8ec8335570effb3207d2564639ab"),
        ("after", None),
        ("after", "z" * 40),
        ("ref", "refs/heads/main"),
        ("repository", {}),
    ],
)
def test_missing_or_changed_event_not_authorized(key, value):
    env, event = grant()
    event[key] = value
    assert not phase.authorized(env, event)


@pytest.mark.parametrize(
    "field", ["repository", "commit", "tree", "run_id", "run_attempt", "variant", "job", "api"]
)
def test_cross_run_context_rejected(field):
    expected = {
        k: "original"
        for k in ["repository", "commit", "tree", "run_id", "run_attempt", "variant", "job", "api"]
    }
    manifest = {"context": dict(expected), "apks": {"app.apk": "hash"}}
    manifest["context"][field] = "different"
    with pytest.raises(ValueError):
        phase.verify(manifest, expected, {"app.apk": "hash"})


def test_apk_hash_and_set_exact():
    m = {"context": {}, "apks": {"a": "hash"}}
    phase.verify(m, {}, {"a": "hash"})
    for f in ({}, {"a": "changed"}, {"a": "hash", "extra": "hash"}):
        with pytest.raises(ValueError):
            phase.verify(m, {}, f)


def test_symlink_rejected(tmp_path):
    out = tmp_path / "android/app/build/outputs/apk"
    out.mkdir(parents=True)
    other = tmp_path / "outside"
    other.write_bytes(b"synthetic")
    (out / "bad.apk").symlink_to(other)
    with pytest.raises(ValueError):
        phase.apk_files(tmp_path)


@pytest.mark.parametrize(
    "approved,outcome,expected,raises",
    [
        ("false", "skipped", "not_run", False),
        ("true", "success", "passed", False),
        ("true", "failure", "failed", True),
        ("true", "skipped", "failed", True),
        ("true", "", "failed", True),
    ],
)
def test_report_cannot_green_failed_authorized_runtime(
    monkeypatch, tmp_path, approved, outcome, expected, raises
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAPPYRUN_RUNTIME_AUTHORIZED", approved)
    monkeypatch.setenv("HAPPYRUN_RUNTIME_OUTCOME", outcome)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr("sys.argv", ["phase", "report", "--variant", "debug"])
    if raises:
        with pytest.raises(SystemExit):
            phase.main()
    else:
        phase.main()
    assert (
        json.loads((tmp_path / "qa/android/runtime-status.json").read_text())["runtime_status"]
        == expected
    )


def test_workflow_runtime_guards_and_artifact_metadata():
    for name, count in [("checks.yml", 2), ("android-remote-https.yml", 1)]:
        text = (ROOT / ".github/workflows" / name).read_text()
        assert text.count("if: steps.runtime_gate.outputs.authorized == 'true'") == count
        assert text.count("HAPPYRUN_REQUIRE_KVM: '1'") == count
        assert text.count("check_android_ci_phase.py verify") == count
        assert text.count("check_android_ci_phase.py report") == count
        assert "runtime-status.json" in text
        assert "build-provenance.json" in text
    shell = (ROOT / "scripts/android_emulator_test.sh").read_text()
    assert shell.index("HAPPYRUN_REQUIRE_KVM") < shell.index("acceleration=off")


@pytest.mark.parametrize("variant", ["debug", "selfProbe", "remoteQa", "unknown"])
def test_missing_variant_roles_rejected(variant):
    with pytest.raises(ValueError):
        phase.required_apks(variant, {"android/app/build/outputs/apk/debug/app-debug.apk": "hash"})


def test_missing_gate_result_is_unknown_and_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HAPPYRUN_RUNTIME_AUTHORIZED", raising=False)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr("sys.argv", ["phase", "report", "--variant", "debug"])
    with pytest.raises(SystemExit):
        phase.main()
    report = json.loads((tmp_path / "qa/android/runtime-status.json").read_text())
    assert report == {"authorized": None, "runtime_status": "unknown"}


def test_dirty_checkout_rejected_before_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(phase.subprocess, "check_output", lambda *a, **k: " M src/file.py\n")
    with pytest.raises(ValueError, match="dirty_checkout"):
        phase.context({}, tmp_path, "debug")


@pytest.mark.parametrize("job", ["android-apk", "android-self-probe", "remote-https"])
@pytest.mark.parametrize("api", ["31", "35"])
def test_exact_final_matrix_only(job, api):
    env, event = grant()
    env.update(GITHUB_JOB=job, HAPPYRUN_ANDROID_API=api)
    assert phase.authorized(env, event) == (
        (job, api) in {("android-apk", "31"), ("remote-https", "35")}
    )
