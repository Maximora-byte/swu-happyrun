"""Execute the adapter's exact filesystem helper on JVM, not Android or MuMu."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
    / "RemoteMumuHttpsAcceptanceTest.java"
)
RUN_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(scope="module")
def namespace_harness(tmp_path_factory):
    source = SOURCE.read_text(encoding="utf-8")
    assert "// BEGIN HOST_TESTABLE_NAMESPACE" in source, (
        "extractable real namespace helper required"
    )
    helper = source.split("// BEGIN HOST_TESTABLE_NAMESPACE", 1)[1].split(
        "// END HOST_TESTABLE_NAMESPACE", 1
    )[0]
    assert "getInstrumentation" not in helper
    java = shutil.which("java")
    if java is None:
        pytest.skip("JVM unavailable; not Android validation")
    directory = tmp_path_factory.mktemp("namespace-jvm")
    harness = """
import java.nio.file.*;
import java.nio.*;
import java.nio.channels.*;
import java.nio.charset.*;
import java.util.*;
public class NamespaceHarness {
HELPER
interface Checked { void run() throws Exception; }
static void rejected(Class<? extends Exception> type, String message, Checked action)
        throws Exception {
    try { action.run(); } catch (Exception actual) {
        if (!type.isInstance(actual)
                || message != null && !message.equals(actual.getMessage())) throw actual;
        return;
    }
    throw new AssertionError("unsafe namespace accepted");
}
public static void main(String[] args) throws Exception {
    Path files = Paths.get(args[0]);
    String mode = args[1];
    byte[] owner = "synthetic-owner".getBytes(StandardCharsets.UTF_8);
    String run = "11111111-1111-4111-8111-111111111111";
    if (mode.equals("core")) {
        Path journal = ownedDirectory(files, run, owner, false);
        if (!ownedDirectory(files,run,owner,true).equals(journal)) throw new AssertionError();
        rejected(FileAlreadyExistsException.class, null,
            () -> ownedDirectory(files,run,owner,false));
        rejected(IllegalStateException.class, "owner_mismatch",
            () -> ownedDirectory(files,run,"other".getBytes(StandardCharsets.UTF_8),true));
        rejected(IllegalArgumentException.class, null,
            () -> ownedDirectory(files,"../other",owner,false));
        rejected(IllegalStateException.class, "unsafe_run_directory",
            () -> ownedDirectory(files,"22222222-2222-4222-8222-222222222222",owner,true));
        Path ownerPath = journal.getParent().resolve("owner");
        Files.write(ownerPath,new byte[4097]);
        rejected(IllegalStateException.class, "owner_limit",
            () -> ownedDirectory(files,run,owner,true));
    } else if (mode.equals("prepare")) {
        ownedDirectory(files, run, owner, false);
    } else if (mode.equals("symlink")) {
        rejected(IllegalStateException.class, args[2],
            () -> ownedDirectory(files,run,owner,true));
    } else {
        throw new AssertionError("unknown harness mode");
    }
    System.out.println("namespace-" + mode + "-passed");
}
}
""".replace("HELPER", helper)
    harness_path = directory / "NamespaceHarness.java"
    harness_path.write_text(harness, encoding="utf-8")
    compiled = subprocess.run(
        [
            java,
            "-Xmx128m",
            "-XX:ActiveProcessorCount=2",
            "com.sun.tools.javac.Main",
            "-source",
            "17",
            "-target",
            "17",
            str(harness_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    if "com.sun.tools.javac.Main" in compiled.stderr and "Could not find" in compiled.stderr:
        pytest.skip("JDK compiler unavailable")
    assert compiled.returncode == 0, compiled.stderr

    def run(private, mode, expected=""):
        result = subprocess.run(
            [
                java,
                "-Xmx64m",
                "-XX:ActiveProcessorCount=2",
                "-cp",
                str(directory),
                "NamespaceHarness",
                str(private),
                mode,
                expected,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"namespace-{mode}-passed"

    return run


def test_namespace_helper_rejects_reuse_and_foreign_recovery(tmp_path, namespace_harness):
    """Core ownership/UUID/recovery checks never depend on symlink capability."""
    private = tmp_path / "private"
    private.mkdir()
    namespace_harness(private, "core")


@pytest.mark.parametrize(
    ("relative", "expected", "is_directory"),
    [
        ("owner", "unsafe_owner_file", False),
        ("journal/journal.bin", "unsafe_journal_file", False),
        ("journal", "unsafe_journal_directory", True),
    ],
)
def test_namespace_helper_rejects_symlinks(
    tmp_path, namespace_harness, symlink_or_skip, relative, expected, is_directory
):
    private = tmp_path / "private"
    private.mkdir()
    namespace_harness(private, "prepare")
    link = private / "mumu-https-qa" / RUN_ID / relative
    if link.is_dir():
        link.rmdir()
    elif link.exists():
        link.unlink()
    outside = tmp_path / "outside"
    if is_directory:
        outside.mkdir()
    else:
        outside.write_bytes(b"synthetic-owner")
    # The native error code classifies fixture availability before Java consumes it.
    # Arbitrary I/O and every Java rejection/assertion failure remain failures.
    symlink_or_skip(link, outside, target_is_directory=is_directory)
    assert link.is_symlink()
    namespace_harness(private, "symlink", expected)
