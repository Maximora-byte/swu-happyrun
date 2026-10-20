"""Never runs on normal collection; no mocks of Windows storage or guards."""

import pytest

from .harness import run_case

pytestmark = pytest.mark.native_enrollment


def test_storage_stage_publish(native_qa_root):
    run_case(native_qa_root, "storage_positive")


def test_account_coordinator_contention(native_qa_root):
    run_case(native_qa_root, "account_contention")


def test_existing_original_device_contention(native_qa_root):
    run_case(native_qa_root, "device_contention")


def test_existing_coordinator_preserves_originals(native_qa_root):
    run_case(native_qa_root, "existing_positive")


@pytest.mark.parametrize("operation", ["write", "fsync", "flush", "move"])
@pytest.mark.parametrize("edge", ["before", "after"])
def test_native_delegating_failure(native_qa_root, operation, edge):
    run_case(native_qa_root, "storage_fault", fault=(operation, edge))
