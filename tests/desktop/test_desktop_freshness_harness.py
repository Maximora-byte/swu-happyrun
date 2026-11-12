"""The desktop regression harness must reject absent, failed or unfinished tests."""

import os
import shutil

import pytest
from test_desktop_freshness import run_node_cases


@pytest.fixture
def node():
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node.js is required for the desktop JavaScript regression")
    return executable


def run_script(node, tmp_path, source, **options):
    script = tmp_path / "case.cjs"
    script.write_text(source, encoding="utf-8")
    return run_node_cases(node, script, tmp_path, **options)


def test_seven_real_cases_pass(node, tmp_path):
    run_script(
        node,
        tmp_path,
        'const {test}=require("node:test");const assert=require("node:assert/strict");'
        f'for(let i=0;i<7;i++) test("case "+i,()=>assert.equal(process.ppid,{os.getpid()}));',
    )


def test_zero_cases_are_not_a_pass(node, tmp_path):
    with pytest.raises(AssertionError, match="receipt"):
        run_script(node, tmp_path, 'console.log("no tests executed");')


def test_assertion_failure_is_reported(node, tmp_path):
    with pytest.raises(AssertionError, match="INTENTIONAL_ASSERTION_FAILURE"):
        run_script(
            node,
            tmp_path,
            'const {test}=require("node:test");'
            'const assert=require("node:assert/strict");'
            'for(let i=0;i<7;i++) test("case "+i,()=>'
            'assert.equal(i,0,"INTENTIONAL_ASSERTION_FAILURE"));',
        )


def test_nonzero_exit_reports_stderr(node, tmp_path):
    with pytest.raises(AssertionError, match="INTENTIONAL_EXIT_FAILURE"):
        run_script(node, tmp_path, 'console.error("INTENTIONAL_EXIT_FAILURE");process.exit(2);')


@pytest.mark.parametrize("option", ["skip", "todo"])
def test_unexecuted_case_is_not_a_pass(node, tmp_path, option):
    with pytest.raises(AssertionError, match="receipt"):
        run_script(
            node,
            tmp_path,
            'const {test}=require("node:test");'
            'for(let i=0;i<6;i++) test("case "+i,()=>{});'
            f'test("unexecuted",{{{option}:true}},()=>{{}});',
        )


def test_timeout_is_a_diagnostic_failure(node, tmp_path):
    with pytest.raises(AssertionError, match="deadline"):
        run_script(node, tmp_path, "setInterval(()=>{},1000);", timeout=0.2)


def test_partial_case_count_is_not_a_pass(node, tmp_path):
    with pytest.raises(AssertionError, match="receipt"):
        run_script(
            node,
            tmp_path,
            'const {test}=require("node:test");for(let i=0;i<6;i++) test("case "+i,()=>{});',
        )


def test_windows_line_endings_preserve_complete_receipt(node, tmp_path):
    run_script(
        node,
        tmp_path,
        "const write=process.stdout.write.bind(process.stdout);"
        "process.stdout.write=(chunk,...args)=>write("
        'typeof chunk==="string"?chunk.replace(/\\n/g,"\\r\\n"):chunk,...args);'
        'const {test}=require("node:test");'
        'for(let i=0;i<7;i++) test("case "+i,()=>{});',
    )
