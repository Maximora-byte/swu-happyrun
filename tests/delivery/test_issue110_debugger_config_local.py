"""Software-only local adapter tests: no Windows API or debugger is executed."""

import importlib.util
import io
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/diagnostics"
USER = "S-1-5-21-1-2-3-1001"
SYSTEM = "S-1-5-18"
ADMIN = "S-1-5-32-544"
OTHER = "S-1-5-32-545"


@pytest.fixture
def acl(monkeypatch):
    path = SCRIPTS / "issue110_local_acl.py"
    assert path.exists(), "read-only local ACL gate missing"
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("issue110_local_acl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sid(value):
    pieces = [int(p) for p in value.split("-")[1:]]
    return (
        bytes((pieces[0], len(pieces) - 2))
        + pieces[1].to_bytes(6, "big")
        + b"".join(struct.pack("<I", p) for p in pieces[2:])
    )


def descriptor(owner=USER, entries=None, control=0x8004):
    if entries is None:
        entries = [(USER, 0x1F01FF, 3, 0)]
    owner_bytes = sid(owner)
    aces = b""
    for trustee, mask, flags, kind in entries:
        body = struct.pack("<I", mask) + sid(trustee)
        aces += struct.pack("<BBH", kind, flags, 4 + len(body)) + body
    dacl = struct.pack("<BBHHH", 2, 0, 8 + len(aces), len(entries), 0) + aces
    return (
        struct.pack("<BBHIIII", 1, 0, control, 20, 0, 0, 20 + len(owner_bytes)) + owner_bytes + dacl
    )


def test_exact_ascii_component_paths(acl):
    assert acl.components(r"C:\private\owned") == ["C:\\", r"C:\private", r"C:\private\owned"]


@pytest.mark.parametrize(
    "path",
    [
        r"\\server\root",
        r"\\?\C:\root",
        r"C:relative",
        r"C:\a\..\root",
        r"C:\a\.\root",
        "C:\\a\\",
        r"C:\a:b",
        "C:\\私有",
        r"C:\with space",
        "C:\\a\\\\b",
        "/tmp/private",
    ],
)
def test_path_unknown_or_ambiguous_rejected(acl, path):
    with pytest.raises(ValueError):
        acl.components(path)


@pytest.mark.parametrize("mask", [0x1F01FF, 0x10000000, 0x80000000, 0x40000000, 0x20000000])
def test_only_trusted_root_allow_aces(acl, mask):
    assert acl.check_descriptor(
        descriptor(entries=[(USER, 0x1F01FF, 3, 0), (SYSTEM, mask, 3, 0)]), USER, private=True
    )


@pytest.mark.parametrize(
    "entries",
    [
        [(USER, 0x1F01FF, 0, 0)],
        [(USER, 0x1F01FF, 1, 0)],
        [(USER, 0x1F01FF, 2, 0)],
        [(USER, 0x1F01FF, 7, 0)],
        [(USER, 0x1F01FF, 11, 0)],
        [(SYSTEM, 0x1F01FF, 3, 0)],
        [(ADMIN, 0x1F01FF, 3, 0)],
        [(USER, 0x1200A9, 3, 0)],
    ],
)
def test_private_dacl_requires_user_full_control_inheritance(acl, entries):
    with pytest.raises(ValueError):
        acl.check_descriptor(descriptor(entries=entries), USER, private=True)


def test_generic_all_user_inheritance_is_supported(acl):
    assert acl.check_descriptor(descriptor(entries=[(USER, 0x10000000, 19, 0)]), USER, private=True)


@pytest.mark.parametrize("mask", [0x120089, 0x1200A0, 0x1200A9, 0x80000000, 0x20000000, 0])
def test_ancestor_outsider_read_execute_only(acl, mask):
    assert acl.check_descriptor(descriptor(entries=[(OTHER, mask, 0, 0)]), USER, private=False)


@pytest.mark.parametrize(
    "mask",
    [2, 4, 0x40, 0x10000, 0x40000, 0x80000, 0x40000000, 0x10000000, 0x02000000, 0x01000000, 0x200],
)
def test_ancestor_outsider_writes_or_unknown_bits_rejected(acl, mask):
    with pytest.raises(ValueError):
        acl.check_descriptor(descriptor(entries=[(OTHER, mask, 0, 0)]), USER, private=False)


def test_inherit_only_ancestor_does_not_grant_effective_access(acl):
    data = descriptor(entries=[(OTHER, 0x1F01FF, 0x0B, 0)])
    assert acl.check_descriptor(data, USER, private=False)
    with pytest.raises(ValueError):
        acl.check_descriptor(data, USER, private=True)


@pytest.mark.parametrize("owner", [USER, SYSTEM, ADMIN])
def test_trusted_owner_all_components(acl, owner):
    assert acl.check_descriptor(descriptor(owner), USER, private=False)


@pytest.mark.parametrize("private", [False, True])
def test_untrusted_owner_rejected_even_read_only(acl, private):
    with pytest.raises(ValueError):
        acl.check_descriptor(descriptor(OTHER), USER, private=private)


@pytest.mark.parametrize("kind", [1, 2, 5, 6, 9, 10, 255])
def test_only_ordinary_allow_ace(acl, kind):
    with pytest.raises(ValueError):
        acl.check_descriptor(descriptor(entries=[(USER, 0x1F01FF, 0, kind)]), USER, private=True)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b[:19],
        lambda b: b[:-1],
        lambda b: b[:2] + b"\x00\x80" + b[4:],
        lambda b: b[:16] + b"\x00" * 4 + b[20:],
        lambda b: b[:4] + struct.pack("<I", 0xFFFFFFF0) + b[8:],
        lambda b: b[:20] + b"\x01\xff" + b[22:],
        lambda b: descriptor(entries=[]),
    ],
)
def test_malformed_security_descriptor_fails_closed(acl, mutate):
    with pytest.raises(ValueError):
        acl.check_descriptor(mutate(descriptor()), USER, private=True)


