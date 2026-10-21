"""Full collection and terminal outcomes must survive the CI partition boundary."""

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci_python_suite.py"


def helper():
    assert SCRIPT.is_file(), "bounded full-suite audit helper is required"
    spec = importlib.util.spec_from_file_location("ci_python_suite", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partition_preserves_order_and_exact_union():
    module = helper()
    nodes = [f"tests/test_x.py::test_{i}" for i in range(17)]
    shards = [module.partition(nodes, index, 6) for index in range(6)]
    assert shards == [nodes[index::6] for index in range(6)]
    assert sorted(node for shard in shards for node in shard) == sorted(nodes)


def test_full_suite_collection_is_stable_across_processes(tmp_path):
    collector = tmp_path / "collect_suite.py"
    collector.write_text(
        """import json
import sys
from pathlib import Path

import pytest

class Collection:
    def pytest_collection_finish(self, session):
        Path(sys.argv[1]).write_text(
            json.dumps([item.nodeid for item in session.items]), encoding="utf-8"
        )

raise SystemExit(pytest.main(["tests", "--collect-only", "-q"], plugins=[Collection()]))
""",
        encoding="utf-8",
    )
    collections = []
    # Sequential full collections separate import-time clocks as well as random values.
    for seed in ("1", "987654321"):
        output = tmp_path / f"collection-{seed}.json"
        env = dict(os.environ, PYTHONHASHSEED=seed)
        for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            env.pop(name, None)
        result = subprocess.run(
            [sys.executable, str(collector), str(output)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        nodes = json.loads(output.read_text(encoding="utf-8"))
        assert nodes and all(isinstance(node, str) and node for node in nodes)
        assert len(nodes) == len(set(nodes))
        collections.append(nodes)

    assert collections[0] == collections[1]
    module = helper()
    for nodes in collections:
        for count in (1, 6):
            shards = [module.partition(nodes, index, count) for index in range(count)]
            assert shards == [nodes[index::count] for index in range(count)]
            assert Counter(node for shard in shards for node in shard) == Counter(nodes)


@pytest.mark.parametrize(
    "nodes,index,count", [([], 0, 1), (["a", "a"], 0, 1), (["a"], 1, 1), (["a"], 0, 2)]
)
def test_invalid_partition_refuses(nodes, index, count):
    with pytest.raises(ValueError):
        helper().partition(nodes, index, count)


def fixture_repository(tmp_path, source):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copyfile(SCRIPT, repo / "scripts/ci_python_suite.py")
    (repo / "tests/test_sample.py").write_text(source, encoding="utf-8")
    (repo / "uv.lock").write_text("synthetic lock\n", encoding="utf-8")
    (repo / ".gitignore").write_text("qa/\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    env = dict(os.environ, GIT_AUTHOR_NAME="QA", GIT_AUTHOR_EMAIL="qa@example.invalid")
    env.update(GIT_COMMITTER_NAME="QA", GIT_COMMITTER_EMAIL="qa@example.invalid")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "synthetic fixture")):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, sha


def run_shard(repo, sha, index=0, count=1, budget=20, extra_env=None):
    output = repo / "qa" / f"shard-{index}"
    env = dict(os.environ)
    # A fixture must not inherit an enclosing workflow's run identity/selection.
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "GITHUB_SHA"):
        env.pop(name, None)
    env.update(GITHUB_RUN_ID="fixture", GITHUB_RUN_ATTEMPT="1")
    env.update(extra_env or {})
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/ci_python_suite.py"),
            "run",
            "--output",
            str(output),
            "--index",
            str(index),
            "--count",
            str(count),
            "--budget-seconds",
            str(budget),
            "--expected-sha",
            sha,
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
    )
    return result, output


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def expected_source(repo):
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip()
    return {
        "expected_tree": tree,
        "expected_lock_sha256": hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest(),
    }


def counts(**values):
    result = {
        key: 0
        for key in (
            "passed",
            "skipped",
            "xfailed",
            "xpassed",
            "subtest_passed",
            "subtest_skipped",
            "subtest_xfailed",
            "subtest_xpassed",
        )
    }
    result.update(values)
    return result


def verify(repo, sha, count=1):
    module = helper()
    return module.verify_matrix(
        repo / "qa",
        expected_sha=sha,
        **expected_source(repo),
        run_id="fixture",
        attempt="1",
        expected=[(platform.system(), f"{sys.version_info.major}.{sys.version_info.minor}", count)],
        job_results=["success"],
    )


