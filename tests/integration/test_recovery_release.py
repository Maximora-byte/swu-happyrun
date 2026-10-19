"""Actual HTTP reservation release after the Issue 36 process-recovery path."""

from test_http_runner import (
    runtime,  # noqa: F401 - pytest fixture registration
)
from test_http_runner import (
    test_finished_stopped_simulation_recovers_completed_without_motion as recover,
)


def test_recovered_completion_releases_device_for_new_job(runtime):  # noqa: F811
    service, _, first = runtime
    # Reuse the actual child crash + fresh runner recovery scenario, including
    # its no-prepare/start/tick assertions. Do not substitute a terminal event.
    recover(runtime)
    completed = service.get("jobs/" + first["job_id"]).json()
    assert completed["state"] == "completed"
    # The crash recovery advanced server UTC by 31 seconds; refresh the actual
    # capability probe before asking the server to assign a distinct new job.
    assert service.hello().status_code == 200
    created = service.create()
    assert created.status_code == 201, created.text
    second = created.json()
    assert second["job_id"] != first["job_id"]
    claimed = service.claim()
    assert claimed.status_code == 200, claimed.text
    grant = claimed.json()
    assert grant["job"]["job_id"] == second["job_id"]
    assert grant["job"]["spec"]["device_id"] == completed["spec"]["device_id"]
    assert grant["fence"] > completed["fence"]
    assert grant["job"]["run_session_id"] != completed["run_session_id"]