class FakeNative:
    def __init__(self):
        self.closed = []
        self.opened = []
        self.user_sid = USER
        self.attributes = 0x10
        self.security = descriptor()
        self.identities = {}
        self.close_error = None

    def drive_mapping(self, root):
        return r"\Device\HarddiskVolume3"

    def open_directory(self, path):
        self.opened.append(path)
        self.identities[path] = len(self.opened)
        return path

    def inspect(self, handle):
        return self.attributes, self.identities[handle], self.security

    def close(self, handle):
        self.closed.append(handle)
        if self.close_error:
            raise self.close_error


def test_root_and_child_handles_retained_until_exit(acl, monkeypatch):
    api = FakeNative()
    made = []
    monkeypatch.setattr(acl.os, "mkdir", made.append)
    with acl.PrivateDirectory(r"C:\private", api) as directory:
        assert str(directory.path) == r"C:\private\issue110-local-config-1"
        assert made == [str(directory.path)]
        assert api.closed == []
        assert len(api.opened) == 3
    assert api.closed == list(reversed(api.opened))


def test_explicit_filter_probe_role_preserves_old_default(acl, monkeypatch):
    api = FakeNative()
    made = []
    monkeypatch.setattr(acl.os, "mkdir", made.append)
    # The same strict prepared ACL is required for this explicit new role.
    api.security = descriptor(
        entries=[(USER, 0x1F01FF, 3, 0), (SYSTEM, 0x1F01FF, 3, 0), (ADMIN, 0x1F01FF, 3, 0)],
        control=0x9004,
    )
    api.volume = lambda _: None
    with acl.PrivateDirectory(
        r"C:\private", api, mode="prepared_top_level", child_role="filter_probe"
    ) as directory:
        assert str(directory.path) == r"C:\private\issue110-filter-probe-1"
        assert directory.handles[-1][2] == "filter_probe"
        assert acl.CHILD == "issue110-local-config-1"
    assert made == [r"C:\private\issue110-filter-probe-1"]


@pytest.mark.parametrize("attributes", [0, 0x410])
def test_non_directory_and_reparse_reject_before_create(acl, monkeypatch, attributes):
    api = FakeNative()
    api.attributes = attributes
    monkeypatch.setattr(acl.os, "mkdir", lambda _: pytest.fail("must not create"))
    with pytest.raises(ValueError):
        with acl.PrivateDirectory(r"C:\private", api):
            pytest.fail("must not enter")
    assert api.closed == api.opened


def test_existing_fixed_child_is_never_reused(acl, monkeypatch):
    api = FakeNative()
    original = FileExistsError("PRIVATE_CANARY")

    def occupied(_):
        raise original

    monkeypatch.setattr(acl.os, "mkdir", occupied)
    with pytest.raises(FileExistsError) as caught:
        with acl.PrivateDirectory(r"C:\private", api):
            pytest.fail("must not enter")
    assert caught.value is original
    assert api.closed == list(reversed(api.opened))


@pytest.mark.parametrize("primary", [ValueError("primary"), KeyboardInterrupt(), SystemExit(7)])
def test_ordinary_close_error_does_not_replace_primary(acl, monkeypatch, primary):
    api = FakeNative()
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    with pytest.raises(type(primary)) as caught:
        with acl.PrivateDirectory(r"C:\private", api):
            api.close_error = OSError("PRIVATE_CANARY")
            raise primary
    assert caught.value is primary
    assert api.closed == list(reversed(api.opened))


@pytest.mark.parametrize("name", ["CON", "prn.txt", "AUX", "NUL", "COM1", "LPT9"])
def test_dos_device_components_rejected(acl, name):
    with pytest.raises(ValueError):
        acl.components("C:\\private\\" + name)


def test_odd_acl_allocation_length_rejected(acl):
    data = bytearray(descriptor())
    offset = struct.unpack_from("<I", data, 16)[0]
    length = struct.unpack_from("<H", data, offset + 2)[0]
    struct.pack_into("<H", data, offset + 2, length + 1)
    with pytest.raises(ValueError):
        acl.check_descriptor(bytes(data) + b"\x00", USER, private=True)


def test_repository_alias_identity_rejected_before_create(acl, monkeypatch):
    api = FakeNative()
    monkeypatch.setattr(acl.os, "mkdir", lambda _: pytest.fail("must not create"))
    with pytest.raises(ValueError):
        with acl.PrivateDirectory(r"C:\private", api, forbidden_identity=2):
            pytest.fail("must not enter")


@pytest.mark.parametrize("change", ["identity", "acl", "reparse"])
def test_chain_rechecked_after_exclusive_child_creation(acl, monkeypatch, change):
    api = FakeNative()
    original = api.inspect
    created = False

    def mkdir(_):
        nonlocal created
        created = True

    def inspect(handle):
        attributes, identity, security = original(handle)
        if created and handle == r"C:\private":
            if change == "identity":
                identity += 999
            elif change == "acl":
                security = descriptor(entries=[(OTHER, 0x1F01FF, 3, 0)])
            else:
                attributes |= 0x400
        return attributes, identity, security

    api.inspect = inspect
    monkeypatch.setattr(acl.os, "mkdir", mkdir)
    with pytest.raises(ValueError):
        with acl.PrivateDirectory(r"C:\private", api):
            pytest.fail("must not enter")
    assert api.closed == list(reversed(api.opened))


def test_file_id_uses_128_bit_handle_information(acl):
    import ctypes as ct

    calls = []
    api = acl.Native.__new__(acl.Native)

    def info(handle, number, buffer, length):
        calls.append((handle, number, length))
        ct.memmove(buffer, struct.pack("<Q", 33) + bytes(range(16)), 24)
        return 1

    api.kernel = SimpleNamespace(GetFileInformationByHandleEx=info)
    assert api.identity(42) == (33, bytes(range(16)))
    assert calls == [(42, 18, 24)]


