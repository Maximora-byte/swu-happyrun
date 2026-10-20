"""Bound test identifiers without shortening any adversarial test payload."""


def test_collected_case_ids_fit_windows_environment(request):
    # PYTEST_CURRENT_TEST includes the node ID. Keep substantial room below the
    # Windows 32767-character environment-variable limit for phase decoration.
    assert all(len(item.nodeid) < 8192 for item in request.session.items)
    enrollment = [item for item in request.session.items if "/test_enrollment_" in item.nodeid]
    assert all(len(item.nodeid) < 512 for item in enrollment)
