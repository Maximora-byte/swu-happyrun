"""Native enrollment tests are inert unless all operator opt-ins are present."""

import os

import pytest

from .harness import gate_reason


def pytest_addoption(parser):
    group = parser.getgroup("native enrollment QA")
    group.addoption("--run-native-enrollment", action="store_true", default=False)
    group.addoption("--native-enrollment-qa-root", default=None, metavar="EXISTING_QA_DIRECTORY")
    group.addoption("--authorize-native-enrollment-writes", action="store_true", default=False)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "native_enrollment: opt-in real Windows storage/coordinator mechanism QA"
    )


def pytest_collection_modifyitems(config, items):
    reason = gate_reason(
        enabled=config.getoption("--run-native-enrollment"),
        authorized=config.getoption("--authorize-native-enrollment-writes"),
        root=config.getoption("--native-enrollment-qa-root"),
        platform=os.name,
    )
    if reason:
        for item in items:
            if item.get_closest_marker("native_enrollment"):
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def native_qa_root(request):
    # Recheck independently of collection. Neither a marker nor a direct fixture
    # invocation can turn a missing operator authorization into permission.
    reason = gate_reason(
        enabled=request.config.getoption("--run-native-enrollment"),
        authorized=request.config.getoption("--authorize-native-enrollment-writes"),
        root=request.config.getoption("--native-enrollment-qa-root"),
        platform=os.name,
    )
    if reason:
        pytest.skip(reason)
    return request.config.getoption("--native-enrollment-qa-root")