def test_failed_file_identity_never_uses_old_64_bit_fallback(acl, monkeypatch):
    api = acl.Native.__new__(acl.Native)
    api.kernel = SimpleNamespace(GetFileInformationByHandleEx=lambda *args: 0)
    error = OSError("PRIVATE_CANARY")
    monkeypatch.setattr(acl.ct, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(acl.ct, "WinError", lambda _: error, raising=False)
    with pytest.raises(OSError) as caught:
        api.identity(42)
    assert caught.value is error


@pytest.fixture
def adapter():
    path = SCRIPTS / "issue110_debugger_config_local.py"
    spec = importlib.util.spec_from_file_location("issue110_debugger_config_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("flags", [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_launch_flags_rejected_before_dependency_code(adapter, monkeypatch, flags):
    monkeypatch.setattr(
        adapter.sys,
        "flags",
        SimpleNamespace(isolated=flags[0], no_site=flags[1], dont_write_bytecode=flags[2]),
    )
    monkeypatch.setattr(adapter, "load_dependencies", lambda: pytest.fail("must not load"))
    with pytest.raises(ValueError, match="launch_flags_unverified"):
        adapter.run_local(r"C:\private", 300)


def test_dependency_hash_mismatch_executes_no_neighbor(adapter, monkeypatch):
    monkeypatch.setattr(
        adapter.Path,
        "open",
        lambda *args, **kwargs: io.BytesIO(b"raise AssertionError('PRIVATE_CANARY')"),
    )
    with pytest.raises(ValueError, match="dependency_hash_mismatch"):
        adapter.load_dependencies()


def test_dependency_read_is_bounded_before_allocation(adapter, monkeypatch):
    sizes = []

    class Stream(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert size == 1024 * 1024 + 1
            return b"x" * size

    monkeypatch.setattr(adapter.Path, "open", lambda *args, **kwargs: Stream())
    with pytest.raises(ValueError, match="dependency_hash_mismatch"):
        adapter.load_dependencies()
    assert sizes == [1024 * 1024 + 1]


def test_file_identity_handle_closed_on_failure(acl):
    api = acl.Native.__new__(acl.Native)
    closed = []
    error = KeyboardInterrupt()
    api.open_directory = lambda _: 9

    def information(_):
        raise error

    api.information = information

    def close(handle):
        closed.append(handle)
        raise OSError("PRIVATE_CLOSE_CANARY")

    api.close = close
    with pytest.raises(KeyboardInterrupt) as caught:
        api.file_identity("python.exe")
    assert caught.value is error and closed == [9]


@pytest.mark.parametrize(
    "kind,mapping",
    [
        (4, "\\Device\\HarddiskVolume3\x00\x00"),
        (3, "\\??\\C:\\private\x00\x00"),
        (3, "\\Device\\Mup\x00\x00"),
        (3, "\\Device\\HarddiskVolume3\x00\\Device\\HarddiskVolume4\x00\x00"),
        (3, "\\Device\\HarddiskVolume3"),
    ],
)
def test_drive_alias_or_network_mapping_is_unsupported(acl, kind, mapping):
    api = acl.Native.__new__(acl.Native)

    def query(drive, buffer, size):
        for i, character in enumerate(mapping):
            buffer[i] = character
        return len(mapping)

    api.kernel = SimpleNamespace(GetDriveTypeW=lambda _: kind, QueryDosDeviceW=query)
    with pytest.raises(ValueError):
        api.drive_mapping("C:\\")


def test_drive_mapping_rechecked_before_session(acl, monkeypatch):
    api = FakeNative()
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    with acl.PrivateDirectory(r"C:\private", api) as directory:
        api.drive_mapping = lambda _: r"\Device\HarddiskVolume4"
        with pytest.raises(ValueError):
            directory.revalidate()


@pytest.fixture
def runtime(adapter, monkeypatch, tmp_path):
    executable, dll = tmp_path / "python.exe", tmp_path / "python.dll"
    executable.write_bytes(b"executable")
    dll.write_bytes(b"runtime")
    monkeypatch.setattr(adapter.sys, "executable", str(executable))
    monkeypatch.setattr(adapter.sys, "dllhandle", 77, raising=False)
    monkeypatch.setattr(adapter.sys, "version", "3.12.14 PRIVATE_BUILD_CANARY")
    api = SimpleNamespace(
        module_path=lambda handle: str(executable if handle is None else dll),
        file_identity=lambda path: (1, b"same_file"),
    )
    capture = SimpleNamespace(x64_pe=lambda _: True)
    return api, capture, tmp_path


def test_actual_runtime_records_private_details_not_public_paths(adapter, runtime):
    api, capture, private = runtime
    result = adapter.verify_runtime(api, capture, private)
    encoded = json.dumps(result)
    assert "PRIVATE_BUILD_CANARY" not in encoded and str(private) not in encoded
    assert result["implementation"] == "cpython" and result["version"] == list(
        adapter.sys.version_info[:3]
    )
    assert result["venv_status"] == "unknown" and type(result["prefixes_differ"]) is bool
    assert [item["name"] for item in result["binaries"]] == [
        "python_executable",
        "python_runtime_dll",
    ]
    assert "PRIVATE_BUILD_CANARY" in (private / "interpreter-private.json").read_text()


@pytest.mark.parametrize("case", ["dll_zero", "dll_bool", "different_exe", "not_x64", "too_old"])
def test_interpreter_identity_fail_closed(adapter, runtime, monkeypatch, case):
    api, capture, private = runtime
    if case.startswith("dll_"):
        monkeypatch.setattr(adapter.sys, "dllhandle", 0 if case == "dll_zero" else True)
    elif case == "different_exe":
        api.module_path = lambda handle: (
            "OTHER_PRIVATE_CANARY" if handle is None else str(private / "python.dll")
        )
        api.file_identity = lambda path: path
    elif case == "not_x64":
        capture.x64_pe = lambda _: False
    else:
        monkeypatch.setattr(adapter.sys, "version_info", (3, 10, 0))
    with pytest.raises(ValueError, match="interpreter_identity_unverified"):
        adapter.verify_runtime(api, capture, private)


@pytest.fixture
def local_fake(adapter, acl, monkeypatch, tmp_path):
    calls = []
    private = tmp_path / "private"

    class Directory:
        def __init__(self, root, api, *, forbidden_identity, mode="generic"):
            calls.append(("root", root, forbidden_identity, mode))
            self.path = private

        def __enter__(self):
            self.path.mkdir()
            return self

        def revalidate(self):
            calls.append(("revalidate",))

        def __exit__(self, *args):
            calls.append(("close",))

    class API:
        def open_directory(self, path):
            return 10

        def information(self, handle):
            return 0x10, (123, bytes(16))

        def close(self, handle):
            calls.append(("repo_close",))

    class Session:
        def run(self, argv, cwd, env, raw_path, nonce, deadline, **kwargs):
            calls.append(("session", argv, deadline, kwargs, env))
            raw_path.write_bytes(b"PRIVATE_RAW_CANARY\n")
            return "IGNORED_DECODED_CANARY", 0, 0, "exited", True, 42

    metadata = [
        {"name": name, "version": "10.0.26100.8249", "sha256": value}
        for name, value in adapter.DEBUGGER_HASHES.items()
    ]

    def installed(env, deadline, receipt):
        calls.append(("signature", deadline))
        return Path("C:/fixed/cdb.exe"), metadata

    def forbidden(*args, **kwargs):
        pytest.fail("broader diagnostic was called")

    capture = SimpleNamespace(
        installed_debugger=installed,
        child_environment=lambda original, executable, root: {"TEMP": str(root / "temp")},
        cdb_argv=lambda cdb, init, symbols, target: [str(cdb), *target],
        MAX_OUTPUT=16 * 1024 * 1024,
        CAPTURE_SECONDS=10,
        main=forbidden,
        verify_subject=forbidden,
        controller_tests=forbidden,
        smoke=forbidden,
        run_one=forbidden,
        load_manifest=forbidden,
        consume=forbidden,
    )
    config = SimpleNamespace(
        VERSION="10.0.26100.8249",
        MAX_OUTPUT=65536,
        TARGET="FIXED_TARGET",
        debugger_scripts=lambda *args: ("INIT", "TERMINAL", "LOAD"),
        observe=lambda *args: dict(
            configuration_readback="format_unknown",
            script_load="observed",
            ready_identity=True,
            stdout_seen=True,
            stderr_seen=True,
            unexpected_callback=False,
        ),
        main=forbidden,
        controller_tests=forbidden,
    )
    modules = {
        "issue110_capture": capture,
        "issue110_debugger_config": config,
        "issue110_win32": SimpleNamespace(Session=Session),
        "issue110_local_acl": SimpleNamespace(
            Native=API, PrivateDirectory=Directory, components=acl.components
        ),
    }
    monkeypatch.setattr(adapter, "load_dependencies", lambda: modules)
    monkeypatch.setattr(adapter, "verify_runtime", lambda *args: {"implementation": "cpython"})
    flags = {name: getattr(sys.flags, name) for name in dir(sys.flags) if not name.startswith("_")}
    flags.update(isolated=1, no_site=1, dont_write_bytecode=1)
    monkeypatch.setattr(adapter.sys, "flags", SimpleNamespace(**flags))
    monkeypatch.setattr(adapter.time, "monotonic", lambda: 10)
    return calls, private, modules, metadata


def test_fixed_local_target_is_one_normal_invocation_and_always_unready(adapter, local_fake):
    calls, private, modules, metadata = local_fake
    report = adapter.run_local(r"C:\private", 310)
    invocations = [c for c in calls if c[0] == "session"]
    assert len(invocations) == 1
    assert invocations[0][1][-6:] == [
        adapter.sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        "FIXED_TARGET",
    ]
    assert invocations[0][2] == 25
    assert invocations[0][3] == {"capture_seconds": 10, "max_output": 16 * 1024 * 1024}
    assert calls.index(("revalidate",)) < calls.index(invocations[0])
    assert report["configuration_readback"] == "format_unknown"
    assert report["target_exit"] == "verified" and report["owned_cleanup"] is True
    assert report["execution_ready"] is False and report["passed"] is False
    text = (private / "summary.json").read_text()
    assert "CANARY" not in text and str(private) not in text and "target_pid" not in text
    assert json.loads(text) == report
    assert calls[-1] == ("close",)


@pytest.mark.parametrize("case", ["hash", "version", "names", "extra", "remaining", "expired"])
def test_prerequisite_failure_has_zero_session_and_private_receipt(adapter, local_fake, case):
    calls, private, modules, metadata = local_fake
    deadline = 310
    if case == "hash":
        metadata[0]["sha256"] = "0" * 64
    elif case == "version":
        metadata[0]["version"] = "10.0.0.0"
    elif case == "names":
        metadata.reverse()
    elif case == "extra":
        metadata[0]["PRIVATE_CANARY"] = "SECRET"
    else:
        deadline = 24.9 if case == "remaining" else 10
    with pytest.raises(ValueError):
        adapter.run_local(r"C:\private", deadline)
    assert not any(c[0] == "session" for c in calls)
    if private.exists():
        report = json.loads((private / "summary.json").read_text())
        assert report["session_invocation_attempted"] is False
        assert "CANARY" not in json.dumps(report)


@pytest.mark.parametrize("error", [OSError("PRIVATE_CANARY"), KeyboardInterrupt(), SystemExit(8)])
def test_original_session_exception_and_cancellation_preserved(adapter, local_fake, error):
    calls, private, modules, _ = local_fake

    class Session:
        def run(self, *args, **kwargs):
            calls.append(("session_failure",))
            raise error

    modules["issue110_win32"].Session = Session
    with pytest.raises(type(error)) as caught:
        adapter.run_local(r"C:\private", 310)
    assert caught.value is error
    report = json.loads((private / "summary.json").read_text())
    assert report["owned_cleanup"] is None and report["target_exit"] == "unknown"
    assert "CANARY" not in json.dumps(report)
    assert calls.count(("session_failure",)) == 1


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(4)])
def test_script_write_cancellation_survives_ordinary_close_error(
    adapter, local_fake, monkeypatch, error
):
    calls, private, _, _ = local_fake
    original = adapter.Path.open

    class Stream:
        def write(self, value):
            raise error

        def close(self):
            raise OSError("PRIVATE_CLOSE_CANARY")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(
        adapter.Path,
        "open",
        lambda path, *args, **kwargs: (
            Stream() if path.name == "init.cdb" else original(path, *args, **kwargs)
        ),
    )
    with pytest.raises(type(error)) as caught:
        adapter.run_local(r"C:\private", 310)
    assert caught.value is error
    assert not any(call[0] == "session" for call in calls)


def test_public_receipt_has_explicit_whitelist(adapter, local_fake):
    _, private, modules, _ = local_fake
    original = modules["issue110_debugger_config"].observe
    modules["issue110_debugger_config"].observe = lambda *args: (
        original(*args) | {"raw": "PRIVATE_CANARY"}
    )
    report = adapter.run_local(r"C:\private", 310)
    assert set(report) == adapter.PUBLIC_FIELDS
    assert "CANARY" not in (private / "summary.json").read_text()


def test_late_session_return_preserves_exit_and_rejects_shared_deadline(
    adapter, local_fake, monkeypatch
):
    _, private, modules, _ = local_fake
    now = [10]
    original = modules["issue110_win32"].Session.run

    def run(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        now[0] = 310
        return value

    monkeypatch.setattr(adapter.time, "monotonic", lambda: now[0])
    modules["issue110_win32"].Session.run = run
    with pytest.raises(ValueError, match="setup_budget_exhausted"):
        adapter.run_local(r"C:\private", 310)
    report = json.loads((private / "summary.json").read_text())
    assert report["child_exit"] == 0 and report["owned_cleanup"] is True
    assert report["passed"] is False


@pytest.mark.parametrize("cleanup", [False, None, "PRIVATE_CANARY"])
def test_cleanup_unknown_or_false_never_passes(adapter, local_fake, cleanup):
    _, _, modules, _ = local_fake
    original = modules["issue110_win32"].Session.run

    def run(self, *args, **kwargs):
        raw, child, debugger, reason, _, pid = original(self, *args, **kwargs)
        return raw, child, debugger, reason, cleanup, pid

    modules["issue110_win32"].Session.run = run
    report = adapter.run_local(r"C:\private", 310)
    assert report["owned_cleanup"] is (False if cleanup is False else None)
    assert report["execution_ready"] is report["passed"] is False


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(5)])
def test_bounded_reader_preserves_primary_cancellation(adapter, error, monkeypatch):
    class Stream:
        def read(self, size):
            assert size == 65537
            raise error

        def close(self):
            raise OSError("PRIVATE_CANARY")

    monkeypatch.setattr(adapter.Path, "open", lambda *args, **kwargs: Stream())
    with pytest.raises(type(error)) as caught:
        adapter.read_bounded(Path("unused"), 65536)
    assert caught.value is error


