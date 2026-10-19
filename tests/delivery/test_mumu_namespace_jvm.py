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


def test_namespace_helper_rejects_reuse_symlinks_and_foreign_recovery(tmp_path):
    source = SOURCE.read_text()
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
    harness = """
import java.nio.file.*;
import java.nio.*;
import java.nio.channels.*;
import java.nio.charset.*;
import java.util.*;
public class NamespaceHarness {
HELPER
interface Checked { void run() throws Exception; }
static void rejected(Checked action) throws Exception {
    try { action.run(); } catch (Exception expected) { return; }
    throw new AssertionError("unsafe namespace accepted");
}
public static void main(String[] args) throws Exception {
    Path files = Paths.get(args[0]);
    byte[] owner = "synthetic-owner".getBytes(StandardCharsets.UTF_8);
    String run = "11111111-1111-4111-8111-111111111111";
    Path journal = ownedDirectory(files, run, owner, false);
    if (!ownedDirectory(files,run,owner,true).equals(journal)) throw new AssertionError();
    rejected(() -> ownedDirectory(files,run,owner,false));
    rejected(() -> ownedDirectory(files,run,"other".getBytes(StandardCharsets.UTF_8),true));
    rejected(() -> ownedDirectory(files,"../other",owner,false));
    rejected(() -> ownedDirectory(files,"22222222-2222-4222-8222-222222222222",owner,true));
    Path ownerPath = journal.getParent().resolve("owner");
    Files.write(ownerPath,new byte[4097]);
    rejected(() -> ownedDirectory(files,run,owner,true));
    Files.write(ownerPath,owner);
    try {
      Path outside = files.resolve("outside"); Files.write(outside,owner);
      Files.delete(ownerPath); Files.createSymbolicLink(ownerPath,outside);
      rejected(() -> ownedDirectory(files,run,owner,true));
      Files.delete(ownerPath); Files.write(ownerPath,owner);
      Files.createSymbolicLink(journal.resolve("journal.bin"),outside);
      rejected(() -> ownedDirectory(files,run,owner,true));
      Files.delete(journal.resolve("journal.bin"));
      Files.delete(journal); Files.createSymbolicLink(journal,files);
      rejected(() -> ownedDirectory(files,run,owner,true));
    } catch (UnsupportedOperationException unavailable) { }
    System.out.println("namespace-behavior-passed");
}
}
""".replace("HELPER", helper)
    (tmp_path / "NamespaceHarness.java").write_text(harness)
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
            str(tmp_path / "NamespaceHarness.java"),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if "com.sun.tools.javac.Main" in compiled.stderr and "Could not find" in compiled.stderr:
        pytest.skip("JDK compiler unavailable")
    assert compiled.returncode == 0, compiled.stderr
    private = tmp_path / "private"
    private.mkdir()
    result = subprocess.run(
        [
            java,
            "-Xmx64m",
            "-XX:ActiveProcessorCount=2",
            "-cp",
            str(tmp_path),
            "NamespaceHarness",
            str(private),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "namespace-behavior-passed"
