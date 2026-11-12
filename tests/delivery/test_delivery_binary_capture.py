"""Real child processes exercise bytes, not Windows text-reader assumptions."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_local_https_delivery as verifier


def child(stdout=b"", stderr=b"", code=0):
    return [
        sys.executable,
        "-c",
        f"import os; os.write(1,{stdout!r}); os.write(2,{stderr!r}); raise SystemExit({code})",
    ]


def test_mixed_gradle_streams_require_explicit_stderr_encoding(tmp_path):
    out = "中文stdout\n".encode()
    err = "使用了未经检查的操作\n".encode("gbk")
    evidence = tmp_path / "private"
    assert (
        verifier.run(child(out, err), stderr_encoding="gbk", private_evidence=evidence)
        == out.decode()
    )
    assert (evidence / "stdout.bin").read_bytes() == out
    assert (evidence / "stderr.bin").read_bytes() == err
    report = json.loads((evidence / "capture.json").read_text(encoding="utf-8"))
    assert report["returncode"] == 0
    assert report["stderr"]["sha256"] == hashlib.sha256(err).hexdigest()
    assert report["stderr"]["size"] == len(err)
    assert report["reason"] == "ok"


def test_machine_outputs_never_guess_gbk(tmp_path):
    err = "使用".encode("gbk")
    with pytest.raises(ValueError):
        verifier.run(child(b"<manifest/>", err), private_evidence=tmp_path / "private")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_invalid_bytes_block_zero_exit(stream, tmp_path):
    values = {stream: b"\xffPRIVATE_SENTINEL"}
    with pytest.raises(ValueError) as caught:
        verifier.run(child(**values), private_evidence=tmp_path / "private")
    assert "PRIVATE_SENTINEL" not in str(caught.value)
    assert (tmp_path / "private" / (stream + ".bin")).read_bytes() == values[stream]


def test_gbk_setting_does_not_change_stdout():
    with pytest.raises(ValueError):
        verifier.run(child("使用".encode("gbk")), stderr_encoding="gbk")


def test_nonzero_preserves_code_and_bytes(tmp_path):
    with pytest.raises(ValueError):
        verifier.run(
            child(b"private-out", b"private-err", 7), private_evidence=tmp_path / "private"
        )
    report = json.loads((tmp_path / "private/capture.json").read_text(encoding="utf-8"))
    assert report["returncode"] == 7
    assert report["reason"] == "nonzero_exit"


def test_timeout_keeps_partial_bytes(tmp_path):
    command = [sys.executable, "-c", "import os,time; os.write(1,b'partial'); time.sleep(10)"]
    with pytest.raises(ValueError):
        verifier.run(command, timeout=2, private_evidence=tmp_path / "private")
    report = json.loads((tmp_path / "private/capture.json").read_text(encoding="utf-8"))
    assert report["reason"] == "timeout"
    assert report["timed_out"] is True
    assert (tmp_path / "private/stdout.bin").read_bytes() == b"partial"


@pytest.mark.parametrize("stream", [1, 2])
def test_output_limit_rejects_and_caps_saved_bytes(tmp_path, stream):
    command = [sys.executable, "-c", f'import os; os.write({stream},b"x"*65537)']
    with pytest.raises(ValueError):
        verifier.run(command, max_output=1024, private_evidence=tmp_path / "private")
    report = json.loads((tmp_path / "private/capture.json").read_text(encoding="utf-8"))
    assert report["reason"] == "output_limit"
    assert report["output_limit_exceeded"] is True
    assert all(
        (tmp_path / "private" / (name + ".bin")).stat().st_size <= 1024
        for name in ("stdout", "stderr")
    )


def test_evidence_directory_is_never_reused(tmp_path):
    evidence = tmp_path / "private"
    evidence.mkdir()
    (evidence / "stdout.bin").write_bytes(b"keep")
    with pytest.raises(ValueError):
        verifier.run(child(), private_evidence=evidence)
    assert (evidence / "stdout.bin").read_bytes() == b"keep"


def test_unknown_encoding_is_rejected():
    with pytest.raises(ValueError):
        verifier.run(child(), stderr_encoding="latin1")


def test_reader_error_reaches_main_and_cannot_succeed(monkeypatch):
    def broken_reader(pipe, target, limit, failed, reasons):
        reasons.append("reader_error")
        failed.set()
        pipe.close()

    monkeypatch.setattr(verifier, "_read_pipe", broken_reader)
    with pytest.raises(ValueError, match="reader_error"):
        verifier.run(child())


def test_real_reader_catches_io_error():
    import threading

    class BrokenPipe:
        def read(self, size):
            raise OSError("PRIVATE_SENTINEL")

        def close(self):
            pass

    event, reasons = threading.Event(), []
    verifier._read_pipe(BrokenPipe(), bytearray(), 1024, event, reasons)
    assert event.is_set()
    assert reasons == ["reader_error"]


def test_private_write_never_overwrites(tmp_path):
    path = tmp_path / "raw"
    path.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        verifier._private_write(path, b"replace")
    assert path.read_bytes() == b"keep"


def test_reader_join_failure_is_not_success(monkeypatch):
    import threading

    release = threading.Event()

    def blocked(pipe, *_args):
        release.wait(10)
        pipe.close()

    monkeypatch.setattr(verifier, "_read_pipe", blocked)
    try:
        with pytest.raises(ValueError, match="reader_join_failed"):
            verifier.run(child(), timeout=0.2)
    finally:
        release.set()


def test_machine_utf8_xml_and_signature_are_unchanged():
    data = '<manifest label="中文"/>\nSHA-256: abc\n'.encode()
    assert verifier.run(child(data)) == data.decode("utf-8")


def test_evidence_symlink_is_rejected_without_spawn(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "is_symlink", lambda _self: True)
    monkeypatch.setattr(
        verifier.subprocess, "Popen", lambda *_a, **_k: pytest.fail("must not spawn")
    )
    with pytest.raises(ValueError, match="symlink"):
        verifier.run(child(), private_evidence=tmp_path / "private")


def test_build_encoding_applies_only_to_two_gradle_calls(monkeypatch, tmp_path):
    import argparse

    import build_local_https_delivery as builder

    source = tmp_path / "source"
    source.mkdir()
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"public")
    args = argparse.Namespace(
        source_root=source,
        output=tmp_path / "bundle",
        ca_cert=ca,
        server_cert=ca,
        host="10.0.0.1",
        openssl="openssl",
        gradle="gradle",
        adapter=None,
        adapter_commit=None,
        gradle_stderr_encoding="gbk",
        private_build_evidence=tmp_path / "private",
    )
    calls = []
    monkeypatch.setattr(builder, "source_identity", lambda *_: {})
    monkeypatch.setattr(builder, "verify_certificates", lambda *_: "10.0.0.1")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 2:
            raise ValueError("synthetic failure")

    monkeypatch.setattr(builder, "run", run)
    with pytest.raises(ValueError, match="synthetic"):
        builder.build(args)
    assert len(calls) == 2
    assert all(k["stderr_encoding"] == "gbk" and k["timeout"] == 1800 for _, k in calls)
    assert [k["private_evidence"].name for _, k in calls] == ["ordinary", "remoteQa"]
    assert calls[0][0][-3:] == ["clean", "assembleDebug", "assembleDebugAndroidTest"]
    assert not (args.output / "delivery.json").exists()
    assert not (source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem").exists()


def test_dotdot_evidence_cannot_enter_source(monkeypatch, tmp_path):
    import argparse

    import build_local_https_delivery as builder

    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"public")
    args = argparse.Namespace(
        source_root=source,
        output=tmp_path / "bundle",
        ca_cert=ca,
        server_cert=ca,
        host="10.0.0.1",
        openssl="openssl",
        gradle="gradle",
        adapter=None,
        adapter_commit=None,
        private_build_evidence=outside / ".." / "source" / "logs",
    )
    monkeypatch.setattr(builder, "source_identity", lambda *_: {})
    monkeypatch.setattr(builder, "verify_certificates", lambda *_: "10.0.0.1")
    monkeypatch.setattr(builder, "run", lambda *_a, **_k: pytest.fail("must reject before Gradle"))
    with pytest.raises(ValueError, match="outside_source_and_bundle"):
        builder.build(args)
    assert not (source / "logs").exists()


def test_packaging_guard_accepts_predecoded_manifest_without_subprocess(monkeypatch, tmp_path):
    import zipfile

    import check_remote_qa_packaging as packaging

    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w"):
        pass
    xml = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<application android:usesCleartextTraffic="false"/></manifest>'
    )
    monkeypatch.setattr(
        packaging.subprocess, "run", lambda *_a, **_k: pytest.fail("hidden subprocess")
    )
    packaging.check_manifest(apk, xml, qa=False, ca=tmp_path / "unused")
    with pytest.raises(ValueError, match="disallow cleartext"):
        packaging.check_manifest(
            apk, xml.replace('"false"', '"true"'), qa=False, ca=tmp_path / "unused"
        )


def test_pair_guard_uses_the_captured_manifest_without_second_process(monkeypatch, tmp_path):
    xml = '<manifest captured="strict-utf8"/>'
    for name in ("ordinary.apk", "ordinary-test.apk"):
        (tmp_path / name).write_bytes(b"fixture")
    commands = []

    def captured(command):
        commands.append(command)
        return xml

    def guard(apk, actual_xml, *, qa, ca):
        assert actual_xml == xml
        assert qa is False
        assert len(commands) == 2
        raise ValueError("reached_pure_guard")

    monkeypatch.setattr(verifier, "run", captured)
    monkeypatch.setattr(verifier, "check", guard)
    with pytest.raises(ValueError, match="reached_pure_guard"):
        verifier.inspect_pairs(
            tmp_path, tmp_path / "ca", apksigner="signer", apkanalyzer="analyzer", aapt2="aapt2"
        )