def test_fixed_loader_uses_reviewed_files_without_path_insertion(adapter, monkeypatch):
    before = list(sys.path)
    for name in adapter.EXPECTED_DEPENDENCIES:
        monkeypatch.setitem(sys.modules, name, None)
        del sys.modules[name]
    modules = adapter.load_dependencies()
    assert list(modules) == list(adapter.EXPECTED_DEPENDENCIES)
    assert modules["issue110_debugger_config"].capture is modules["issue110_capture"]
    assert sys.path == before
    for name, expected in adapter.EXPECTED_DEPENDENCIES.items():
        assert (
            adapter.hashlib.sha256((SCRIPTS / (name + ".py")).read_bytes()).hexdigest() == expected
        )


def test_parent_main_sets_its_own_shared_deadline_only(adapter, monkeypatch):
    calls = []
    monkeypatch.setattr(adapter.time, "monotonic", lambda: 123)
    monkeypatch.setattr(adapter.sys, "argv", ["local.py", "--private-root", r"C:\private"])
    monkeypatch.setattr(adapter, "run_local", lambda *args: calls.append(args))
    assert adapter.main() == 1
    assert calls == [(r"C:\private", 423)]


@pytest.mark.parametrize(
    "error,category,blocker",
    [
        (ValueError("private_path_unverified"), "validation_error", "private_path_unverified"),
        (OSError("C:\\PRIVATE_CANARY\\nonce-secret"), "os_error", "prerequisite_or_harness_error"),
        (ValueError("PRIVATE_CANARY"), "validation_error", "prerequisite_or_harness_error"),
    ],
)
def test_entry_failure_prints_only_safe_json(
    adapter, monkeypatch, capsys, error, category, blocker
):
    monkeypatch.setattr(adapter.sys, "argv", ["local.py", "--private-root", r"C:\PRIVATE_CANARY"])

    def fail(*args):
        raise error

    monkeypatch.setattr(adapter, "run_local", fail)
    assert adapter.main() == 1
    text = capsys.readouterr().out
    report = json.loads(text)
    assert report["stage"] == "entry"
    assert report["error_category"] == category and report["blocker"] == blocker
    assert "PRIVATE_CANARY" not in text and "nonce-secret" not in text


