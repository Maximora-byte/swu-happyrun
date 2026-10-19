"""Exercise source guards under a GBK-default file reader without changing the OS."""

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OWNED = (
    "scripts/check_mumu_https.py",
    "scripts/mumu_https_fixture.py",
    "tests/delivery/test_mumu_https.py",
    "tests/delivery/test_mumu_https_fixture.py",
    "tests/delivery/test_mumu_build_only_workflow.py",
    "tests/delivery/test_mumu_namespace_jvm.py",
    "tests/delivery/test_mumu_namespace_portability.py",
    "tests/delivery/test_mumu_version_binding.py",
    "tests/delivery/test_mumu_text_encoding.py",
)


def test_source_privacy_guard_runs_with_gbk_default(monkeypatch):
    original = Path.read_text

    def gbk_default(path, encoding=None, errors=None):
        return original(path, encoding=encoding or "gbk", errors=errors)

    # Actual UTF-8 runner includes an en dash; prove the old locale-dependent read fails.
    source = ROOT / "scripts/check_mumu_https.py"
    with pytest.raises(UnicodeDecodeError):
        gbk_default(source)
    spec = importlib.util.spec_from_file_location(
        "mumu_encoding_guard_target", ROOT / "tests/delivery/test_mumu_https.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(Path, "read_text", gbk_default)
    module.MumuHttpsTests().test_no_pm_clear_or_old_avd_guard_override_in_new_source()
    module.test_adapter_namespace_and_guards_are_required()


@pytest.mark.parametrize("relative", OWNED)
def test_owned_source_and_fixture_text_io_declares_utf8(relative):
    tree = ast.parse((ROOT / relative).read_bytes())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"read_text", "write_text"}:
            continue
        encoding = next((kw.value for kw in node.keywords if kw.arg == "encoding"), None)
        assert isinstance(encoding, ast.Constant) and encoding.value == "utf-8", (
            relative,
            node.lineno,
            "owned UTF-8 text I/O must not depend on locale",
        )
