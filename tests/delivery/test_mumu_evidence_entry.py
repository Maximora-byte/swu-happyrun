"""Synthetic host-only evidence; never real device acceptance."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    path = ROOT / "scripts" / (name + ".py")
    assert path.exists(), "MuMu evidence entry missing"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture(tmp_path, code=0):
    xml = tmp_path / "new.xml"
    xml.write_text('<hierarchy><node package="org.happyrun.app" text="PRIVATE"/></hierarchy>')
    focus = dict(
        package="org.happyrun.app",
        activity="org.happyrun.app.MainActivity",
        task_id=42,
        display_id=0,
        task_count=1,
        focused=True,
        signature_sha256="a" * 64,
    )
    return dict(
        xml_file=str(xml),
        absent_before=True,
        dump_exit=code,
        capture_id="1b07e57a-d891-4f1f-bbcb-52809b678ab7",
        file_capture_id="1b07e57a-d891-4f1f-bbcb-52809b678ab7",
        before=focus.copy(),
        after=focus.copy(),
    )


@pytest.mark.parametrize("code", [0, 139, 135, 1])
def test_fresh_xml_never_overrides_vendor_exit(tmp_path, code):
    result = load("classify_mumu_xml").classify(capture(tmp_path, code))
    assert result["dump_succeeded"] is (code == 0)
    assert result["dump_exit"] == code
    assert result["manual_review_candidate"] is (code in (0, 139, 135))
    assert result["driver_input_permitted"] is False
    assert result["record_verified"] is False
    assert "PRIVATE" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize(
    "bad",
    [
        "old",
        "wrong_capture",
        "unknown_focus",
        "other_focus",
        "other_xml",
        "mixed_xml",
        "task",
        "display",
        "multiple",
        "signature",
        "malformed",
        "missing",
        "entity",
    ],
)
def test_ambiguous_or_old_xml_never_eligible(tmp_path, bad):
    data = capture(tmp_path)
    if bad == "old":
        data["absent_before"] = False
    if bad == "wrong_capture":
        data["file_capture_id"] = "old"
    if bad == "unknown_focus":
        data["before"]["focused"] = None
    if bad == "other_focus":
        data["after"]["package"] = "other.app"
    if bad == "task":
        data["after"]["task_id"] += 1
    if bad == "display":
        data["after"]["display_id"] += 1
    if bad == "multiple":
        data["before"]["task_count"] = 2
    if bad == "signature":
        data["after"]["signature_sha256"] = "b" * 64
    if bad in ("other_xml", "mixed_xml", "malformed", "entity"):
        Path(data["xml_file"]).write_text(
            {
                "other_xml": '<hierarchy><node package="other.app"/></hierarchy>',
                "mixed_xml": (
                    '<hierarchy><node package="org.happyrun.app"/>'
                    '<node package="other.app"/></hierarchy>'
                ),
                "malformed": "<hierarchy>",
                "entity": '<!DOCTYPE hierarchy [<!ENTITY x "secret">]><hierarchy/>',
            }[bad]
        )
    if bad == "missing":
        Path(data["xml_file"]).unlink()
    result = load("classify_mumu_xml").classify(data)
    assert result["manual_review_candidate"] is False
    assert result["dump_succeeded"] is False
    assert result["driver_input_permitted"] is False


def test_native_entry_explicit_adb(monkeypatch, tmp_path):
    import sys

    module = load("check_mumu_observation")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observe",
            "--adb",
            "/qa/adb",
            "--serial",
            "qa-only",
            "--display",
            "0",
            "--task",
            "42",
            "--signature-sha256",
            "a" * 64,
            "--isolated-no-personal-data",
            "--output",
            str(tmp_path / "result.json"),
        ],
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        raise OSError("PRIVATE")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main() == 1
    assert commands[0][:3] == ["/qa/adb", "-s", "qa-only"]
    assert "PRIVATE" not in (tmp_path / "result.json").read_text()


@pytest.mark.parametrize("code", [0, 139, 135, 7])
def test_offline_cli_preserves_nonzero_exit(monkeypatch, tmp_path, capsys, code):
    import sys

    module = load("classify_mumu_xml")
    manifest = tmp_path / "capture.json"
    manifest.write_text(json.dumps(capture(tmp_path, code)))
    monkeypatch.setattr(sys, "argv", ["classify", "--manifest", str(manifest)])
    assert module.main() == (0 if code == 0 else 1)
    report = json.loads(capsys.readouterr().out)
    assert report["dump_exit"] == code
    assert report["independently_verified"] is False


@pytest.mark.parametrize("data", [None, [], {}, {"dump_exit": True}, {"dump_exit": 999}])
def test_invalid_manifest_fails_closed(data):
    result = load("classify_mumu_xml").classify(data)
    assert result["dump_succeeded"] is False
    assert result["manual_review_candidate"] is False


def test_missing_manifest_cli_no_raw_path(monkeypatch, tmp_path, capsys):
    import sys

    module = load("classify_mumu_xml")
    monkeypatch.setattr(sys, "argv", ["classify", "--manifest", str(tmp_path / "PRIVATE.json")])
    assert module.main() == 1
    assert "PRIVATE" not in capsys.readouterr().out


def test_xml_encoding_cannot_hide_entity_declarations(tmp_path):
    data = capture(tmp_path)
    Path(data["xml_file"]).write_bytes(
        (
            '<?xml version="1.0" encoding="utf-16"?>'
            '<!DOCTYPE hierarchy [<!ENTITY x "PRIVATE">]>'
            '<hierarchy><node package="org.happyrun.app" text="&x;"/></hierarchy>'
        ).encode("utf-16")
    )
    assert not load("classify_mumu_xml").classify(data)["manual_review_candidate"]


def test_boolean_task_count_not_accepted_as_integer(tmp_path):
    data = capture(tmp_path)
    data["after"]["task_count"] = True
    assert not load("classify_mumu_xml").classify(data)["manual_review_candidate"]


def test_manifest_nonregular_file_rejected_before_open(monkeypatch, tmp_path, capsys):
    import sys

    module = load("classify_mumu_xml")
    monkeypatch.setattr(sys, "argv", ["classify", "--manifest", str(tmp_path)])
    calls = []

    def forbidden_open(*args, **kwargs):
        calls.append(True)
        raise OSError

    monkeypatch.setattr(Path, "open", forbidden_open)
    assert module.main() == 1
    assert not calls
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_manifest"


def test_manifest_fifo_rejected_without_blocking(monkeypatch, tmp_path, capsys):
    import os
    import sys

    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO fixture unavailable")
    fifo = tmp_path / "capture.fifo"
    os.mkfifo(fifo)
    module = load("classify_mumu_xml")
    monkeypatch.setattr(sys, "argv", ["classify", "--manifest", str(fifo)])
    calls = []

    def forbidden_open(*args, **kwargs):
        calls.append(True)
        raise OSError

    monkeypatch.setattr(Path, "open", forbidden_open)
    assert module.main() == 1
    assert not calls


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_xml_no_bom_encoding_cannot_hide_entity_declarations(tmp_path, encoding):
    data = capture(tmp_path)
    Path(data["xml_file"]).write_bytes(
        (
            '<!DOCTYPE hierarchy [<!ENTITY x "PRIVATE">]>'
            '<hierarchy><node package="org.happyrun.app" text="&x;"/></hierarchy>'
        ).encode(encoding)
    )
    assert not load("classify_mumu_xml").classify(data)["manual_review_candidate"]