@pytest.fixture
def native_fake(acl, monkeypatch):
    ct = acl.ct
    calls = []
    state = {"security": descriptor(), "probe_success": False, "token_offset": 16}

    class Function:
        def __init__(self, name, function):
            self.name, self.function = name, function

        def __call__(self, *args):
            calls.append((self.name, args))
            return self.function(*args)

    def output_u32(pointer, value):
        ct.cast(pointer, ct.POINTER(ct.c_uint32)).contents.value = value

    def token(process, access, pointer):
        ct.cast(pointer, ct.POINTER(ct.c_void_p)).contents.value = 44
        return 1

    def token_info(handle, kind, buffer, size, needed):
        raw = sid(USER)
        output_u32(needed, 16 + len(raw))
        if buffer is None:
            return int(state["probe_success"])
        data = struct.pack("<QII", ct.addressof(buffer) + state["token_offset"], 0, 0) + raw
        ct.memmove(buffer, data, len(data))
        return 1

    def security(handle, flags, buffer, size, needed):
        assert flags == 5
        raw = state["security"]
        output_u32(needed, len(raw))
        if buffer is None:
            return int(state["probe_success"])
        ct.memmove(buffer, raw, len(raw))
        return 1

    def information(handle, buffer):
        ct.memmove(buffer, struct.pack("<13I", 0x10, *([0] * 12)), 52)
        return 1

    def file_id(handle, kind, buffer, size):
        assert kind == 18 and size == 24
        ct.memmove(buffer, struct.pack("<Q", 22) + bytes(range(16)), size)
        return 1

    implementations = {
        "GetCurrentProcess": lambda: 55,
        "OpenProcessToken": token,
        "GetTokenInformation": token_info,
        "GetKernelObjectSecurity": security,
        "GetFileInformationByHandle": information,
        "GetFileInformationByHandleEx": file_id,
    }
    kernel, advapi = SimpleNamespace(), SimpleNamespace()
    for dll, names in (
        (
            kernel,
            (
                "CreateFileW",
                "CloseHandle",
                "GetFileInformationByHandle",
                "GetFileInformationByHandleEx",
                "GetVolumeInformationByHandleW",
                "GetDriveTypeW",
                "QueryDosDeviceW",
                "GetCurrentProcess",
                "GetModuleFileNameW",
            ),
        ),
        (
            advapi,
            ("OpenProcessToken", "GetTokenInformation", "GetKernelObjectSecurity", "IsValidSid"),
        ),
    ):
        for name in names:
            setattr(dll, name, Function(name, implementations.get(name, lambda *args: 1)))
    monkeypatch.setattr(acl.os, "name", "nt")
    monkeypatch.setattr(
        ct, "WinDLL", lambda name, **kwargs: kernel if name == "kernel32" else advapi, raising=False
    )
    monkeypatch.setattr(ct, "get_last_error", lambda: 122, raising=False)
    monkeypatch.setattr(
        ct, "WinError", lambda code: OSError(code, "PRIVATE_API_CANARY"), raising=False
    )
    return state, calls, kernel, advapi


