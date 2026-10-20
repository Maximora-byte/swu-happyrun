from dataclasses import replace
from uuid import UUID

import pytest

from swu_happyrun.drivers.mumu.instance_attribution import (
    FileIdentity,
    attribute_processes,
    compare_static_instances,
    inspect_static_instance,
)
from swu_happyrun.drivers.mumu.windows_process_facts import ProcessFact, ProcessFactsSnapshot

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"


def setup_instance(tmp_path, index="0", value=UUID_A):
    directory = tmp_path / f"MuMuPlayer-15.0-{index}"
    directory.mkdir()
    config = directory / (directory.name + ".nemu")
    xml = f'<VirtualBox><Machine uuid="{{{value}}}" name="{directory.name}"/></VirtualBox>'
    config.write_text(xml)
    config.with_suffix(".nemu-prev").write_text(xml)
    manager = tmp_path / "MuMuManager.exe"
    if not manager.exists():
        manager.write_bytes(b"not executable synthetic fixture")
    return config, dict(instance_index=index, manager_path=manager, manager_version="6.8.4.0")


def test_identity_domains_preserve_all_bits():
    assert FileIdentity("python_stat", 1, 2) != FileIdentity("win32_legacy_ntfs", 1, 2)
    assert FileIdentity("python_stat", 1, 2) != FileIdentity("python_stat", 1, 2 + 2**64)
    with pytest.raises(ValueError):
        FileIdentity("win32_legacy_ntfs", 2**32, 2)
    with pytest.raises(ValueError):
        FileIdentity("win32_legacy_ntfs", 1, 2**64)
    with pytest.raises(ValueError):
        FileIdentity("unlabelled", 1, 2)