@pytest.mark.parametrize("strict", [False, True])
def test_real_pytest_shards_keep_pass_skip_xfail_and_complete_lifecycles(tmp_path, strict):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        """import pytest

def test_pass(): assert True
@pytest.mark.skip(reason="capability unavailable")
def test_skip(): assert False
@pytest.mark.xfail(reason="known synthetic failure", strict=STRICT)
def test_xfail(): assert False
def test_last(): assert True
""".replace("STRICT", str(strict)),
    )
    for index in range(2):
        result, output = run_shard(repo, sha, index, 2)
        assert result.returncode == 0, result.stdout + result.stderr
        assert read(output / "process.json")["returncode"] == 0
    totals = verify(repo, sha, 2)
    assert totals == counts(passed=2, skipped=1, xfailed=1)
    all_nodes = read(repo / "qa/shard-0/manifest.json")["collected"]
    assert all_nodes == read(repo / "qa/shard-1/manifest.json")["collected"]
    assert len(all_nodes) == 4


@pytest.mark.parametrize("exit_code", [0, 7])
def test_abrupt_child_exit_never_looks_complete(tmp_path, exit_code):
    helper()
    repo, sha = fixture_repository(
        tmp_path, f"import os\ndef test_crash(): os._exit({exit_code})\n"
    )
    result, output = run_shard(repo, sha)
    assert result.returncode != 0
    assert read(output / "process.json")["returncode"] == exit_code
    with pytest.raises(ValueError):
        verify(repo, sha)


def test_finite_timeout_is_not_success(tmp_path):
    helper()
    repo, sha = fixture_repository(tmp_path, "import time\ndef test_hang(): time.sleep(10)\n")
    result, output = run_shard(repo, sha, budget=1)
    assert result.returncode != 0
    assert read(output / "process.json")["timed_out"] is True
    with pytest.raises(ValueError):
        verify(repo, sha)


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_assertion_or_fixture_failure_never_passes(tmp_path, phase):
    helper()
    source = """import pytest
@pytest.fixture
def fixture():
    SETUP
    yield
    TEARDOWN
def test_case(fixture): CALL
""".replace("SETUP", "assert False" if phase == "setup" else "pass")
    source = source.replace("TEARDOWN", "assert False" if phase == "teardown" else "pass")
    source = source.replace("CALL", "assert False" if phase == "call" else "pass")
    repo, sha = fixture_repository(tmp_path, source)
    result, _ = run_shard(repo, sha)
    assert result.returncode != 0
    with pytest.raises(ValueError):
        verify(repo, sha)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "terminal", "collection", "identity", "job"]
)
def test_missing_duplicate_changed_or_unfinished_evidence_refuses(tmp_path, mutation):
    helper()
    repo, sha = fixture_repository(tmp_path, "def test_one(): pass\ndef test_two(): pass\n")
    for index in range(2):
        result, _ = run_shard(repo, sha, index, 2)
        assert result.returncode == 0, result.stdout + result.stderr
    assert verify(repo, sha, 2)["passed"] == 2
    shard = repo / "qa/shard-1"
    if mutation == "missing":
        shutil.rmtree(shard)
    elif mutation == "duplicate":
        shutil.copytree(shard, repo / "qa/duplicate")
    elif mutation == "terminal":
        events = shard / "events.jsonl"
        lines = events.read_text().splitlines()
        events.write_text("\n".join(lines[:-1]) + "\n")
    elif mutation in {"collection", "identity"}:
        path = shard / "manifest.json"
        data = read(path)
        if mutation == "collection":
            data["collected"].append("tests/test_sample.py::test_omitted")
        else:
            data["identity"]["tree"] = "f" * 40
        path.write_text(json.dumps(data))
    if mutation == "job":
        manifest = read(repo / "qa/shard-0/manifest.json")
        with pytest.raises(ValueError):
            helper().verify_matrix(
                repo / "qa",
                expected_sha=sha,
                **expected_source(repo),
                run_id="fixture",
                attempt="1",
                expected=[(manifest["identity"]["os"], manifest["identity"]["python_minor"], 2)],
                job_results=["cancelled"],
            )
    else:
        with pytest.raises(ValueError):
            verify(repo, sha, 2)


def test_hidden_pytest_selection_is_rejected(tmp_path):
    helper()
    repo, sha = fixture_repository(tmp_path, "def test_one(): pass\ndef test_two(): pass\n")
    result, _ = run_shard(repo, sha, extra_env={"PYTEST_ADDOPTS": "-k one"})
    assert result.returncode != 0
    assert "PYTEST_ADDOPTS" in result.stderr


@pytest.mark.parametrize("failing", [False, True])
def test_real_subtests_are_not_duplicate_calls_and_failures_are_retained(tmp_path, failing):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        f"""def test_subtests(subtests):
    for i in range(3):
        with subtests.test(i=i):
            assert i != {1 if failing else 4}
""",
    )
    result, output = run_shard(repo, sha)
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    assert len([event for event in events if event["kind"] == "subtest"]) == 3
    if failing:
        assert result.returncode != 0
        with pytest.raises(ValueError):
            verify(repo, sha)
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert verify(repo, sha)["passed"] == 1