def test_native_api_signatures_and_same_handle_security(acl, native_fake):
    state, calls, kernel, advapi = native_fake
    api = acl.Native()
    assert api.user_sid == USER
    assert acl.ct.sizeof(kernel.GetFileInformationByHandle.restype) == 4
    assert acl.ct.sizeof(kernel.CreateFileW.argtypes[1]) == 4
    assert acl.ct.sizeof(kernel.CreateFileW.restype) == acl.ct.sizeof(acl.ct.c_void_p)
    assert api.inspect(9) == (0x10, (22, bytes(range(16))), descriptor())
    api.open_directory(r"C:\private")
    create = [args for name, args in calls if name == "CreateFileW"]
    assert create == [(r"C:\private", 0x20080, 3, None, 3, 0x02200000, None)]
    assert [args[0] for name, args in calls if name == "GetKernelObjectSecurity"] == [9, 9]
    assert [args[0].value for name, args in calls if name == "CloseHandle"] == [44]


@pytest.mark.parametrize("kind", ["token", "descriptor"])
def test_successful_null_buffer_probe_is_not_valid_size_evidence(acl, native_fake, kind):
    state, _, _, _ = native_fake
    if kind == "token":
        state["probe_success"] = True
        operation = acl.Native
    else:
        api = acl.Native()
        state["probe_success"] = True

        def operation():
            return api.inspect(9)

    with pytest.raises(ValueError):
        operation()


@pytest.mark.parametrize(
    "data",
    [b"x" * 19, b"x" * 65537, descriptor()[:-1], bytes(24)],
    ids=["undersized", "oversized", "truncated", "zeroed"],
)
def test_unbounded_or_malformed_descriptor_never_reaches_isvalidsid(acl, native_fake, data):
    state, calls, _, _ = native_fake
    api = acl.Native()
    state["security"] = data
    before = sum(name == "IsValidSid" for name, _ in calls)
    with pytest.raises(ValueError):
        api.inspect(9)
    assert sum(name == "IsValidSid" for name, _ in calls) == before


@pytest.mark.parametrize("offset", [-1, 0, 8, 1000000])
def test_token_sid_pointer_is_bounded_before_native_sid_validation(acl, native_fake, offset):
    state, calls, _, _ = native_fake
    state["token_offset"] = offset
    with pytest.raises(ValueError):
        acl.Native()
    assert not any(name == "IsValidSid" for name, _ in calls)
    assert [args[0].value for name, args in calls if name == "CloseHandle"] == [44]


