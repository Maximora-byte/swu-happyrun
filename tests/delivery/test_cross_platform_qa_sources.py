"""Guard explicit source encodings and bounded pytest IDs on Windows."""

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name",
    [
        "scripts/check_native_navigation.py",
        "tests/delivery/test_foreground_activity_contract.py",
    ],
)
def test_source_text_io_is_explicit_utf8(name):
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "write_text"}
    ]
    assert calls
    for node in calls:
        encoding = next((arg.value for arg in node.keywords if arg.arg == "encoding"), None)
        assert isinstance(encoding, ast.Constant) and encoding.value == "utf-8"


def test_large_inventory_parameter_has_bounded_explicit_id():
    path = ROOT / "tests/agent/test_adapter_inputs.py"
    spec = importlib.util.spec_from_file_location("synthetic_adapter_input_checks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = module.test_bad_json_duplicate_keys_and_large_inputs_rejected
    mark = next(mark for mark in function.pytestmark if mark.name == "parametrize")
    ids = mark.kwargs.get("ids")
    assert ids is not None and len(ids) == len(mark.args[1])
    assert all(isinstance(item, str) and 0 < len(item) < 80 for item in ids)
    assert len(set(ids)) == len(ids)
    assert len(mark.args[1][-1]) == 65537  # The over-limit payload itself remains real.