@pytest.mark.parametrize("strict", [False, True])
def test_xpass_is_never_counted_as_pass(tmp_path, strict):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        f"""import pytest
@pytest.mark.xfail(reason="synthetic", strict={strict})
def test_xpass(): pass
""",
    )
    result, _ = run_shard(repo, sha)
    if strict:
        assert result.returncode != 0
        with pytest.raises(ValueError):
            verify(repo, sha)
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert verify(repo, sha) == counts(xpassed=1)


def test_setup_skip_and_ordinary_duplicate_phase_are_distinct(tmp_path):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        """import pytest
@pytest.fixture
def fixture(): pytest.skip("missing capability")
def test_case(fixture): assert False
""",
    )
    result, output = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    assert verify(repo, sha)["skipped"] == 1
    events = output / "events.jsonl"
    lines = events.read_text().splitlines()
    lines.insert(2, lines[1])
    events.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        verify(repo, sha)


@pytest.mark.parametrize(
    "expected", [[], [("Linux", "3.11", 0)], [("Linux", "3.11", 1), ("Linux", "3.11", 2)]]
)
def test_invalid_expected_matrix_cannot_produce_vacuous_success(tmp_path, expected):
    with pytest.raises(ValueError):
        helper().verify_matrix(
            tmp_path,
            expected_sha="a" * 40,
            expected_tree="b" * 40,
            expected_lock_sha256="c" * 64,
            run_id="1",
            attempt="1",
            expected=expected,
            job_results=["success"],
        )


def test_subtest_skip_and_xfail_are_reported_separately_from_parent(tmp_path):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        """import pytest

def test_subcases(subtests):
    with subtests.test(case="pass"): pass
    with subtests.test(case="skip"): pytest.skip("capability")
    with subtests.test(case="xfail"): pytest.xfail("known")
""",
    )
    result, _ = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    counts = verify(repo, sha)
    assert counts["passed"] == 1
    assert counts["skipped"] == counts["xfailed"] == 0
    assert counts["subtest_passed"] == 1
    assert counts["subtest_skipped"] == 1
    assert counts["subtest_xfailed"] == 1
    assert counts["subtest_xpassed"] == 0


def test_subtest_nonstrict_xpass_is_not_added_to_pass_count(tmp_path):
    helper()
    repo, sha = fixture_repository(
        tmp_path,
        """import pytest
@pytest.mark.xfail(reason="synthetic", strict=False)
def test_subcases(subtests):
    with subtests.test(): pass
""",
    )
    result, _ = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    counts = verify(repo, sha)
    assert counts["passed"] == counts["subtest_passed"] == 0
    assert counts["xpassed"] == counts["subtest_xpassed"] == 1


@pytest.mark.parametrize(
    "field", ["tree", "lock_sha256", "python", "implementation", "platform", "pytest"]
)
@pytest.mark.parametrize("bad_value", [None, "", 123])
def test_incomplete_or_mistyped_receipt_identity_is_rejected(tmp_path, field, bad_value):
    helper()
    repo, sha = fixture_repository(tmp_path, "def test_one(): pass\n")
    result, output = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    path = output / "manifest.json"
    data = read(path)
    if bad_value is None:
        del data["identity"][field]
    else:
        data["identity"][field] = bad_value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify(repo, sha)


@pytest.mark.parametrize(
    "field,value", [("tree", "f" * 40), ("lock_sha256", "f" * 64), ("python", "3.99.1")]
)
def test_provenance_and_full_interpreter_must_match_own_checkout(tmp_path, field, value):
    helper()
    repo, sha = fixture_repository(tmp_path, "def test_one(): pass\n")
    result, output = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    path = output / "manifest.json"
    data = read(path)
    data["identity"][field] = value
    path.write_text(json.dumps(data))
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/ci_python_suite.py"),
            "verify",
            "--root",
            str(repo / "qa"),
            "--expected-sha",
            sha,
            "--run-id",
            "fixture",
            "--attempt",
            "1",
            "--expect",
            f"{platform.system()}:{sys.version_info.major}.{sys.version_info.minor}:1",
            "--job-result",
            "success",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0, result.stdout + result.stderr


def test_source_mismatch_cannot_hide_in_a_different_platform_group(tmp_path):
    helper()
    repo, sha = fixture_repository(tmp_path, "def test_one(): pass\n")
    result, output = run_shard(repo, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    other = repo / "qa/other-platform"
    shutil.copytree(output, other)
    path = other / "manifest.json"
    data = read(path)
    data["identity"].update(
        os="Other", platform="Other-platform", tree="f" * 40, lock_sha256="f" * 64
    )
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        helper().verify_matrix(
            repo / "qa",
            expected_sha=sha,
            **expected_source(repo),
            run_id="fixture",
            attempt="1",
            expected=[
                (platform.system(), data["identity"]["python_minor"], 1),
                ("Other", data["identity"]["python_minor"], 1),
            ],
            job_results=["success"],
        )