def test_real_isolated_python_entry_fails_closed_on_linux():
    import os
    import subprocess

    if os.name == "nt":
        pytest.skip("Never invoke real native prerequisites from this software test")
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(SCRIPTS / "issue110_debugger_config_local.py"),
            "--private-root",
            r"C:\PRIVATE_CANARY",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={"PRIVATE_SECRET": "PRIVATE_CANARY"},
    )
    assert result.returncode == 1 and result.stderr == ""
    assert json.loads(result.stdout)["blocker"] == "windows_required"
    assert "PRIVATE_CANARY" not in result.stdout


# These public synthetic fixtures are not evidence about any real private root.
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
PREPARED_ROOT = r"C:\PublicFixture"
PREPARED_MODE = "prepared_top_level"
EXACT_ENTRIES = [(who, 0x1F01FF, 3, 0) for who in (USER, SYSTEM, ADMIN)]


def prepared_descriptor():
    return descriptor(entries=EXACT_ENTRIES, control=0x9004)


class PreparedNative(FakeNative):
    def __init__(self):
        super().__init__()
        self.security_by_path = {
            "C:\\": descriptor(TRUSTED_INSTALLER, [(OTHER, 0x1200AD, 0, 0)]),
            PREPARED_ROOT: prepared_descriptor(),
            PREPARED_ROOT + r"\issue110-local-config-1": descriptor(
                entries=[(who, 0x1F01FF, 19, 0) for who in (USER, SYSTEM, ADMIN)]
            ),
        }
        self.volume_calls = []

    def inspect(self, handle):
        return self.attributes, self.identities[handle], self.security_by_path[handle]

    def volume(self, handle):
        self.volume_calls.append(handle)


@pytest.mark.parametrize(
    "data",
    [descriptor(TRUSTED_INSTALLER), descriptor(entries=[(OTHER, 4, 0, 0)])],
)
def test_prepared_exceptions_never_broaden_default_policy(acl, data):
    for private in (False, True):
        with pytest.raises(ValueError, match="acl_unverified"):
            acl.check_descriptor(data, USER, private=private)


@pytest.mark.parametrize(
    "root,mode",
    [
        (r"C:\PublicFixture\deeper", PREPARED_MODE),
        (PREPARED_ROOT, "unknown"),
        (PREPARED_ROOT, None),
    ],
)
def test_prepared_path_and_mode_gate_precede_all_native_calls(acl, monkeypatch, root, mode):
    class NoNative:
        def __getattr__(self, name):
            pytest.fail("native must not be inspected")

    monkeypatch.setattr(acl.os, "mkdir", lambda _: pytest.fail("must not create"))
    with pytest.raises(ValueError, match="private_path_unverified"):
        with acl.PrivateDirectory(root, NoNative(), mode=mode):
            pytest.fail("must not enter")


def test_prepared_chain_retains_roles_and_accepts_inherited_child(acl, monkeypatch):
    api = PreparedNative()
    made = []
    monkeypatch.setattr(acl.os, "mkdir", made.append)
    with acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE) as directory:
        assert [role for _, _, role in directory.handles] == [
            "volume_root",
            "prepared_private_root",
            "sample_child",
        ]
        assert made == [str(directory.path)]
        assert api.volume_calls == ["C:\\", "C:\\"]
        directory.revalidate()
        assert api.volume_calls == ["C:\\"] * 3
        assert api.closed == []
    assert api.closed == list(reversed(api.opened))


@pytest.mark.parametrize("owner", [USER, SYSTEM, ADMIN, TRUSTED_INSTALLER])
@pytest.mark.parametrize("mask,flags", [(0x1200AD, 0), (4, 0), (0x1F01FF, 11)])
def test_prepared_volume_policy_exact_trusted_owners_and_bounded_rights(
    acl, monkeypatch, owner, mask, flags
):
    api = PreparedNative()
    api.security_by_path["C:\\"] = descriptor(owner, [(OTHER, mask, flags, 0)])
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    with acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE):
        pass


@pytest.mark.parametrize(
    "data",
    [
        descriptor(TRUSTED_INSTALLER + "-1"),
        descriptor("S-1-5-80-1"),
        descriptor(OTHER),
        *[
            descriptor(entries=[(OTHER, mask, 0, 0)])
            for mask in (2, 0x40, 0x10000, 0x40000, 0x80000, 0x40000000, 0x10000000, 0x200)
        ],
        descriptor(entries=[(OTHER, 0x200, 11, 0)]),
    ],
)
def test_prepared_volume_rejects_owner_prefixes_writes_and_unknown_bits(acl, monkeypatch, data):
    api = PreparedNative()
    api.security_by_path["C:\\"] = data
    monkeypatch.setattr(acl.os, "mkdir", lambda _: pytest.fail("must not create"))
    with pytest.raises(ValueError, match="acl_unverified"):
        with acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE):
            pytest.fail("must not enter")
    assert api.closed == list(reversed(api.opened))


@pytest.mark.parametrize(
    "data",
    [
        *[descriptor(owner, EXACT_ENTRIES, 0x9004) for owner in (SYSTEM, ADMIN, TRUSTED_INSTALLER)],
        descriptor(entries=EXACT_ENTRIES),
        descriptor(entries=EXACT_ENTRIES[:2], control=0x9004),
        descriptor(entries=EXACT_ENTRIES + [EXACT_ENTRIES[0]], control=0x9004),
        descriptor(entries=EXACT_ENTRIES + [(OTHER, 0, 0, 0)], control=0x9004),
        *[
            descriptor(entries=[(USER, mask, flags, kind), *EXACT_ENTRIES[1:]], control=0x9004)
            for mask, flags, kind in (
                (0x10000000, 3, 0),
                (0x1200A9, 3, 0),
                (0x1F01FF, 19, 0),
                (0x1F01FF, 11, 0),
                (0x1F01FF, 7, 0),
                (0x1F01FF, 0, 0),
                (0x1F01FF, 3, 1),
            )
        ],
    ],
)
def test_prepared_private_root_requires_exact_protected_explicit_acl(acl, monkeypatch, data):
    api = PreparedNative()
    api.security_by_path[PREPARED_ROOT] = data
    monkeypatch.setattr(acl.os, "mkdir", lambda _: pytest.fail("must not create"))
    with pytest.raises(ValueError, match="acl_unverified"):
        with acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE):
            pytest.fail("must not enter")
    assert api.closed == list(reversed(api.opened))