def test_static_read_only_and_private_repr(tmp_path):
    config, args = setup_instance(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_ino) for p in tmp_path.rglob("*") if p.is_file()}
    result = inspect_static_instance(config, **args)
    assert result.status == "known"
    assert result.instance.stable_instance == str(UUID(UUID_A))
    assert result.instance.config.identity.domain == "python_stat"
    assert UUID_A not in repr(result)
    assert str(tmp_path) not in repr(result)
    after = {p: (p.read_bytes(), p.stat().st_ino) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize(
    "bad",
    [
        "<VirtualBox/>",
        '<VirtualBox><Machine uuid="bad" name="x"/></VirtualBox>',
        "<VirtualBox><Machine/><Machine/></VirtualBox>",
        '<!DOCTYPE x [<!ENTITY x "hello">]><VirtualBox/>',
        '<VirtualBox><Machine uuid="' + UUID_A + '" name="wrong"/></VirtualBox>',
        "x" * (1024 * 1024 + 1),
    ],
    ids=["missing-machine", "invalid-uuid", "duplicate-machine", "dtd", "wrong-name", "oversized"],
)
def test_bad_static_is_unknown(tmp_path, bad, request):
    # Pytest copies node IDs into PYTEST_CURRENT_TEST, including on Windows.
    assert len(request.node.nodeid) < 512
    config, args = setup_instance(tmp_path)
    config.write_text(bad)
    assert inspect_static_instance(config, **args).status == "unknown"


def test_prev_disagreement_and_absence(tmp_path):
    config, args = setup_instance(tmp_path)
    previous = config.with_suffix(".nemu-prev")
    previous.write_text(previous.read_text().replace(UUID_A, UUID_B))
    assert inspect_static_instance(config, **args).status == "unknown"
    previous.unlink()
    assert inspect_static_instance(config, **args).status == "unknown"


def test_missing_does_not_create(tmp_path):
    config = tmp_path / "absent" / "x.nemu"
    result = inspect_static_instance(
        config, instance_index="0", manager_path=tmp_path / "x.exe", manager_version="6.8.4.0"
    )
    assert result.status == "unknown"
    assert list(tmp_path.iterdir()) == []


def test_duplicates_recreation_and_relocation(tmp_path):
    config, args = setup_instance(tmp_path)
    one = inspect_static_instance(config, **args).instance
    config2, args2 = setup_instance(tmp_path, "1")
    two = inspect_static_instance(config2, **args2).instance
    assert compare_static_instances([one, two]).status == "unknown"
    assert (
        compare_static_instances([replace(one, stable_instance=UUID_B)], previous=[one]).status
        == "unknown"
    )
    assert (
        compare_static_instances([replace(one, directory=tmp_path)], previous=[one]).status
        == "unknown"
    )
    assert (
        inspect_static_instance(
            config, expected=replace(one, stable_instance=UUID_B), **args
        ).status
        == "unknown"
    )


def test_process_facts_never_bridge_static_identity(tmp_path):
    config, args = setup_instance(tmp_path)
    static = inspect_static_instance(config, **args)
    facts = ProcessFactsSnapshot("complete", (ProcessFact(100, 99, 123, "MuMu.exe", (1, 2), "ok"),))
    assert attribute_processes(static, facts).status == "unknown"
    assert attribute_processes(static, ProcessFactsSnapshot("complete")).status == "unknown"
    reused = replace(facts, processes=(replace(facts.processes[0], creation_time_100ns=124),))
    assert attribute_processes(static, reused, previous=facts).status == "conflict"
    assert attribute_processes(static, replace(facts, status="partial")).status == "unknown"


def test_prior_snapshot_rejects_same_uuid_content_change(tmp_path):
    config, args = setup_instance(tmp_path)
    old = inspect_static_instance(config, **args).instance
    config.write_text(config.read_text().replace("/>", ' other="changed"/>'))
    assert inspect_static_instance(config, expected=old, **args).status == "unknown"


def test_symlink_parent_unknown(tmp_path):
    config, args = setup_instance(tmp_path)
    link = tmp_path / "alias"
    try:
        link.symlink_to(config.parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink fixture unavailable")
    assert inspect_static_instance(link / config.name, **args).status == "unknown"


def test_permission_error_is_sanitized(tmp_path, monkeypatch):
    from swu_happyrun.drivers.mumu import instance_attribution as module

    config, args = setup_instance(tmp_path)

    def denied(*args, **kwargs):
        raise PermissionError("private path not for output")

    monkeypatch.setattr(module.os, "open", denied)
    result = inspect_static_instance(config, **args)
    assert result.status == "unknown"
    assert "private path" not in repr(result)


@pytest.mark.parametrize("index", ["00", "-1", 0, "all"])
def test_bad_index_unknown(tmp_path, index):
    config, args = setup_instance(tmp_path)
    args["instance_index"] = index
    assert inspect_static_instance(config, **args).status == "unknown"


def test_namespaced_machine_uuid(tmp_path):
    config, args = setup_instance(tmp_path)
    for path in (config, config.with_suffix(".nemu-prev")):
        path.write_text(path.read_text().replace("<VirtualBox>", '<VirtualBox xmlns="urn:test">'))
    assert inspect_static_instance(config, **args).status == "known"


def _script():
    import runpy
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts/mumu_static_inspect.py"
    return runpy.run_path(str(path))


@pytest.mark.parametrize("corrupt", [False, True])
def test_cli_read_only_safe_summary(tmp_path, capsys, monkeypatch, corrupt):
    import json
    import subprocess

    config, args = setup_instance(tmp_path)
    if corrupt:
        config.write_text("invalid private raw contents")
    before = {p: (p.read_bytes(), p.stat().st_ino) for p in tmp_path.rglob("*") if p.is_file()}

    def denied(*args, **kwargs):
        raise AssertionError("must not start a process")

    monkeypatch.setattr(subprocess, "Popen", denied)
    code = _script()["main"](
        [
            "--config",
            str(config),
            "--index",
            args["instance_index"],
            "--manager",
            str(args["manager_path"]),
            "--manager-version",
            args["manager_version"],
        ]
    )
    out = capsys.readouterr()
    value = json.loads(out.out)
    assert code == (3 if corrupt else 0)
    assert value["status"] == ("unknown" if corrupt else "known")
    assert value["execution_ready"] is False
    assert value["attribution_status"] == "unknown"
    assert UUID_A not in out.out and str(tmp_path) not in out.out
    assert out.err == ""
    assert set(value) == {"status", "reason_code", "execution_ready", "attribution_status"}
    after = {p: (p.read_bytes(), p.stat().st_ino) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_cli_bad_arguments_do_not_echo_values(capsys):
    assert _script()["main"](["--private-token-value"]) == 3
    out = capsys.readouterr()
    assert "private-token-value" not in out.out + out.err


def test_same_bytes_replacement_identity_rejected(tmp_path):
    config, args = setup_instance(tmp_path)
    old = inspect_static_instance(config, **args).instance
    replacement = config.with_suffix(".replacement")
    replacement.write_bytes(config.read_bytes())
    assert replacement.stat().st_ino != config.stat().st_ino
    replacement.replace(config)
    assert inspect_static_instance(config, expected=old, **args).status == "unknown"


def test_read_rechecks_path_identity(tmp_path, monkeypatch):
    from swu_happyrun.drivers.mumu import instance_attribution as module

    config, args = setup_instance(tmp_path)
    replacement = config.with_suffix(".replacement")
    replacement.write_bytes(config.read_bytes())
    original = module._chain
    count = 0

    def changed(path):
        nonlocal count
        if path == config:
            count += 1
            if count == 2:
                replacement.replace(config)
        return original(path)

    monkeypatch.setattr(module, "_chain", changed)
    assert inspect_static_instance(config, **args).status == "unknown"


def test_fifo_rejected_before_open(tmp_path, monkeypatch):
    import os

    from swu_happyrun.drivers.mumu import instance_attribution as module

    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO not supported")
    config, args = setup_instance(tmp_path)
    config.unlink()
    os.mkfifo(config)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("FIFO must be rejected before open")

    monkeypatch.setattr(module.os, "open", forbidden)
    assert inspect_static_instance(config, **args).status == "unknown"
    assert calls == []