def test_generic_mode_does_not_query_filesystem(acl, monkeypatch):
    api = FakeNative()
    api.volume = lambda _: pytest.fail("legacy must not query volume")
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    with acl.PrivateDirectory(r"C:\private\nested", api):
        pass


@pytest.mark.parametrize(
    "name,flags,result", [("NTFS", 0, 1), ("ReFS", 8, 1), ("ntfs", 8, 1), ("NTFS", 8, 0)]
)
def test_native_volume_fails_closed(acl, name, flags, result):
    api = acl.Native.__new__(acl.Native)

    def volume(handle, label, size, serial, maximum, output_flags, output_name, length):
        assert (handle, label, size, serial, maximum, length) == (9, None, 0, None, None, 32)
        acl.ct.cast(output_flags, acl.ct.POINTER(acl.ct.c_uint32)).contents.value = flags
        output_name.value = name
        return result

    api.kernel = SimpleNamespace(GetVolumeInformationByHandleW=volume)
    with pytest.raises(ValueError, match="private_directory_unverified"):
        api.volume(9)


def test_native_volume_signature_and_held_handle(acl, native_fake):
    _, calls, kernel, _ = native_fake
    api = acl.Native()
    function = kernel.GetVolumeInformationByHandleW
    assert function.argtypes == [
        acl.ct.c_void_p,
        acl.ct.c_wchar_p,
        acl.ct.c_uint32,
        acl.ct.c_void_p,
        acl.ct.c_void_p,
        acl.ct.c_void_p,
        acl.ct.c_wchar_p,
        acl.ct.c_uint32,
    ]
    assert function.restype is acl.ct.c_int32

    def volume(handle, label, size, serial, maximum, flags, name, length):
        assert (handle, label, size, serial, maximum, length) == (9, None, 0, None, None, 32)
        acl.ct.cast(flags, acl.ct.POINTER(acl.ct.c_uint32)).contents.value = 8
        name.value = "NTFS"
        return 1

    function.function = volume
    api.volume(9)
    assert [args[0] for name, args in calls if name == "GetVolumeInformationByHandleW"] == [9]


@pytest.mark.parametrize(
    "role", ["volume_root", "prepared_private_root", "sample_child", "filesystem"]
)
def test_prepared_role_revalidation_stops_before_session(
    acl, adapter, local_fake, monkeypatch, role
):
    calls, _, modules, _ = local_fake
    api = PreparedNative()
    original_mkdir = acl.os.mkdir
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    directory = acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE)
    directory.__enter__()
    monkeypatch.setattr(acl.os, "mkdir", original_mkdir)
    modules["issue110_local_acl"].PrivateDirectory.revalidate = lambda self: directory.revalidate()
    installed = modules["issue110_capture"].installed_debugger

    def mutate(*args, **kwargs):
        if role == "filesystem":

            def fail(_):
                raise ValueError("private_directory_unverified")

            api.volume = fail
        else:
            handle = next(
                handle for handle, _, stored_role in directory.handles if stored_role == role
            )
            api.security_by_path[handle] = {
                "volume_root": descriptor(entries=[(OTHER, 2, 0, 0)]),
                "prepared_private_root": descriptor(entries=EXACT_ENTRIES),
                "sample_child": descriptor(entries=[(OTHER, 0x1F01FF, 19, 0)]),
            }[role]
        return installed(*args, **kwargs)

    modules["issue110_capture"].installed_debugger = mutate
    try:
        with pytest.raises(ValueError):
            adapter.run_local(PREPARED_ROOT, 310)
        assert not any(call[0] == "session" for call in calls)
    finally:
        directory.__exit__(None, None, None)
    assert api.closed == list(reversed(api.opened))


def test_local_adapter_explicitly_selects_prepared_mode(adapter, local_fake):
    calls, _, _, _ = local_fake
    adapter.run_local(PREPARED_ROOT, 310)
    assert [call[-1] for call in calls if call[0] == "root"] == [PREPARED_MODE]


def test_local_adapter_deep_path_rejected_before_native_construction(adapter, local_fake):
    _, _, modules, _ = local_fake
    modules["issue110_local_acl"].Native = lambda: pytest.fail("must not construct Native")
    with pytest.raises(ValueError, match="private_path_unverified"):
        adapter.run_local(PREPARED_ROOT + r"\deeper", 310)


def test_observer_never_imports_or_provisions_prepared_root(adapter, acl):
    import ast

    sources = [Path(module.__file__).read_text() for module in (adapter, acl)]
    for source in sources:
        assert "issue110_prepare_private_root" not in source
        assert "CreateDirectoryW" not in source
        assert "SetSecurity" not in source
    mkdir_calls = [
        node
        for node in ast.walk(ast.parse(sources[1]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mkdir"
    ]
    assert len(mkdir_calls) == 1
    assert ast.unparse(mkdir_calls[0].args[0]) == "str(self.path)"


@pytest.mark.parametrize("unknown_role", ["unknown", "prepared_private_rooot", None, True])
def test_unknown_held_role_revalidation_fails_closed(acl, monkeypatch, unknown_role):
    api = PreparedNative()
    monkeypatch.setattr(acl.os, "mkdir", lambda _: None)
    with acl.PrivateDirectory(PREPARED_ROOT, api, mode=PREPARED_MODE) as directory:
        handle, identity, _ = directory.handles[1]
        directory.handles[1] = (handle, identity, unknown_role)
        with pytest.raises(ValueError, match="private_directory_unverified"):
            directory.revalidate()
